#!/usr/bin/env python3
"""Validate typed Markdown context records without third-party dependencies."""
import argparse
import json
import re
import sys
from pathlib import Path

TYPES = {
    "project": ["Summary", "Goals", "Status", "Links"],
    "decision": ["Decision", "Alternatives", "Rationale", "Consequences"],
    "learning": ["Situation", "Insight", "Evidence", "Reuse When"],
    "reference": ["Summary", "Source Details", "Notes"],
    "session": ["Task", "Outcome", "Changed", "Unresolved"],
}
REQUIRED = {"id", "type", "title", "status", "scope", "created", "updated", "author", "source"}
LINK_RE = re.compile(r"\[\[([^]|#]+)(?:#[^]|]+)?(?:\|[^]]+)?\]\]")


def parse_value(raw):
    raw = raw.strip()
    if not raw:
        return ""
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        return [] if not inner else [part.strip().strip("'\"") for part in inner.split(",")]
    return raw.strip("'\"")


def parse_frontmatter(path):
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end < 0:
        return {}, text
    data = {}
    current = None
    for line in text[4:end].splitlines():
        if line.startswith("  - ") and current:
            data.setdefault(current, []).append(parse_value(line[4:]))
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        data[key] = parse_value(value)
        current = key if not value.strip() else None
    return data, text[end + 4 :]


def body_sections(body):
    return set(re.findall(r"^##\s+(.+?)\s*$", body, re.MULTILINE))


def record_paths(root):
    return sorted((root / "brain" / "records").rglob("*.md"))


def known_targets(root):
    targets = set()
    for path in record_paths(root):
        meta, _ = parse_frontmatter(path)
        if meta.get("id"):
            targets.add(str(meta["id"]))
        targets.add(path.stem)
    targets.update(path.stem for path in (root / "brain" / "wiki").glob("*.md"))
    targets.update(path.stem for path in (root / "brain" / "weekly_logs").rglob("*.md"))
    return targets


def validate_file(path, root, targets=None):
    findings = []
    meta, body = parse_frontmatter(path)
    missing = sorted(REQUIRED - set(meta))
    if missing:
        findings.append(f"{path}: missing frontmatter: {', '.join(missing)}")
        return findings
    kind = str(meta["type"])
    if kind not in TYPES:
        findings.append(f"{path}: unsupported type: {kind}")
    if not meta.get("source"):
        findings.append(f"{path}: source must contain at least one provenance path")
    for section in TYPES.get(kind, []):
        if section not in body_sections(body):
            findings.append(f"{path}: missing section: {section}")
    targets = targets or known_targets(root)
    for target in LINK_RE.findall(body):
        if target.strip() not in targets:
            findings.append(f"{path}: broken wikilink: [[{target.strip()}]]")
    return findings


def validate(root, path):
    paths = record_paths(root) if path.is_dir() else [path]
    findings = []
    ids = {}
    for record in paths:
        meta, _ = parse_frontmatter(record)
        ident = meta.get("id")
        if ident:
            if ident in ids:
                findings.append(f"duplicate id {ident}: {ids[ident]} and {record}")
            ids[ident] = record
    targets = known_targets(root)
    for record in paths:
        findings.extend(validate_file(record, root, targets))
    return findings


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("validate")
    check.add_argument("path", type=Path)
    check.add_argument("--root", type=Path, default=None)
    check.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.command == "validate":
        root = (args.root or Path(__file__).resolve().parent.parent).resolve()
        findings = validate(root, args.path.resolve())
        if args.json:
            print(json.dumps({"valid": not findings, "findings": findings}, indent=2))
        else:
            for finding in findings:
                print(finding, file=sys.stderr)
        return 1 if findings else 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
