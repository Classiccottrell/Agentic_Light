#!/usr/bin/env python3
"""Suggest or apply conservative cross-links for a human context record."""
import argparse
import hashlib
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from context_catalog import documents
from context_validate import parse_frontmatter

STOP = {
    "about", "after", "again", "all", "also", "and", "any", "are", "being", "but", "can", "could",
    "does", "for", "from", "has", "have", "how", "into", "its", "may", "more", "must", "need",
    "needs", "new", "not", "now", "one", "only", "our", "out", "should", "some", "than", "that",
    "the", "their", "them", "then", "there", "these", "they", "this", "use", "used", "uses",
    "using", "was", "way", "were", "what", "when", "which", "while", "will", "with", "would", "you",
}


def tokens(text):
    return {word for word in re.findall(r"[a-z0-9][a-z0-9-]{2,}", text.lower()) if word not in STOP}


def _confidence(title_tokens, title_overlap, overlap):
    """`high` (auto-applied by --apply) needs the target's title, not
    incidental vocabulary: two of its title words in the source, or its
    whole one-word title plus two more shared terms. One shared title word
    was enough before, so "Use SQLite for the agent cache" auto-linked
    "Agent timeouts need a watchdog" on `agent` alone."""
    if len(title_overlap) >= 2 or (len(title_tokens) == 1 and title_overlap and len(overlap) >= 3):
        return "high"
    if title_overlap or len(overlap) >= 2:
        return "medium"
    return "low"


def _atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def candidates(root, source):
    source_meta, source_body = parse_frontmatter(source)
    source_text = f"{source_meta.get('title', '')} {source_body}"
    source_tokens = tokens(source_text)
    result = []
    for item in documents(root):
        if str(root / item["path"]) == str(source):
            continue
        if item["path"].startswith("brain/records/sessions/curation-"):
            continue
        target_text = f"{item['title']} {item['excerpt']}"
        overlap = source_tokens & tokens(target_text)
        title_tokens = tokens(item["title"])
        title_overlap = title_tokens & source_tokens
        confidence = _confidence(title_tokens, title_overlap, overlap)
        result.append({"id": item["id"], "path": item["path"], "title": item["title"], "confidence": confidence, "overlap": sorted(overlap)})
    return sorted(result, key=lambda item: ({"high": 0, "medium": 1, "low": 2}[item["confidence"]], -len(item["overlap"]), item["id"]))


def session_record(root, source, accepted, rejected):
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    # Microseconds in the digest: two curations of the same file within one
    # second used to share a filename, and the second overwrote the first.
    digest = hashlib.sha1(f"{source}|{now.isoformat()}".encode()).hexdigest()[:8]
    path = root / "brain" / "records" / "sessions" / f"curation-{stamp}-{digest}.md"
    rel = str(source.relative_to(root))
    lines = [
        "---", f"id: curation-{stamp.lower()}-{digest}", "type: session", "title: Context curation", "status: active", "scope: session",
        f"created: {stamp[:10]}", f"updated: {stamp[:10]}", "author: ai", f"source: [{rel}]", "---", "## Task", f"Curate links for {rel}.",
        "## Outcome", f"Accepted: {', '.join(item['id'] for item in accepted) or 'none'}.", "## Changed", "Applied validated high-confidence links only.",
        "## Unresolved", f"Rejected or review-needed: {', '.join(item['id'] for item in rejected) or 'none'}.", "",
    ]
    _atomic_write(path, "\n".join(lines))


def apply_links(source, accepted):
    """Append new links to the record's `## Related Context` section,
    creating it once; a second run used to add a duplicate heading."""
    text = source.read_text(encoding="utf-8")
    new_links = [f"- [[{item['id']}]]" for item in accepted if f"[[{item['id']}]]" not in text]
    if not new_links:
        return False
    lines = text.rstrip("\n").split("\n")
    heading = next((i for i, line in enumerate(lines) if line.strip() == "## Related Context"), None)
    if heading is None:
        lines += ["", "## Related Context"] + new_links
    else:
        end = next((i for i in range(heading + 1, len(lines)) if lines[i].startswith("#")), len(lines))
        while end > heading + 1 and not lines[end - 1].strip():
            end -= 1
        lines[end:end] = new_links
    _atomic_write(source, "\n".join(lines) + "\n")
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--root", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--suggest", action="store_true")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--review", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    source = args.path.resolve()
    found = candidates(root, source)
    if args.suggest or args.review:
        for item in found:
            print(f"{item['confidence']}\t{item['id']}\t{item['title']}\t{','.join(item['overlap'])}")
        return 0
    accepted = [item for item in found if item["confidence"] == "high"]
    rejected = [item for item in found if item["confidence"] != "high"]
    changed = apply_links(source, accepted)
    session_record(root, source, accepted, rejected)
    print(f"context_curate: applied={len(accepted)} changed={'yes' if changed else 'no'} review={len(rejected)}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
