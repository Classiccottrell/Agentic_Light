#!/usr/bin/env python3
"""dashboard.py — terminal-native status readout for this fork's current
state. Python port of dashboard.sh. Plain print/box-drawing, no ncurses, no
new dependency. A status readout, not an interactive app: no input
handling, prints and exits.

Reads (all optional — a fresh, unspecialized clone must print cleanly):
  System_Config/agent-roster.json   (written by specialize.py)
  pipeline/gate-config.json         (written by specialize.py)
  .agentic-light.conf               (written by bootstrap.py; parsed as
                                      data via config.py's config_value,
                                      never sourced/exec'd — security
                                      convention)
  brain/weekly_logs/YYYY/YYYY-Www.md (current ISO week's note)
  pipeline/logs/*.log                (most recent gate runs)

Relocatable (ROOT computed from __file__, never hardcoded). JSON is parsed
with the stdlib json module directly — dashboard.sh had to shell out to
`python3 -c "..."` for this (bash has no JSON support); now that the whole
script IS Python, that subprocess round-trip is gone, same rationale as
healthcheck.py's gen_*.py self-heal imports.

Every helper below takes its file paths as explicit arguments rather than
reading module-level globals (a deliberate improvement over dashboard.sh's
own approach, which had to save/restore global variables around its
self-test's fixture — see self_test() below): this way the self-test calls
the real functions directly against a scratch fixture dir with no
save/restore dance needed.

Usage: python3 System_Config/dashboard.py
       python3 System_Config/dashboard.py --self-test
"""
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

import config

ROOT = Path(os.path.abspath(__file__)).parent.parent
SYSCFG = ROOT / "System_Config"
ROSTER_FILE = SYSCFG / "agent-roster.json"
GATE_FILE = ROOT / "pipeline" / "gate-config.json"
PLOGS = ROOT / "pipeline" / "logs"
WIDTH = 63  # inner content width; box fits standard 80-col terminals

USAGE = "Usage: python3 System_Config/dashboard.py\n       python3 System_Config/dashboard.py --self-test"

_SESSION_HEADING_RE = re.compile(r'^## (Agent|Claude) Sessions\s*$')
_SEP_RE = re.compile(r'^---\s*$')


def _pad_line(text, width=WIDTH):
    """Right-pads/truncates `text` to `width` and wraps with box-drawing
    verticals. Long names are truncated with a trailing ellipsis rather
    than widening the box, so the box always fits 80 columns."""
    if len(text) > width:
        text = text[: width - 1] + "…"
    else:
        text = text + " " * (width - len(text))
    return f"│ {text} │"


def _rule(width=WIDTH):
    return "├" + "─" * (width + 2) + "┤"


def _top_rule(title, width=WIDTH):
    return "┌─ " + title + " " + "─" * (width - len(title) - 1) + "┐"


def _bot_rule(width=WIDTH):
    return "└" + "─" * (width + 2) + "┘"


def roster_lines(roster_file):
    """Roster role lines (or the "not configured" line), one per entry,
    from agent-roster.json."""
    if not roster_file.is_file():
        return ["no roster configured — run specialize.py"]
    try:
        data = json.loads(roster_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ["roster file unreadable — run specialize.py"]
    roles = data.get("roles", {})
    if not roles:
        return ["no roster configured — run specialize.py"]
    return [f"{name} [{'active' if cfg.get('active') else 'inactive'}]" for name, cfg in roles.items()]


def gate_lines(gate_file):
    """Gate name/status lines (or the "not configured" line), from
    pipeline/gate-config.json. Gates don't carry a runtime status of their
    own in the config, so this reports "configured" here; actual pass/fail
    comes from the recent-runs section."""
    if not gate_file.is_file():
        return ["no gates configured"]
    try:
        data = json.loads(gate_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ["gate file unreadable"]
    gates = data.get("gates", [])
    if not gates:
        return ["no gates configured"]
    out = []
    for g in gates:
        if isinstance(g, str):
            out.append(f"{g} [configured]")
        else:
            out.append(f"{g.get('name', 'custom')} [configured]")
    return out


def preset_summary(roster_file):
    """One line: preset label, or "not specialized"."""
    if not roster_file.is_file():
        return "not specialized — run specialize.py"
    try:
        data = json.loads(roster_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "not specialized — run specialize.py"
    roles = data.get("roles", {})
    active = [n for n, c in roles.items() if c.get("active")]
    if not active:
        return "specialized (no roles active)"
    return f"specialized — {len(active)} role(s) active"


def provider_summary():
    """Active provider from .agentic-light.conf, or "not configured". Uses
    config.py's config_value (plain-text parse, never sources the file) per
    the established security convention."""
    priority = config.config_value("PRIORITY") or config.config_value("PROVIDERS")
    if not priority:
        return "not configured — run bootstrap.py"
    first = priority.split(",")[0]
    return f"{first} (priority: {priority})"


def last_session_line(brain):
    """Most recent "- <timestamp>: ..." line under the current week's
    "## Agent Sessions" heading, or "none yet"."""
    iso_year, iso_week, _ = date.today().isocalendar()
    note = brain / "weekly_logs" / f"{iso_year}" / f"{iso_year}-W{iso_week:02d}.md"
    if not note.is_file():
        return f"none yet — no weekly note for {iso_year}-W{iso_week:02d}"
    in_section = False
    last = ""
    for line in note.read_text(encoding="utf-8").splitlines():
        if _SESSION_HEADING_RE.match(line):
            in_section = True
            continue
        if in_section and _SEP_RE.match(line):
            in_section = False
            continue
        if in_section and line.startswith("- "):
            last = line
    return last if last else "none yet this week"


def recent_gate_runs(n, plogs):
    """Last N pipeline/logs/*.log filenames, newest first, each with its
    run task line (if present). Logs are plain-text transcripts (see
    pipeline/run.py), not structured — pull the header "Task:" line as the
    summary."""
    if not plogs.is_dir():
        return ["no pipeline logs yet"]
    files = sorted((p for p in plogs.glob("*.log") if p.is_file()), reverse=True)[:n]
    if not files:
        return ["no pipeline logs yet"]
    out = []
    for f in files:
        base = f.stem
        task = ""
        try:
            for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith(" Task:"):
                    task = line[len(" Task:"):].strip()
                    break
        except OSError:
            pass
        out.append(f"{base} — {task}" if task else base)
    return out


def render(roster_file, gate_file, brain, plogs):
    lines = [
        _top_rule("Agentic Light"),
        _pad_line(f"Preset: {preset_summary(roster_file)}"),
        _pad_line(f"Provider: {provider_summary()}"),
        _rule(),
        _pad_line("Roster"),
    ]
    for l in roster_lines(roster_file):
        lines.append(_pad_line(f"  {l}"))
    lines.append(_pad_line(""))
    lines.append(_pad_line("Gates"))
    for l in gate_lines(gate_file):
        lines.append(_pad_line(f"  {l}"))
    lines.append(_rule())
    lines.append(_pad_line("Last session"))
    lines.append(_pad_line(f"  {last_session_line(brain)}"))
    lines.append(_rule())
    lines.append(_pad_line("Recent gate runs"))
    for l in recent_gate_runs(3, plogs):
        lines.append(_pad_line(f"  {l}"))
    lines.append(_bot_rule())
    return "\n".join(lines)


def self_test():
    import tempfile

    failures = []

    def check(label, cond, detail=""):
        if not cond:
            failures.append(f"{label}: {detail}")
        else:
            print(f"dashboard: self-test fixture ok: {label}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        roster_file = tmp / "agent-roster.json"
        gate_file = tmp / "gate-config.json"
        brain = tmp / "brain"
        plogs = tmp / "pipeline_logs"
        brain.mkdir()
        plogs.mkdir()

        # 1. Fresh/unspecialized: no roster, no gates, no logs.
        out = roster_lines(roster_file)
        check("fresh roster_lines", out == ["no roster configured — run specialize.py"], out)
        out = gate_lines(gate_file)
        check("fresh gate_lines", out == ["no gates configured"], out)
        out = preset_summary(roster_file)
        check("fresh preset_summary", out == "not specialized — run specialize.py", out)
        out = last_session_line(brain)
        check("fresh last_session_line", out.startswith("none yet"), out)
        out = recent_gate_runs(3, plogs)
        check("fresh recent_gate_runs", out == ["no pipeline logs yet"], out)

        # 2. Specialized fixture: roster + gates present.
        roster_file.write_text(
            json.dumps({"roles": {"coder": {"active": True, "capabilities": ["read", "write"]}, "qa": {"active": False}}}),
            encoding="utf-8",
        )
        gate_file.write_text(
            json.dumps({"gates": ["eslint", {"name": "custom", "script": "pipeline/lib/x.py"}]}),
            encoding="utf-8",
        )
        out = roster_lines(roster_file)
        check("roster active parsed", "coder [active]" in out, out)
        check("roster inactive parsed", "qa [inactive]" in out, out)
        out = gate_lines(gate_file)
        check("gate string parsed", "eslint [configured]" in out, out)
        check("custom gate parsed", "custom [configured]" in out, out)
        out = preset_summary(roster_file)
        check("preset_summary specialized", out.startswith("specialized"), out)

        # 3. Weekly note with an Agent Sessions line.
        iso_year, iso_week, _ = date.today().isocalendar()
        note_dir = brain / "weekly_logs" / f"{iso_year}"
        note_dir.mkdir(parents=True)
        note = note_dir / f"{iso_year}-W{iso_week:02d}.md"
        note.write_text(
            "## Agent Sessions\n"
            "> Auto-appended after each agent work session.\n"
            "- 2026-09-21 10:00:00: claude / coder — exit 0 (exit)\n"
            "- 2026-09-21 11:00:00: codex / qa — exit 1 (timeout)\n"
            "\n---\n",
            encoding="utf-8",
        )
        out = last_session_line(brain)
        check("last_session_line picked correct line", "codex / qa — exit 1" in out, out)

        # 4. pipeline log fixture.
        (plogs / "20260101-000000-1.log").write_text(" Task:        do the thing\n", encoding="utf-8")
        out = recent_gate_runs(3, plogs)
        check("recent_gate_runs picked up task line", any("do the thing" in l for l in out), out)

    if failures:
        print("dashboard: self-test FAILED:", file=sys.stderr)
        for f in failures:
            print(f"  {f}", file=sys.stderr)
        return 1
    print("self-test OK")
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    arg = argv[0] if argv else ""
    if arg == "--self-test":
        return self_test()
    if arg in ("-h", "--help"):
        print(USAGE)
        return 0
    if arg:
        print(f"unknown arg: {arg}", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 1
    print(render(ROSTER_FILE, GATE_FILE, config.BRAIN, PLOGS))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
