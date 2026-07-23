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
RUN_ID="$(date +%Y%m%d-%H%M%S)"
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
# Step 1/5: Code Patch (coder)
# ---------------------------------------------------------------------------
echo "-> [1/5] Code patch step"
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
  PROMPT="Target repo: $TARGET_REPO. Task: $TASK_DESC. Create a feature branch, implement the change, and commit it."
  if ! LOG="$RUN_LOG" BRAIN="$TARGET_REPO" run_agent "$PROMPT"; then
    echo "FAILED: code patch step (coder agent exited non-zero)"
    exit 1
  fi
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
DIFF="$(cd "$TARGET_REPO" && git diff HEAD 2>/dev/null || true)"
SUMMARY="Task: $TASK_DESC
Target repo: $TARGET_REPO
ESLint gate: passed/skipped (see log above)
Playwright gate: passed/skipped (see log above)

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
# Step 5/5: PR creation — only reachable after explicit approval above.
# ---------------------------------------------------------------------------
echo "-> [5/5] PR creation"
"$LIB/pr_create.sh" "$TARGET_REPO" --confirmed "$TASK_DESC"
echo
echo "=================================================="
echo " Pipeline complete — run $RUN_ID"
echo "=================================================="
