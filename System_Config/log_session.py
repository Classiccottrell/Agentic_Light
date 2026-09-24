#!/usr/bin/env python3
"""log_session.py — launcher-level session logger (no AI/LLM call; pure
deterministic formatting/append). Python port of log_session.sh. Called once
by pipeline/run.py after the coder step completes; deliberately independent
of config.py (matches log_session.sh, which never sourced config.sh — it
derives its own ROOT/BRAIN directly).

Usage: log_session.py --provider <name> --role <role> --status <exit-code> --reason <exit|timeout|signal|refused> [--note <path>]
       log_session.py --self-test

Appends one line under the current ISO week's weekly note's
'## Agent Sessions' heading (brain/weekly_logs/YYYY/YYYY-Www.md). Also
matches the legacy '## Claude Sessions' heading still present in notes
created before the rename. --note (or LOG_SESSION_NOTE env var) overrides
the target file (never auto-created). If the default current-week note is
missing, monday_init.py is run first to create it from the template.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(os.path.abspath(__file__)).parent.parent
BRAIN = ROOT / "brain"


def _child_env():
    """env for a spawned Python child — PYTHONUTF8=1 so its own default I/O
    encoding is UTF-8 regardless of platform."""
    return {**os.environ, "PYTHONUTF8": "1"}


HEADING_RE = re.compile(r'^## (Agent|Claude) Sessions\s*$')
SEP_RE = re.compile(r'^---\s*$')
VALID_REASONS = ("exit", "timeout", "signal", "refused")


def _atomic_write(path, text):
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp_name, str(path))
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def append_session_line(note_path, provider, role, status, reason):
    ts = _now_str()
    line = f"- {ts}: {provider} / {role} — exit {status} ({reason})"
    text = note_path.read_text(encoding="utf-8")
    raw_lines = text.splitlines()

    if any(HEADING_RE.match(l) for l in raw_lines):
        out_lines = []
        incs = False
        done = False
        for current in raw_lines:
            if HEADING_RE.match(current):
                incs = True
            if incs and SEP_RE.match(current) and not done:
                out_lines.append(line)
                done = True
                incs = False
            out_lines.append(current)
        if not done:
            out_lines.append(line)
        new_text = "\n".join(out_lines) + "\n"
    else:
        prefix = text if text.endswith("\n") or not text else text + "\n"
        new_text = (prefix + "\n## Agent Sessions\n"
                    "> Auto-appended after each launcher-completed session.\n"
                    f"{line}\n")
    _atomic_write(note_path, new_text)


def _now_str():
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def current_week_note():
    year, week, _ = date.today().isocalendar()
    return BRAIN / "weekly_logs" / f"{year}" / f"{year}-W{week:02d}.md"


def self_test():
    failures = []

    def check(label, cond, detail=""):
        if not cond:
            failures.append(f"{label}: {detail}")

    tmp = Path(tempfile.mkstemp(suffix=".md")[1])
    tmp.write_text(
        "# W99 — Self-Test\n---\n\n## Decisions\n| Decision | Rationale | Date |\n|----------|-----------|------|\n\n---\n",
        encoding="utf-8",
    )
    append_session_line(tmp, "claude", "coder", "0", "exit")
    text = tmp.read_text(encoding="utf-8")
    check("heading created", "## Agent Sessions" in text)
    check("line 1 appended", text.count("exit 0 (exit)") == 1)

    append_session_line(tmp, "codex", "qa", "1", "timeout")
    text = tmp.read_text(encoding="utf-8")
    check("no duplicate heading", text.count("## Agent Sessions") == 1)
    check("two runs yield two lines", len(re.findall(r'^- \d{4}', text, re.MULTILINE)) == 2)
    tmp.unlink()

    # Legacy-heading compat.
    tmp = Path(tempfile.mkstemp(suffix=".md")[1])
    tmp.write_text(
        "# W99 — Self-Test\n---\n\n## Claude Sessions\n> Auto-appended after each AI work session.\n-\n\n---\n",
        encoding="utf-8",
    )
    append_session_line(tmp, "gemini", "coder", "0", "exit")
    text = tmp.read_text(encoding="utf-8")
    check("legacy heading not duplicated", text.count("## Claude Sessions") == 1)
    check("no unexpected new heading alongside legacy one", "## Agent Sessions" not in text)
    check("line stamped into legacy heading", text.count("exit 0 (exit)") == 1)
    tmp.unlink()

    # Missing current-week note: run a copy of this script + monday_init.py
    # + config.py + template from a temp workspace, so the real vault is
    # never touched.
    os.environ.pop("LOG_SESSION_NOTE", None)
    ws = Path(tempfile.mkdtemp())
    (ws / "System_Config").mkdir()
    (ws / "brain" / "weekly_logs").mkdir(parents=True)
    shutil.copy(Path(__file__), ws / "System_Config" / "log_session.py")
    shutil.copy(ROOT / "System_Config" / "monday_init.py", ws / "System_Config" / "monday_init.py")
    shutil.copy(ROOT / "System_Config" / "config.py", ws / "System_Config" / "config.py")
    (ws / "brain" / "weekly_logs" / "Weekly_Note_Template.md").write_text(
        "# W{{WEEK_NUM}} {{YEAR}} — TEMPLATE-MARKER\n---\n\n## Agent Sessions\n"
        "> Auto-appended after each launcher-completed session.\n\n---\n",
        encoding="utf-8",
    )
    year, week, _ = date.today().isocalendar()
    note = ws / "brain" / "weekly_logs" / f"{year}" / f"{year}-W{week:02d}.md"
    proc = subprocess.run(
        [sys.executable, str(ws / "System_Config" / "log_session.py"),
         "--provider", "claude", "--role", "coder", "--status", "0", "--reason", "exit"],
        capture_output=True, encoding="utf-8", env=_child_env(),
    )
    check("missing note auto-created via monday_init.py", note.is_file())
    if note.is_file():
        note_text = note.read_text(encoding="utf-8")
        check("auto-created note is from template", "TEMPLATE-MARKER" in note_text)
        section = note_text.split("## Agent Sessions", 1)[-1].split("---", 1)[0]
        check("line landed under ## Agent Sessions in auto-created note", section.count("claude / coder — exit 0 (exit)") == 1)
    check("stdout contract unchanged (empty)", proc.stdout == "", proc.stdout)

    # monday_init.py fails (no template): still exit 0, no note written.
    shutil.rmtree(ws / "brain" / "weekly_logs")
    (ws / "brain" / "weekly_logs").mkdir(parents=True)
    proc2 = subprocess.run(
        [sys.executable, str(ws / "System_Config" / "log_session.py"),
         "--provider", "claude", "--role", "coder", "--status", "0", "--reason", "exit"],
        capture_output=True, encoding="utf-8", env=_child_env(),
    )
    check("non-zero exit when monday_init.py fails should still be 0", proc2.returncode == 0, proc2.returncode)
    check("note not written despite monday_init.py failure", not note.is_file())

    # Explicit --note that doesn't exist: skip, never auto-create.
    proc3 = subprocess.run(
        [sys.executable, str(ws / "System_Config" / "log_session.py"),
         "--provider", "claude", "--role", "coder", "--status", "0", "--reason", "exit",
         "--note", str(ws / "nope.md")],
        capture_output=True, encoding="utf-8", env=_child_env(),
    )
    check("explicit missing --note exits 0", proc3.returncode == 0, proc3.returncode)
    check("explicit --note does not trigger auto-create", not (ws / "nope.md").exists() and not (ws / "brain" / "weekly_logs" / f"{year}").is_dir())

    shutil.rmtree(ws, ignore_errors=True)

    if failures:
        print("log_session: self-test FAILED:", file=sys.stderr)
        for f in failures:
            print(f"  {f}", file=sys.stderr)
        return 1
    print("self-test OK")
    return 0


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--provider", default="")
    parser.add_argument("--role", default="")
    parser.add_argument("--status", default="")
    parser.add_argument("--reason", default="")
    parser.add_argument("--note", default=os.environ.get("LOG_SESSION_NOTE", ""))
    parser.add_argument("-h", "--help", action="store_true")
    args = parser.parse_args()

    if args.help:
        print(f"Usage: {Path(sys.argv[0]).name} --provider <name> --role <role> --status <exit-code> --reason <exit|timeout|signal|refused> [--note <path>]", file=sys.stderr)
        print(f"       {Path(sys.argv[0]).name} --self-test", file=sys.stderr)
        return 0

    if args.self_test:
        return self_test()

    if not (args.provider and args.role and args.status and args.reason):
        print(f"Usage: {Path(sys.argv[0]).name} --provider <name> --role <role> --status <exit-code> --reason <exit|timeout|signal|refused> [--note <path>]", file=sys.stderr)
        return 1
    if args.reason not in VALID_REASONS:
        print(f"invalid --reason: {args.reason}", file=sys.stderr)
        return 1

    note = Path(args.note) if args.note else None
    if note is not None:
        if not note.is_file():
            print(f"log_session.py: no weekly note at {note} — skipping (explicit --note is never auto-created)", file=sys.stderr)
            return 0
    else:
        note = current_week_note()
        if not note.is_file():
            print(f"log_session.py: no weekly note at {note} — running monday_init.py to create it", file=sys.stderr)
            monday_init_py = ROOT / "System_Config" / "monday_init.py"
            result = subprocess.run([sys.executable, str(monday_init_py)],
                                     capture_output=True, encoding="utf-8", env=_child_env())
            if result.stdout:
                print(result.stdout, end="", file=sys.stderr)
            if result.stderr:
                print(result.stderr, end="", file=sys.stderr)
            if result.returncode != 0:
                print("log_session.py: monday_init.py exited non-zero", file=sys.stderr)
            if not note.is_file():
                print(f"log_session.py: weekly note still missing at {note} after monday_init.py — skipping", file=sys.stderr)
                return 0

    append_session_line(note, args.provider, args.role, args.status, args.reason)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
