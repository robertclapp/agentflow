#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
. "$script_dir/custom-local-kimi-helpers.sh"
python_bin="$(agentflow_repo_python "$repo_root")"
bundled_smoke_pipeline="$repo_root/examples/local-real-agents-kimi-smoke.yaml"

run_step() {
  local label="$1"
  shift

  printf "\n== %s ==\n" "$label"
  "$@"
}

run_step "Shell toolchain" bash "$script_dir/verify-local-kimi-shell.sh"
run_step "Bundled toolchain-local" agentflow_run_with_timeout "$python_bin" "$python_bin" -m agentflow toolchain-local --output summary
run_step "Bundled inspect-local" agentflow_run_with_timeout "$python_bin" "$python_bin" -m agentflow inspect "$bundled_smoke_pipeline" --output summary
run_step "Bundled doctor-local" agentflow_run_with_timeout "$python_bin" "$python_bin" -m agentflow doctor "$bundled_smoke_pipeline" --output summary
run_step "Bundled smoke-local" agentflow_run_with_timeout "$python_bin" "$python_bin" -m agentflow smoke "$bundled_smoke_pipeline" --output summary
run_step "Bundled run-local" bash "$script_dir/verify-bundled-local-kimi-run.sh"
run_step "External custom doctor" bash "$script_dir/verify-custom-local-kimi-doctor.sh"
run_step "External custom doctor (shell_init)" env AGENTFLOW_KIMI_PIPELINE_MODE=shell-init bash "$script_dir/verify-custom-local-kimi-doctor.sh"
run_step "External custom doctor (target.shell)" env AGENTFLOW_KIMI_PIPELINE_MODE=shell-wrapper bash "$script_dir/verify-custom-local-kimi-doctor.sh"
run_step "External custom inspect" bash "$script_dir/verify-custom-local-kimi-inspect.sh"
run_step "External custom inspect (shell_init)" env AGENTFLOW_KIMI_PIPELINE_MODE=shell-init bash "$script_dir/verify-custom-local-kimi-inspect.sh"
run_step "External custom inspect (target.shell)" env AGENTFLOW_KIMI_PIPELINE_MODE=shell-wrapper bash "$script_dir/verify-custom-local-kimi-inspect.sh"
run_step "Bundled check-local" agentflow_run_with_timeout "$python_bin" "$python_bin" -m agentflow check-local --output summary
run_step "External custom check-local" bash "$script_dir/verify-custom-local-kimi-pipeline.sh"
run_step "External custom check-local (shell_init)" bash "$script_dir/verify-custom-local-kimi-shell-init.sh"
run_step "External custom check-local (target.shell)" env AGENTFLOW_KIMI_PIPELINE_MODE=shell-wrapper bash "$script_dir/verify-custom-local-kimi-pipeline.sh"
run_step "External custom run" bash "$script_dir/verify-custom-local-kimi-run.sh"
run_step "External custom run (shell_init)" env AGENTFLOW_KIMI_PIPELINE_MODE=shell-init bash "$script_dir/verify-custom-local-kimi-run.sh"
run_step "External custom run (target.shell)" env AGENTFLOW_KIMI_PIPELINE_MODE=shell-wrapper bash "$script_dir/verify-custom-local-kimi-run.sh"
