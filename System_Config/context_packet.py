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
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Per-section line budgets, so no single source (the roadmap used to take 80
# of the default 120 lines) crowds the session facts and matches out.
ROADMAP_LINES = 40
SESSION_LINES = 25
MATCH_LINES = 20
WEEKLY_NOTE_RE = re.compile(r"^\d{4}-W\d{2}\.md$")
STOPWORDS = {"the", "and", "for", "with", "this", "that", "from", "into", "add", "fix", "use", "make", "update"}
# Docs about the brain and its empty note form, not context worth injecting.
BOILERPLATE = {"README.md", "CLAUDE.md", "Weekly_Note_Template.md"}


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


def _roadmap_lines(path, n):
    """The roadmap's actionable `## Next` section (up to the next `## `
    heading), capped at n lines; the file's head when it has no such
    section. Shipped history is the least useful part for resuming work."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    start = next((i for i, line in enumerate(lines) if line.strip() == "## Next"), None)
    if start is None:
        return lines[:n]
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return lines[start:end][:n]


def latest_weekly_note(weekly_dir):
    """Newest `YYYY-Www.md` note anywhere under weekly_dir. Only real
    weekly notes qualify: a plain path sort picked Weekly_Note_Template.md
    (it sorts after `2026/...`), so the packet reported the template as
    the latest session facts."""
    if not weekly_dir.is_dir():
        return None
    notes = [p for p in weekly_dir.rglob("*.md") if WEEKLY_NOTE_RE.match(p.name)]
    return max(notes, key=lambda p: p.name) if notes else None


def _query_terms(query):
    return sorted({t for t in re.findall(r"[a-z0-9][a-z0-9_-]+", query.lower()) if len(t) >= 3 and t not in STOPWORDS})


def _fts_matches(root, context_dir, query, top):
    """Ranked matches from memory_index.py's FTS5 cache, or None when the
    cache isn't built (the caller then falls back to a term scan)."""
    db_path = root / "brain" / "index" / "memory.sqlite3"
    if not db_path.is_file():
        return None
    try:
        from memory_search import fts_search
        conn = sqlite3.connect(str(db_path))
        try:
            rows = fts_search(conn, " ".join(_query_terms(query)), top * 4)
        finally:
            conn.close()
    except (ImportError, sqlite3.Error):
        return None
    found = []
    for row in rows:
        path = root / row["path"]
        if path.is_file() and context_dir in path.parents and path.name not in BOILERPLATE:
            found.append(path)
    return found[:top]


def _term_matches(md_files, query, top):
    """Files ranked by how many distinct query terms they contain. A whole
    task sentence never appears verbatim in a note, so the old substring
    test matched nothing once the pipeline started passing the task."""
    terms = _query_terms(query)
    if not terms:
        return []
    scored = []
    for p in md_files:
        try:
            text = p.read_text(encoding="utf-8", errors="replace").lower()
        except OSError:
            continue
        hits = sum(1 for t in terms if t in text)
        if hits:
            scored.append((-hits, str(p), p))
    return [p for _, _, p in sorted(scored)[:top]]


def _recent_records(md_files, top):
    """No query: newest records first, by frontmatter `updated:`, skipping
    BOILERPLATE (already filtered out of md_files). Undated files sort last."""
    def updated(p):
        try:
            head = p.read_text(encoding="utf-8", errors="replace")[:2000]
        except OSError:
            return ""
        m = re.search(r"^updated:\s*(\S+)", head, re.MULTILINE) if head.startswith("---") else None
        return m.group(1) if m else ""
    return sorted(md_files, key=lambda p: (updated(p), str(p)), reverse=True)[:top]


def build_packet(root, profile_name, profile_explicit, query, top, max_lines, max_bytes):
    """Raises RuntimeError on a bad/missing profile or context root — a
    plain exception, not SystemExit, so an importing caller (pipeline/run.py
    calls this directly per the import-vs-subprocess convention) can catch
    it and degrade to "no packet" the same way bash's run.sh swallowed a
    nonzero context_packet.sh exit via `set +e`. main() below is the only
    caller that turns this into a process exit.

    Query matching: ranked FTS5 matches from memory_index.py's cache
    (brain/index/memory.sqlite3) when it has been built, else files ranked
    by how many distinct query terms (3+ chars, minus a few stopwords) they
    contain. Lexical either way; no embeddings are requested here.
    """
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
    # .astimezone() attaches the local zone to an otherwise-naive
    # datetime.now(), so %Z renders an abbreviation (e.g. "PDT") instead of
    # an empty string — matches bash's `date '+... %Z'` byte-for-byte on a
    # given machine (both derive the abbreviation from the same OS tzdata).
    lines.append(f"Generated: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}")
    lines.append("")

    if not profile_explicit:
        lines.append("## Roadmap")
        roadmap = root / "ROADMAP.md"
        if roadmap.is_file():
            lines.extend(_roadmap_lines(roadmap, ROADMAP_LINES))
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
        note = latest_weekly_note(root / "brain" / "weekly_logs")
        if note:
            lines.append(f"Source: {note.relative_to(root).as_posix()}")
            lines.extend(_tail_lines(note, SESSION_LINES))
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
    # key=str — see the "Recent Session Facts" sort above for why (matches
    # bash's flat-string `sort`, not Path's part-tuple ordering). Hidden
    # files/dirs (a leading '.') are skipped, matching `rg`'s default
    # behavior on the --query path below (see build_packet's docstring on
    # the query-match method's other, accepted differences from `rg`).
    md_files = sorted(
        (p for p in context_dir.rglob("*.md") if p.is_file() and p.name not in BOILERPLATE and not any(part.startswith(".") for part in p.relative_to(context_dir).parts)),
        key=str,
    )
    if query:
        matches = _fts_matches(root, context_dir, query, top)
        if matches is None:
            matches = _term_matches(md_files, query, top)
    else:
        matches = _recent_records(md_files, top) if top > 0 else []
    if not matches:
        lines.append("No matching context records.")
    else:
        for match in matches:
            rel = match.relative_to(root)
            lines.append(f"### {rel}")
            lines.extend(_head_lines(match, MATCH_LINES))
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
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
