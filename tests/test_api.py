from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from agentflow.app import create_app
from agentflow.orchestrator import Orchestrator
from agentflow.store import RunStore
from tests.test_orchestrator import make_orchestrator


def test_api_starts_and_returns_run_details(tmp_path):
    orchestrator = make_orchestrator(tmp_path)
    app = create_app(store=orchestrator.store, orchestrator=orchestrator)
    client = TestClient(app)

    payload = {
        "pipeline": {
            "name": "api-run",
            "working_dir": str(tmp_path),
            "nodes": [
                {"id": "alpha", "agent": "codex", "prompt": "api success"},
            ],
        }
    }
    response = client.post("/api/runs", json=payload)
    assert response.status_code == 200
    run_id = response.json()["id"]
    asyncio.run(orchestrator.wait(run_id, timeout=5))
    run_response = client.get(f"/api/runs/{run_id}")
    assert run_response.status_code == 200
    body = run_response.json()
    assert body["status"] == "completed"
    assert body["nodes"]["alpha"]["output"] == "api success"


def test_api_returns_default_example_payload(tmp_path):
    orchestrator = make_orchestrator(tmp_path)
    app = create_app(store=orchestrator.store, orchestrator=orchestrator)
    client = TestClient(app)

    response = client.get("/api/examples/default")
    assert response.status_code == 200
    assert "parallel-code-orchestration" in response.json()["yaml"]


def test_api_supports_validation_and_artifacts(tmp_path):
    orchestrator = make_orchestrator(tmp_path)
    app = create_app(store=orchestrator.store, orchestrator=orchestrator)
    client = TestClient(app)

    validate = client.post(
        "/api/runs/validate",
        json={"yaml": "name: ok\nworking_dir: .\nnodes:\n  - id: alpha\n    agent: codex\n    prompt: hi\n"},
    )
    assert validate.status_code == 200
    assert validate.json()["pipeline"]["name"] == "ok"

    invalid = client.post(
        "/api/runs/validate",
        json={"yaml": "name: bad\nnodes:\n  - id: a\n    agent: codex\n    prompt: hi\n    depends_on: [b]\n"},
    )
    assert invalid.status_code == 422

    create = client.post(
        "/api/runs",
        json={"pipeline": {"name": "artifact", "working_dir": str(tmp_path), "nodes": [{"id": "alpha", "agent": "codex", "prompt": "artifact output"}]}}
    )
    run_id = create.json()["id"]
    asyncio.run(orchestrator.wait(run_id, timeout=5))
    artifact = client.get(f"/api/runs/{run_id}/artifacts/alpha/output.txt")
    assert artifact.status_code == 200
    assert artifact.text == "artifact output"


def test_api_supports_cancel_and_rerun(tmp_path):
    orchestrator = make_orchestrator(tmp_path)
    app = create_app(store=orchestrator.store, orchestrator=orchestrator)
    client = TestClient(app)

    create = client.post(
        "/api/runs",
        json={"pipeline": {"name": "cancel", "working_dir": str(tmp_path), "nodes": [{"id": "slow", "agent": "codex", "prompt": "slow"}]}}
    )
    run_id = create.json()["id"]
    for _ in range(50):
        run = orchestrator.store.get_run(run_id)
        if run.status.value == "running":
            break
        import time
        time.sleep(0.05)
    cancel = client.post(f"/api/runs/{run_id}/cancel")
    assert cancel.status_code == 200
    completed = asyncio.run(orchestrator.wait(run_id, timeout=5))
    assert completed.status.value == "cancelled"

    rerun = client.post(f"/api/runs/{run_id}/rerun")
    assert rerun.status_code == 200
    rerun_id = rerun.json()["id"]
    assert rerun_id != run_id
