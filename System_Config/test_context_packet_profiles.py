#!/usr/bin/env python3
"""test_context_packet_profiles.py — fixture test for `context.py packet
--profile`. Python port of test_context_packet_profiles.sh: a profile's
explicit include lands in the packet, nothing outside its context_root
leaks in, and the packet stays under its --max-bytes budget with
multi-byte content."""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SC = ROOT / "System_Config"
sys.path.insert(0, str(SC))
from test_support import rmtree_force, run_py, write_file  # noqa: E402

_FAILURES = []


def check(label, cond, detail=""):
    if not cond:
        _FAILURES.append(f"{label}: {detail}")
        print(f"FAIL: {label}: {detail}", file=sys.stderr)


def _run(tmp):
    write_file(tmp / "System_Config/context_profiles/example-app.json",
               '{"name":"example-app","context_root":"app-context","default_scopes":["learning"],'
               '"include_paths":["app-context/learning.md"]}\n')
    write_file(tmp / "ROADMAP.md", "private workspace roadmap must not leak\n")
    write_file(tmp / "app-context/learning.md", "app learning: café, résumé, naïve, façade\n")

    proc = run_py(SC / "context.py", "--root", tmp, "packet", "--profile", "example-app",
                  "--query", "learning", "--max-bytes", "300")
    check("packet exits 0", proc.returncode == 0, proc.stderr)
    packet = proc.stdout.rstrip("\n")
    check("app record in packet", "app learning" in packet, packet)
    check("profile does not leak outside context_root", "private workspace roadmap" not in packet, packet)
    check("profile include header", "Profile Include: app-context/learning.md" in packet, packet)
    size = len(packet.encode("utf-8"))
    check("packet within 300 bytes", size <= 300, size)


def main():
    tmp = Path(tempfile.mkdtemp(prefix="agentic-light-context-profiles-test."))
    try:
        _run(tmp)
    finally:
        rmtree_force(tmp)
    if _FAILURES:
        print(f"context packet profile fixture: FAILED ({len(_FAILURES)} check(s))", file=sys.stderr)
        return 1
    print("context packet profile fixture: PASS")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
