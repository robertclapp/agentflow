from __future__ import annotations

from pathlib import Path

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
    retries: 1
    retry_backoff_seconds: 1
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
    example_path = Path(__file__).resolve().parents[1] / "examples" / "pipeline.yaml"
    if example_path.exists():
        return example_path.read_text(encoding="utf-8")
    return DEFAULT_PIPELINE_YAML
