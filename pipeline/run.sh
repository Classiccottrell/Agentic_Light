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
# Step 1/5: Code Patch (coder)
# The pipeline — not the coder prompt — owns git: it creates the feature
# branch here and commits the coder's edits below. That keeps the ask
# consistent with System_Config/run_agent.sh's claude invocation, which runs
# with --disallowedTools "Bash,..." and so cannot branch or commit itself.
# ---------------------------------------------------------------------------
echo "-> [1/5] Code patch step"
echo "  creating feature branch: $BRANCH_NAME"
if ! git -C "$TARGET_REPO" checkout -b "$BRANCH_NAME"; then
  echo "FAILED: could not create feature branch $BRANCH_NAME in $TARGET_REPO"
  exit 1
fi

if [ -n "${PIPELINE_CODER_CMD:-}" ]; then
  echo "  using PIPELINE_CODER_CMD override: $PIPELINE_CODER_CMD"
  if ! $PIPELINE_CODER_CMD "$TASK_DESC" "$TARGET_REPO"; then
    echo "FAILED: code patch step (PIPELINE_CODER_CMD exited non-zero)"
    exit 1
  fi
else
  echo "  invoking coder via System_Config/run_agent.sh"
  # shellcheck source=../System_Config/run_agent.sh
  source "$ROOT/System_Config/run_agent.sh"
  PROMPT="Target repo: $TARGET_REPO. Task: $TASK_DESC. Implement the change on the current branch. Do not run shell commands, create branches, or commit — the pipeline handles all git operations."
  if ! LOG="$RUN_LOG" BRAIN="$TARGET_REPO" run_agent "$PROMPT"; then
    echo "FAILED: code patch step (coder agent exited non-zero)"
    exit 1
  fi
fi

# Capture what the coder changed before committing it — tracked-file diff
# plus any new (non-ignored) files, which is exactly what `git add -A` below
# will stage. Reused verbatim in the Human Gate summary at step 4 so what's
# shown to the human matches what's actually in the commit.
DIFF="$(cd "$TARGET_REPO" && git diff HEAD 2>/dev/null || true)"
UNTRACKED="$(cd "$TARGET_REPO" && git ls-files --others --exclude-standard 2>/dev/null || true)"
if [ -z "$DIFF" ] && [ -z "$UNTRACKED" ]; then
  echo "FAILED: code patch step produced no changes — nothing to commit, no PR will be created"
  exit 1
fi
if [ -n "$UNTRACKED" ]; then
  DIFF="$DIFF

--- new files ---
$UNTRACKED"
fi
echo "  committing coder's changes"
if ! ( cd "$TARGET_REPO" && git add -A && git commit -q -m "Agentic Light: $TASK_DESC" ); then
  echo "FAILED: could not commit coder's changes in $TARGET_REPO"
  exit 1
fi
echo "  code patch step complete"
echo

# ---------------------------------------------------------------------------
# Step 2/5: ESLint gate — hard stop, no further steps, on failure.
# ---------------------------------------------------------------------------
echo "-> [2/5] ESLint gate"
if ! "$LIB/eslint_gate.sh" "$TARGET_REPO"; then
  echo "FAILED: ESLint gate — halting, no further steps, no PR will be created"
  exit 1
fi
echo

# ---------------------------------------------------------------------------
# Step 3/5: Playwright gate — hard stop, no further steps, on failure.
# ---------------------------------------------------------------------------
echo "-> [3/5] Playwright E2E gate"
if ! "$LIB/playwright_gate.sh" "$TARGET_REPO"; then
  echo "FAILED: Playwright gate — halting, no further steps, no PR will be created"
  exit 1
fi
echo

# ---------------------------------------------------------------------------
# Step 4/5: Human Gate — blocks on TTY y/N; never auto-approves.
# ---------------------------------------------------------------------------
echo "-> [4/5] Human gate"
SUMMARY="Task: $TASK_DESC
Target repo: $TARGET_REPO
Branch:      $BRANCH_NAME
ESLint gate: passed/skipped (see log above)
Playwright gate: passed/skipped (see log above)

--- diff (already committed to $BRANCH_NAME in step 1) ---
${DIFF:-<no diff available>}"

# PIPELINE_HUMAN_GATE_CMD mirrors PIPELINE_CODER_CMD above — lets tests drive
# the approved path without faking a TTY.
HUMAN_GATE_CMD="${PIPELINE_HUMAN_GATE_CMD:-$LIB/human_gate.sh}"
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
# Step 5/5: PR creation — only reachable after explicit approval above.
# ---------------------------------------------------------------------------
echo "-> [5/5] PR creation"
"$LIB/pr_create.sh" "$TARGET_REPO" --confirmed "$TASK_DESC"
echo
echo "=================================================="
echo " Pipeline complete — run $RUN_ID"
echo "=================================================="
