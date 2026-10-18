#!/usr/bin/env python3
"""test_context_packet.py — fixture tests for System_Config/context_packet.py.
Python port of test_context_packet.sh. Same check(label, cond, detail)
convention as other test_*.py in this repo.

Runs the REAL context_packet.py against a scratch fixture root via its own
--root flag — no need to copy the script into a fake System_Config/ tree
the way the bash version did (context_packet.sh had no --root flag when
that fixture was written; context_packet.py's --root already redirects
every path it touches, so this port is simpler, not just translated).
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "context_packet.py"

_FAILURES = []


def check(label, cond, detail=""):
    if not cond:
        _FAILURES.append(f"{label}: {detail}")
        print(f"FAIL: {label}: {detail}", file=sys.stderr)


def main():
    tmp_root = Path(tempfile.mkdtemp(prefix="agentic-light-context-packet-test."))
    fake_root = tmp_root / "fake-root"
    (fake_root / "brain" / "weekly_logs" / "2024" / "W10").mkdir(parents=True)

    # Line 1 of ROADMAP.md is packed with 60 em dashes (3 bytes each in
    # UTF-8) — lands as line 5 of the packet under
    # AGENTIC_LIGHT_CONTEXT_MAX_LINES=5 below (packet lines 1-4 are the
    # fixed header/Generated/blank/## Roadmap). Chosen so the packet's
    # total CHARACTER count stays under MAX_BYTES=200 (so a naive
    # str[:200] character slice would not truncate at all and would
    # silently emit well over 200 bytes) while its total BYTE count
    # exceeds 200 — this is exactly the scenario that proves the
    # byte-exact fix, not just exercises it.
    (fake_root / "ROADMAP.md").write_text("—" * 60 + "\n", encoding="utf-8")
    (fake_root / "brain" / "weekly_logs" / "2024" / "W10" / "2024-W10.md").write_text(
        "## Agent Sessions\n- did a thing\n", encoding="utf-8",
    )

    base_env = {**os.environ, "PYTHONUTF8": "1"}
    for var in ("AGENTIC_LIGHT_CONTEXT_QUERY", "AGENTIC_LIGHT_CONTEXT_MAX_LINES", "AGENTIC_LIGHT_CONTEXT_MAX_BYTES"):
        base_env.pop(var, None)

    try:
        # ---------------------------------------------------------------
        # Fixture 1: a tiny byte budget with a dense multi-byte first
        # ROADMAP line still respects both AGENTIC_LIGHT_CONTEXT_MAX_LINES
        # and AGENTIC_LIGHT_CONTEXT_MAX_BYTES, and still contains the
        # Generated: line. Captured as raw bytes — no `encoding=` on
        # subprocess.run — the byte-exact 200-byte cut can legitimately
        # land mid multi-byte UTF-8 sequence, which would raise under
        # strict text-mode decoding. This is a deliberate deviation from
        # this repo's usual "encoding=utf-8 on every subprocess" rule,
        # required here because the thing under test IS the raw byte
        # boundary.
        # ---------------------------------------------------------------
        env1 = {**base_env, "AGENTIC_LIGHT_CONTEXT_MAX_LINES": "5", "AGENTIC_LIGHT_CONTEXT_MAX_BYTES": "200"}
        proc1 = subprocess.run([sys.executable, str(SCRIPT), "--root", str(fake_root)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env1)
        out1_bytes = proc1.stdout

        env_full = {**base_env, "AGENTIC_LIGHT_CONTEXT_MAX_LINES": "5"}
        proc_full = subprocess.run([sys.executable, str(SCRIPT), "--root", str(fake_root)],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env_full)
        full_chars1 = len(proc_full.stdout.decode("utf-8", errors="replace"))

        check("sanity: untruncated char count fits in 200 too "
              "(a char-sliced packet would also slip through under the old buggy line)",
              full_chars1 <= 200, full_chars1)
        check("byte budget actually held", len(out1_bytes) <= 200, len(out1_bytes))
        check("packet still contains a Generated: line",
              b"Generated:" in out1_bytes, out1_bytes[:120])
        print("fixture 1 (tiny byte budget respected with dense multi-byte content): PASS")

        # ---------------------------------------------------------------
        # Fixture 2: default budget contains all provenance headers.
        # ---------------------------------------------------------------
        proc2 = subprocess.run([sys.executable, str(SCRIPT), "--root", str(fake_root)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=base_env)
        out2 = proc2.stdout.decode("utf-8", errors="replace")
        check("default budget: title header", out2.startswith("# Agentic Light Context Packet\n"), out2[:200])
        check("default budget: Generated header", "\nGenerated:" in out2 or out2.startswith("Generated:"), out2[:200])
        check("default budget: Roadmap header", "\n## Roadmap\n" in out2, out2[:200])
        check("default budget: Active Preset header", "\n## Active Preset\n" in out2, out2[:200])
        check("default budget: Recent Session Facts header", "\n## Recent Session Facts\n" in out2, out2[:200])
        print("fixture 2 (default budget contains all provenance headers): PASS")
    finally:
        from test_support import rmtree_force
        try:
            rmtree_force(tmp_root)
        except OSError:
            pass

    if _FAILURES:
        print("context packet test: FAILED:", file=sys.stderr)
        for f in _FAILURES:
            print(f"  {f}", file=sys.stderr)
        return 1
    print("context packet test: PASS")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
