#!/usr/bin/env python3
"""skills.py — lightweight, provider-neutral skill CLI. Python port of
skills.sh.

Scans skills/*/SKILL.md (generic frontmatter: name/description), no
Claude-specific assumptions, so any SKILL.md-based loader can reuse it.

  skills.py list                  -- list all skills (name — description)
  skills.py run <name> [args...]  -- run skills/<name>/run_<name>.py (or
                                      .sh, or the sole run_* entrypoint
                                      found)

Deliberate interface improvement over skills.sh's `run <name> "<args>"`
(one quoted, word-split string): argv passes through as a real list
(argparse REMAINDER), no re-splitting. Safe to change — nothing in this
repo calls `skills.sh run` today (no skill currently ships a run_*
entrypoint). .py entrypoints are preferred over .sh and dispatched via
sys.executable (blueprint suffix-dispatch convention); Windows has no
execute bit/shebang dispatch for a bare .sh.
"""
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

_FRONTMATTER_DELIM = re.compile(r'^---\s*$')


def frontmatter_field(path, key):
    """Value of a "key: value" line inside the leading --- ... --- block.
    Same awk-equivalent pattern as route_skill.py's frontmatter_field —
    each script keeps its own copy, matching this repo's own convention
    (frontmatter parsing is duplicated per-script, not shared via a lib)."""
    key_re = re.compile(rf'^{re.escape(key)}:\s*(.*)$')
    depth = 0
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    for line in text.splitlines():
        if _FRONTMATTER_DELIM.match(line):
            depth += 1
            if depth >= 2:
                break
            continue
        if depth == 1:
            m = key_re.match(line)
            if m:
                return m.group(1).strip()
    return ""


def cmd_list():
    for smd in sorted(ROOT.glob("*/SKILL.md"), key=str):
        name = frontmatter_field(smd, "name") or smd.parent.name
        desc = frontmatter_field(smd, "description") or "(no description)"
        print(f"{name} — {desc}")
    return 0


def _find_entrypoint(skill_dir, name):
    """skills/<name>/run_<name>.py or .sh (.py preferred), else the sole
    run_* entrypoint in the skill dir if exactly one exists — mirrors
    skills.sh's fallback."""
    for suffix in (".py", ".sh"):
        candidate = skill_dir / f"run_{name}{suffix}"
        if candidate.is_file():
            return candidate
    matches = sorted(p for p in skill_dir.glob("run_*") if p.is_file())
    return matches[0] if len(matches) == 1 else None


def cmd_run(name, args):
    skill_dir = ROOT / name
    if not skill_dir.is_dir():
        print(f"skills.py: no such skill: {name} (looked in {skill_dir})", file=sys.stderr)
        return 1

    entry = _find_entrypoint(skill_dir, name)
    if entry is None:
        print(f"skills.py: skill '{name}' has no executable entrypoint "
              f"(expected {skill_dir / f'run_{name}.py'})", file=sys.stderr)
        return 1

    if entry.suffix == ".py":
        argv = [sys.executable, str(entry), *args]
    elif entry.suffix == ".sh" and os.name == "nt":
        print(f"skills.py: entrypoint {entry} is a Bash script — Bash is required to run it "
              f"(use WSL or Git Bash, or provide run_{name}.py)", file=sys.stderr)
        return 1
    else:
        if not os.access(entry, os.X_OK):
            print(f"skills.py: found entrypoint but it is not executable: {entry} (chmod +x it)", file=sys.stderr)
            return 1
        argv = [str(entry), *args]

    proc = subprocess.run(argv)
    return proc.returncode


def main():
    parser = argparse.ArgumentParser(add_help=False)
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("list")
    run_p = sub.add_parser("run")
    run_p.add_argument("name")
    run_p.add_argument("args", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    if args.command == "list":
        return cmd_list()
    if args.command == "run":
        return cmd_run(args.name, args.args)
    print("usage: skills.py list", file=sys.stderr)
    print("       skills.py run <name> [args...]", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
