from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Mapping


@dataclass(frozen=True)
class BundledTemplateParameter:
    name: str
    description: str
    default: str


@dataclass(frozen=True)
class BundledTemplate:
    name: str
    example_name: str
    description: str
    parameters: tuple[BundledTemplateParameter, ...] = ()
    support_files: tuple[str, ...] = ()


@dataclass(frozen=True)
class RenderedBundledTemplateFile:
    relative_path: str
    content: str


@dataclass(frozen=True)
class RenderedBundledTemplate:
    yaml: str
    support_files: tuple[RenderedBundledTemplateFile, ...] = ()


_DEFAULT_CODEX_REPO_SWEEP_BATCHED_SHARDS = 128
_DEFAULT_CODEX_REPO_SWEEP_BATCHED_BATCH_SIZE = 16
_DEFAULT_CODEX_REPO_SWEEP_BATCHED_CONCURRENCY = 32
_DEFAULT_CODEX_REPO_SWEEP_BATCHED_FOCUS = "bugs, risky code paths, and missing tests"


def _parse_positive_template_int(template_name: str, field_name: str, raw_value: str) -> int:
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"template `{template_name}` expects `{field_name}` to be an integer, got `{raw_value}`") from exc
    if value < 1:
        raise ValueError(f"template `{template_name}` expects `{field_name}` to be at least 1, got `{raw_value}`")
    return value


def _template_string_value(template_name: str, field_name: str, raw_value: str | None, *, default: str) -> str:
    value = (raw_value if raw_value is not None else default).strip()
    if not value:
        raise ValueError(f"template `{template_name}` expects `{field_name}` to be a non-empty string")
    return value


def _validate_template_settings(template_name: str, raw_values: Mapping[str, str], *, allowed: set[str]) -> None:
    unknown = sorted(set(raw_values) - allowed)
    if unknown:
        supported = ", ".join(f"`{name}`" for name in sorted(allowed))
        unknown_display = ", ".join(f"`{name}`" for name in unknown)
        raise ValueError(
            f"template `{template_name}` does not recognize {unknown_display}; supported settings: {supported}"
        )


def _render_codex_repo_sweep_batched_template(values: Mapping[str, str] | None = None) -> RenderedBundledTemplate:
    template_name = "codex-repo-sweep-batched"
    raw_values = dict(values or {})
    allowed = {"shards", "batch_size", "concurrency", "focus", "name", "working_dir"}
    _validate_template_settings(template_name, raw_values, allowed=allowed)

    shards = _parse_positive_template_int(
        template_name,
        "shards",
        raw_values.get("shards", str(_DEFAULT_CODEX_REPO_SWEEP_BATCHED_SHARDS)),
    )
    batch_size = _parse_positive_template_int(
        template_name,
        "batch_size",
        raw_values.get("batch_size", str(_DEFAULT_CODEX_REPO_SWEEP_BATCHED_BATCH_SIZE)),
    )
    concurrency = _parse_positive_template_int(
        template_name,
        "concurrency",
        raw_values.get("concurrency", str(_DEFAULT_CODEX_REPO_SWEEP_BATCHED_CONCURRENCY)),
    )
    focus = _template_string_value(
        template_name,
        "focus",
        raw_values.get("focus"),
        default=_DEFAULT_CODEX_REPO_SWEEP_BATCHED_FOCUS,
    )
    name = _template_string_value(
        template_name,
        "name",
        raw_values.get("name"),
        default=f"codex-repo-sweep-batched-{shards}",
    )
    working_dir = _template_string_value(
        template_name,
        "working_dir",
        raw_values.get("working_dir"),
        default=f"./codex_repo_sweep_batched_{shards}",
    )
    batch_count = max(1, (shards + batch_size - 1) // batch_size)

    rendered_yaml = Template(
        """# Configurable large-scale Codex repository sweep
#
# This scaffold fans out a large repo review into many Codex shards, then
# inserts batched reducers so a 128-worker sweep still lands in a readable
# maintainer handoff.
#
# Usage:
#   agentflow init repo-sweep-batched.yaml --template codex-repo-sweep-batched
#   agentflow init repo-sweep-security.yaml --template codex-repo-sweep-batched --set shards=64 --set batch_size=8 --set concurrency=16 --set focus="security bugs, privilege boundaries, and missing coverage"
#   agentflow inspect repo-sweep-batched.yaml --output summary
#   agentflow run repo-sweep-batched.yaml

name: $name
description: Configurable $shards-shard Codex repository sweep with automatic $batch_count-way batched reducers for maintainer review.
working_dir: $working_dir
concurrency: $concurrency

node_defaults:
  agent: codex
  tools: read_only
  capture: final
  timeout_seconds: 900

agent_defaults:
  codex:
    model: gpt-5-codex
    retries: 1
    retry_backoff_seconds: 1
    extra_args:
      - "--search"
      - "-c"
      - 'model_reasoning_effort="high"'

nodes:
  - id: prepare
    prompt: |
      Inspect the repository and write shared instructions for a $shards-shard Codex maintainer sweep.

      Review goal:
      - Focus on $focus.
      - Prefer concrete bugs, risky assumptions, or clearly missing tests over generic style feedback.
      - Make the sweep reproducible by using a stable path-hash modulo strategy across $shards shards.
      - Call out hot subsystems or directories that deserve extra attention.
      - End with a compact rubric the reducers can use to rank findings by severity and confidence.

  - id: sweep
    fanout:
      count: $shards
      as: shard
      derive:
        label: "slice {{ shard.number }}/{{ shard.count }}"
    depends_on: [prepare]
    prompt: |
      You are Codex repository sweep shard {{ shard.number }} of {{ shard.count }}.

      Shared plan:
      {{ nodes.prepare.output }}

      Your shard contract:
      - Stable identity: {{ shard.node_id }} (suffix {{ shard.suffix }})
      - Review files whose stable path hash modulo {{ shard.count }} equals {{ shard.index }}.
      - Focus on $focus.
      - Avoid duplicate work outside your modulo slice unless you need one small neighboring file for context.
      - Report concrete findings first. Include file paths, the failure mode, and the missing validation or test if applicable.
      - If your slice is quiet, report the most suspicious code paths worth a second pass.

  - id: batch_merge
    fanout:
      as: batch
      batches:
        from: sweep
        size: $batch_size
    depends_on: [sweep]
    prompt: |
      Prepare the maintainer handoff for review batch {{ current.number }} of {{ current.count }}.

      Batch coverage:
      - Source group: {{ current.source_group }}
      - Total source shards: {{ current.source_count }}
      - Batch size: {{ current.scope.size }}
      - Shard range: {{ current.start_number }} through {{ current.end_number }}
      - Shard ids: {{ current.scope.ids | join(", ") }}
      - Completed shards: {{ current.scope.summary.completed }}
      - Failed shards: {{ current.scope.summary.failed }}
      - Silent shards: {{ current.scope.summary.without_output }}

      Rank the batch findings by severity, then confidence, then breadth of impact. If the batch is quiet, say so explicitly and point to the slices that should be rerun or retargeted.

      {% for shard in current.scope.with_output.nodes %}
      ## {{ shard.label }} :: {{ shard.node_id }} (status: {{ shard.status }})
      {{ shard.output }}

      {% endfor %}
      {% if current.scope.failed.size %}
      Failed slices:
      {% for shard in current.scope.failed.nodes %}
      - {{ shard.id }} :: {{ shard.label }}
      {% endfor %}
      {% endif %}
      {% if not current.scope.with_output.size %}
      No slice in this batch produced reducer-ready output. Say that explicitly and use the failed shard list to suggest retargeting.
      {% endif %}

  - id: merge
    depends_on: [batch_merge]
    prompt: |
      Consolidate this $shards-shard repository sweep into a maintainer summary.
      Start with the highest-risk findings, then repeated patterns across batches, and end with quiet or failed slices that need a follow-up pass.

      Campaign status:
      - Total review shards: {{ fanouts.sweep.size }}
      - Completed shards: {{ fanouts.sweep.summary.completed }}
      - Failed shards: {{ fanouts.sweep.summary.failed }}
      - Silent shards: {{ fanouts.sweep.summary.without_output }}
      - Batch reducers completed: {{ fanouts.batch_merge.summary.completed }} / {{ fanouts.batch_merge.size }}

      {% for batch in fanouts.batch_merge.with_output.nodes %}
      ## Batch {{ batch.number }} :: shards {{ batch.start_number }}-{{ batch.end_number }} (status: {{ batch.status }})
      {{ batch.output }}

      {% endfor %}
      {% if fanouts.batch_merge.without_output.size %}
      Batch reducers needing attention:
      {% for batch in fanouts.batch_merge.without_output.nodes %}
      - {{ batch.id }} :: shards {{ batch.start_number }}-{{ batch.end_number }} (status: {{ batch.status }})
      {% endfor %}
      {% endif %}
"""
    ).substitute(
        name=name,
        shards=shards,
        batch_size=batch_size,
        batch_count=batch_count,
        concurrency=concurrency,
        working_dir=working_dir,
        focus=focus,
    )
    return RenderedBundledTemplate(yaml=rendered_yaml)


_BUNDLED_TEMPLATES = (
    BundledTemplate(
        name="pipeline",
        example_name="pipeline.yaml",
        description="Generic Codex/Claude/Kimi starter DAG.",
    ),
    BundledTemplate(
        name="codex-fanout-repo-sweep",
        example_name="codex-fanout-repo-sweep.yaml",
        description="Codex repo sweep that fans out one plan into 8 review shards and a final merge.",
    ),
    BundledTemplate(
        name="codex-repo-sweep-batched",
        example_name="codex-repo-sweep-batched.yaml",
        description="Configurable large-scale Codex repo sweep that uses `fanout.batches` plus `node_defaults` / `agent_defaults` to keep 128-shard maintainer reviews readable.",
        parameters=(
            BundledTemplateParameter(
                name="shards",
                description="Number of Codex review workers to fan out.",
                default=str(_DEFAULT_CODEX_REPO_SWEEP_BATCHED_SHARDS),
            ),
            BundledTemplateParameter(
                name="batch_size",
                description="Number of review shards each intermediate reducer should own.",
                default=str(_DEFAULT_CODEX_REPO_SWEEP_BATCHED_BATCH_SIZE),
            ),
            BundledTemplateParameter(
                name="concurrency",
                description="Maximum number of review shards to run in parallel.",
                default=str(_DEFAULT_CODEX_REPO_SWEEP_BATCHED_CONCURRENCY),
            ),
            BundledTemplateParameter(
                name="focus",
                description="Shared review focus for the batched maintainer sweep.",
                default=_DEFAULT_CODEX_REPO_SWEEP_BATCHED_FOCUS,
            ),
            BundledTemplateParameter(
                name="name",
                description="Pipeline name override.",
                default="codex-repo-sweep-batched-<shards>",
            ),
            BundledTemplateParameter(
                name="working_dir",
                description="Pipeline working directory override.",
                default="./codex_repo_sweep_batched_<shards>",
            ),
        ),
    ),
    BundledTemplate(
        name="local-kimi-smoke",
        example_name="local-real-agents-kimi-smoke.yaml",
        description="Local Codex plus Claude-on-Kimi smoke DAG using `bootstrap: kimi`.",
    ),
    BundledTemplate(
        name="local-kimi-shell-init-smoke",
        example_name="local-real-agents-kimi-shell-init-smoke.yaml",
        description="Local Codex plus Claude-on-Kimi smoke DAG using explicit `shell_init: kimi`.",
    ),
    BundledTemplate(
        name="local-kimi-shell-wrapper-smoke",
        example_name="local-real-agents-kimi-shell-wrapper-smoke.yaml",
        description="Local Codex plus Claude-on-Kimi smoke DAG using an explicit `target.shell` Kimi wrapper.",
    ),
)

_BUNDLED_TEMPLATE_FILES = {template.name: template.example_name for template in _BUNDLED_TEMPLATES}
_BUNDLED_TEMPLATE_SUPPORT_FILES = {template.name: template.support_files for template in _BUNDLED_TEMPLATES}
_BUNDLED_TEMPLATE_RENDERERS = {
    "codex-repo-sweep-batched": _render_codex_repo_sweep_batched_template,
}

DEFAULT_PIPELINE_YAML = """name: parallel-code-orchestration
description: Codex plans, Claude implements, and Kimi reviews in parallel before a final Codex merge.
working_dir: .
concurrency: 3
nodes:
  - id: plan
    agent: codex
    model: gpt-5-codex
    tools: read_only
    capture: final
    prompt: |
      Inspect the repository and create a short implementation plan.

  - id: implement
    agent: claude
    model: claude-sonnet-4-5
    tools: read_write
    capture: final
    depends_on: [plan]
    prompt: |
      Use the plan below and implement the requested change.

      Plan:
      {{ nodes.plan.output }}

  - id: review
    agent: kimi
    model: kimi-k2-turbo-preview
    tools: read_only
    capture: trace
    depends_on: [plan]
    prompt: |
      Review the proposed implementation plan.

      Plan:
      {{ nodes.plan.output }}

  - id: merge
    agent: codex
    model: gpt-5-codex
    tools: read_only
    depends_on: [implement, review]
    success_criteria:
      - kind: output_contains
        value: success
    prompt: |
      Combine these two perspectives into a final release summary and include the word success.

      Implementation output:
      {{ nodes.implement.output }}

      Review trace:
      {{ nodes.review.output }}
"""


def load_default_pipeline_yaml() -> str:
    example_path = bundled_example_path("pipeline.yaml")
    if example_path.exists():
        return example_path.read_text(encoding="utf-8")
    return DEFAULT_PIPELINE_YAML


def bundled_example_path(name: str) -> Path:
    return Path(__file__).resolve().parents[1] / "examples" / name


def bundled_templates() -> tuple[BundledTemplate, ...]:
    return _BUNDLED_TEMPLATES


def bundled_template_names() -> tuple[str, ...]:
    return tuple(template.name for template in bundled_templates())


def bundled_template_path(name: str) -> Path:
    try:
        example_name = _BUNDLED_TEMPLATE_FILES[name]
    except KeyError as exc:
        available = ", ".join(f"`{template}`" for template in bundled_template_names())
        raise ValueError(
            f"unknown bundled template `{name}` (available: {available}; see `agentflow templates`)"
        ) from exc
    return bundled_example_path(example_name)


def bundled_template_support_files(name: str) -> tuple[str, ...]:
    try:
        return _BUNDLED_TEMPLATE_SUPPORT_FILES[name]
    except KeyError as exc:
        available = ", ".join(f"`{template}`" for template in bundled_template_names())
        raise ValueError(
            f"unknown bundled template `{name}` (available: {available}; see `agentflow templates`)"
        ) from exc


def render_bundled_template(name: str, values: Mapping[str, str] | None = None) -> RenderedBundledTemplate:
    template_values = dict(values or {})
    if name == "pipeline":
        if template_values:
            raise ValueError("template `pipeline` does not accept `--set` values")
        return RenderedBundledTemplate(yaml=load_default_pipeline_yaml())

    renderer = _BUNDLED_TEMPLATE_RENDERERS.get(name)
    if renderer is not None:
        return renderer(template_values)

    template_path = bundled_template_path(name)
    if template_values:
        raise ValueError(f"template `{name}` does not accept `--set` values")

    rendered_support_files = tuple(
        RenderedBundledTemplateFile(
            relative_path=relative_path,
            content=(template_path.parent / relative_path).resolve().read_text(encoding="utf-8"),
        )
        for relative_path in bundled_template_support_files(name)
    )
    return RenderedBundledTemplate(
        yaml=template_path.read_text(encoding="utf-8"),
        support_files=rendered_support_files,
    )


def load_bundled_template_yaml(name: str, values: Mapping[str, str] | None = None) -> str:
    return render_bundled_template(name, values=values).yaml


def default_smoke_pipeline_path() -> str:
    return str(bundled_example_path("local-real-agents-kimi-smoke.yaml"))
