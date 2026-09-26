#!/usr/bin/env python3
"""test_context_search.py — fixture test for memory_index.py +
memory_search.py lexical (FTS) search. Python port of
test_context_search.sh: after cataloging and indexing, a query for a
learning's excerpt ranks that learning first."""
import json
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


RETRIEVAL = """---
id: retrieval-learning
type: learning
title: Retrieval Learning
status: active
scope: workspace
created: 2026-09-23
updated: 2026-09-23
author: human
source: [brain/raw/source.md]
---
## Situation
Context retrieval needs a lexical fallback.
## Insight
FTS excerpts keep the packet useful when embeddings are unavailable.
## Evidence
Fixture.
## Reuse When
Local model is offline.
"""

OTHER = """---
id: other-project
type: project
title: Other Project
status: active
scope: project
created: 2026-09-23
updated: 2026-09-23
author: human
source: [brain/raw/source.md]
---
## Summary
Unrelated project.
## Goals
- Test indexing.
## Status
Active.
## Links
"""


def _run(tmp):
    (tmp / "brain/index").mkdir(parents=True)
    write_file(tmp / "brain/records/learnings/retrieval.md", RETRIEVAL)
    write_file(tmp / "brain/records/projects/other.md", OTHER)
    write_file(tmp / "brain/wiki/context.md", "Wiki page\n")
    write_file(tmp / "brain/weekly_logs/2026/2026-W39.md", "Weekly project retrieval note\n")

    proc = run_py(SC / "context_catalog.py", "build", "--root", tmp, "--out-dir", tmp / "brain/index")
    check("catalog builds", proc.returncode == 0, proc.stdout + proc.stderr)
    proc = run_py(SC / "memory_index.py", "--root", tmp)
    check("index builds", proc.returncode == 0, proc.stdout + proc.stderr)

    proc = run_py(SC / "memory_search.py", "FTS excerpts", "--root", tmp, "--json")
    check("json search exits 0", proc.returncode == 0, proc.stderr)
    try:
        result = json.loads(proc.stdout)
    except ValueError:
        result = []
    check("top hit is the learning", bool(result) and result[0]["type"] == "learning", proc.stdout)
    check("top hit excerpt matches", bool(result) and "FTS excerpts" in result[0]["excerpt"], proc.stdout)

    proc = run_py(SC / "memory_search.py", "FTS excerpts", "--root", tmp)
    check("plain search exits 0", proc.returncode == 0, proc.stderr)


def main():
    tmp = Path(tempfile.mkdtemp(prefix="agentic-light-context-search-test."))
    try:
        _run(tmp)
    finally:
        rmtree_force(tmp)
    if _FAILURES:
        print(f"context search fixture: FAILED ({len(_FAILURES)} check(s))", file=sys.stderr)
        return 1
    print("context search fixture: PASS")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
