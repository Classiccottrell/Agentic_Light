#!/usr/bin/env python3
"""Audit a specialized fork after white-label pruning."""
import argparse
import json
import tempfile
from pathlib import Path


def audit(root, name, preset, old_name="Agentic Light"):
    root = Path(root)
    errors = []
    config = root / "System_Config"
    try:
        roster = json.loads((config / "agent-roster.json").read_text())
        presets = json.loads((config / "presets.json").read_text())
    except Exception as exc:
        return [f"cannot read specialized config: {exc}"]
    active = {role for role, data in roster.get("roles", {}).items() if data.get("active")}
    expected = set(presets.get(preset, {}).get("roles", []))
    if active != expected:
        errors.append(f"active roster {sorted(active)} != preset roster {sorted(expected)}")
    files = {p.stem for p in (root / "agents").glob("*.md") if p.name != "README.md"}
    if files != active:
        errors.append(f"agent files {sorted(files)} != active roster {sorted(active)}")
    selected_path = config / "skills-selected.json"
    if selected_path.exists():
        selected = set(json.loads(selected_path.read_text()).get("selected", []))
        on_disk = {p.name for p in (root / "skills").iterdir() if p.is_dir() and (p / "SKILL.md").exists()}
        if selected != on_disk:
            errors.append(f"selected skills {sorted(selected)} != on-disk skills {sorted(on_disk)}")
    generated = [root / "README.md", root / "CLAUDE.md", root / "GOVERNANCE.md", root / "microsite"]
    for path in generated:
        paths = [path] if path.is_file() else list(path.rglob("*.html"))
        for file in paths:
            text = file.read_text(errors="replace")
            if old_name in text:
                errors.append(f"old identity remains in {file.relative_to(root)}")
            if name not in text:
                errors.append(f"new identity missing from {file.relative_to(root)}")
    return errors


def self_test():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "System_Config").mkdir()
        (root / "agents").mkdir()
        (root / "skills" / "wcag-audit").mkdir(parents=True)
        (root / "microsite").mkdir()
        (root / "System_Config/agent-roster.json").write_text('{"roles":{"coder":{"active":true}}}')
        (root / "System_Config/presets.json").write_text('{"wcag-harness":{"roles":["coder"]}}')
        (root / "System_Config/skills-selected.json").write_text('{"selected":["wcag-audit"]}')
        (root / "agents/coder.md").write_text("coder")
        (root / "skills/wcag-audit/SKILL.md").write_text("skill")
        for file in ("README.md", "CLAUDE.md", "GOVERNANCE.md"):
            (root / file).write_text("CleanName")
        (root / "microsite/index.html").write_text("CleanName")
        assert not audit(root, "CleanName", "wcag-harness")
    print("white_label_check: self-test OK")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--name")
    parser.add_argument("--preset")
    parser.add_argument("--old-name", default="Agentic Light")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.name or not args.preset:
        parser.error("--name and --preset are required unless --self-test is used")
    errors = audit(args.root, args.name, args.preset, args.old_name)
    if errors:
        for error in errors:
            print(f"white_label_check: FAIL: {error}")
        return 1
    print(f"white_label_check: PASS: {args.preset} white-label contract valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
