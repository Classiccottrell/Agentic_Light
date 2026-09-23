#!/usr/bin/env python3
"""Suggest or apply conservative cross-links for a human context record."""
import argparse
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from context_catalog import documents
from context_validate import parse_frontmatter

STOP = {"about", "after", "again", "being", "could", "from", "have", "into", "that", "the", "this", "with", "when"}


def tokens(text):
    return {word for word in re.findall(r"[a-z0-9][a-z0-9-]{2,}", text.lower()) if word not in STOP}


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
        title_overlap = tokens(item["title"]) & source_tokens
        confidence = "high" if len(title_overlap) >= 1 and len(overlap) >= 2 else "medium" if len(overlap) >= 1 else "low"
        result.append({"id": item["id"], "path": item["path"], "title": item["title"], "confidence": confidence, "overlap": sorted(overlap)})
    return sorted(result, key=lambda item: ({"high": 0, "medium": 1, "low": 2}[item["confidence"]], -len(item["overlap"]), item["id"]))


def session_record(root, source, accepted, rejected):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    digest = hashlib.sha1(str(source).encode()).hexdigest()[:8]
    path = root / "brain" / "records" / "sessions" / f"curation-{stamp}-{digest}.md"
    rel = str(source.relative_to(root))
    lines = [
        "---", f"id: curation-{stamp.lower()}-{digest}", "type: session", "title: Context curation", "status: active", "scope: session",
        f"created: {stamp[:10]}", f"updated: {stamp[:10]}", "author: ai", f"source: [{rel}]", "---", "## Task", f"Curate links for {rel}.",
        "## Outcome", f"Accepted: {', '.join(item['id'] for item in accepted) or 'none'}.", "## Changed", "Applied validated high-confidence links only.",
        "## Unresolved", f"Rejected or review-needed: {', '.join(item['id'] for item in rejected) or 'none'}.", "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def apply_links(source, accepted):
    text = source.read_text(encoding="utf-8")
    new_links = [f"- [[{item['id']}]]" for item in accepted if f"[[{item['id']}]]" not in text]
    if not new_links:
        return False
    suffix = "\n## Related Context\n" + "\n".join(new_links) + "\n"
    source.write_text(text.rstrip() + suffix, encoding="utf-8")
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
    raise SystemExit(main())
