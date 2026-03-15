# AgentFlow

AgentFlow is a general agent orchestration package for dependency-aware DAGs. It runs `codex`, `claude`, and `kimi` nodes locally, in containers, or on AWS Lambda.

## Quickstart

Requirements:

- Python 3.11+
- The agent CLIs your pipeline uses

Install:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .[dev]
```

Scaffold and run a pipeline:

```bash
agentflow templates
agentflow init > pipeline.yaml
agentflow validate pipeline.yaml
agentflow run pipeline.yaml
```

Useful next commands:

```bash
agentflow init repo-sweep.yaml --template codex-fanout-repo-sweep
agentflow init repo-sweep-batched.yaml --template codex-repo-sweep-batched
agentflow inspect pipeline.yaml
agentflow serve --host 127.0.0.1 --port 8000
agentflow smoke
```

## Bundled Templates

- `pipeline`: generic Codex/Claude/Kimi starter DAG
- `codex-fanout-repo-sweep`: small repo review fanout
- `codex-repo-sweep-batched`: large repo sweep with staged batch reducers
- `local-kimi-smoke`: shortest real-agent local smoke DAG
- `local-kimi-shell-init-smoke`: explicit `shell_init: kimi` smoke DAG
- `local-kimi-shell-wrapper-smoke`: explicit `target.shell` wrapper smoke DAG

## Fanout

AgentFlow keeps the framework generic. The core fanout surface is:

- `count`
- `values`
- `values_path`
- `matrix`
- `matrix_path`
- `group_by`
- `batches`
- optional `derive`, plus matrix-only `include` and `exclude`

Use these primitives directly in YAML or via the Python DSL helpers.

## Examples

The repo keeps two advanced fuzz examples as examples only, not as framework features:

- `examples/airflow_like_fuzz_batched.py`
- `examples/airflow_like_fuzz_grouped.py`

Those examples show how to model a large shard campaign using only the generic fanout primitives.
