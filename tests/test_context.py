from __future__ import annotations

from pathlib import Path

from agentflow.context import build_render_context, render_node_prompt
from agentflow.loader import load_pipeline_from_data
from agentflow.specs import NodeResult, NodeStatus


def _fanout_pipeline(tmp_path: Path):
    return load_pipeline_from_data(
        {
            "name": "fanout-context",
            "working_dir": str(tmp_path),
            "nodes": [
                {
                    "id": "worker",
                    "fanout": {
                        "as": "shard",
                        "values": [
                            {"target": "libpng", "seed": 1001},
                            {"target": "sqlite", "seed": 2002},
                            {"target": "openssl", "seed": 3003},
                        ],
                    },
                    "agent": "codex",
                    "prompt": "worker {{ shard.target }} seed {{ shard.seed }}",
                },
                {
                    "id": "merge",
                    "agent": "codex",
                    "depends_on": ["worker"],
                    "prompt": (
                        "completed={{ fanouts.worker.summary.completed }}/{{ fanouts.worker.size }} "
                        "failed={{ fanouts.worker.summary.failed }} :: "
                        "{% for shard in fanouts.worker.with_output.nodes %}"
                        "{{ shard.id }}={{ shard.target }}:{{ shard.output }};"
                        "{% endfor %}"
                    ),
                },
            ],
        },
        base_dir=tmp_path,
    )


def _batched_pipeline(tmp_path: Path):
    return load_pipeline_from_data(
        {
            "name": "batched-context",
            "working_dir": str(tmp_path),
            "nodes": [
                {
                    "id": "worker",
                    "fanout": {
                        "count": 3,
                        "as": "shard",
                        "derive": {
                            "workspace": "agents/agent_{{ shard.suffix }}",
                        },
                    },
                    "agent": "codex",
                    "prompt": "worker {{ shard.number }}",
                },
                {
                    "id": "batch_merge",
                    "fanout": {
                        "as": "batch",
                        "batches": {
                            "from": "worker",
                            "size": 2,
                        },
                    },
                    "agent": "codex",
                    "depends_on": ["worker"],
                    "prompt": (
                        "batch={{ current.number }}/{{ current.count }} "
                        "range={{ current.start_number }}-{{ current.end_number }} "
                        "ids={{ current.member_ids | join(',') }} :: "
                        "{% for shard in current.members %}"
                        "{{ shard.node_id }}@{{ shard.workspace }}={{ nodes[shard.node_id].output or '(no output)' }};"
                        "{% endfor %}"
                    ),
                },
            ],
        },
        base_dir=tmp_path,
    )


def _grouped_pipeline(tmp_path: Path):
    return load_pipeline_from_data(
        {
            "name": "grouped-context",
            "working_dir": str(tmp_path),
            "nodes": [
                {
                    "id": "worker",
                    "fanout": {
                        "as": "shard",
                        "values": [
                            {"target": "libpng", "seed": 1001, "workspace": "agents/libpng_0"},
                            {"target": "libpng", "seed": 1002, "workspace": "agents/libpng_1"},
                            {"target": "sqlite", "seed": 2002, "workspace": "agents/sqlite_2"},
                        ],
                    },
                    "agent": "codex",
                    "prompt": "worker {{ shard.target }} seed {{ shard.seed }}",
                },
                {
                    "id": "family_merge",
                    "fanout": {
                        "as": "family",
                        "group_by": {
                            "from": "worker",
                            "fields": ["target"],
                        },
                    },
                    "agent": "codex",
                    "depends_on": ["worker"],
                    "prompt": (
                        "family={{ current.target }} ids={{ current.member_ids | join(',') }} :: "
                        "{% for shard in current.members %}"
                        "{{ shard.node_id }}@{{ shard.seed }}={{ nodes[shard.node_id].output or '(no output)' }};"
                        "{% endfor %}"
                    ),
                },
            ],
        },
        base_dir=tmp_path,
    )


def test_build_render_context_exposes_fanout_status_and_output_subsets(tmp_path: Path):
    pipeline = _fanout_pipeline(tmp_path)
    results = {
        "worker_0": NodeResult(node_id="worker_0", status=NodeStatus.COMPLETED, output="ok libpng"),
        "worker_1": NodeResult(node_id="worker_1", status=NodeStatus.FAILED, output="retry sqlite"),
        "worker_2": NodeResult(node_id="worker_2", status=NodeStatus.COMPLETED, output=""),
        "merge": NodeResult(node_id="merge"),
    }

    context = build_render_context(pipeline, results)
    worker = context["fanouts"]["worker"]

    assert worker["size"] == 3
    assert worker["summary"]["total"] == 3
    assert worker["summary"]["completed"] == 2
    assert worker["summary"]["failed"] == 1
    assert worker["summary"]["with_output"] == 2
    assert worker["summary"]["without_output"] == 1
    assert worker["status_counts"]["completed"] == 2
    assert worker["status_counts"]["failed"] == 1
    assert [node["id"] for node in worker["completed"]["nodes"]] == ["worker_0", "worker_2"]
    assert [node["id"] for node in worker["failed"]["nodes"]] == ["worker_1"]
    assert [node["id"] for node in worker["with_output"]["nodes"]] == ["worker_0", "worker_1"]
    assert [node["id"] for node in worker["without_output"]["nodes"]] == ["worker_2"]
    assert worker["failed"]["nodes"][0]["target"] == "sqlite"
    assert worker["completed"]["nodes"][1]["seed"] == 3003


def test_render_node_prompt_can_use_fanout_summary_and_filtered_nodes(tmp_path: Path):
    pipeline = _fanout_pipeline(tmp_path)
    results = {
        "worker_0": NodeResult(node_id="worker_0", status=NodeStatus.COMPLETED, output="ok libpng"),
        "worker_1": NodeResult(node_id="worker_1", status=NodeStatus.FAILED, output="retry sqlite"),
        "worker_2": NodeResult(node_id="worker_2", status=NodeStatus.COMPLETED, output=""),
        "merge": NodeResult(node_id="merge"),
    }

    rendered = render_node_prompt(pipeline, pipeline.node_map["merge"], results)

    assert rendered == (
        "completed=2/3 failed=1 :: "
        "worker_0=libpng:ok libpng;"
        "worker_1=sqlite:retry sqlite;"
    )


def test_build_render_context_exposes_current_node_metadata_for_runtime_reducers(tmp_path: Path):
    pipeline = _batched_pipeline(tmp_path)
    results = {
        "worker_0": NodeResult(node_id="worker_0", status=NodeStatus.COMPLETED, output="alpha"),
        "worker_1": NodeResult(node_id="worker_1", status=NodeStatus.FAILED, output="beta"),
        "worker_2": NodeResult(node_id="worker_2", status=NodeStatus.COMPLETED, output=""),
        "batch_merge_0": NodeResult(node_id="batch_merge_0"),
        "batch_merge_1": NodeResult(node_id="batch_merge_1"),
    }

    context = build_render_context(pipeline, results, current_node=pipeline.node_map["batch_merge_0"])

    assert context["current"] == {
        "id": "batch_merge_0",
        "agent": "codex",
        "depends_on": ["worker_0", "worker_1"],
        "fanout_group": "batch_merge",
        "index": 0,
        "number": 1,
        "count": 2,
        "suffix": "0",
        "value": {
            "source_group": "worker",
            "source_count": 3,
            "size": 2,
            "member_ids": ["worker_0", "worker_1"],
            "members": [
                {
                    "index": 0,
                    "number": 1,
                    "count": 3,
                    "suffix": "0",
                    "value": 0,
                    "template_id": "worker",
                    "node_id": "worker_0",
                    "workspace": "agents/agent_0",
                },
                {
                    "index": 1,
                    "number": 2,
                    "count": 3,
                    "suffix": "1",
                    "value": 1,
                    "template_id": "worker",
                    "node_id": "worker_1",
                    "workspace": "agents/agent_1",
                },
            ],
            "start_index": 0,
            "end_index": 1,
            "start_number": 1,
            "end_number": 2,
            "start_suffix": "0",
            "end_suffix": "1",
        },
        "template_id": "batch_merge",
        "node_id": "batch_merge_0",
        "source_group": "worker",
        "source_count": 3,
        "size": 2,
        "member_ids": ["worker_0", "worker_1"],
        "members": [
            {
                "index": 0,
                "number": 1,
                "count": 3,
                "suffix": "0",
                "value": 0,
                "template_id": "worker",
                "node_id": "worker_0",
                "workspace": "agents/agent_0",
            },
            {
                "index": 1,
                "number": 2,
                "count": 3,
                "suffix": "1",
                "value": 1,
                "template_id": "worker",
                "node_id": "worker_1",
                "workspace": "agents/agent_1",
            },
        ],
        "start_index": 0,
        "end_index": 1,
        "start_number": 1,
        "end_number": 2,
        "start_suffix": "0",
        "end_suffix": "1",
    }


def test_render_node_prompt_can_use_current_node_and_batch_members(tmp_path: Path):
    pipeline = _batched_pipeline(tmp_path)
    results = {
        "worker_0": NodeResult(node_id="worker_0", status=NodeStatus.COMPLETED, output="alpha"),
        "worker_1": NodeResult(node_id="worker_1", status=NodeStatus.FAILED, output="beta"),
        "worker_2": NodeResult(node_id="worker_2", status=NodeStatus.COMPLETED, output=""),
        "batch_merge_0": NodeResult(node_id="batch_merge_0"),
        "batch_merge_1": NodeResult(node_id="batch_merge_1"),
    }

    rendered = render_node_prompt(pipeline, pipeline.node_map["batch_merge_0"], results)

    assert rendered == (
        "batch=1/2 range=1-2 ids=worker_0,worker_1 :: "
        "worker_0@agents/agent_0=alpha;"
        "worker_1@agents/agent_1=beta;"
    )


def test_build_render_context_exposes_current_node_metadata_for_grouped_reducers(tmp_path: Path):
    pipeline = _grouped_pipeline(tmp_path)
    results = {
        "worker_0": NodeResult(node_id="worker_0", status=NodeStatus.COMPLETED, output="alpha"),
        "worker_1": NodeResult(node_id="worker_1", status=NodeStatus.FAILED, output="beta"),
        "worker_2": NodeResult(node_id="worker_2", status=NodeStatus.COMPLETED, output="gamma"),
        "family_merge_0": NodeResult(node_id="family_merge_0"),
        "family_merge_1": NodeResult(node_id="family_merge_1"),
    }

    context = build_render_context(pipeline, results, current_node=pipeline.node_map["family_merge_0"])

    assert context["current"] == {
        "id": "family_merge_0",
        "agent": "codex",
        "depends_on": ["worker_0", "worker_1"],
        "fanout_group": "family_merge",
        "index": 0,
        "number": 1,
        "count": 2,
        "suffix": "0",
        "value": {
            "source_group": "worker",
            "source_count": 3,
            "size": 2,
            "member_ids": ["worker_0", "worker_1"],
            "members": [
                {
                    "index": 0,
                    "number": 1,
                    "count": 3,
                    "suffix": "0",
                    "value": {"target": "libpng", "seed": 1001, "workspace": "agents/libpng_0"},
                    "template_id": "worker",
                    "node_id": "worker_0",
                    "target": "libpng",
                    "seed": 1001,
                    "workspace": "agents/libpng_0",
                },
                {
                    "index": 1,
                    "number": 2,
                    "count": 3,
                    "suffix": "1",
                    "value": {"target": "libpng", "seed": 1002, "workspace": "agents/libpng_1"},
                    "template_id": "worker",
                    "node_id": "worker_1",
                    "target": "libpng",
                    "seed": 1002,
                    "workspace": "agents/libpng_1",
                },
            ],
            "target": "libpng",
        },
        "template_id": "family_merge",
        "node_id": "family_merge_0",
        "source_group": "worker",
        "source_count": 3,
        "size": 2,
        "member_ids": ["worker_0", "worker_1"],
        "members": [
            {
                "index": 0,
                "number": 1,
                "count": 3,
                "suffix": "0",
                "value": {"target": "libpng", "seed": 1001, "workspace": "agents/libpng_0"},
                "template_id": "worker",
                "node_id": "worker_0",
                "target": "libpng",
                "seed": 1001,
                "workspace": "agents/libpng_0",
            },
            {
                "index": 1,
                "number": 2,
                "count": 3,
                "suffix": "1",
                "value": {"target": "libpng", "seed": 1002, "workspace": "agents/libpng_1"},
                "template_id": "worker",
                "node_id": "worker_1",
                "target": "libpng",
                "seed": 1002,
                "workspace": "agents/libpng_1",
            },
        ],
        "target": "libpng",
    }


def test_render_node_prompt_can_use_current_node_and_group_members(tmp_path: Path):
    pipeline = _grouped_pipeline(tmp_path)
    results = {
        "worker_0": NodeResult(node_id="worker_0", status=NodeStatus.COMPLETED, output="alpha"),
        "worker_1": NodeResult(node_id="worker_1", status=NodeStatus.FAILED, output="beta"),
        "worker_2": NodeResult(node_id="worker_2", status=NodeStatus.COMPLETED, output="gamma"),
        "family_merge_0": NodeResult(node_id="family_merge_0"),
        "family_merge_1": NodeResult(node_id="family_merge_1"),
    }

    rendered = render_node_prompt(pipeline, pipeline.node_map["family_merge_0"], results)

    assert rendered == (
        "family=libpng ids=worker_0,worker_1 :: "
        "worker_0@1001=alpha;"
        "worker_1@1002=beta;"
    )


def test_current_node_context_preserves_runtime_identity_when_member_keys_conflict(tmp_path: Path):
    pipeline = load_pipeline_from_data(
        {
            "name": "fanout-current-collision",
            "working_dir": str(tmp_path),
            "nodes": [
                {
                    "id": "worker",
                    "fanout": {
                        "as": "shard",
                        "values": [
                            {
                                "id": "manifest-id",
                                "agent": "manifest-agent",
                                "depends_on": ["manifest-dependency"],
                                "target": "libpng",
                            }
                        ],
                    },
                    "agent": "codex",
                    "prompt": "worker {{ shard.target }}",
                }
            ],
        },
        base_dir=tmp_path,
    )
    results = {"worker_0": NodeResult(node_id="worker_0")}

    context = build_render_context(pipeline, results, current_node=pipeline.node_map["worker_0"])

    assert context["current"]["id"] == "worker_0"
    assert context["current"]["agent"] == "codex"
    assert context["current"]["depends_on"] == []
    assert context["current"]["target"] == "libpng"
    assert context["current"]["value"] == {
        "id": "manifest-id",
        "agent": "manifest-agent",
        "depends_on": ["manifest-dependency"],
        "target": "libpng",
    }
