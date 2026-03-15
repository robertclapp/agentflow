# Pipeline Reference

Pipeline authoring details, execution targets, and per-agent launch behavior.

## Airflow-like Python DAG

```python
from agentflow import DAG, claude, codex, kimi

with DAG("demo", working_dir=".", concurrency=3) as dag:
    plan = codex(task_id="plan", prompt="Inspect the repo and plan the work.")
    implement = claude(
        task_id="implement",
        prompt="Implement the plan:\n\n{{ nodes.plan.output }}",
        tools="read_write",
    )
    review = kimi(
        task_id="review",
        prompt="Review the plan:\n\n{{ nodes.plan.output }}",
        capture="trace",
    )
    merge = codex(
        task_id="merge",
        prompt="Merge the implementation and review outputs.",
    )

    plan >> [implement, review]
    [implement, review] >> merge

spec = dag.to_spec()
```

The Python helpers accept the same per-node kwargs as YAML, including `fanout`.
Import `fanout_count(...)`, `fanout_values(...)`, `fanout_values_path(...)`, `fanout_matrix(...)`, `fanout_matrix_path(...)`, `fanout_group_by(...)`, or `fanout_batches(...)` when you want Python-native fanout payloads instead of raw dictionaries.
`DAG(...)` also accepts `fail_fast`, `node_defaults`, `agent_defaults`, and `local_target_defaults`.
Use `dag.to_json()` or `dag.to_yaml()` to serialize a compact runnable pipeline, `dag.to_payload()` for the raw object structure, and `dag.to_spec()` for the fully expanded in-memory pipeline object.

See `examples/airflow_like.py` for the small static DAG. `examples/airflow_like_fuzz_batched.py` and `examples/airflow_like_fuzz_grouped.py` remain in the repo as advanced fanout examples only.

## Pipeline schema

Each node supports:

- `agent`: `codex`, `claude`, or `kimi`
- `fanout`: `count`, `values`, `values_path`, `matrix`, `matrix_path`, `group_by`, or `batches`, plus optional `as`, `derive`, and matrix-only `include` / `exclude`
- `model`: any model string understood by the backend
- `provider`: a string or a structured provider config with `base_url`, `api_key_env`, headers, and env
- `tools`: `read_only` or `read_write`
- `mcps`: a list of MCP server definitions
- `skills`: a list of local skill paths or names
- `target`: `local`, `container`, or `aws_lambda`
- local target fields: `cwd`, `bootstrap`, `shell`, `shell_login`, `shell_interactive`, and `shell_init`
- `capture`: `final` or `trace`
- `retries` and `retry_backoff_seconds`
- `success_criteria`: output or filesystem checks evaluated after execution

Skill entries are resolved from the pipeline `working_dir`. You can point `skills:` at a plain file, a `.md` file, a home-relative path such as `~/.codex/skills/release-skill`, or a directory that contains `SKILL.md`.

Top-level pipeline controls include:

- `concurrency`: max parallel nodes within a run
- `fail_fast`: skip downstream work after the first failed node
- `node_defaults`: shared node fields merged into every node before validation
- `agent_defaults`: agent-specific shared node fields keyed by `codex`, `claude`, or `kimi`

`node_defaults` is the pipeline-wide baseline. `agent_defaults` is the agent-specific override layer. Explicit node values always win.

```yaml
node_defaults:
  agent: codex
  tools: read_only
  capture: final

agent_defaults:
  codex:
    model: gpt-5-codex
    retries: 1
    retry_backoff_seconds: 1
    extra_args:
      - "--search"
      - "-c"
      - 'model_reasoning_effort="high"'
```

## Fan-out nodes

Use `fanout` when a DAG needs many nearly identical nodes, such as repository sweeps, release checklists, or shardable audits. AgentFlow expands those nodes into an ordinary concrete DAG before validation and execution.

For uniform work, use `fanout.count`:

```yaml
nodes:
  - id: review
    fanout:
      count: 8
      as: shard
    agent: codex
    prompt: |
      You are shard {{ shard.number }} of {{ shard.count }}.
      Use suffix {{ shard.suffix }} for any per-shard paths.

  - id: merge
    agent: codex
    depends_on: [review]
    prompt: |
      {% for shard in fanouts.review.nodes %}
      ## {{ shard.id }}
      {{ shard.output or "(no output)" }}

      {% endfor %}
```

For scaffolds, start with one of the bundled templates:

```bash
agentflow init > pipeline.yaml
agentflow init repo-sweep.yaml --template codex-fanout-repo-sweep
agentflow init repo-sweep-batched.yaml --template codex-repo-sweep-batched
```

The bundled repo sweep examples are [`examples/codex-fanout-repo-sweep.yaml`](/home/shou/agentflow/examples/codex-fanout-repo-sweep.yaml) and [`examples/codex-repo-sweep-batched.yaml`](/home/shou/agentflow/examples/codex-repo-sweep-batched.yaml). The repository also keeps [`examples/airflow_like_fuzz_batched.py`](/home/shou/agentflow/examples/airflow_like_fuzz_batched.py) and [`examples/airflow_like_fuzz_grouped.py`](/home/shou/agentflow/examples/airflow_like_fuzz_grouped.py) as advanced examples only.

When each member needs explicit metadata, use `fanout.values`:

```yaml
nodes:
  - id: review
    fanout:
      as: shard
      values:
        - repo: api
          owner: platform
          priority: high
        - repo: billing
          owner: payments
          priority: medium
    agent: codex
    prompt: |
      Review {{ shard.repo }} for {{ shard.owner }} (priority: {{ shard.priority }}).
```

When the metadata is naturally multi-axis, use `fanout.matrix`. Add `fanout.exclude` and `fanout.include` when a cartesian product needs a few curated adjustments:

```yaml
nodes:
  - id: review
    fanout:
      as: shard
      matrix:
        repo:
          - name: api
            owner: platform
          - name: billing
            owner: payments
        check:
          - kind: security
          - kind: docs
      exclude:
        - name: billing
          kind: docs
      include:
        - repo:
            name: marketing
            owner: growth
          check:
            kind: docs
    agent: codex
    prompt: |
      Run the {{ shard.kind }} review for {{ shard.name }}.
```

When prompts and workdirs should share computed fields, add `fanout.derive`:

```yaml
nodes:
  - id: review
    fanout:
      as: shard
      matrix:
        repo:
          - name: api
          - name: billing
        check:
          - kind: security
          - kind: docs
      derive:
        label: "{{ shard.name }}/{{ shard.kind }}"
        workspace: "agents/{{ shard.name }}_{{ shard.kind }}_{{ shard.suffix }}"
    agent: codex
    target:
      kind: local
      cwd: "{{ shard.workspace }}"
    prompt: |
      Work in {{ shard.workspace }} and summarize {{ shard.label }}.
```

When the roster should live outside the pipeline file, use `fanout.values_path` or `fanout.matrix_path`. `values_path` accepts JSON/YAML lists and CSV rows. `matrix_path` accepts JSON/YAML objects. Relative paths resolve from the pipeline file.

```yaml
nodes:
  - id: review
    fanout:
      as: shard
      values_path: manifests/repos.yaml
    agent: codex
    prompt: |
      Review {{ shard.repo }} for {{ shard.owner }}.
```

When reducers should follow fields already present on another fanout, use `fanout.group_by`:

```yaml
nodes:
  - id: review
    fanout:
      as: shard
      values_path: manifests/repos.yaml
    agent: codex
    prompt: |
      Review {{ shard.repo }} for {{ shard.owner }}.

  - id: owner_merge
    fanout:
      as: owner
      group_by:
        from: review
        fields: [owner]
    agent: codex
    depends_on: [review]
    prompt: |
      Reduce {{ current.owner }} with {{ current.member_ids | length }} scoped inputs.

      {% for shard in current.scope.with_output.nodes %}
      ## {{ shard.node_id }} :: {{ shard.repo }}
      {{ shard.output }}

      {% endfor %}
```

When one final reducer would be too noisy, use `fanout.batches`:

```yaml
nodes:
  - id: review
    fanout:
      count: 128
      as: shard
      derive:
        workspace: "agents/review_{{ shard.suffix }}"

  - id: batch_merge
    fanout:
      as: batch
      batches:
        from: review
        size: 16
    depends_on: [review]
    prompt: |
      Reduce shards {{ current.start_number }} through {{ current.end_number }}.

      {% for shard in current.scope.with_output.nodes %}
      ## {{ shard.node_id }} (status: {{ shard.status }})
      {{ shard.output }}

      {% endfor %}
```

Prompt rendering exposes `fanouts.<group>.nodes`, `outputs`, `values`, `summary`, `completed`, `failed`, `with_output`, and `without_output`. Reducers created from `fanout.group_by` or `fanout.batches` also get `current.member_ids`, `current.members`, and `current.scope`.

Expansion rules:

- A fan-out node accepts exactly one expansion mode: `count`, `values`, `values_path`, `matrix`, `matrix_path`, `group_by`, or `batches`.
- A fan-out node with `id: review` and `count: 8` expands to `review_0` through `review_7`. The suffix is zero-padded when needed.
- `fanout.values` and `fanout.values_path` lift identifier-friendly dictionary keys onto the alias.
- `fanout.matrix` and `fanout.matrix_path` expand the cartesian product in declaration order. Axis dictionaries are available both under the axis name and as lifted keys.
- `fanout.group_by` creates one reducer member per unique field combination from the source fanout, in first-seen order.
- `fanout.batches` partitions a source fanout into fixed-size reducer groups.
- `fanout.exclude` removes matrix members whose metadata matches every field in a selector object. `fanout.include` appends explicit members after exclusions.
- `fanout.derive` adds computed fields after the base expansion is resolved. Derived fields render in declaration order.
- `fanout.as` picks the template variable name for pre-validation substitution.
- Ordinary runtime prompt templates such as `{{ nodes.prepare.output }}` are left intact and still render at execution time.
- A downstream `depends_on: [review]` expands to all members of the `review` group.

Runtime numeric settings are validated up front: `concurrency` must be at least `1`, `timeout_seconds` must be greater than `0`, and both `retries` and `retry_backoff_seconds` must be non-negative.

MCP definitions are also validated before launch: `stdio` servers require `command` and reject HTTP-only fields such as `url`, `streamable_http` servers require `url` and reject stdio-only fields such as `command`, and MCP server names must be unique within a node.

Built-in provider shorthands:

- `codex`: `openai`
- `claude`: `anthropic`, `kimi`
- `kimi`: `kimi`, `moonshot`, `moonshot-ai`

`provider: kimi` is intentionally rejected on `codex` nodes. Codex requires an OpenAI Responses API backend, and Kimi's public endpoints do not expose `/responses`.

When both `provider.env` and `node.env` define the same variable, `node.env` wins. For Claude-compatible Kimi setups, `doctor` and `inspect` also recognize providers that set `ANTHROPIC_BASE_URL=https://api.kimi.com/coding/` in `provider.env` even when `provider.base_url` is omitted.

## Execution targets

### Local

Runs the prepared agent command directly on the host. Set `target.shell` to wrap the command in a specific shell, such as `bash -lc`. If you provide a shell name without an explicit command flag, AgentFlow uses `-c` by default. Opt into startup file loading with `shell_login: true` and `shell_interactive: true`.

`target.cwd` controls the local node working directory. Absolute paths are used as-is; relative paths are resolved from the pipeline `working_dir`. AgentFlow creates that directory right before launch when it does not already exist.

The local bootstrap fields `shell_login`, `shell_interactive`, and `shell_init` require `target.shell`. For the common Kimi helper case, `target.bootstrap: kimi` expands to the same `bash` + login + interactive + `shell_init` setup automatically.

```yaml
target:
  kind: local
  bootstrap: kimi
```

When most local nodes share the same shell bootstrap, move that block to top-level `local_target_defaults` and only override the nodes that differ.

```yaml
local_target_defaults:
  bootstrap: kimi

nodes:
  - id: codex_plan
    agent: codex
    prompt: Reply with exactly: codex ok

  - id: claude_review
    agent: claude
    provider: kimi
    prompt: Reply with exactly: claude ok
    target:
      cwd: review
```

If one local node should not inherit the shared bootstrap, set `target.bootstrap: null` on that node.
`shell_init` is treated as a bootstrap prerequisite: if it exits non-zero, AgentFlow does not launch the wrapped agent command.

### Container

Wraps the command in `docker run`, mounts the working directory, runtime directory, and the AgentFlow app, then streams stdout and stderr back into the run trace.

### AWS Lambda

Invokes `agentflow.remote.lambda_handler.handler`. The payload contains the prepared command, environment, runtime files, and execution metadata so the Lambda package can execute the node remotely.

## Agent notes

### Codex

- Uses `codex exec --json`
- Maps tools mode to Codex sandboxing
- Keeps model-only Codex nodes on the ambient CLI login path instead of forcing an isolated `CODEX_HOME`
- Writes `CODEX_HOME/config.toml` only when provider or MCP selection requires an isolated home

### Claude

- Uses `claude -p ... --output-format stream-json --verbose`
- Passes `--tools` according to the read-only vs read-write policy
- Writes a per-node MCP JSON config and passes it with `--mcp-config`

### Kimi

- Uses the active Python interpreter via `sys.executable -m agentflow.remote.kimi_bridge`
- Emits a Kimi-style JSON-RPC event stream
- Calls Moonshot's OpenAI-compatible chat completions API
- Provides a small built-in tool layer for read, search, write, and shell actions
