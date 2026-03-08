from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

import pytest

from agentflow.agents.base import AgentAdapter
from agentflow.agents.registry import AdapterRegistry
from agentflow.orchestrator import Orchestrator
from agentflow.prepared import ExecutionPaths, PreparedExecution
from agentflow.runners.registry import RunnerRegistry
from agentflow.specs import AgentKind, PipelineSpec
from agentflow.store import RunStore


class MockAdapter(AgentAdapter):
    def prepare(self, node, prompt: str, paths: ExecutionPaths) -> PreparedExecution:
        script = r'''
import json
import sys
import sys
import time
from pathlib import Path

node_id = sys.argv[1]
prompt = sys.argv[2]
agent = sys.argv[3]
workdir = Path.cwd()
if node_id in {"alpha", "beta"}:
    time.sleep(0.25)
if node_id == "slow":
    for _ in range(200):
        time.sleep(0.05)
if node_id == "flaky":
    marker = workdir / ".flaky"
    if not marker.exists():
        marker.write_text("first failure", encoding="utf-8")
        print("transient failure", file=sys.stderr)
        raise SystemExit(3)
if node_id == "writer":
    (workdir / "artifact.txt").write_text("file data", encoding="utf-8")
if agent == "codex":
    print(json.dumps({"type": "response.output_item.done", "item": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": prompt}]}}))
elif agent == "claude":
    print(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": prompt}]}}))
    print(json.dumps({"type": "result", "result": prompt}))
else:
    print(json.dumps({"jsonrpc": "2.0", "method": "event", "params": {"type": "ContentPart", "payload": {"type": "text", "text": prompt}}}))
'''
        return PreparedExecution(
            command=["python3", "-c", script, node.id, prompt, node.agent.value],
            env={},
            cwd=str(paths.host_workdir),
            trace_kind=node.agent.value,
        )


def make_orchestrator(tmp_path: Path) -> Orchestrator:
    adapters = AdapterRegistry()
    adapters.register(AgentKind.CODEX, MockAdapter())
    adapters.register(AgentKind.CLAUDE, MockAdapter())
    adapters.register(AgentKind.KIMI, MockAdapter())
    return Orchestrator(store=RunStore(tmp_path / "runs"), adapters=adapters, runners=RunnerRegistry())


@pytest.mark.asyncio
async def test_orchestrator_runs_parallel_and_templates_outputs(tmp_path: Path):
    orchestrator = make_orchestrator(tmp_path)
    pipeline = PipelineSpec.model_validate(
        {
            "name": "parallel",
            "working_dir": str(tmp_path),
            "concurrency": 2,
            "nodes": [
                {"id": "alpha", "agent": "codex", "prompt": "alpha"},
                {"id": "beta", "agent": "claude", "prompt": "beta"},
                {
                    "id": "gamma",
                    "agent": "kimi",
                    "depends_on": ["alpha", "beta"],
                    "prompt": "merge {{ nodes.alpha.output }} + {{ nodes.beta.output }}",
                },
            ],
        }
    )
    started = asyncio.get_running_loop().time()
    run = await orchestrator.submit(pipeline)
    completed = await orchestrator.wait(run.id, timeout=5)
    elapsed = asyncio.get_running_loop().time() - started

    alpha = completed.nodes["alpha"]
    beta = completed.nodes["beta"]
    gamma = completed.nodes["gamma"]
    assert completed.status.value == "completed"
    assert alpha.output == "alpha"
    assert beta.output == "beta"
    assert "alpha" in gamma.output
    assert "beta" in gamma.output
    alpha_start = datetime.fromisoformat(alpha.started_at)
    beta_start = datetime.fromisoformat(beta.started_at)
    assert abs((alpha_start - beta_start).total_seconds()) < 0.15
    assert elapsed < 1.0


@pytest.mark.asyncio
async def test_orchestrator_applies_success_criteria(tmp_path: Path):
    orchestrator = make_orchestrator(tmp_path)
    pipeline = PipelineSpec.model_validate(
        {
            "name": "writer",
            "working_dir": str(tmp_path),
            "nodes": [
                {
                    "id": "writer",
                    "agent": "codex",
                    "prompt": "success",
                    "success_criteria": [
                        {"kind": "file_exists", "path": "artifact.txt"},
                        {"kind": "file_contains", "path": "artifact.txt", "value": "file data"},
                    ],
                }
            ],
        }
    )
    run = await orchestrator.submit(pipeline)
    completed = await orchestrator.wait(run.id, timeout=5)
    assert completed.nodes["writer"].status.value == "completed"
    assert (tmp_path / "artifact.txt").read_text(encoding="utf-8") == "file data"


@pytest.mark.asyncio
async def test_orchestrator_retries_failed_nodes(tmp_path: Path):
    orchestrator = make_orchestrator(tmp_path)
    pipeline = PipelineSpec.model_validate(
        {
            "name": "retry",
            "working_dir": str(tmp_path),
            "nodes": [
                {
                    "id": "flaky",
                    "agent": "codex",
                    "prompt": "recovered",
                    "retries": 1,
                    "retry_backoff_seconds": 0.01,
                }
            ],
        }
    )
    run = await orchestrator.submit(pipeline)
    completed = await orchestrator.wait(run.id, timeout=5)
    node = completed.nodes["flaky"]
    assert completed.status.value == "completed"
    assert node.status.value == "completed"
    assert node.current_attempt == 2
    assert len(node.attempts) == 2
    assert node.attempts[0].status.value == "failed"
    assert node.attempts[1].status.value == "completed"
    assert orchestrator.store.read_artifact_text(completed.id, "flaky", "output.txt") == "recovered"


@pytest.mark.asyncio
async def test_orchestrator_cancels_running_nodes(tmp_path: Path):
    orchestrator = make_orchestrator(tmp_path)
    pipeline = PipelineSpec.model_validate(
        {
            "name": "cancel",
            "working_dir": str(tmp_path),
            "nodes": [
                {
                    "id": "slow",
                    "agent": "codex",
                    "prompt": "eventually cancelled",
                    "timeout_seconds": 30,
                }
            ],
        }
    )
    run = await orchestrator.submit(pipeline)
    for _ in range(50):
        snapshot = orchestrator.store.get_run(run.id)
        if snapshot.status.value == "running":
            break
        await asyncio.sleep(0.05)
    await orchestrator.cancel(run.id)
    completed = await orchestrator.wait(run.id, timeout=5)
    assert completed.status.value == "cancelled"
    assert completed.nodes["slow"].status.value == "cancelled"
    assert "Cancelled by user" in orchestrator.store.read_artifact_text(completed.id, "slow", "stderr.log")
