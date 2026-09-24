#!/usr/bin/env python3
"""friday_process.py — Weekly close-out. Python port of friday_process.sh.

Locates brain/weekly_logs/<YEAR>/<WEEK_TAG>.md, appends a close-out entry
to its '## Agent Sessions' section (or the legacy '## Claude Sessions'
heading, matched for compatibility with pre-rename notes), and fills the
Master Note row's Summary cell for this week (backup -> rewrite ->
validate -> rollback). Manual-trigger only — no launchd/cron in Agentic
Light.

Usage: python3 System_Config/friday_process.py [YYYY-Www]
       python3 System_Config/friday_process.py --dry-run   (or DRY_RUN=1)
       python3 System_Config/friday_process.py --self-test
"""
import argparse
import os
import re
import sys
import time
from datetime import date
from pathlib import Path

import config

SENTINEL = "<!-- WEEKLY-INDEX-INSERT -->"
_HEADING_RE = re.compile(r'^## (Agent|Claude) Sessions\s*$')
_SEP_RE = re.compile(r'^---\s*$')
_WEEK_TAG_RE = re.compile(r'^\d{4}-W\d{2}$')


def stamp_closeout(text, line):
    """Insert `line` right after the first '---' separator following a
    '## Agent Sessions'/'## Claude Sessions' heading; if no such separator
    (or no heading at all) is ever found, append `line` as the last line of
    the file. Direct port of friday_process.sh's awk stamp — deliberately
    simpler than log_session.py's append_session_line (which synthesizes a
    heading when none exists); friday_process.sh never did that."""
    out_lines = []
    incs = False
    done = False
    for current in text.splitlines():
        if _HEADING_RE.match(current) or current in ("## Agent Sessions", "## Claude Sessions"):
            incs = True
        if incs and _SEP_RE.match(current) and not done:
            out_lines.append(line)
            done = True
            incs = False
        out_lines.append(current)
    if not done:
        out_lines.append(line)
    return "\n".join(out_lines) + "\n"


def rewrite_master_row(text, tag, summary):
    """Rewrite field 6 (1-indexed, the Summary cell) of every row whose
    trimmed field 2 == `tag`. Non-matching lines pass through byte-for-byte
    unchanged (mirrors awk: a line's $0 is only rebuilt via OFS when a
    field on THAT line was actually assigned). Returns (new_text, hit)."""
    hit = False
    out_lines = []
    for line in text.splitlines():
        fields = line.split("|")
        if len(fields) >= 6 and fields[1].strip() == tag:
            fields[5] = f" {summary} "
            line = "|".join(fields)
            hit = True
        out_lines.append(line)
    return "\n".join(out_lines) + "\n", hit


def _atomic_write(path, text):
    import tempfile
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


def run(week_tag_arg, dry_run, log):
    today = date.today().isoformat()

    if week_tag_arg:
        week_tag = week_tag_arg
        if not _WEEK_TAG_RE.match(week_tag):
            log(f"FATAL: invalid week arg '{week_tag}' — expected YYYY-Www")
            return 1
        year = week_tag.split("-W")[0]
    else:
        iso_year, iso_week, _unused = date.today().isocalendar()
        year, week = f"{iso_year:04d}", f"{iso_week:02d}"
        week_tag = f"{year}-W{week}"

    weekly_logs = config.BRAIN / "weekly_logs"
    note_abs = weekly_logs / year / f"{week_tag}.md"
    master = weekly_logs / f"{year} Master Note.md"

    if not config.BRAIN.is_dir():
        log(f"FATAL: brain dir missing: {config.BRAIN} — aborting")
        return 1
    if not note_abs.is_file():
        log(f"no weekly note for {week_tag} at {note_abs} — nothing to process; exiting")
        return 0

    note_text = note_abs.read_text(encoding="utf-8")
    if f"{today}: Friday close-out" in note_text:
        log(f"already closed out for {today} — nothing to do; exiting")
        return 0

    if dry_run:
        print(f"── DRY RUN — would process weekly_logs/{year}/{week_tag}.md ──")
        print("  -> append close-out line to '## Agent Sessions' (or legacy '## Claude Sessions')")
        print(f"  -> fill the Master Note row's Summary cell for [[{week_tag}]] (backup + validate + rollback)")
        log("dry run")
        return 0

    lock_dir = config.LOG_DIR / "friday_process.lock"
    with config.acquire_lock(lock_dir, max_age=600) as held:
        if not held:
            log(f"another friday_process holds {lock_dir} — skipping")
            return 0

        closeout = f"- {today}: Friday close-out — week closed out"
        try:
            _atomic_write(note_abs, stamp_closeout(note_text, closeout))
            log(f"close-out stamped into {week_tag}.md")
        except OSError:
            log(f"WARNING: failed to stamp close-out into {week_tag}.md")

        summary = f"Week closed out {today}."
        if master.is_file():
            master_text = master.read_text(encoding="utf-8")
            pre_rows = len(re.findall(r'^\| \[\[', master_text, re.MULTILINE))
            config.LOG_DIR.mkdir(parents=True, exist_ok=True)
            backup = config.LOG_DIR / f"master.{int(time.time())}.bak"
            with open(backup, "w", encoding="utf-8", newline="\n") as f:
                f.write(master_text)

            new_master_text, hit = rewrite_master_row(master_text, f"[[{week_tag}]]", summary)
            if not hit:
                log(f"WARNING: no Master Note row matched [[{week_tag}]] — summary not written; backup at {backup}")
            else:
                post_rows = len(re.findall(r'^\| \[\[', new_master_text, re.MULTILINE))
                if SENTINEL not in new_master_text or post_rows != pre_rows:
                    log(f"VALIDATION FAILED — sentinel missing or row count {pre_rows}->{post_rows}; "
                        f"Master Note left unchanged (backup {backup})")
                else:
                    _atomic_write(master, new_master_text)
                    backup.unlink()
                    log(f"Master Note summary written for {week_tag}")
        else:
            log(f"WARNING: Master Note not found at {master} — summary not written")

        log(f"friday_process done — {week_tag} closed out OK")
        return 0


def self_test():
    import shutil
    import subprocess
    import tempfile

    failures = []

    def check(label, cond, detail=""):
        if not cond:
            failures.append(f"{label}: {detail}")
            print(f"FAIL: {label}: {detail}", file=sys.stderr)

    # -- Pure functions --
    text = "# W10 2026\n---\n\n## Agent Sessions\n> auto\n\n---\n\n## Later\n"
    out = stamp_closeout(text, "- CLOSEOUT")
    check("closeout stamped immediately before the Agent Sessions separator", "\n- CLOSEOUT\n---\n" in out, out)

    legacy = "# W10 2026\n---\n\n## Claude Sessions\n>auto\n-\n\n---\n"
    out = stamp_closeout(legacy, "- CLOSEOUT")
    check("legacy heading recognized", "- CLOSEOUT" in out, out)

    no_heading = "# W10 2026\nno sessions section here\n"
    out = stamp_closeout(no_heading, "- CLOSEOUT")
    check("no heading -> appended at end", out.splitlines()[-1] == "- CLOSEOUT", out)

    master = ("# 2026 Master Note\n\n| Week | Sprint | Q | Label | Summary |\n"
              "|---|---|---|---|---|\n"
              "| [[2026-W10]] | 5 | Q1 | Mar 2-6 | _pending Friday summary_ |\n"
              "| [[2026-W11]] | 6 | Q1 | Mar 9-13 | old |\n"
              f"{SENTINEL}\n")
    new_text, hit = rewrite_master_row(master, "[[2026-W10]]", "Week closed out 2026-03-06.")
    check("row rewrite hit", hit)
    check("target row summary replaced", " Week closed out 2026-03-06. " in new_text, new_text)
    check("other row untouched", "| [[2026-W11]] | 6 | Q1 | Mar 9-13 | old |" in new_text, new_text)
    check("non-target lines byte-identical", "|---|---|---|---|---|" in new_text, new_text)
    _, hit2 = rewrite_master_row(master, "[[2026-W99]]", "x")
    check("no match -> hit False", hit2 is False)

    # -- Isolated temp workspace integration test --
    ws = Path(tempfile.mkdtemp(prefix="agentic-light-friday-process-test."))
    try:
        syscfg = ws / "System_Config"
        syscfg.mkdir()
        (ws / "brain" / "weekly_logs" / "2026").mkdir(parents=True)
        shutil.copy(Path(__file__), syscfg / "friday_process.py")
        shutil.copy(Path(__file__).parent / "config.py", syscfg / "config.py")

        note = ws / "brain" / "weekly_logs" / "2026" / "2026-W10.md"
        note.write_text("# W10 2026\n---\n\n## Agent Sessions\n> auto\n\n---\n", encoding="utf-8")
        master = ws / "brain" / "weekly_logs" / "2026 Master Note.md"
        master.write_text("# 2026 Master Note\n\n| Week | Sprint | Q | Label | Summary |\n"
                           "|---|---|---|---|---|\n"
                           "| [[2026-W10]] | 5 | Q1 | Mar 2-6 | _pending Friday summary_ |\n"
                           f"{SENTINEL}\n", encoding="utf-8")

        env = {**os.environ, "PYTHONUTF8": "1"}
        script = syscfg / "friday_process.py"

        proc = subprocess.run([sys.executable, str(script), "--dry-run", "2026-W10"],
                               cwd=str(ws), capture_output=True, encoding="utf-8", env=env)
        check("dry-run exits 0", proc.returncode == 0, proc.returncode)
        check("dry-run does not stamp the note", "Friday close-out" not in note.read_text(encoding="utf-8"))

        proc = subprocess.run([sys.executable, str(script), "2026-W10"],
                               cwd=str(ws), capture_output=True, encoding="utf-8", env=env)
        check("real run exits 0", proc.returncode == 0, proc.stderr)
        note_text = note.read_text(encoding="utf-8")
        check("note stamped", "Friday close-out" in note_text, note_text)
        master_text = master.read_text(encoding="utf-8")
        check("master summary filled", "Week closed out" in master_text, master_text)

        proc = subprocess.run([sys.executable, str(script), "2026-W10"],
                               cwd=str(ws), capture_output=True, encoding="utf-8", env=env)
        check("idempotent re-run exits 0", proc.returncode == 0, proc.stderr)
        check("idempotent re-run does not duplicate close-out",
              note.read_text(encoding="utf-8").count("Friday close-out") == 1)

        proc = subprocess.run([sys.executable, str(script), "not-a-week"],
                               cwd=str(ws), capture_output=True, encoding="utf-8", env=env)
        check("invalid week arg exits 1", proc.returncode == 1, proc.returncode)

        proc = subprocess.run([sys.executable, str(script), "2099-W01"],
                               cwd=str(ws), capture_output=True, encoding="utf-8", env=env)
        check("missing note for arbitrary week exits 0 (nothing to process)", proc.returncode == 0, proc.stderr)
    finally:
        from test_support import rmtree_force
        try:
            rmtree_force(ws)
        except OSError:
            pass

    if failures:
        print("friday_process: self-test FAILED:", file=sys.stderr)
        for f in failures:
            print(f"  {f}", file=sys.stderr)
        return 1
    print("self-test OK")
    return 0


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("week_tag", nargs="?", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = config.LOG_DIR / "friday_process.log"

    def log(msg):
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(log_path, "a", encoding="utf-8", newline="\n") as f:
            f.write(f"[{ts}] {msg}\n")

    log("friday_process start")
    dry_run = args.dry_run or os.environ.get("DRY_RUN", "0") == "1"
    return run(args.week_tag, dry_run, log)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
