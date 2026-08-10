#!/usr/bin/env bash
# test_pipeline.sh — fixture tests for pipeline/run.sh and its lib/ scripts.
# Pattern mirrors System_Config/test_providers.sh: plain bash assertions
# ([[ ]] / grep -q) under set -euo pipefail, mktemp -d scratch, EXIT trap.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN="$ROOT/pipeline/run.sh"
LIB="$ROOT/pipeline/lib"

TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/agentic-light-pipeline-test.XXXXXX")"
PRE_LOGS="$(ls "$ROOT/pipeline/logs"/*.log 2>/dev/null || true)"
cleanup() {
  rm -rf "$TMP_ROOT"
  # run.sh tees its own log into the real repo's pipeline/logs/ (gitignored
  # but still real files on disk) — remove only the ones this test run added.
  local f
  for f in "$ROOT/pipeline/logs"/*.log; do
    [ -e "$f" ] || continue
    case "$PRE_LOGS" in *"$f"*) continue ;; esac
    rm -f "$f"
  done
}
trap cleanup EXIT

# git identity via env — no dependency on a real ~/.gitconfig.
export GIT_AUTHOR_NAME="Agentic Light Test" GIT_AUTHOR_EMAIL="test@agentic.light"
export GIT_COMMITTER_NAME="Agentic Light Test" GIT_COMMITTER_EMAIL="test@agentic.light"

# fake HOME so config.sh's PATH reset (System_Config/config.sh puts
# $HOME/.local/bin first) resolves our stub `gh` instead of the real one,
# without touching the real $HOME or any system bin dir. /opt/homebrew/bin
# is also on config.sh's fixed PATH list, so real npm/npx still resolve.
FAKE_HOME="$TMP_ROOT/fakehome"
mkdir -p "$FAKE_HOME/.local/bin"
CALLS="$TMP_ROOT/gh_calls"
cat > "$FAKE_HOME/.local/bin/gh" <<'EOF'
#!/usr/bin/env bash
printf 'gh %s\n' "$*" >> "$CALLS"
exit 0
EOF
chmod +x "$FAKE_HOME/.local/bin/gh"

# coder stub: PIPELINE_CODER_CMD override (already-documented test hook) —
# modifies a tracked file (seed.txt, exercises `git diff HEAD`) and adds an
# untracked one (PATCHED.txt, exercises the `git ls-files --others` half) so
# both halves of run.sh's DIFF-capture logic are covered.
CODER_STUB="$TMP_ROOT/coder_stub.sh"
cat > "$CODER_STUB" <<'EOF'
#!/usr/bin/env bash
# $1=task $2=target-repo
echo "modified" >> "$2/seed.txt"
echo "patched by test" >> "$2/PATCHED.txt"
EOF
chmod +x "$CODER_STUB"

# no-op coder stub: for the "coder made no changes" fixture.
NOOP_CODER_STUB="$TMP_ROOT/noop_coder_stub.sh"
cat > "$NOOP_CODER_STUB" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
chmod +x "$NOOP_CODER_STUB"

# human-gate stub: PIPELINE_HUMAN_GATE_CMD override — always approves.
# Exercises the pass-through path without faking a TTY.
APPROVE_STUB="$TMP_ROOT/approve_stub.sh"
cat > "$APPROVE_STUB" <<'EOF'
#!/usr/bin/env bash
echo "[approve_stub] auto-approving: $1"
exit 0
EOF
chmod +x "$APPROVE_STUB"

# new_target_repo <name> — git-init a fresh target repo with one commit.
new_target_repo() {
  local dir="$TMP_ROOT/$1"
  mkdir -p "$dir"
  git -C "$dir" init -q -b main
  echo "seed" > "$dir/seed.txt"
  git -C "$dir" add seed.txt
  git -C "$dir" commit -q -m "seed"
  printf '%s' "$dir"
}

run_pipeline() {
  # run_pipeline <target-repo> [extra env assignments already exported]
  env HOME="$FAKE_HOME" CALLS="$CALLS" PIPELINE_CODER_CMD="$CODER_STUB" \
      "$@"
}

# ---------------------------------------------------------------------------
# Fixture 1: normal pass — no lint/e2e config (gates WARN+skip), approved
# human gate, PR actually created (stubbed gh receives `pr create`).
# ---------------------------------------------------------------------------
REPO1="$(new_target_repo repo1)"
: > "$CALLS"
set +e
OUT1="$(run_pipeline env PIPELINE_HUMAN_GATE_CMD="$APPROVE_STUB" bash "$RUN" "add a widget" "$REPO1" 2>&1)"
RC1=$?
set -e
echo "$OUT1" | grep -q "code patch step complete"
echo "$OUT1" | grep -q "human gate: APPROVED"
echo "$OUT1" | grep -q "Pipeline complete"
[[ "$RC1" -eq 0 ]]
grep -q "^gh pr create" "$CALLS"
git -C "$REPO1" branch --show-current | grep -q '^agentic-light/'
[[ "$(git -C "$REPO1" log --oneline main.. | wc -l | tr -d ' ')" -ge 1 ]]
# The gate summary the approve stub echoed must show both the tracked
# modification (git diff HEAD) and the untracked new file (git ls-files
# --others) — i.e. what's shown to the human matches what got committed.
echo "$OUT1" | grep -q "seed.txt"
echo "$OUT1" | grep -q "PATCHED.txt"
echo "fixture 1 (normal pass): PASS"

# ---------------------------------------------------------------------------
# Fixture 1b: coder produces no changes -> fails, nothing committed, no PR.
# ---------------------------------------------------------------------------
REPO1B="$(new_target_repo repo1b)"
: > "$CALLS"
set +e
OUT1B="$(env HOME="$FAKE_HOME" CALLS="$CALLS" PIPELINE_CODER_CMD="$NOOP_CODER_STUB" \
  PIPELINE_HUMAN_GATE_CMD="$APPROVE_STUB" bash "$RUN" "no-op task" "$REPO1B" 2>&1)"
RC1B=$?
set -e
[[ "$RC1B" -eq 1 ]]
echo "$OUT1B" | grep -q "produced no changes"
[[ ! -s "$CALLS" ]]
echo "fixture 1b (coder produces no changes): PASS"

# ---------------------------------------------------------------------------
# Fixture 2: ESLint gate failure — hard stop, no PR.
# ---------------------------------------------------------------------------
REPO2="$(new_target_repo repo2)"
printf '{"scripts":{"lint":"exit 1"}}' > "$REPO2/package.json"
git -C "$REPO2" add package.json
git -C "$REPO2" commit -q -m "add failing lint script"
: > "$CALLS"
set +e
OUT2="$(run_pipeline env PIPELINE_HUMAN_GATE_CMD="$APPROVE_STUB" bash "$RUN" "task" "$REPO2" 2>&1)"
RC2=$?
set -e
[[ "$RC2" -eq 1 ]]
echo "$OUT2" | grep -q "FAILED: ESLint gate"
[[ ! -s "$CALLS" ]]
echo "fixture 2 (ESLint gate failure): PASS"

# ---------------------------------------------------------------------------
# Fixture 3: Playwright gate failure — hard stop, no PR.
# ---------------------------------------------------------------------------
REPO3="$(new_target_repo repo3)"
printf '{"scripts":{"test:e2e":"exit 1"}}' > "$REPO3/package.json"
git -C "$REPO3" add package.json
git -C "$REPO3" commit -q -m "add failing e2e script"
: > "$CALLS"
set +e
OUT3="$(run_pipeline env PIPELINE_HUMAN_GATE_CMD="$APPROVE_STUB" bash "$RUN" "task" "$REPO3" 2>&1)"
RC3=$?
set -e
[[ "$RC3" -eq 1 ]]
echo "$OUT3" | grep -q "FAILED: Playwright gate"
[[ ! -s "$CALLS" ]]
echo "fixture 3 (Playwright gate failure): PASS"

# ---------------------------------------------------------------------------
# Fixture 4: no-TTY behavior — real human_gate.sh, no TTY on stdin (default
# when run.sh is invoked from this script) -> pending, exit 2, no PR.
# ---------------------------------------------------------------------------
REPO4="$(new_target_repo repo4)"
: > "$CALLS"
set +e
OUT4="$(run_pipeline bash "$RUN" "task" "$REPO4" 2>&1 </dev/null)"
RC4=$?
set -e
[[ "$RC4" -eq 2 ]]
echo "$OUT4" | grep -q "PENDING: human gate awaiting interactive review"
[[ ! -s "$CALLS" ]]
echo "fixture 4 (no-TTY pending): PASS"

# ---------------------------------------------------------------------------
# Fixture 5: declined human-approval response. run.sh's own stdin has no TTY
# when driven from a script (fixture 4 above), so the *interactive* decline
# branch of lib/human_gate.sh needs a real pty; exercised directly here via
# Python's pty module rather than through run.sh end to end.
# ---------------------------------------------------------------------------
PTY_OUT="$TMP_ROOT/pty_out"
set +e
python3 - "n" "$PTY_OUT" "$LIB/human_gate.sh" "declined-fixture summary" <<'PY'
import os, pty, subprocess, sys, time
input_line, outfile = sys.argv[1], sys.argv[2]
cmd = sys.argv[3:]
master, slave = pty.openpty()
p = subprocess.Popen(cmd, stdin=slave, stdout=slave, stderr=slave)
os.close(slave)
os.write(master, (input_line + "\n").encode())
time.sleep(0.3)
data = b""
while True:
    try:
        chunk = os.read(master, 4096)
    except OSError:
        break
    if not chunk:
        break
    data += chunk
rc = p.wait()
with open(outfile, "wb") as f:
    f.write(data)
sys.exit(rc)
PY
RC5=$?
set -e
[[ "$RC5" -eq 1 ]]
grep -q "Declined" "$PTY_OUT"
echo "fixture 5 (declined human gate): PASS"

# ---------------------------------------------------------------------------
# Fixture 6: direct lib/pr_create.sh call without --confirmed -> refused,
# gh never invoked.
# ---------------------------------------------------------------------------
REPO6="$(new_target_repo repo6)"
: > "$CALLS"
set +e
OUT6="$(env HOME="$FAKE_HOME" CALLS="$CALLS" bash "$LIB/pr_create.sh" "$REPO6" 2>&1)"
RC6=$?
set -e
[[ "$RC6" -eq 1 ]]
echo "$OUT6" | grep -q "refusing to run: missing --confirmed guard flag"
[[ ! -s "$CALLS" ]]
echo "fixture 6 (pr_create.sh without --confirmed): PASS"

# ---------------------------------------------------------------------------
# Fixture 7: coder prompt no longer asks Claude to branch/commit itself
# (that contradicted run_agent.sh's --disallowedTools "Bash,...").
# ---------------------------------------------------------------------------
grep -q "the pipeline handles all git operations" "$RUN"
if grep -q "Create a feature branch, implement the change, and commit it" "$RUN"; then
  echo "fixture 7: stale 'Create a feature branch ... commit it' prompt text found in run.sh" >&2
  exit 1
fi
echo "fixture 7 (coder prompt no longer asks for branch/commit): PASS"

echo "pipeline test: PASS"
