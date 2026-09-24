#!/usr/bin/env python3
"""context_packet.py — profile-driven, bounded context packet. Python port
of context_packet.sh. Markdown remains the source of truth; this script only
assembles and truncates it.

Output is written as raw bytes to stdout (sys.stdout.buffer), not via
print(): the final byte-exact truncation (matching bash's `LC_ALL=C head -c`)
can legitimately cut a multi-byte UTF-8 sequence in half, which would raise
on decode if re-assembled as str.
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _head_lines(path, n):
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return text.splitlines()[:n]


def _tail_lines(path, n):
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return text.splitlines()[-n:] if n > 0 else []


def build_packet(root, profile_name, profile_explicit, query, top, max_lines, max_bytes):
    """Raises RuntimeError on a bad/missing profile or context root — a
    plain exception, not SystemExit, so an importing caller (pipeline/run.py
    calls this directly per the import-vs-subprocess convention) can catch
    it and degrade to "no packet" the same way bash's run.sh swallowed a
    nonzero context_packet.sh exit via `set +e`. main() below is the only
    caller that turns this into a process exit."""
    lines = []

    profile_path = root / "System_Config" / "context_profiles" / f"{profile_name}.json"
    if not profile_path.is_file():
        if profile_explicit:
            raise RuntimeError(f"context_packet: profile not found: {profile_path}")
        name, context_root, include_paths = "agentic-light", "brain", ["ROADMAP.md"]
    else:
        try:
            data = json.loads(profile_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"context_packet: cannot read profile {profile_path}: {exc}")
        name = data.get("name") or "unnamed"
        context_root = data.get("context_root") or "brain"
        include_paths = data.get("include_paths") or []

    context_dir = root / context_root
    if not context_dir.is_dir():
        raise RuntimeError(f"context_packet: context root not found: {context_dir}")

    if not profile_explicit:
        lines.append("# Agentic Light Context Packet")
    else:
        lines.append("# Context Packet")
        lines.append(f"Profile: {name}")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")

    if not profile_explicit:
        lines.append("## Roadmap")
        roadmap = root / "ROADMAP.md"
        if roadmap.is_file():
            lines.extend(_head_lines(roadmap, 80))
        else:
            lines.append("ROADMAP.md unavailable")
        lines.append("")
        lines.append("## Active Preset")
        active_preset = root / "System_Config" / ".active-preset"
        if active_preset.is_file():
            lines.append(active_preset.read_text(encoding="utf-8", errors="replace").strip())
        else:
            lines.append("unspecialized")
        lines.append("")
        lines.append("## Recent Session Facts")
        weekly_dir = root / "brain" / "weekly_logs"
        candidates = sorted(weekly_dir.rglob("*.md")) if weekly_dir.is_dir() else []
        if candidates:
            lines.extend(_tail_lines(candidates[-1], 25))
        else:
            lines.append("No weekly log found")
    elif include_paths:
        for include in include_paths:
            if not include:
                continue
            path = root / include
            if not path.is_file():
                continue
            lines.append(f"## Profile Include: {include}")
            lines.extend(_head_lines(path, 80))
            lines.append("")

    lines.append("## Context Matches")
    md_files = sorted(p for p in context_dir.rglob("*.md") if p.is_file())
    if query:
        query_lc = query.lower()
        matches = []
        for p in md_files:
            try:
                if query_lc in p.read_text(encoding="utf-8", errors="replace").lower():
                    matches.append(p)
            except OSError:
                continue
            if len(matches) >= top:
                break
    else:
        matches = md_files[-top:] if top > 0 else []

    if not matches:
        lines.append("No matching context records.")
    else:
        for match in matches:
            rel = match.relative_to(root)
            lines.append(f"### {rel}")
            lines.extend(_head_lines(match, 80))
            lines.append("")

    text = "\n".join(lines[:max_lines]) + "\n"
    return text.encode("utf-8")[:max_bytes]


def _positive_int(raw, default):
    try:
        value = int(raw)
        return value if value >= 0 else default
    except (TypeError, ValueError):
        return default


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--root", default=None)
    parser.add_argument("--profile", default=None)
    parser.add_argument("--query", default=None)
    parser.add_argument("--top", default=None)
    parser.add_argument("--max-lines", default=None)
    parser.add_argument("--max-bytes", default=None)
    parser.add_argument("query_positional", nargs="?", default=None)
    args = parser.parse_args()

    root = Path(args.root) if args.root else ROOT
    profile_explicit = args.profile is not None
    profile_name = args.profile if profile_explicit else "agentic-light"

    env_query = os.environ.get("AGENTIC_LIGHT_CONTEXT_QUERY", "")
    if args.query is not None:
        query = args.query
    elif env_query:
        query = env_query
    else:
        query = args.query_positional or ""

    top = _positive_int(args.top, 5)
    max_lines = _positive_int(args.max_lines or os.environ.get("AGENTIC_LIGHT_CONTEXT_MAX_LINES"), 120)
    max_bytes = _positive_int(args.max_bytes or os.environ.get("AGENTIC_LIGHT_CONTEXT_MAX_BYTES"), 12000)

    try:
        packet = build_packet(root, profile_name, profile_explicit, query, top, max_lines, max_bytes)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    sys.stdout.buffer.write(packet)
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
