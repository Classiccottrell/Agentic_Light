#!/usr/bin/env bash
# run.sh — Agentic Light pipeline orchestrator.
# Task Input -> coder -> ESLint gate -> Playwright gate -> Human Gate -> gh pr create
# Usage: run.sh "<task description>" [target-repo-path]
#   target-repo-path defaults to $PWD. This pipeline operates against an
#   EXTERNAL target repo, not against Agentic_Light itself.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PIPELINE_DIR="$ROOT/pipeline"
LIB="$PIPELINE_DIR/lib"

# shellcheck source=../System_Config/config.sh
source "$ROOT/System_Config/config.sh"

TASK_DESC="${1:?usage: run.sh \"<task description>\" [target-repo-path]}"
TARGET_REPO="$(cd "${2:-$PWD}" && pwd)"

mkdir -p "$PIPELINE_DIR/logs"

# ---------------------------------------------------------------------------
# Concurrency lock — one pipeline run per TARGET_REPO at a time. Without this,
# two concurrent runs against the same target repo can interleave the coder
# agent's git operations (branch creation, commits) in the same working tree
# and corrupt its state. Keyed by a checksum of the target path so distinct
# target repos still run in parallel. 2h stale-reclaim ceiling covers a
# realistic worst-case coder+lint+e2e run; a genuinely crashed run's lock is
# reclaimed rather than blocking every future run forever.
# ---------------------------------------------------------------------------
LOCK_KEY="$(printf '%s' "$TARGET_REPO" | cksum | awk '{print $1}')"
LOCK_DIR="$PIPELINE_DIR/logs/.run.${LOCK_KEY}.lock"
if ! acquire_lock "$LOCK_DIR" 7200; then
  echo "[run.sh] another pipeline run holds the lock for $TARGET_REPO ($LOCK_DIR) — refusing to run concurrently." >&2
  exit 1
fi

RUN_ID="$(date +%Y%m%d-%H%M%S)-$$"
RUN_LOG="$PIPELINE_DIR/logs/${RUN_ID}.log"

exec > >(tee -a "$RUN_LOG") 2>&1

echo "=================================================="
echo " Agentic Light Pipeline — run $RUN_ID"
echo " Task:        $TASK_DESC"
echo " Target repo: $TARGET_REPO"
echo " Log:         $RUN_LOG"
echo "=================================================="
echo

# ---------------------------------------------------------------------------
# Gate-config validation — before anything runs, not just before the gate
# step, so a malformed pipeline/gate-config.json fails fast (clear
# "FAILED:" message, exit 1) instead of surfacing mid-run under `set -u`
# after the coder step has already made changes.
# ---------------------------------------------------------------------------
GATE_CONFIG="$PIPELINE_DIR/gate-config.json"
if [ -f "$GATE_CONFIG" ]; then
  command -v python3 >/dev/null 2>&1 || { echo "FAILED: pipeline/gate-config.json present but python3 not found — cannot validate gates"; exit 1; }
  if ! python3 - "$GATE_CONFIG" <<'PYEOF'
import json, sys

path = sys.argv[1]
try:
    with open(path) as f:
        cfg = json.load(f)
except Exception as e:
    print("FAILED: pipeline/gate-config.json is not valid JSON: %s" % e)
    sys.exit(1)

if not isinstance(cfg, dict) or "gates" not in cfg:
    print("FAILED: pipeline/gate-config.json must be an object with a \"gates\" array")
    sys.exit(1)

gates = cfg["gates"]
if not isinstance(gates, list):
    print("FAILED: pipeline/gate-config.json \"gates\" must be an array")
    sys.exit(1)

KNOWN = ("eslint", "playwright")
for i, gate in enumerate(gates):
    if isinstance(gate, str):
        if gate not in KNOWN:
            print("FAILED: pipeline/gate-config.json gates[%d] unknown gate name %r (expected one of %s or a custom object)" % (i, gate, KNOWN))
            sys.exit(1)
        continue
    if isinstance(gate, dict):
        if gate.get("name") != "custom":
            print("FAILED: pipeline/gate-config.json gates[%d] object gate must have \"name\": \"custom\"" % i)
            sys.exit(1)
        script = gate.get("script")
        if not isinstance(script, str) or not script:
            print("FAILED: pipeline/gate-config.json gates[%d] custom gate missing required string \"script\"" % i)
            sys.exit(1)
        cwd = gate.get("cwd", ".")
        if not isinstance(cwd, str):
            print("FAILED: pipeline/gate-config.json gates[%d] custom gate \"cwd\" must be a string" % i)
            sys.exit(1)
        args = gate.get("args", [])
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            print("FAILED: pipeline/gate-config.json gates[%d] custom gate \"args\" must be an array of strings" % i)
            sys.exit(1)
        extra = set(gate.keys()) - {"name", "script", "cwd", "args"}
        if extra:
            print("FAILED: pipeline/gate-config.json gates[%d] custom gate has unknown fields: %s" % (i, sorted(extra)))
            sys.exit(1)
        continue
    print("FAILED: pipeline/gate-config.json gates[%d] must be a known gate name or a custom gate object" % i)
    sys.exit(1)
PYEOF
  then
    exit 1
  fi
fi

# ---------------------------------------------------------------------------
# Skill routing — best-effort. If pipeline/../System_Config/route_skill.sh
# matches any skill against TASK_DESC, prepend those skills' SKILL.md
# contents to the coder prompt below. No match (or router unavailable) is a
# silent no-op — proceeds exactly as before this wiring existed.
#
# route_skill.sh's matcher is a deliberately basic substring/keyword match
# (its own header comment) and can match many skills on an ordinary task
# sentence — e.g. "add a dark mode toggle ... with a persisted user
# preference" matched 9 of 12 shipped figma-* skills. Concatenating every
# match's full SKILL.md would dump ~160KB into the coder prompt, drowning
# the actual task. Capped at the first SKILL_MATCH_LIMIT matches (router's
# own output order) so a genuine single-skill match still gets its full
# guidance while a broad/noisy match degrades instead of ballooning.
# ---------------------------------------------------------------------------
SKILL_CONTEXT=""
SKILL_MATCH_LIMIT=3
ROUTE_SKILL="$ROOT/System_Config/route_skill.sh"
if [ -x "$ROUTE_SKILL" ]; then
  set +e
  MATCHED_SKILLS="$("$ROUTE_SKILL" "$TASK_DESC" 2>/dev/null)"
  set -e
  if [ -n "$MATCHED_SKILLS" ]; then
    SKILL_MATCH_COUNT=0
    while IFS= read -r SKILL_DIR; do
      [ -n "$SKILL_DIR" ] || continue
      [ -f "$SKILL_DIR/SKILL.md" ] || continue
      SKILL_MATCH_COUNT=$((SKILL_MATCH_COUNT + 1))
      if [ "$SKILL_MATCH_COUNT" -gt "$SKILL_MATCH_LIMIT" ]; then
        echo "  routed skill: $SKILL_DIR (skipped — over ${SKILL_MATCH_LIMIT}-match cap)"
        continue
      fi
      echo "  routed skill: $SKILL_DIR"
      SKILL_CONTEXT="${SKILL_CONTEXT}$(cat "$SKILL_DIR/SKILL.md")
"
    done <<EOF
$MATCHED_SKILLS
EOF
  fi
fi

# ---------------------------------------------------------------------------
# Step 1: Code Patch (coder)
# ---------------------------------------------------------------------------
echo "-> [1] Code patch step"

# reason_for_status <exit-code> <provider> — maps a completed coder
# process's exit status to log_session.sh's --reason vocabulary
# (exit|timeout|signal|refused). 64 is run_agent.sh's documented Ollama
# write-workflow refusal — only meaningful when the resolved provider for
# this run was actually ollama; any other provider exiting 64 falls through
# to the generic "exit" classification instead of being misreported as a
# refusal. 137/143 are SIGKILL/SIGTERM as seen by a parent shell (128+9,
# 128+15) — the watchdog's termination signals; any other 128+n is some
# other signal. Everything else (including other non-zero exits) is
# reported as "exit".
reason_for_status() {
  local st="$1" provider="${2:-}"
  case "$st" in
    64) if [ "$provider" = "ollama" ]; then echo "refused"; else echo "exit"; fi ;;
    137|143) echo "timeout" ;;
    *) if [ "$st" -gt 128 ] 2>/dev/null; then echo "signal"; else echo "exit"; fi ;;
  esac
}

CODER_RC=0
if [ -n "${PIPELINE_CODER_CMD:-}" ]; then
  echo "  using PIPELINE_CODER_CMD override: $PIPELINE_CODER_CMD"
  set +e
  $PIPELINE_CODER_CMD "$TASK_DESC" "$TARGET_REPO"
  CODER_RC=$?
  set -e
  CODER_PROVIDER="${AGENT_PROVIDER:-override}"
else
  echo "  invoking coder via System_Config/run_agent.sh"
  # shellcheck source=../System_Config/run_agent.sh
  source "$ROOT/System_Config/run_agent.sh"
  PROMPT="Target repo: $TARGET_REPO. Task: $TASK_DESC. Create a feature branch, implement the change, and commit it."
  if [ -n "$SKILL_CONTEXT" ]; then
    PROMPT="Relevant skill guidance:
${SKILL_CONTEXT}
${PROMPT}"
  fi
  set +e
  LOG="$RUN_LOG" BRAIN="$TARGET_REPO" run_agent "$PROMPT"
  CODER_RC=$?
  set -e
  CODER_PROVIDER="${AGENT_PROVIDER:-unknown}"
fi

# Step 5: session logging — exactly once, after the coder process exits,
# covering the success, timeout, and refusal paths alike. Deliberately not
# inside run_agent() itself: that function is also called once per clip by
# daily_ingest.sh, and logging there would emit N entries per ingest run
# and break "exactly once" (also true for the PIPELINE_CODER_CMD override
# used by test_providers.sh's fakes, which must never touch the real vault
# outside this launcher path).
"$ROOT/System_Config/log_session.sh" \
  --provider "$CODER_PROVIDER" --role coder \
  --status "$CODER_RC" --reason "$(reason_for_status "$CODER_RC" "$CODER_PROVIDER")" || true

if [ "$CODER_RC" -ne 0 ]; then
  echo "FAILED: code patch step (coder exited $CODER_RC)"
  exit 1
fi
echo "  code patch step complete"
echo

# ---------------------------------------------------------------------------
# Step 2: Gates — hard stop, no further steps, on any gate failure.
#
# If pipeline/gate-config.json is present, its ordered "gates" list drives
# this step (parsed with python3, per gate-config.schema.json); a "custom"
# gate's script/args/cwd are resolved relative to TARGET_REPO, same as
# eslint_gate.sh/playwright_gate.sh already `cd "$TARGET"`. No config file
# yet (a fork that hasn't run specialize.sh) falls back to the original
# hardcoded eslint+playwright pair so nothing breaks on an un-specialized
# fork. gate-config.json present but python3 missing is a hard failure, not
# a silent skip — running the wrong gate set defeats the "100% pass before
# a human sees the diff" contract. (GATE_CONFIG validated up front, before
# the coder step, and reused here as-is.)
# ---------------------------------------------------------------------------

run_gate() {
  local gate="$1" n="$2"
  case "$gate" in
    eslint)
      echo "-> [gate $n] ESLint gate"
      "$LIB/eslint_gate.sh" "$TARGET_REPO"
      ;;
    playwright)
      echo "-> [gate $n] Playwright E2E gate"
      "$LIB/playwright_gate.sh" "$TARGET_REPO"
      ;;
    *)
      # custom gate, tab-delimited: custom<TAB>script<TAB>cwd<TAB>args...
      local IFS_OLD="$IFS" fields name script cwd
      IFS=$'\t' read -r -a fields <<<"$gate"
      IFS="$IFS_OLD"
      name="${fields[0]}"; script="${fields[1]}"; cwd="${fields[2]:-.}"
      echo "-> [gate $n] custom gate: $script"
      ( cd "$TARGET_REPO/$cwd" && "$TARGET_REPO/$script" "${fields[@]:3}" )
      ;;
  esac
}

if [ -f "$GATE_CONFIG" ]; then
  echo "-> [2] Gates (from pipeline/gate-config.json)"
  command -v python3 >/dev/null 2>&1 || { echo "FAILED: pipeline/gate-config.json present but python3 not found — cannot parse gates"; exit 1; }

  GATE_LIST_FILE="$(mktemp)"
  # Folds in acquire_lock's own EXIT trap (see config.sh acquire_lock) since
  # this trap replaces it wholesale; restored below once GATE_LIST_FILE is
  # gone so the lock still releases on later exit paths (success or failure).
  trap 'rm -f "$GATE_LIST_FILE"; rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT
  python3 - "$GATE_CONFIG" > "$GATE_LIST_FILE" <<'PYEOF'
import json, sys
with open(sys.argv[1]) as f:
    cfg = json.load(f)
for gate in cfg.get("gates", []):
    if isinstance(gate, str):
        print(gate)
    elif isinstance(gate, dict) and gate.get("name") == "custom":
        script = gate.get("script", "")
        cwd = gate.get("cwd", ".")
        args = gate.get("args", [])
        print("\t".join(["custom", script, cwd] + args))
PYEOF

  N=0
  # Read from a temp file, not a pipe: a `| while read` loop runs in a
  # subshell under bash 3.2, so a failing gate's `exit 1` would kill only
  # the subshell and silently continue the pipeline — breaking the
  # halt-on-failure guarantee.
  while IFS= read -r GATE_LINE; do
    [ -n "$GATE_LINE" ] || continue
    N=$((N + 1))
    if ! run_gate "$GATE_LINE" "$N"; then
      echo "FAILED: gate $N ($GATE_LINE) — halting, no further steps, no PR will be created"
      exit 1
    fi
    echo
  done < "$GATE_LIST_FILE"
  rm -f "$GATE_LIST_FILE"
  trap "rmdir '$LOCK_DIR' 2>/dev/null || true" EXIT
else
  echo "-> [2] Gates (no gate-config.json found — using default eslint+playwright)"
  if ! run_gate "eslint" 1; then
    echo "FAILED: ESLint gate — halting, no further steps, no PR will be created"
    exit 1
  fi
  echo
  if ! run_gate "playwright" 2; then
    echo "FAILED: Playwright gate — halting, no further steps, no PR will be created"
    exit 1
  fi
  echo
fi

# ---------------------------------------------------------------------------
# Step 3: Human Gate — blocks on TTY y/N; never auto-approves.
# ---------------------------------------------------------------------------
echo "-> [3] Human gate"
DIFF="$(cd "$TARGET_REPO" && git diff HEAD 2>/dev/null || true)"
SUMMARY="Task: $TASK_DESC
Target repo: $TARGET_REPO
Gates: passed/skipped (see log above)

--- diff ---
${DIFF:-<no diff available>}"

set +e
"$LIB/human_gate.sh" "$SUMMARY"
GATE_RC=$?
set -e

case "$GATE_RC" in
  0) echo "  human gate: APPROVED" ;;
  2) echo "PENDING: human gate awaiting interactive review — exiting without creating a PR"; exit 2 ;;
  *) echo "FAILED: human gate declined — no PR will be created"; exit 1 ;;
esac
echo

# ---------------------------------------------------------------------------
# Step 4: PR creation — only reachable after explicit approval above.
# ---------------------------------------------------------------------------
echo "-> [4] PR creation"
"$LIB/pr_create.sh" "$TARGET_REPO" --confirmed "$TASK_DESC"
echo
echo "=================================================="
echo " Pipeline complete — run $RUN_ID"
echo "=================================================="
