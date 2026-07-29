#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/agentic-light-test.XXXXXX")"
trap 'rm -rf "$TMP_ROOT"' EXIT
mkdir -p "$TMP_ROOT/bin" "$TMP_ROOT/brain"
printf '#!/usr/bin/env bash\nprintf "codex:%%s\\n" "$*" >> "$CALLS"\nexit "${FAKE_RC:-0}"\n' > "$TMP_ROOT/bin/codex"
printf '#!/usr/bin/env bash\nprintf "claude:%%s\\n" "$*" >> "$CALLS"\n' > "$TMP_ROOT/bin/claude"
chmod +x "$TMP_ROOT/bin/codex" "$TMP_ROOT/bin/claude"

CALLS="$TMP_ROOT/calls"; export CALLS
PATH="$TMP_ROOT/bin:/usr/bin:/bin"
AGENTIC_LIGHT_PROVIDERS="gemini,codex,claude"
AGENTIC_LIGHT_PRIORITY="gemini,codex,claude"
unset AGENT_TYPE
LOG="$TMP_ROOT/log"
MAX_SECONDS=5
source "$ROOT/System_Config/config.sh"
if [[ "$(date_offset 2024-03-04 4 %Y-%m-%d)" != "2024-03-08" ]]; then
  echo "Darwin date offset failed" >&2
  exit 1
fi
PATH="$TMP_ROOT/bin:/usr/bin:/bin"
BRAIN="$TMP_ROOT/brain"
source "$ROOT/System_Config/run_agent.sh"
run_agent "hello"
grep -q '^codex:exec hello$' "$CALLS"
[[ "$(wc -l < "$CALLS" | tr -d ' ')" = 1 ]]
FAKE_RC=7; export FAKE_RC
if run_agent "fail"; then
  echo "expected provider failure" >&2
  exit 1
else
  rc=$?
fi
[[ "$rc" = 7 ]]
[[ "$(wc -l < "$CALLS" | tr -d ' ')" = 2 ]]
echo "provider test: PASS"
