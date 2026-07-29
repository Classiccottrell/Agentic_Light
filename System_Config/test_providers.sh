#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/agentic-light-test.XXXXXX")"
trap 'rm -rf "$TMP_ROOT"' EXIT
mkdir -p "$TMP_ROOT/bin" "$TMP_ROOT/brain"
for provider in claude agy codex ollama; do
  printf '#!/usr/bin/env bash\nprintf "%s:%%s\\n" "$*" >> "$CALLS"\nexit "${FAKE_RC:-0}"\n' "$provider" > "$TMP_ROOT/bin/$provider"
  chmod +x "$TMP_ROOT/bin/$provider"
done

CALLS="$TMP_ROOT/calls"; export CALLS
PATH="$TMP_ROOT/bin:/usr/bin:/bin"
AGENTIC_LIGHT_PROVIDERS="gemini,codex,claude"
AGENTIC_LIGHT_PRIORITY="gemini,codex,claude"
AGENTIC_LIGHT_MODEL_GEMINI="gemini-test"
unset AGENT_TYPE
LOG="$TMP_ROOT/log"; MAX_SECONDS=5
source "$ROOT/System_Config/config.sh"
[[ "$(date_offset 2024-03-04 4 %Y-%m-%d)" = "2024-03-08" ]]
PATH="$TMP_ROOT/bin:/usr/bin:/bin"
BRAIN="$TMP_ROOT/brain"
source "$ROOT/System_Config/run_agent.sh"

run_agent "gemini prompt"
grep -q '^agy:-p gemini prompt --model gemini-test --sandbox --approval-mode auto_edit$' "$CALLS"

rm "$TMP_ROOT/bin/agy"; : > "$CALLS"
AGENTIC_LIGHT_MODEL_CODEX="codex-test"
resolve_agent_provider
run_agent "codex prompt"
grep -q '^codex:exec --sandbox workspace-write --model codex-test codex prompt$' "$CALLS"

FAKE_RC=7; export FAKE_RC
if run_agent "fail"; then exit 1; else rc=$?; fi
[[ "$rc" = 7 ]]
[[ "$(wc -l < "$CALLS" | tr -d ' ')" = 2 ]]
unset FAKE_RC

AGENTIC_LIGHT_PROVIDERS="claude"; AGENTIC_LIGHT_PRIORITY="claude"
AGENTIC_LIGHT_MODEL_CLAUDE="claude-test"
: > "$CALLS"
resolve_agent_provider
run_agent "claude prompt"
grep -q '^claude:-p claude prompt --model claude-test --allowedTools Read,Write,Edit,Glob,Grep --disallowedTools Bash,KillShell,Task,WebFetch,WebSearch,NotebookEdit --permission-mode acceptEdits --max-budget-usd 2.00$' "$CALLS"
[[ "$(wc -l < "$CALLS" | tr -d ' ')" = 1 ]]

validate_provider_lists "claude,codex" "codex,claude"
for pair in "claude,claude|claude" "wat|wat" "claude,codex|claude" "claude,|claude"; do
  left="${pair%%|*}"; right="${pair#*|}"
  ! validate_provider_lists "$left" "$right"
done

rm "$TMP_ROOT/bin/codex" "$TMP_ROOT/bin/claude"; : > "$CALLS"
AGENTIC_LIGHT_PROVIDERS="codex,claude"; AGENTIC_LIGHT_PRIORITY="codex,claude"
if run_agent "none"; then exit 1; else rc=$?; fi
[[ "$rc" = 127 ]]

AGENTIC_LIGHT_PROVIDERS="ollama"; AGENTIC_LIGHT_PRIORITY="ollama"
resolve_agent_provider
if run_agent "write"; then exit 1; else rc=$?; fi
[[ "$rc" = 64 && ! -s "$CALLS" ]]
echo "provider test: PASS"
