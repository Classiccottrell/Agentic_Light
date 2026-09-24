#!/usr/bin/env python3
"""test_providers.py — fixture tests for config.py + run_agent.py. Python
port of test_providers.sh. Runs config.resolve_agent_provider()/
run_agent.run_agent() directly, in-process (Python's module-cache import
gives the same "once per process" semantics bash's `source` gave) — no
subprocess layer for THESE two, since they're plain library calls.

Fake provider binaries ARE genuinely PATH-discoverable executables (per
blueprint §3): resolve_agent_provider() does a bare-name shutil.which()
lookup, so the fake must be found the same way the real thing would be.
"""
import os
import stat
import sys
import tempfile
from pathlib import Path

ROOT = Path(os.path.abspath(__file__)).parent.parent
TMP_ROOT = Path(tempfile.mkdtemp(prefix="agentic-light-test."))
BIN_DIR = TMP_ROOT / "bin"
BRAIN_DIR = TMP_ROOT / "brain"
BIN_DIR.mkdir(parents=True)
BRAIN_DIR.mkdir(parents=True)

CALLS = TMP_ROOT / "calls"
os.environ["CALLS"] = str(CALLS)
os.environ["PATH"] = f"{BIN_DIR}:/usr/bin:/bin"
os.environ["AGENTIC_LIGHT_PROVIDERS"] = "gemini,codex,claude"
os.environ["AGENTIC_LIGHT_PRIORITY"] = "gemini,codex,claude"
os.environ["AGENTIC_LIGHT_MODEL_GEMINI"] = "gemini-test"
os.environ.pop("AGENT_TYPE", None)
os.environ["LOG"] = str(TMP_ROOT / "log")
os.environ["MAX_SECONDS"] = "5"
os.environ["BRAIN"] = str(BRAIN_DIR)

sys.path.insert(0, str(ROOT / "System_Config"))
import config          # noqa: E402  (env must be set before import — mirrors bash `source` ordering)
import run_agent as ra  # noqa: E402

_FAILURES = []


def check(label, cond, detail=""):
    if not cond:
        _FAILURES.append(f"{label}: {detail}")
        print(f"FAIL: {label}: {detail}", file=sys.stderr)


_FAKE_TEMPLATE = '''#!/usr/bin/env python3
import os, sys
calls = os.environ.get("CALLS")
if calls:
    with open(calls, "a", encoding="utf-8") as f:
        f.write("{name}:" + " ".join(sys.argv[1:]) + "\\n")
sys.exit(int(os.environ.get("FAKE_RC", "0")))
'''

_FAKE_CMD_TEMPLATE = '@echo off\r\npython "%~dp0{name}" %*\r\n'


def write_fake(name):
    """Create bin_dir/<name> (POSIX-executable, python3-shebang) and
    bin_dir/<name>.cmd (Windows PATHEXT wrapper) — see blueprint §3."""
    path = BIN_DIR / name
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(_FAKE_TEMPLATE.format(name=name))
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    with open(BIN_DIR / f"{name}.cmd", "w", encoding="utf-8", newline="") as f:
        f.write(_FAKE_CMD_TEMPLATE.format(name=name))


def remove_fake(name):
    for suffix in ("", ".cmd"):
        p = BIN_DIR / f"{name}{suffix}"
        if p.exists():
            p.unlink()


def calls_has_line(expected):
    if not CALLS.exists():
        return False
    return expected in CALLS.read_text(encoding="utf-8").splitlines()


def reset_calls():
    CALLS.write_text("", encoding="utf-8")


def calls_line_count():
    if not CALLS.exists():
        return 0
    return len(CALLS.read_text(encoding="utf-8").splitlines())


def main():
    import argparse
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--self-test", action="store_true", help="no-op: running this script always self-tests")
    parser.parse_args()

    for name in ("claude", "agy", "codex", "ollama"):
        write_fake(name)

    check("date_offset", config.date_offset("2024-03-04", 4, "%Y-%m-%d") == "2024-03-08",
          config.date_offset("2024-03-04", 4, "%Y-%m-%d"))

    reset_calls()
    ra.run_agent("gemini prompt")
    check("gemini with model --add-dir",
          calls_has_line(f"agy:-p gemini prompt --model gemini-test --add-dir {BRAIN_DIR} --sandbox --approval-mode auto_edit"),
          CALLS.read_text(encoding="utf-8") if CALLS.exists() else "<no calls file>")

    # No-model gemini sub-branch: force the fallthrough past
    # AGENTIC_LIGHT_MODEL_GEMINI and away from any real, gitignored
    # .agentic-light.conf on this machine, so the --add-dir assertion
    # covers both sub-branches, not just the --model one above.
    del os.environ["AGENTIC_LIGHT_MODEL_GEMINI"]
    config.AGENT_CONFIG = TMP_ROOT / "none.conf"
    reset_calls()
    ra.run_agent("gemini prompt")
    check("gemini no-model --add-dir",
          calls_has_line(f"agy:-p gemini prompt --add-dir {BRAIN_DIR} --sandbox --approval-mode auto_edit"),
          CALLS.read_text(encoding="utf-8") if CALLS.exists() else "<no calls file>")
    os.environ["AGENTIC_LIGHT_MODEL_GEMINI"] = "gemini-test"

    remove_fake("agy")
    reset_calls()
    os.environ["AGENTIC_LIGHT_MODEL_CODEX"] = "codex-test"
    ra.run_agent("codex prompt")
    check("codex with model",
          calls_has_line("codex:exec --sandbox workspace-write --model codex-test codex prompt"),
          CALLS.read_text(encoding="utf-8") if CALLS.exists() else "<no calls file>")

    os.environ["FAKE_RC"] = "7"
    rc = ra.run_agent("fail")
    check("fake_rc propagates", rc == 7, f"rc={rc}")
    check("fail call reused codex (agy removed)", calls_line_count() == 2, calls_line_count())
    del os.environ["FAKE_RC"]

    os.environ["AGENTIC_LIGHT_PROVIDERS"] = "claude"
    os.environ["AGENTIC_LIGHT_PRIORITY"] = "claude"
    os.environ["AGENTIC_LIGHT_MODEL_CLAUDE"] = "claude-test"
    reset_calls()
    ra.run_agent("claude prompt")
    check("claude with model",
          calls_has_line("claude:-p claude prompt --model claude-test --allowedTools Read,Write,Edit,Glob,Grep "
                          "--disallowedTools Bash,KillShell,Task,WebFetch,WebSearch,NotebookEdit "
                          "--permission-mode acceptEdits --max-budget-usd 2.00"),
          CALLS.read_text(encoding="utf-8") if CALLS.exists() else "<no calls file>")
    check("claude call count", calls_line_count() == 1, calls_line_count())

    check("validate_provider_lists valid", config.validate_provider_lists("claude,codex", "codex,claude") is True)
    for left, right in (("claude,claude", "claude"), ("wat", "wat"), ("claude,codex", "claude"), ("claude,", "claude")):
        check(f"validate_provider_lists rejects ({left!r}, {right!r})",
              config.validate_provider_lists(left, right) is False)

    remove_fake("codex")
    remove_fake("claude")
    reset_calls()
    os.environ["AGENTIC_LIGHT_PROVIDERS"] = "codex,claude"
    os.environ["AGENTIC_LIGHT_PRIORITY"] = "codex,claude"
    rc = ra.run_agent("none")
    check("no provider executable -> 127", rc == 127, f"rc={rc}")

    os.environ["AGENTIC_LIGHT_PROVIDERS"] = "ollama"
    os.environ["AGENTIC_LIGHT_PRIORITY"] = "ollama"
    rc = ra.run_agent("write")
    check("ollama refuses write workflow -> 64", rc == 64, f"rc={rc}")
    check("ollama refusal never invoked a binary", calls_line_count() == 0, calls_line_count())

    if _FAILURES:
        print("provider test: FAILED:", file=sys.stderr)
        for f in _FAILURES:
            print(f"  {f}", file=sys.stderr)
        return 1
    print("provider test: PASS")

    # Chain to test_run_agent.py exactly as test_providers.sh chained to
    # test_run_agent.sh — as a fresh subprocess (not an in-process import),
    # so its own module-level MAX_SECONDS/MAX_BUDGET capture and env-var
    # state start clean. Strip the AGENT_* exports resolve_agent_provider()
    # accumulated above before launching it, or a stale AGENT_TYPE would be
    # inherited as a (bogus) legacy override.
    for var in ("AGENT_TYPE", "AGENT_PROVIDER", "AGENT_COMMAND", "AGENT_MODEL", "CLAUDE"):
        os.environ.pop(var, None)
    import subprocess
    proc = subprocess.run([sys.executable, str(ROOT / "System_Config" / "test_run_agent.py")])
    return proc.returncode


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        import shutil as _shutil
        _shutil.rmtree(TMP_ROOT, ignore_errors=True)
