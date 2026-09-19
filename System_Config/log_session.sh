#!/usr/bin/env bash
# log_session.sh — launcher-level session logger (no AI/LLM call; pure
# deterministic formatting/append). Called once by pipeline/run.sh after
# the coder step completes; not wired into run_agent.sh itself (see
# pipeline/run.sh's own comment on why: run_agent() is also called once
# per clip by daily_ingest.sh, and logging there would break "exactly
# once" per pipeline run).
#
# Usage: log_session.sh --provider <name> --role <role> --status <exit-code> --reason <exit|timeout|signal|refused> [--note <path>]
#        log_session.sh --self-test
#
# Appends one line under the current ISO week's weekly note's
# '## Agent Sessions' heading (brain/weekly_logs/YYYY/YYYY-Www.md). Also
# matches the legacy '## Claude Sessions' heading still present in notes
# created before the rename, so an older note gets one section stamped
# in place rather than a second duplicate heading. --note overrides the
# target file (used by --self-test to avoid touching the real vault).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BRAIN="$ROOT/brain"

usage() {
  echo "Usage: $(basename "$0") --provider <name> --role <role> --status <exit-code> --reason <exit|timeout|signal|refused> [--note <path>]" >&2
  echo "       $(basename "$0") --self-test" >&2
}

# append_session_line <note-path> <provider> <role> <status> <reason>
# Inserts under '## Agent Sessions', before the next '---' separator (or at
# EOF if the heading has no trailing separator yet). Creates the heading
# (with the standard sub-line) at EOF if the note has no such section yet.
append_session_line() {
  local note="$1" provider="$2" role="$3" status="$4" reason="$5" line ts
  ts="$(date +%Y-%m-%d\ %H:%M:%S)"
  line="- ${ts}: ${provider} / ${role} — exit ${status} (${reason})"

  if grep -qE "^## (Agent|Claude) Sessions[[:space:]]*$" "$note"; then
    awk -v line="$line" '
      $0=="## Agent Sessions" || $0=="## Claude Sessions" { incs=1 }
      incs && /^---[[:space:]]*$/ && !done { print line; done=1; incs=0 }
      { print }
      END { if (!done) print line }
    ' "$note" > "$note.tmp" && mv "$note.tmp" "$note"
  else
    {
      echo ""
      echo "## Agent Sessions"
      echo "> Auto-appended after each launcher-completed session."
      echo "$line"
    } >> "$note"
  fi
}

# current_week_note — prints brain/weekly_logs/YYYY/YYYY-Www.md for today.
current_week_note() {
  local year week
  year="$(date +%G)"
  week="$(date +%V)"
  echo "$BRAIN/weekly_logs/${year}/${year}-W${week}.md"
}

self_test() {
  local tmp
  tmp="$(mktemp -t log_session_selftest.XXXXXX).md"
  cat > "$tmp" <<'EOF'
# W99 — Self-Test
---

## Decisions
| Decision | Rationale | Date |
|----------|-----------|------|

---
EOF
  append_session_line "$tmp" "claude" "coder" "0" "exit"
  grep -qF "## Agent Sessions" "$tmp" || { echo "FAIL: heading not created" >&2; exit 1; }
  [[ "$(grep -cF "exit 0 (exit)" "$tmp")" -eq 1 ]] || { echo "FAIL: line 1 not appended" >&2; exit 1; }

  append_session_line "$tmp" "codex" "qa" "1" "timeout"
  [[ "$(grep -cF '## Agent Sessions' "$tmp")" -eq 1 ]] || { echo "FAIL: duplicate heading" >&2; exit 1; }
  [[ "$(grep -c '^- 20' "$tmp")" -eq 2 ]] || { echo "FAIL: two runs did not yield two lines" >&2; exit 1; }

  rm -f "$tmp"

  # Legacy-heading compat: a pre-rename note must be stamped in place, not
  # given a second, duplicate section.
  tmp="$(mktemp -t log_session_selftest.XXXXXX).md"
  cat > "$tmp" <<'EOF'
# W99 — Self-Test
---

## Claude Sessions
> Auto-appended after each AI work session.
-

---
EOF
  append_session_line "$tmp" "gemini" "coder" "0" "exit"
  [[ "$(grep -cF '## Claude Sessions' "$tmp")" -eq 1 ]] || { echo "FAIL: legacy heading duplicated" >&2; exit 1; }
  grep -qF "## Agent Sessions" "$tmp" && { echo "FAIL: unexpected new heading alongside legacy one" >&2; exit 1; }
  [[ "$(grep -cF 'exit 0 (exit)' "$tmp")" -eq 1 ]] || { echo "FAIL: line not stamped into legacy heading" >&2; exit 1; }
  rm -f "$tmp"

  echo "self-test OK"
}

PROVIDER="" ROLE="" STATUS="" REASON="" NOTE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --self-test) self_test; exit 0 ;;
    --provider) PROVIDER="$2"; shift 2 ;;
    --role) ROLE="$2"; shift 2 ;;
    --status) STATUS="$2"; shift 2 ;;
    --reason) REASON="$2"; shift 2 ;;
    --note) NOTE="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown arg: $1" >&2; usage; exit 1 ;;
  esac
done

[[ -n "$PROVIDER" && -n "$ROLE" && -n "$STATUS" && -n "$REASON" ]] || { usage; exit 1; }
case "$REASON" in exit|timeout|signal|refused) ;; *) echo "invalid --reason: $REASON" >&2; exit 1 ;; esac

NOTE="${NOTE:-$(current_week_note)}"
if [[ ! -f "$NOTE" ]]; then
  echo "log_session.sh: no weekly note at $NOTE — skipping (run monday_init.sh first)" >&2
  exit 0
fi

append_session_line "$NOTE" "$PROVIDER" "$ROLE" "$STATUS" "$REASON"
