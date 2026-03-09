#!/usr/bin/env bash
set -euo pipefail

expected_anthropic_base_url='https://api.kimi.com/coding/'

EXPECTED_ANTHROPIC_BASE_URL="$expected_anthropic_base_url" bash -lic '
command -v kimi >/dev/null 2>&1
kimi >/dev/null
[ -n "${ANTHROPIC_API_KEY:-}" ] || {
  echo "kimi did not export ANTHROPIC_API_KEY" >&2
  exit 1
}
[ -n "${ANTHROPIC_BASE_URL:-}" ] || {
  echo "kimi did not export ANTHROPIC_BASE_URL" >&2
  exit 1
}
[ "${ANTHROPIC_BASE_URL%/}" = "${EXPECTED_ANTHROPIC_BASE_URL%/}" ] || {
  printf "Unexpected ANTHROPIC_BASE_URL=%s\n" "$ANTHROPIC_BASE_URL" >&2
  printf "Expected ANTHROPIC_BASE_URL=%s\n" "$EXPECTED_ANTHROPIC_BASE_URL" >&2
  exit 1
}
printf "ANTHROPIC_BASE_URL=%s\n" "$ANTHROPIC_BASE_URL"
if codex login status >/dev/null 2>&1; then
  printf "codex auth: login\n"
elif [ -n "${OPENAI_API_KEY:-}" ]; then
  printf "codex auth: OPENAI_API_KEY\n"
else
  echo "codex is not logged in and OPENAI_API_KEY is not exported" >&2
  exit 1
fi
printf "codex: "
codex --version
printf "claude: "
claude --version
' 2> >(
  grep -v \
    -e '^bash: cannot set terminal process group (' \
    -e '^bash: initialize_job_control: no job control in background:' \
    -e '^bash: no job control in this shell$' >&2
)
