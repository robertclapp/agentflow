#!/usr/bin/env bash

agentflow_repo_python() {
  local repo_root="$1"
  local python_bin="${AGENTFLOW_PYTHON:-}"

  if [ -n "$python_bin" ]; then
    printf '%s\n' "$python_bin"
    return
  fi

  if [ -x "$repo_root/.venv/bin/python" ]; then
    printf '%s\n' "$repo_root/.venv/bin/python"
    return
  fi

  printf '%s\n' "python3"
}

select_custom_local_kimi_pipeline_mode() {
  local pipeline_mode="${AGENTFLOW_KIMI_PIPELINE_MODE:-bootstrap}"

  case "$pipeline_mode" in
    bootstrap)
      CUSTOM_LOCAL_KIMI_PIPELINE_MODE="$pipeline_mode"
      CUSTOM_LOCAL_KIMI_PIPELINE_SUFFIX=""
      CUSTOM_LOCAL_KIMI_PIPELINE_LABEL="bootstrap"
      CUSTOM_LOCAL_KIMI_EXPECTED_TRIGGER="target.bootstrap"
      CUSTOM_LOCAL_KIMI_PIPELINE_WRITER="write_custom_local_kimi_pipeline"
      ;;
    shell-init)
      CUSTOM_LOCAL_KIMI_PIPELINE_MODE="$pipeline_mode"
      CUSTOM_LOCAL_KIMI_PIPELINE_SUFFIX="-shell-init"
      CUSTOM_LOCAL_KIMI_PIPELINE_LABEL="shell_init"
      CUSTOM_LOCAL_KIMI_EXPECTED_TRIGGER="target.shell_init"
      CUSTOM_LOCAL_KIMI_PIPELINE_WRITER="write_custom_local_kimi_shell_init_pipeline"
      ;;
    shell-wrapper)
      CUSTOM_LOCAL_KIMI_PIPELINE_MODE="$pipeline_mode"
      CUSTOM_LOCAL_KIMI_PIPELINE_SUFFIX="-shell-wrapper"
      CUSTOM_LOCAL_KIMI_PIPELINE_LABEL="target.shell wrapper"
      CUSTOM_LOCAL_KIMI_EXPECTED_TRIGGER="target.shell"
      CUSTOM_LOCAL_KIMI_PIPELINE_WRITER="write_custom_local_kimi_shell_wrapper_pipeline"
      ;;
    *)
      printf 'unsupported AGENTFLOW_KIMI_PIPELINE_MODE: %s\n' "$pipeline_mode" >&2
      return 1
      ;;
  esac
}

write_custom_local_kimi_pipeline() {
  local pipeline_path="$1"
  local pipeline_name="$2"
  local pipeline_description="$3"

  cat >"$pipeline_path" <<YAML
name: $pipeline_name
description: $pipeline_description
working_dir: .
concurrency: 2
local_target_defaults:
  bootstrap: kimi
nodes:
  - id: codex_plan
    agent: codex
    env:
      OPENAI_BASE_URL: ""
    prompt: |
      Reply with exactly: codex ok
    timeout_seconds: 180
    success_criteria:
      - kind: output_contains
        value: codex ok

  - id: claude_review
    agent: claude
    provider: kimi
    prompt: |
      Reply with exactly: claude ok
    timeout_seconds: 180
    success_criteria:
      - kind: output_contains
        value: claude ok
YAML
}

write_custom_local_kimi_shell_init_pipeline() {
  local pipeline_path="$1"
  local pipeline_name="$2"
  local pipeline_description="$3"

  cat >"$pipeline_path" <<YAML
name: $pipeline_name
description: $pipeline_description
working_dir: .
concurrency: 2
local_target_defaults:
  shell: bash
  shell_login: true
  shell_interactive: true
  shell_init: kimi
nodes:
  - id: codex_plan
    agent: codex
    env:
      OPENAI_BASE_URL: ""
    prompt: |
      Reply with exactly: codex ok
    timeout_seconds: 180
    success_criteria:
      - kind: output_contains
        value: codex ok

  - id: claude_review
    agent: claude
    provider: kimi
    prompt: |
      Reply with exactly: claude ok
    timeout_seconds: 180
    success_criteria:
      - kind: output_contains
        value: claude ok
YAML
}

write_custom_local_kimi_shell_wrapper_pipeline() {
  local pipeline_path="$1"
  local pipeline_name="$2"
  local pipeline_description="$3"

  cat >"$pipeline_path" <<YAML
name: $pipeline_name
description: $pipeline_description
working_dir: .
concurrency: 2
local_target_defaults:
  shell: "bash -lic 'command -v kimi >/dev/null 2>&1 && kimi && {command}'"
nodes:
  - id: codex_plan
    agent: codex
    env:
      OPENAI_BASE_URL: ""
    prompt: |
      Reply with exactly: codex ok
    timeout_seconds: 180
    success_criteria:
      - kind: output_contains
        value: codex ok

  - id: claude_review
    agent: claude
    provider: kimi
    prompt: |
      Reply with exactly: claude ok
    timeout_seconds: 180
    success_criteria:
      - kind: output_contains
        value: claude ok
YAML
}
