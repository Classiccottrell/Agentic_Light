#!/usr/bin/env python3
"""Build disposable metadata and link projections for the context layer."""
import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

from context_validate import LINK_RE, parse_frontmatter, record_paths, validate


def excerpt(body, limit=280):
    text = re.sub(r"^---.*?---\s*", "", body, flags=re.DOTALL)
    text = re.sub(r"^##\s+.*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"[#>*`\[\]]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit].rstrip() + ("…" if len(text) > limit else "")


def documents(root):
    found = []
    paths = record_paths(root)
    paths += sorted((root / "brain" / "wiki").glob("*.md"))
    paths += sorted((root / "brain" / "weekly_logs").rglob("*.md"))
    seen = set()
    for path in paths:
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        meta, body = parse_frontmatter(path)
        rel = str(path.relative_to(root))
        kind = str(meta.get("type") or ("wiki" if "/wiki/" in rel else "session"))
        found.append({
            "id": str(meta.get("id") or path.stem),
            "path": rel,
            "type": kind,
            "title": str(meta.get("title") or path.stem),
            "scope": str(meta.get("scope") or "workspace"),
            "projects": meta.get("projects", []),
            "tags": meta.get("tags", []),
            "updated": str(meta.get("updated") or ""),
            "excerpt": excerpt(body),
        })
    return found


def links(root, docs):
    by_id = {item["id"]: item["path"] for item in docs}
    output = []
    for item in docs:
        path = root / item["path"]
        meta, body = parse_frontmatter(path)
        for target in LINK_RE.findall(body):
            target = target.strip()
            output.append({"source": item["path"], "target": by_id.get(target, target), "relation": "related", "origin": "body", "confidence": 1.0 if target in by_id else 0.0})
        for field in ("related", "source"):
            values = meta.get(field, [])
            if not isinstance(values, list):
                values = [values]
            for target in LINK_RE.findall(" ".join(str(value) for value in values)):
                target = target.strip()
                output.append({"source": item["path"], "target": by_id.get(target, target), "relation": field, "origin": "frontmatter", "confidence": 1.0 if target in by_id else 0.0})
    return output


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def build(root, out_dir):
    findings = validate(root, root / "brain" / "records")
    if findings:
        raise SystemExit("context_catalog: validation failed\n" + "\n".join(findings))
    docs = documents(root)
    atomic_json(out_dir / "catalog.json", {"documents": docs})
    atomic_json(out_dir / "links.json", {"links": links(root, docs)})


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    cmd = sub.add_parser("build")
    cmd.add_argument("--root", type=Path, required=True)
    cmd.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "build":
        build(args.root.resolve(), args.out_dir.resolve())
        print(f"context_catalog: wrote {args.out_dir / 'catalog.json'} and {args.out_dir / 'links.json'}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    main()
