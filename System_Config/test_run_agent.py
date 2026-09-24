#!/usr/bin/env python3
"""test_run_agent.py — regression test for the gemini/agy --add-dir write-
confinement bug: agy silently ignores process cwd for writes unless
--add-dir <target> is passed, landing writes in
~/.gemini/antigravity-cli/scratch/ instead of $BRAIN. Python port of
test_run_agent.sh. Stubs agy to emulate that exact contract, so a future
edit that drops the flag fails this test instead of silently regressing
Agentic Light's write workflows.
"""
import importlib.util
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path

SYSCFG = Path(os.path.abspath(__file__)).parent
FIXTURE = Path(tempfile.mkdtemp(prefix="agentic-light-run-agent-test."))

BRAIN_DIR = FIXTURE / "brain"
FAKE_SCRATCH = FIXTURE / "fake_scratch"
BIN_DIR = FIXTURE / "bin"
for d in (BRAIN_DIR, FAKE_SCRATCH, FIXTURE / "logs", BIN_DIR):
    d.mkdir(parents=True)

# Stub agy: writes a marker into --add-dir's target if present, else into a
# stand-in for ~/.gemini/antigravity-cli/scratch/ — the real binary's
# documented behavior. Always exits 0: assertions below are filesystem-
# based, not exit-code-based. Writes to the ABSOLUTE FAKE_SCRATCH path (via
# the FAKE_SCRATCH env var, not a relative one) because run_agent already
# sets cwd=BRAIN before invoking this stub — a relative-path stub would
# land inside BRAIN even without --add-dir and silently defeat the control.
_AGY_STUB = '''#!/usr/bin/env python3
import os, sys
args = sys.argv[1:]
target = None
for i, a in enumerate(args):
    if a == "--add-dir" and i + 1 < len(args):
        target = args[i + 1]
if target:
    with open(os.path.join(target, "write-marker.txt"), "w", encoding="utf-8") as f:
        f.write("WRITE-NONCE\\n")
else:
    with open(os.path.join(os.environ["FAKE_SCRATCH"], "write-marker.txt"), "w", encoding="utf-8") as f:
        f.write("WRITE-NONCE\\n")
sys.exit(0)
'''

agy_path = BIN_DIR / "agy"
with open(agy_path, "w", encoding="utf-8", newline="\n") as f:
    f.write(_AGY_STUB)
agy_path.chmod(agy_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
with open(BIN_DIR / "agy.cmd", "w", encoding="utf-8", newline="") as f:
    f.write('@echo off\r\npython "%~dp0agy" %*\r\n')

# resolve_agent_provider() re-derives AGENT_COMMAND from PATH on every
# run_agent call, so the stub must be discoverable as "agy" on PATH rather
# than passed as an explicit bin path.
os.environ["PATH"] = f"{BIN_DIR}:/usr/bin:/bin"
os.environ["LOG"] = str(FIXTURE / "logs" / "run.log")
os.environ["FAKE_SCRATCH"] = str(FAKE_SCRATCH)
os.environ["MAX_SECONDS"] = "5"
os.environ["AGENTIC_LIGHT_PROVIDERS"] = "gemini"
os.environ["AGENTIC_LIGHT_PRIORITY"] = "gemini"
os.environ["AGENTIC_LIGHT_MODEL_GEMINI"] = "gemini-test"
os.environ["BRAIN"] = str(BRAIN_DIR)

sys.path.insert(0, str(SYSCFG))
import config          # noqa: E402
import run_agent as ra  # noqa: E402

_FAILURES = []


def check(label, cond, detail=""):
    if not cond:
        _FAILURES.append(f"{label}: {detail}")
        print(f"  [FAIL] {label}: {detail}", file=sys.stderr)


def main():
    marker = BRAIN_DIR / "write-marker.txt"
    scratch_marker = FAKE_SCRATCH / "write-marker.txt"

    ra.run_agent("regression probe")
    check("fixed gemini branch: write landed in $BRAIN", marker.is_file())
    check("fixed gemini branch: write did not leak into scratch dir", not scratch_marker.is_file())
    if marker.exists():
        marker.unlink()

    # Negative control: strip --add-dir from a copy of run_agent.py and
    # confirm the write escapes into the scratch dir instead. Proves this
    # test would have caught the original bug (silent mis-write), not just
    # that agy is reachable.
    original_src = (SYSCFG / "run_agent.py").read_text(encoding="utf-8")
    mutated_lines = [line for line in original_src.splitlines() if "--add-dir" not in line]
    mutated_path = FIXTURE / "run_agent_no_add_dir.py"
    mutated_path.write_text("\n".join(mutated_lines) + "\n", encoding="utf-8")

    spec = importlib.util.spec_from_file_location("run_agent_no_add_dir", mutated_path)
    mutated = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mutated)
    mutated.run_agent("regression probe")
    check("negative control: write escaped into scratch dir when --add-dir is stripped", scratch_marker.is_file())
    check("negative control: write should not have landed in $BRAIN without --add-dir", not marker.is_file())

    if _FAILURES:
        print("test_run_agent: FAILED", file=sys.stderr)
        return 1
    print("  [ok] gemini/agy --add-dir write-confinement regression test")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(FIXTURE, ignore_errors=True)
