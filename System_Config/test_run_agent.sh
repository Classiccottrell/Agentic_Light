#!/usr/bin/env bash
# test_run_agent.sh — regression test for the gemini/agy --add-dir write-confinement
# bug: agy silently ignores process cwd for writes unless --add-dir <target> is
# passed, landing writes in ~/.gemini/antigravity-cli/scratch/ instead of $BRAIN.
# Mirrors the fix already landed and verified in the parent workspace's
# System_Config/test_run_agent.sh. Stubs agy to emulate that exact contract, so
# a future edit that drops the flag fails this test instead of silently
# regressing Agentic Light's write workflows.
set -euo pipefail

SYSCFG="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIXTURE="$(mktemp -d)"
trap 'rm -rf "$FIXTURE"' EXIT

mkdir -p "$FIXTURE/brain" "$FIXTURE/fake_scratch" "$FIXTURE/logs" "$FIXTURE/bin"

# Stub agy: writes a marker into --add-dir's target if present, else into a
# stand-in for ~/.gemini/antigravity-cli/scratch/ — the real binary's
# documented behavior. Always exits 0: assertions below are filesystem-based,
# not exit-code-based, so `set -e` never masks a failure. Writes to the
# ABSOLUTE $FAKE_SCRATCH path (not a relative one) because run_agent already
# `cd`s to $BRAIN before invoking this stub — a relative-path stub would land
# inside $BRAIN even without --add-dir and silently defeat the control.
cat > "$FIXTURE/bin/agy" <<'STUB'
#!/usr/bin/env bash
target=""
prev=""
for a in "$@"; do
  [[ "$prev" == "--add-dir" ]] && target="$a"
  prev="$a"
done
if [[ -n "$target" ]]; then
  printf 'WRITE-NONCE\n' > "$target/write-marker.txt"
else
  printf 'WRITE-NONCE\n' > "$FAKE_SCRATCH/write-marker.txt"
fi
exit 0
STUB
chmod +x "$FIXTURE/bin/agy"

# resolve_agent_provider() re-derives $AGENT_COMMAND from $PATH on every
# run_agent call, so the stub must be discoverable as "agy" on $PATH rather
# than exported as a bin path (production's AGENT_BIN override doesn't apply
# to this repo's config.sh contract).
PATH="$FIXTURE/bin:/usr/bin:/bin"
LOG="$FIXTURE/logs/run.log"
FAKE_SCRATCH="$FIXTURE/fake_scratch"
MAX_SECONDS=5
AGENTIC_LIGHT_PROVIDERS="gemini"
AGENTIC_LIGHT_PRIORITY="gemini"
AGENTIC_LIGHT_MODEL_GEMINI="gemini-test"
export PATH LOG FAKE_SCRATCH MAX_SECONDS AGENTIC_LIGHT_PROVIDERS AGENTIC_LIGHT_PRIORITY AGENTIC_LIGHT_MODEL_GEMINI

# config.sh unconditionally overwrites PATH (with $HOME/.local/bin first) and
# derives BRAIN from its own location ($WORKSPACE/brain), clobbering both
# overrides above. Re-assign PATH and BRAIN AFTER sourcing config.sh, not
# before (matches test_providers.sh's ordering) — otherwise provider_command()
# resolves the real, non-stub agy off this machine's PATH.
source "$SYSCFG/config.sh"
PATH="$FIXTURE/bin:/usr/bin:/bin"
BRAIN="$FIXTURE/brain"
source "$SYSCFG/run_agent.sh"
run_agent "regression probe"
[[ -f "$BRAIN/write-marker.txt" ]] ||
  { echo "  [FAIL] fixed gemini branch: write did not land in \$BRAIN"; exit 1; }
[[ ! -f "$FAKE_SCRATCH/write-marker.txt" ]] ||
  { echo "  [FAIL] fixed gemini branch: write leaked into the scratch dir"; exit 1; }
rm -f "$BRAIN/write-marker.txt"

# 2) Negative control: strip --add-dir from a copy and confirm the write
# escapes into the scratch dir instead. Proves this test would have caught
# the original bug (silent mis-write), not just that agy is reachable.
cp "$SYSCFG/run_agent.sh" "$FIXTURE/run_agent_no_add_dir.sh"
sed -i.bak '/--add-dir/d' "$FIXTURE/run_agent_no_add_dir.sh"
source "$FIXTURE/run_agent_no_add_dir.sh"
run_agent "regression probe"
[[ -f "$FAKE_SCRATCH/write-marker.txt" ]] ||
  { echo "  [FAIL] negative control: expected write in scratch dir when --add-dir is stripped"; exit 1; }
[[ ! -f "$BRAIN/write-marker.txt" ]] ||
  { echo "  [FAIL] negative control: write should not have landed in \$BRAIN without --add-dir"; exit 1; }

echo "  [ok] gemini/agy --add-dir write-confinement regression test"
