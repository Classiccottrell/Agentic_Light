#!/usr/bin/env python3
"""test_context_catalog.py — fixture tests for context_validate.py and
context_catalog.py. Python port of test_context_catalog.sh: a valid record
validates and catalogs (raw source untouched), a record missing provenance
fails validation, and a duplicate id fails validation."""
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


DEMO = """---
id: demo-project
type: project
title: Demo Project
status: active
scope: project
projects: [demo]
tags: [test]
created: 2026-09-23
updated: 2026-09-23
author: human
source: [brain/raw/2026/W39/source.md]
related: []
---
## Summary
Demo project.
## Goals
- Test catalog.
## Status
Active.
## Links
"""

BROKEN = """---
id: broken
type: learning
title: Broken
status: active
scope: workspace
created: 2026-09-23
updated: 2026-09-23
author: human
source: []
---
## Situation
Test.
## Insight
Broken.
## Evidence
None.
## Reuse When
Never.
"""


def _run(tmp):
    for d in ("records/projects", "records/learnings", "wiki", "raw/2026/W39", "index"):
        (tmp / "brain" / d).mkdir(parents=True, exist_ok=True)
    demo = tmp / "brain/records/projects/demo.md"
    source = tmp / "brain/raw/2026/W39/source.md"
    write_file(demo, DEMO)
    write_file(source, "# immutable\n")

    proc = run_py(SC / "context_validate.py", "validate", demo, "--root", tmp)
    check("valid record validates", proc.returncode == 0, proc.stdout + proc.stderr)
    proc = run_py(SC / "context_catalog.py", "build", "--root", tmp, "--out-dir", tmp / "brain/index")
    check("catalog builds", proc.returncode == 0, proc.stdout + proc.stderr)

    catalog = json.loads((tmp / "brain/index/catalog.json").read_text(encoding="utf-8"))
    check("catalog first id", catalog["documents"][0]["id"] == "demo-project", catalog["documents"][0])
    check("catalog excerpt", catalog["documents"][0]["excerpt"].startswith("Demo project."), catalog["documents"][0])
    check("raw source immutable", source.read_text(encoding="utf-8") == "# immutable\n")

    broken = tmp / "brain/records/learnings/broken.md"
    write_file(broken, BROKEN)
    proc = run_py(SC / "context_validate.py", "validate", broken, "--root", tmp)
    check("missing provenance fails", proc.returncode != 0, "expected missing provenance failure")

    write_file(tmp / "brain/records/projects/duplicate.md", DEMO)
    proc = run_py(SC / "context_validate.py", "validate", tmp / "brain", "--root", tmp)
    check("duplicate id fails", proc.returncode != 0, "expected duplicate-id failure")


def main():
    tmp = Path(tempfile.mkdtemp(prefix="agentic-light-context-catalog-test."))
    try:
        _run(tmp)
    finally:
        rmtree_force(tmp)
    if _FAILURES:
        print(f"context catalog fixture: FAILED ({len(_FAILURES)} check(s))", file=sys.stderr)
        return 1
    print("context catalog fixture: PASS")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
