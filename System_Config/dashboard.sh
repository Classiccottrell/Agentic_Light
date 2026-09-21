#!/usr/bin/env bash
# dashboard.sh — terminal-native status readout for this fork's current
# state. Plain printf/box-drawing, no ncurses, no new dependency. A status
# readout, not an interactive app: no input handling, prints and exits.
#
# Reads (all optional — a fresh, unspecialized clone must print cleanly):
#   System_Config/agent-roster.json   (written by specialize.sh)
#   pipeline/gate-config.json         (written by specialize.sh)
#   .agentic-light.conf               (written by bootstrap.sh; parsed as
#                                       data via config.sh's config_value,
#                                       never sourced — security convention)
#   brain/weekly_logs/YYYY/YYYY-Www.md (current ISO week's note)
#   pipeline/logs/*.log                (most recent gate runs)
#
# Bash 3.2-safe, relocatable, set -euo pipefail (per CLAUDE.md Terminal
# Constraints). JSON is parsed with python3 stdlib json, matching this
# project's established config-parsing convention (specialize.sh).
#
# Usage: dashboard.sh
#        dashboard.sh --self-test
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SYSCFG="$ROOT/System_Config"
# shellcheck source=System_Config/config.sh
source "$SYSCFG/config.sh"

ROSTER_FILE="$SYSCFG/agent-roster.json"
GATE_FILE="$ROOT/pipeline/gate-config.json"
PLOGS="$ROOT/pipeline/logs"
WIDTH=63 # inner content width; box fits standard 80-col terminals

usage() {
  echo "Usage: $(basename "$0")" >&2
  echo "       $(basename "$0") --self-test" >&2
}

# pad_line <text> — right-pads/truncates <text> to WIDTH and wraps with
# box-drawing verticals. Long names are truncated with a trailing ellipsis
# rather than widening the box, so the box always fits 80 columns.
pad_line() {
  local text="$1" len
  len=${#text}
  if [ "$len" -gt "$WIDTH" ]; then
    text="${text:0:$((WIDTH - 1))}…"
  else
    text="${text}$(printf '%*s' "$((WIDTH - len))" '')"
  fi
  printf '│ %s │\n' "$text"
}

rule() { printf '├%s┤\n' "$(printf '─%.0s' $(seq 1 $((WIDTH + 2))))"; }
top_rule() { printf '┌─ %s %s┐\n' "$1" "$(printf '─%.0s' $(seq 1 $((WIDTH - ${#1} - 1))))"; }
bot_rule() { printf '└%s┘\n' "$(printf '─%.0s' $(seq 1 $((WIDTH + 2))))"; }

# roster_lines — prints roster role lines (or the "not configured" line),
# one per line, from agent-roster.json via python3.
roster_lines() {
  if [ ! -f "$ROSTER_FILE" ]; then
    echo "no roster configured — run specialize.sh"
    return
  fi
  python3 -c "
import json, sys
try:
    with open(sys.argv[1]) as f:
        d = json.load(f)
except Exception:
    print('roster file unreadable — run specialize.sh')
    sys.exit(0)
roles = d.get('roles', {})
if not roles:
    print('no roster configured — run specialize.sh')
    sys.exit(0)
for name, cfg in roles.items():
    state = 'active' if cfg.get('active') else 'inactive'
    print('%s [%s]' % (name, state))
" "$ROSTER_FILE"
}

# gate_lines — prints gate name/status lines (or the "not configured"
# line), one per line, from pipeline/gate-config.json via python3. Gates
# don't carry a runtime status of their own in the config, so we report
# "configured" here; actual pass/fail comes from the recent-runs section.
gate_lines() {
  if [ ! -f "$GATE_FILE" ]; then
    echo "no gates configured"
    return
  fi
  python3 -c "
import json, sys
try:
    with open(sys.argv[1]) as f:
        d = json.load(f)
except Exception:
    print('gate file unreadable')
    sys.exit(0)
gates = d.get('gates', [])
if not gates:
    print('no gates configured')
    sys.exit(0)
for g in gates:
    if isinstance(g, str):
        print('%s [configured]' % g)
    else:
        print('%s [configured]' % g.get('name', 'custom'))
" "$GATE_FILE"
}

# preset_summary — one line: preset label, or "not specialized".
preset_summary() {
  if [ ! -f "$ROSTER_FILE" ]; then
    echo "not specialized — run specialize.sh"
    return
  fi
  python3 -c "
import json, sys
try:
    with open(sys.argv[1]) as f:
        d = json.load(f)
except Exception:
    print('not specialized — run specialize.sh')
    raise SystemExit
roles = d.get('roles', {})
active = [n for n, c in roles.items() if c.get('active')]
if not active:
    print('specialized (no roles active)')
else:
    print('specialized — %d role(s) active' % len(active))
" "$ROSTER_FILE" 2>/dev/null || echo "not specialized — run specialize.sh"
}

# provider_summary — active provider from .agentic-light.conf, or
# "not configured". Uses config.sh's config_value (sed-based, never
# sources the file) per the established security convention.
provider_summary() {
  local enabled priority first
  enabled="$(config_value PROVIDERS)"
  priority="$(config_value PRIORITY)"
  [ -n "$priority" ] || priority="$enabled"
  if [ -z "$priority" ]; then
    echo "not configured — run bootstrap.sh"
    return
  fi
  first="${priority%%,*}"
  echo "$first (priority: $priority)"
}

# last_session_line — most recent "- <timestamp>: ..." line under the
# current week's "## Agent Sessions" heading, or "none yet".
last_session_line() {
  local year week note
  year="$(date +%G)"
  week="$(date +%V)"
  note="$BRAIN/weekly_logs/${year}/${year}-W${week}.md"
  if [ ! -f "$note" ]; then
    echo "none yet — no weekly note for ${year}-W${week}"
    return
  fi
  local line
  line="$(awk '
    /^## (Agent|Claude) Sessions[[:space:]]*$/ { insec=1; next }
    insec && /^---[[:space:]]*$/ { insec=0 }
    insec && /^- / { last=$0 }
    END { if (last != "") print last }
  ' "$note")"
  if [ -z "$line" ]; then
    echo "none yet this week"
  else
    echo "$line"
  fi
}

# recent_gate_runs <n> — last N pipeline/logs/*.log filenames, newest
# first, each with its run task line (if present). Logs are plain text
# transcripts (see pipeline/run.sh), not structured — pull the header
# "Task:" line as the summary.
recent_gate_runs() {
  local n="$1"
  if [ ! -d "$PLOGS" ]; then
    echo "no pipeline logs yet"
    return
  fi
  local files
  files="$(find "$PLOGS" -maxdepth 1 -type f -name '*.log' 2>/dev/null | sort -r | head -n "$n")"
  if [ -z "$files" ]; then
    echo "no pipeline logs yet"
    return
  fi
  local f base task
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    base="$(basename "$f" .log)"
    task="$(grep -m1 '^ Task:' "$f" 2>/dev/null | sed 's/^ Task:[[:space:]]*//')"
    if [ -n "$task" ]; then
      echo "${base} — ${task}"
    else
      echo "${base}"
    fi
  done <<EOF
$files
EOF
}

render() {
  top_rule "Agentic Light"
  pad_line "Preset: $(preset_summary)"
  pad_line "Provider: $(provider_summary)"
  rule
  pad_line "Roster"
  while IFS= read -r l; do pad_line "  $l"; done <<EOF
$(roster_lines)
EOF
  pad_line ""
  pad_line "Gates"
  while IFS= read -r l; do pad_line "  $l"; done <<EOF
$(gate_lines)
EOF
  rule
  pad_line "Last session"
  pad_line "  $(last_session_line)"
  rule
  pad_line "Recent gate runs"
  while IFS= read -r l; do pad_line "  $l"; done <<EOF
$(recent_gate_runs 3)
EOF
  bot_rule
}

self_test() {
  local tmp fail=0
  tmp="$(mktemp -d -t dashboard_selftest.XXXXXX)"

  # 1. Fresh/unspecialized: no roster, no gates, no conf, no logs.
  # Exercise the helper functions directly against a scratch fixture dir
  # (config.sh derives WORKSPACE from its own path, not env — see its
  # header — so we override the module-level path vars instead).
  local out
  mkdir -p "$tmp/System_Config" "$tmp/pipeline/logs" "$tmp/brain/weekly_logs"
  local SAVE_ROSTER=$ROSTER_FILE SAVE_GATE=$GATE_FILE SAVE_PLOGS=$PLOGS SAVE_BRAIN=$BRAIN
  ROSTER_FILE="$tmp/System_Config/agent-roster.json"
  GATE_FILE="$tmp/pipeline/gate-config.json"
  PLOGS="$tmp/pipeline/logs"
  BRAIN="$tmp/brain"

  out="$(roster_lines)"
  [ "$out" = "no roster configured — run specialize.sh" ] || { echo "FAIL: fresh roster_lines: $out" >&2; fail=1; }
  out="$(gate_lines)"
  [ "$out" = "no gates configured" ] || { echo "FAIL: fresh gate_lines: $out" >&2; fail=1; }
  out="$(preset_summary)"
  [ "$out" = "not specialized — run specialize.sh" ] || { echo "FAIL: fresh preset_summary: $out" >&2; fail=1; }
  out="$(last_session_line)"
  [[ "$out" == none\ yet* ]] || { echo "FAIL: fresh last_session_line: $out" >&2; fail=1; }
  out="$(recent_gate_runs 3)"
  [ "$out" = "no pipeline logs yet" ] || { echo "FAIL: fresh recent_gate_runs: $out" >&2; fail=1; }

  # 2. Specialized fixture: roster + gates present.
  cat > "$ROSTER_FILE" <<'JSON'
{"roles":{"coder":{"active":true,"capabilities":["read","write"]},"qa":{"active":false}}}
JSON
  cat > "$GATE_FILE" <<'JSON'
{"gates":["eslint",{"name":"custom","script":"pipeline/lib/x.sh"}]}
JSON
  out="$(roster_lines)"
  [[ "$out" == *"coder [active]"* ]] || { echo "FAIL: roster active not parsed" >&2; fail=1; }
  [[ "$out" == *"qa [inactive]"* ]] || { echo "FAIL: roster inactive not parsed" >&2; fail=1; }
  out="$(gate_lines)"
  [[ "$out" == *"eslint [configured]"* ]] || { echo "FAIL: gate string not parsed" >&2; fail=1; }
  [[ "$out" == *"custom [configured]"* ]] || { echo "FAIL: custom gate not parsed" >&2; fail=1; }
  out="$(preset_summary)"
  [[ "$out" == "specialized"* ]] || { echo "FAIL: preset_summary specialized: $out" >&2; fail=1; }

  # 3. Weekly note with an Agent Sessions line.
  mkdir -p "$BRAIN/weekly_logs/2026"
  local year week note
  year="$(date +%G)"; week="$(date +%V)"
  note="$BRAIN/weekly_logs/${year}/${year}-W${week}.md"
  mkdir -p "$(dirname "$note")"
  cat > "$note" <<'EOF'
## Agent Sessions
> Auto-appended after each agent work session.
- 2026-09-21 10:00:00: claude / coder — exit 0 (exit)
- 2026-09-21 11:00:00: codex / qa — exit 1 (timeout)

---
EOF
  out="$(last_session_line)"
  [[ "$out" == *"codex / qa — exit 1"* ]] || { echo "FAIL: last_session_line picked wrong/no line: $out" >&2; fail=1; }

  # 4. pipeline log fixture.
  printf ' Task:        do the thing\n' > "$PLOGS/20260101-000000-1.log"
  out="$(recent_gate_runs 3)"
  [[ "$out" == *"do the thing"* ]] || { echo "FAIL: recent_gate_runs did not pick up task line: $out" >&2; fail=1; }

  ROSTER_FILE=$SAVE_ROSTER; GATE_FILE=$SAVE_GATE; PLOGS=$SAVE_PLOGS; BRAIN=$SAVE_BRAIN
  rm -rf "$tmp"

  if [ "$fail" -eq 0 ]; then
    echo "self-test OK"
  else
    exit 1
  fi
}

case "${1:-}" in
  --self-test) self_test; exit 0 ;;
  -h|--help) usage; exit 0 ;;
  "") render ;;
  *) echo "unknown arg: $1" >&2; usage; exit 1 ;;
esac
