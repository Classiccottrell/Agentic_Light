#!/usr/bin/env python3
"""test_context_layer.py — end-to-end fixture for the context layer.
Python port of test_context_layer.sh: record validation, frontmatter/body
links, curation, FTS search, bounded packets, unrelated profiles, broken
links, duplicate IDs, stale embedding dimensions, Ollama absence, Unicode
byte caps, and raw-source immutability."""
import hashlib
import os
import re
import shutil
import subprocess
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


LIGHT = """---
id: light-project
type: project
title: Agentic Light
status: active
scope: project
created: 2026-09-23
updated: 2026-09-23
author: human
source: [brain/raw/source.md]
related: [[[human-learning]]]
---
## Summary
Agentic Light keeps context portable.
## Goals
- Keep context searchable.
## Status
Active.
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
The context layer needs app-agnostic records.
## Insight
Human records for Agentic Light should be linked by the agent.
## Evidence
The project needs searchable memory.
## Reuse When
Building a new harness.
"""

SEARCH = """---
id: search-decision
type: decision
title: Search Decision
status: active
scope: workspace
created: 2026-09-23
updated: 2026-09-23
author: agent
source: [brain/raw/source.md]
---
## Decision
Use SQLite FTS5 as the offline index.
## Alternatives
Hosted vector service.
## Rationale
The source must stay local and rebuildable.
## Consequences
Semantic search remains optional.
"""

WIKI = """---
title: Context Wiki
---
The context layer is searchable.
"""


def _stale_dimension_check(db_path):
    """Bump every stored embedding's dim: search() must skip mismatched
    vectors rather than rank them."""
    from memory_index import fake_embed, open_db
    from memory_search import search
    db = open_db(db_path)
    try:
        db.execute("UPDATE pages SET dim = dim + 1")
        db.commit()
        hits = search(db, fake_embed("context layer"), 10)
    finally:
        db.close()
    check("stale embedding dimension skipped",
          all(path != "brain/wiki/context.md" for path, _ in hits), hits)


def _run(base):
    tmp = base / "root"
    for d in ("records/projects", "records/decisions", "records/learnings", "records/sessions",
              "raw", "wiki", "index", "other"):
        (tmp / "brain" / d).mkdir(parents=True, exist_ok=True)
    write_file(tmp / "System_Config/context_profiles/other.json",
               '{"name":"other","context_root":"brain/other","include_paths":[]}\n')
    source = tmp / "brain/raw/source.md"
    write_file(source, "immutable raw source\n")
    write_file(tmp / "brain/records/projects/light.md", LIGHT)
    human = tmp / "brain/records/learnings/human.md"
    write_file(human, HUMAN)
    write_file(tmp / "brain/records/decisions/search.md", SEARCH)
    write_file(tmp / "brain/wiki/context.md", WIKI)

    raw_hash = sha256(source)
    proc = run_py(SC / "context.py", "--root", tmp, "validate")
    check("validate exits 0", proc.returncode == 0, proc.stdout + proc.stderr)
    proc = run_py(SC / "context.py", "--root", tmp, "catalog")
    check("catalog exits 0", proc.returncode == 0, proc.stdout + proc.stderr)
    links = (tmp / "brain/index/links.json").read_text(encoding="utf-8")
    check("links.json has related relation", '"relation": "related"' in links, links)
    check("links.json has human record", "brain/records/learnings/human.md" in links, links)

    proc = run_py(SC / "context.py", "--root", tmp, "curate", human, "--suggest")
    check("curate suggests light-project", "light-project" in proc.stdout, proc.stdout + proc.stderr)
    proc = run_py(SC / "context.py", "--root", tmp, "curate", human, "--apply")
    check("curate apply exits 0", proc.returncode == 0, proc.stderr)
    check("curate applied link", "[[light-project]]" in human.read_text(encoding="utf-8"))
    check("raw source unchanged", sha256(source) == raw_hash)

    proc = run_py(SC / "memory_index.py", "--root", tmp)
    check("memory_index exits 0", proc.returncode == 0, proc.stdout + proc.stderr)
    proc = run_py(SC / "memory_search.py", "--root", tmp, "--json", "context layer")
    check("search finds human-learning", "human-learning" in proc.stdout, proc.stdout + proc.stderr)

    proc = run_py(SC / "context.py", "--root", tmp, "packet", "--profile", "other", "--max-bytes", "1200")
    packet = proc.stdout.rstrip("\n")
    check("profile packet within 1200", len(packet) <= 1200, len(packet))
    check("unrelated profile excludes workspace records", "Agentic Light" not in packet, packet)

    invalid = base / "root-invalid"
    shutil.copytree(tmp, invalid)
    with open(invalid / "brain/records/learnings/human.md", "a", encoding="utf-8", newline="\n") as fh:
        fh.write("[[missing-record]]\n")
    proc = run_py(SC / "context.py", "--root", invalid, "validate")
    check("broken link fails validation", proc.returncode != 0)
    shutil.copy(tmp / "brain/records/projects/light.md", tmp / "brain/records/projects/duplicate.md")
    proc = run_py(SC / "context.py", "--root", tmp, "validate")
    check("duplicate id fails validation", proc.returncode != 0)

    _stale_dimension_check(tmp / "brain/index/memory.sqlite3")

    proc = run_py(SC / "memory_index.py", "--root", tmp, "--semantic")
    check("Ollama absence reported",
          re.search(r"Ollama|semantic indexing skipped|lexical index ready", proc.stderr) is not None,
          proc.stderr)

    write_file(tmp / "ROADMAP.md", "—" * 4000)
    # Raw bytes, not text: byte-exact truncation may split a multi-byte char.
    proc = subprocess.run([sys.executable, str(SC / "context_packet.py"), "--root", str(tmp)],
                          capture_output=True,
                          env={**os.environ, "AGENTIC_LIGHT_CONTEXT_MAX_BYTES": "256"})
    size = len(proc.stdout)
    check("unicode packet within 256 bytes", size <= 256, size)


def main():
    base = Path(tempfile.mkdtemp(prefix="agentic-light-context-layer-test."))
    try:
        _run(base)
    finally:
        rmtree_force(base)
    if _FAILURES:
        print(f"context layer fixture: FAILED ({len(_FAILURES)} check(s))", file=sys.stderr)
        return 1
    print("context layer fixture: PASS")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
