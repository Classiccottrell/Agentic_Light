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

case "${1:-}" in
  -h|--help)
    sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
    ;;
esac

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
BRANCH_NAME="agentic-light/${RUN_ID}"

exec > >(tee -a "$RUN_LOG") 2>&1

echo "=================================================="
echo " Agentic Light Pipeline — run $RUN_ID"
echo " Task:        $TASK_DESC"
echo " Target repo: $TARGET_REPO"
echo " Branch:      $BRANCH_NAME"
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
  if ! python3 - "$GATE_CONFIG" "$ROOT/System_Config/gate-config.schema.json" <<'PYEOF'
import json, sys

path = sys.argv[1]
schema_path = sys.argv[2]
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

# Known gate names come from the schema's enum (same path specialize.sh
# reads), so a gate added to the schema needs no edit here.
try:
    with open(schema_path) as f:
        KNOWN = tuple(json.load(f)["definitions"]["gate"]["oneOf"][0]["enum"])
except Exception as e:
    print("FAILED: cannot read known gate names from System_Config/gate-config.schema.json: %s" % e)
    sys.exit(1)

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
# Pre-flight sensitive-file scan — the coder's cwd is TARGET_REPO, an
# arbitrary external repo, and run_agent.sh's --allowedTools "Read,...Grep"
# gates which TOOLS run, not which PATHS they touch. This is an existence
# check on filenames, not access control: it does NOT stop the coder from
# reading a sensitive file that doesn't match these globs, one created
# mid-run, or a nested .git/node_modules it skips — and once the coder
# launches, Read/Grep still work on anything else in cwd. Deliberately
# includes gitignored files (unlike healthcheck.sh's Config Security Scan,
# which skips them) — a real .env is normally gitignored, which is exactly
# where this needs to look.
# ---------------------------------------------------------------------------
echo "-> [0] Pre-flight sensitive-file scan: $TARGET_REPO"
SENSITIVE_HITS="$(find "$TARGET_REPO" \( -path '*/.git' -o -path '*/node_modules' \) -prune -o \
  -type f \( -name '.env*' -o -name '*.key' -o -name '*.pem' -o -name 'id_rsa*' \) -print 2>/dev/null)"
if [ -n "$SENSITIVE_HITS" ]; then
  echo "WARNING: $TARGET_REPO contains file(s) matching sensitive-file patterns (.env*, *.key, *.pem, id_rsa*):"
  echo "$SENSITIVE_HITS" | sed 's/^/  /'
  if [ "${AGENTIC_LIGHT_ALLOW_SENSITIVE_REPO:-}" != "1" ]; then
    echo "FAILED: refusing to launch the coder with these files present in its cwd (advisory filename screening, not a security boundary — see comment above) — its Read/Grep tools have no path restriction beyond cwd."
    echo "  Set AGENTIC_LIGHT_ALLOW_SENSITIVE_REPO=1 to proceed anyway (e.g. once you've confirmed these are dummy/fixture files)."
    exit 1
  fi
  echo "  AGENTIC_LIGHT_ALLOW_SENSITIVE_REPO=1 set — proceeding despite the match(es) above."
fi
echo

# ---------------------------------------------------------------------------
# Step 1: Code Patch (coder)
# The pipeline — not the coder prompt — owns git: it creates the feature
# branch here and commits the coder's edits below. That keeps the ask
# consistent with System_Config/run_agent.sh's claude invocation, which runs
# with --disallowedTools "Bash,..." and so cannot branch or commit itself.
# ---------------------------------------------------------------------------
echo "-> [1] Code patch step"

# Precondition: the pipeline's contract is "coder starts on a clean index,
# pipeline commits only what it added." `git checkout -b` below carries any
# pre-existing staged changes onto the new branch, and the secret-scan
# rollback later (`git reset -q`) resets the WHOLE index — correct only if
# nothing was staged before this step. Assert that here, before branching or
# invoking the coder, so a dirty-index caller fails fast and cheaply instead
# of losing work after a full (possibly costly) coder run.
if ! git -C "$TARGET_REPO" diff --cached --quiet; then
  echo "FAILED: $TARGET_REPO has staged changes before the pipeline started — refusing to run. Commit or unstage them first; this pipeline assumes a clean index so its own rollback/commit steps don't touch changes it doesn't own."
  exit 1
fi

echo "  creating feature branch: $BRANCH_NAME"
if ! git -C "$TARGET_REPO" checkout -b "$BRANCH_NAME"; then
  echo "FAILED: could not create feature branch $BRANCH_NAME in $TARGET_REPO"
  exit 1
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
#
# Overridable via AGENTIC_LIGHT_SKILL_MATCH_LIMIT (must be a non-negative
# integer; 0 is valid and injects no skill context at all). Malformed or
# unset falls back to the documented default of 3.
# ---------------------------------------------------------------------------
SKILL_CONTEXT=""
SKILL_MATCH_LIMIT_RAW="${AGENTIC_LIGHT_SKILL_MATCH_LIMIT-}"
case "$SKILL_MATCH_LIMIT_RAW" in
  ''|*[!0-9]*)
    if [ -n "${AGENTIC_LIGHT_SKILL_MATCH_LIMIT+set}" ]; then
      echo "  AGENTIC_LIGHT_SKILL_MATCH_LIMIT=\"$SKILL_MATCH_LIMIT_RAW\" is not a non-negative integer — falling back to 3" >&2
    fi
    SKILL_MATCH_LIMIT=3
    ;;
  *)
    SKILL_MATCH_LIMIT="$SKILL_MATCH_LIMIT_RAW"
    ;;
esac
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
# Context packet — opt-in only. This pipeline operates against an EXTERNAL
# target repo (see file header); unconditionally prepending Agentic Light's
# own roadmap/session context into every coder prompt would be exactly the
# "unrelated target repositories" context leak the roadmap item warns
# against. Only activates when explicitly requested
# (AGENTIC_LIGHT_CONTEXT_PACKET=1), or automatically when this pipeline is
# dogfooding a run against Agentic Light's own root (TARGET_REPO resolves,
# symlink-safe via `pwd -P` on both sides, to $ROOT). Calls
# System_Config/context_packet.sh from $ROOT — never `cd`'d into
# $TARGET_REPO first. Fails silently, same as the skill-routing block
# above — never blocks the coder step.
# ---------------------------------------------------------------------------
CONTEXT_PACKET=""
CONTEXT_PACKET_SCRIPT="$ROOT/System_Config/context_packet.sh"
ROOT_P="$(cd "$ROOT" && pwd -P)"
TARGET_P="$(cd "$TARGET_REPO" && pwd -P)"
if [ "${AGENTIC_LIGHT_CONTEXT_PACKET:-}" = "1" ] || [ "$TARGET_P" = "$ROOT_P" ]; then
  if [ -x "$CONTEXT_PACKET_SCRIPT" ]; then
    set +e
    if [ -n "${AGENTIC_LIGHT_CONTEXT_PROFILE:-}" ]; then
      CONTEXT_PACKET="$("$ROOT/System_Config/context.sh" packet --profile "$AGENTIC_LIGHT_CONTEXT_PROFILE" 2>/dev/null)"
    else
      CONTEXT_PACKET="$("$CONTEXT_PACKET_SCRIPT" 2>/dev/null)"
    fi
    set -e
  fi
fi

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
  PROMPT="Target repo: $TARGET_REPO. Task: $TASK_DESC. Implement the change on the current branch. Do not run shell commands, create branches, or commit — the pipeline handles all git operations."
  if [ -n "$SKILL_CONTEXT" ]; then
    PROMPT="Relevant skill guidance:
${SKILL_CONTEXT}
${PROMPT}"
  fi
  if [ -n "$CONTEXT_PACKET" ]; then
    PROMPT="Resume context packet:
${CONTEXT_PACKET}

${PROMPT}"
  fi
  set +e
  LOG="$RUN_LOG" BRAIN="$TARGET_REPO" run_agent "$PROMPT"
  CODER_RC=$?
  set -e
  CODER_PROVIDER="${AGENT_PROVIDER:-unknown}"
fi

# Session logging — exactly once, after the coder process exits,
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

# Stage first, then diff --cached — git diff HEAD only covers tracked-file
# modifications; a brand-new file the coder created would otherwise only
# appear as a bare filename (see the old UNTRACKED handling), never scanned
# by content below. Staging first makes new files' full content visible to
# both the secret scan and the Human Gate summary at step 4.
echo "  staging coder's changes"
if ! ( cd "$TARGET_REPO" && git add -A ); then
  echo "FAILED: could not stage coder's changes in $TARGET_REPO"
  exit 1
fi
DIFF="$(cd "$TARGET_REPO" && git diff --cached 2>/dev/null || true)"
if [ -z "$DIFF" ]; then
  echo "FAILED: code patch step produced no changes — nothing to commit, no PR will be created"
  exit 1
fi

# ---------------------------------------------------------------------------
# Secret scan (hard stop) — reuses config.sh's looks_like_secret, the same
# pattern set as healthcheck.sh's Config Security Scan, so there is one
# regex definition, not two. Scanned lines only (excluding the "+++ b/..."
# diff header) to keep this a real gate rather than tripping on every
# ordinary line of an unrelated diff; still a best-effort, repo-specific
# pattern set, not a general secret scanner (same caveat as healthcheck.sh).
# `|| true` on the assignment: looks_like_secret's greps exit non-zero on a
# clean (no-match) diff, which would otherwise abort this script under
# `set -e`.
#
# `git reset -q` below resets the WHOLE index, not just what this run staged
# — that's only correct because step 1 already asserted the index was empty
# before this run touched it (see the precondition check above `checkout
# -b`). Given that precondition, "reset to nothing staged" is exactly
# "reset to what this repo looked like before the pipeline ran," not a
# blanket wipe of unrelated staged work.
# ---------------------------------------------------------------------------
SECRET_HIT="$(printf '%s\n' "$DIFF" | grep '^+' | grep -v '^+++' | looks_like_secret /dev/stdin | head -1 || true)"
if [ -n "$SECRET_HIT" ]; then
  echo "FAILED: likely secret detected in staged changes — refusing to commit."
  echo "  match: $SECRET_HIT"
  ( cd "$TARGET_REPO" && git reset -q )
  exit 1
fi

echo "  committing coder's changes"
if ! ( cd "$TARGET_REPO" && git commit -q -m "Agentic Light: $TASK_DESC" ); then
  echo "FAILED: could not commit coder's changes in $TARGET_REPO"
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
    axe)
      echo "-> [gate $n] Accessibility (axe) gate"
      "$LIB/axe_gate.sh" "$TARGET_REPO"
      ;;
    vpat-lint)
      echo "-> [gate $n] VPAT draft lint gate"
      "$LIB/vpat_lint_gate.sh" "$TARGET_REPO"
      ;;
    *)
      # custom gate, tab-delimited: custom<TAB>script<TAB>cwd<TAB>args...
      # Containment check: script/cwd come from pipeline/gate-config.json,
      # which lives in the Agentic Light workspace (this repo), not the
      # target repo — an attacker who controls this fork's gate-config.json
      # (e.g. a malicious/compromised fork) could otherwise point a gate at
      # anything reachable from $TARGET_REPO with no check at all. Resolve
      # both with `cd ... && pwd -P` (this project's existing idiom, e.g.
      # config.sh's ROOT resolution; no `realpath` dependency) and reject
      # anything that escapes $TARGET_REPO. `-P` on both sides of the
      # comparison so a symlinked /tmp (macOS: /tmp -> /private/tmp) doesn't
      # false-reject a legitimate path.
      #
      # Parent-directory resolution alone isn't enough: if $script_abs's
      # final path component is itself a symlink pointing outside
      # $TARGET_REPO, resolving only its parent dir passes containment while
      # exec still follows the symlink out of the sandbox. So the final path
      # component is checked for a symlink explicitly, in addition to
      # resolving the parent dir. This is a check-then-exec: it does not
      # close the TOCTOU window (a symlink swapped in between this check and
      # the `exec` below is not prevented), only the static/at-rest case.
      local IFS_OLD="$IFS" fields name script cwd target_p cwd_abs cwd_p script_abs script_dir_p script_p
      IFS=$'\t' read -r -a fields <<<"$gate"
      IFS="$IFS_OLD"
      name="${fields[0]}"; script="${fields[1]}"; cwd="${fields[2]:-.}"
      target_p="$(cd "$TARGET_REPO" && pwd -P)"
      cwd_abs="$TARGET_REPO/$cwd"
      [ -d "$cwd_abs" ] || { echo "FAILED: custom gate cwd does not resolve to a directory: $cwd_abs"; return 1; }
      cwd_p="$(cd "$cwd_abs" && pwd -P)"
      case "$cwd_p" in
        "$target_p"|"$target_p"/*) ;;
        *) echo "FAILED: custom gate cwd escapes target repo: $cwd (resolved: $cwd_p)"; return 1 ;;
      esac
      script_abs="$TARGET_REPO/$script"
      [ -f "$script_abs" ] || { echo "FAILED: custom gate script not found: $script_abs"; return 1; }
      if [ -L "$script_abs" ]; then
        echo "FAILED: custom gate script is a symlink, refusing (its target may resolve outside the target repo): $script"
        return 1
      fi
      script_dir_p="$(cd "$(dirname "$script_abs")" && pwd -P)"
      script_p="$script_dir_p/$(basename "$script_abs")"
      case "$script_p" in
        "$target_p"|"$target_p"/*) ;;
        *) echo "FAILED: custom gate script escapes target repo: $script (resolved: $script_p)"; return 1 ;;
      esac
      echo "-> [gate $n] custom gate: $script"
      ( cd "$cwd_p" && "$script_p" "${fields[@]:3}" )
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
SUMMARY="Task: $TASK_DESC
Target repo: $TARGET_REPO
Branch:      $BRANCH_NAME
Gates: passed/skipped (see log above)

--- diff (already committed to $BRANCH_NAME in step 1) ---
${DIFF:-<no diff available>}"

# PIPELINE_HUMAN_GATE_CMD mirrors PIPELINE_CODER_CMD above — lets tests drive
# the approved path without faking a TTY. Test-only: honored only alongside
# AGENTIC_LIGHT_TEST_MODE=1, so a caller can't set this one env var to skip
# human approval on a real run (see pipeline/README.md).
HUMAN_GATE_CMD="$LIB/human_gate.sh"
if [ -n "${PIPELINE_HUMAN_GATE_CMD:-}" ]; then
  if [ "${AGENTIC_LIGHT_TEST_MODE:-}" = "1" ]; then
    HUMAN_GATE_CMD="$PIPELINE_HUMAN_GATE_CMD"
  else
    echo "WARNING: PIPELINE_HUMAN_GATE_CMD is set but AGENTIC_LIGHT_TEST_MODE=1 is not — ignoring override, using the real human gate (PIPELINE_HUMAN_GATE_CMD is test-only)." >&2
  fi
fi
set +e
"$HUMAN_GATE_CMD" "$SUMMARY"
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
