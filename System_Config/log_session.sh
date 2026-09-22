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
# target file (never auto-created). If the default current-week note is
# missing, monday_init.sh is run first to create it from the template (see
# the comment at the bottom of this file).
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
  unset LOG_SESSION_NOTE  # the auto-init case below needs the default path
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

  # Missing current-week note: run a copy of this script + monday_init.sh +
  # config.sh from a temp workspace (both derive brain/ from their own path),
  # so the real vault is never touched. Must create the note from the
  # template, stamp the line under '## Agent Sessions', and print nothing
  # on stdout.
  local ws out note
  ws="$(mktemp -d -t log_session_ws.XXXXXX)"
  mkdir -p "$ws/System_Config" "$ws/brain/weekly_logs"
  cp "$ROOT/System_Config/log_session.sh" "$ROOT/System_Config/monday_init.sh" "$ROOT/System_Config/config.sh" "$ws/System_Config/"
  cat > "$ws/brain/weekly_logs/Weekly_Note_Template.md" <<'EOF'
# W{{WEEK_NUM}} {{YEAR}} — TEMPLATE-MARKER
---

## Agent Sessions
> Auto-appended after each launcher-completed session.

---
EOF
  note="$ws/brain/weekly_logs/$(date +%G)/$(date +%G)-W$(date +%V).md"
  out="$(bash "$ws/System_Config/log_session.sh" --provider claude --role coder --status 0 --reason exit 2>/dev/null)"
  [[ -f "$note" ]] || { echo "FAIL: missing note not auto-created via monday_init.sh" >&2; rm -rf "$ws"; exit 1; }
  grep -qF "TEMPLATE-MARKER" "$note" || { echo "FAIL: auto-created note not from template" >&2; rm -rf "$ws"; exit 1; }
  [[ "$(awk '/^## Agent Sessions/{s=1} s&&/^---/{exit} s' "$note" | grep -cF 'claude / coder — exit 0 (exit)')" -eq 1 ]] \
    || { echo "FAIL: line not under ## Agent Sessions in auto-created note" >&2; rm -rf "$ws"; exit 1; }
  [[ -z "$out" ]] || { echo "FAIL: stdout contract changed: $out" >&2; rm -rf "$ws"; exit 1; }

  # monday_init.sh fails (no template): still exit 0, no note written.
  rm -rf "$ws/brain/weekly_logs"; mkdir -p "$ws/brain/weekly_logs"
  bash "$ws/System_Config/log_session.sh" --provider claude --role coder --status 0 --reason exit >/dev/null 2>&1 \
    || { echo "FAIL: non-zero exit when monday_init.sh fails" >&2; rm -rf "$ws"; exit 1; }
  [[ ! -f "$note" ]] || { echo "FAIL: note written despite monday_init.sh failure" >&2; rm -rf "$ws"; exit 1; }

  # Explicit --note that doesn't exist: skip, never auto-create.
  bash "$ws/System_Config/log_session.sh" --provider claude --role coder --status 0 --reason exit --note "$ws/nope.md" >/dev/null 2>&1 \
    || { echo "FAIL: non-zero exit on missing --note" >&2; rm -rf "$ws"; exit 1; }
  [[ ! -e "$ws/nope.md" && ! -d "$ws/brain/weekly_logs/$(date +%G)" ]] \
    || { echo "FAIL: explicit --note triggered auto-create" >&2; rm -rf "$ws"; exit 1; }
  rm -rf "$ws"

  echo "self-test OK"
}

# LOG_SESSION_NOTE: env equivalent of --note (same explicit, never-auto-
# created semantics) for callers that reach this script indirectly via
# pipeline/run.sh — test_pipeline.sh uses it to keep fixtures out of brain/.
PROVIDER="" ROLE="" STATUS="" REASON="" NOTE="${LOG_SESSION_NOTE:-}"
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

# Missing note: this used to always skip, so a stub note lacking the
# template's sections was never written — but that silently dropped runs
# from the audit trail (GOVERNANCE.md §3) in any week monday_init.sh hadn't
# run yet. Now, for the default current-week note only, run monday_init.sh
# (as a subprocess: its acquire_lock EXIT trap stays in the child; lock is
# System_Config/logs/monday_init.lock, distinct from pipeline/run.sh's
# pipeline/logs/.run.*.lock) to create the full templated note, exactly as a
# human run would. Its stdout goes to stderr to keep this script's output
# contract. An explicit --note is never auto-created. If init fails or the
# note is still missing, skip as before — logging never fails the caller.
if [[ -n "$NOTE" ]]; then
  if [[ ! -f "$NOTE" ]]; then
    echo "log_session.sh: no weekly note at $NOTE — skipping (explicit --note is never auto-created)" >&2
    exit 0
  fi
else
  NOTE="$(current_week_note)"
  if [[ ! -f "$NOTE" ]]; then
    echo "log_session.sh: no weekly note at $NOTE — running monday_init.sh to create it" >&2
    bash "$ROOT/System_Config/monday_init.sh" >&2 || echo "log_session.sh: monday_init.sh exited non-zero" >&2
    if [[ ! -f "$NOTE" ]]; then
      echo "log_session.sh: weekly note still missing at $NOTE after monday_init.sh — skipping" >&2
      exit 0
    fi
  fi
fi

append_session_line "$NOTE" "$PROVIDER" "$ROLE" "$STATUS" "$REASON"
