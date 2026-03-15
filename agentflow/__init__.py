"""AgentFlow public package surface."""

from agentflow.dsl import (
    DAG,
    claude,
    codex,
    fanout_batches,
    fanout_count,
    fanout_group_by,
    fanout_matrix,
    fanout_matrix_path,
    fanout_values,
    fanout_values_path,
    kimi,
)


def create_app(*args, **kwargs):
    from agentflow.app import create_app as _create_app

    return _create_app(*args, **kwargs)


__all__ = [
    "DAG",
    "claude",
    "codex",
    "fanout_batches",
    "fanout_count",
    "fanout_group_by",
    "fanout_matrix",
    "fanout_matrix_path",
    "fanout_values",
    "fanout_values_path",
    "kimi",
    "create_app",
]
