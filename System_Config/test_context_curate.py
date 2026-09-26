#!/usr/bin/env python3
"""test_context_curate.py — fixture tests for `context.py curate`. Python
port of test_context_curate.sh: --suggest proposes the high-confidence link
without modifying the record, --apply writes only that link (not the
low-confidence one), records a curation session that is never itself
suggested, and leaves brain/raw/ untouched."""
import hashlib
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


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


DEPLOYMENT = """---
id: deployment-pipeline
type: project
title: Deployment Pipeline
status: active
scope: project
created: 2026-09-23
updated: 2026-09-23
author: human
source: [brain/raw/source.md]
---
## Summary
The deployment pipeline ships verified releases.
## Goals
- Keep deployment pipeline reliable.
## Status
Active.
## Links
"""

ARCHIVE = """---
id: archive-project
type: project
title: Archive
status: stale
scope: project
created: 2026-09-23
updated: 2026-09-23
author: human
source: [brain/raw/source.md]
---
## Summary
Archive.
## Goals
- Preserve history.
## Status
Stale.
## Links
"""

HUMAN = """---
id: human-learning
type: learning
title: Human Learning
status: active
scope: workspace
created: 2026-09-23
updated: 2026-09-23
author: human
source: [brain/raw/source.md]
---
## Situation
The deployment pipeline is slow.
## Insight
The deployment pipeline needs a smaller verification pass.
## Evidence
Human observation.
## Reuse When
Pipeline work repeats.
"""


def _run(tmp):
    for d in ("records/learnings", "records/projects", "records/sessions", "raw"):
        (tmp / "brain" / d).mkdir(parents=True, exist_ok=True)
    source = tmp / "brain/raw/source.md"
    write_file(source, "immutable source\n")
    write_file(tmp / "brain/records/projects/deployment.md", DEPLOYMENT)
    write_file(tmp / "brain/records/projects/archive.md", ARCHIVE)
    human = tmp / "brain/records/learnings/human.md"
    write_file(human, HUMAN)

    source_hash = sha256(human)
    proc = run_py(SC / "context.py", "--root", tmp, "curate", human, "--suggest")
    check("suggest exits 0", proc.returncode == 0, proc.stderr)
    check("suggest proposes deployment-pipeline", "deployment-pipeline" in proc.stdout, proc.stdout)
    check("suggest leaves record unchanged", sha256(human) == source_hash)

    proc = run_py(SC / "context.py", "--root", tmp, "curate", human, "--apply")
    check("apply exits 0", proc.returncode == 0, proc.stderr)
    text = human.read_text(encoding="utf-8")
    check("apply writes high-confidence link", "[[deployment-pipeline]]" in text, text)

    proc = run_py(SC / "context.py", "--root", tmp, "curate", human, "--suggest")
    check("curation session not suggested", "curation-" not in proc.stdout, proc.stdout)
    check("low-confidence link not applied", "[[archive-project]]" not in text, text)
    check("curation session recorded", any((tmp / "brain/records/sessions").rglob("*.md")))
    check("raw source immutable", source.read_text(encoding="utf-8") == "immutable source\n")


def main():
    tmp = Path(tempfile.mkdtemp(prefix="agentic-light-context-curate-test."))
    try:
        _run(tmp)
    finally:
        rmtree_force(tmp)
    if _FAILURES:
        print(f"context curation fixture: FAILED ({len(_FAILURES)} check(s))", file=sys.stderr)
        return 1
    print("context curation fixture: PASS")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
