#!/usr/bin/env python3
"""monday_init.py — Weekly Workspace Initializer. Python port of
monday_init.sh.

Creates this week's note from the template (filling Sprint + Quarter),
creates this week's brain/raw/ folder, and adds a row to the Master Note's
Weekly Index. Idempotent: if the note already exists, skips re-templating
but still backfills a missing Master Note row. Dates are anchored to the
MONDAY of the current ISO week (config.week_info), so the note is correct
no matter which weekday the script runs.

Vacation Recovery: if the most recent logged week is more than 7 days
behind the current week, insert exactly ONE synthetic catch-up row into
the Master Note's Weekly Index (no per-week backfill), then proceed
normally.

Usage: python3 System_Config/monday_init.py
       python3 System_Config/monday_init.py --dry-run   (or DRY_RUN=1)
       python3 System_Config/monday_init.py --self-test
"""
import argparse
import os
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import config

SENTINEL = "<!-- WEEKLY-INDEX-INSERT -->"
_WEEK_STEM_RE = re.compile(r'^(\d{4})-W(\d{2})$')
_QUARTER_OF_MONTH = {1: 1, 2: 1, 3: 1, 4: 2, 5: 2, 6: 2,
                      7: 3, 8: 3, 9: 3, 10: 4, 11: 4, 12: 4}


def compute_context(today=None):
    """All the derived values monday_init needs for `today` (injectable —
    see config.week_info). Pure function, no I/O, so --self-test can
    exercise every date edge case directly. Reads config.BRAIN/config.RAW
    module-level (this script has exactly one workspace concept; the
    isolated-copy trick --self-test uses for the write path, same as
    log_session.py's, naturally retargets those to a scratch tree)."""
    monday, year, week_num, week_label = config.week_info(today)
    month_n = monday.month
    date_start = monday.isoformat()
    date_end = (monday + timedelta(days=4)).isoformat()
    init_date = (today or date.today()).isoformat()
    sprint = (int(week_num) + 1) // 2
    quarter = _QUARTER_OF_MONTH[month_n]
    weekly_logs = config.BRAIN / "weekly_logs"
    year_dir = weekly_logs / year
    wikilink = f"[[{year}-W{week_num}]]"
    return {
        "monday": monday, "year": year, "week_num": week_num,
        "sprint": sprint, "quarter": quarter, "week_label": week_label,
        "date_start": date_start, "date_end": date_end, "init_date": init_date,
        "weekly_logs": weekly_logs, "year_dir": year_dir,
        "note_file": year_dir / f"{year}-W{week_num}.md",
        "master": weekly_logs / f"{year} Master Note.md",
        "template": weekly_logs / "Weekly_Note_Template.md",
        "wikilink": wikilink,
        "index_row": f"| {wikilink} | {sprint} | Q{quarter} | {week_label} | _pending Friday summary_ |",
        "raw_dir": config.RAW / year / f"W{week_num} {week_label}",
    }


def iso_monday(year, week):
    """Monday of ISO (year, week) — Jan 4 is always in ISO week 1."""
    jan4 = date(int(year), 1, 4)
    week1_monday = jan4 - timedelta(days=jan4.isoweekday() - 1)
    return week1_monday + timedelta(weeks=int(week) - 1)


def find_last_note(weekly_logs):
    """Lexically latest weekly_logs/*/*.md (mindepth 2, maxdepth 2) — matches
    bash's `find ... | sort | tail -1`. Master Notes/template are naturally
    excluded downstream by the YYYY-Www stem regex, not by this glob."""
    if not weekly_logs.is_dir():
        return None
    candidates = sorted((p for p in weekly_logs.glob("*/*.md") if p.is_file()), key=str)
    return candidates[-1] if candidates else None


def gap_row_for(weekly_logs, monday, year, week_num):
    """Vacation Recovery: the synthetic catch-up Master Note row, or "" if
    the most recently logged week is within 7 days of (year, week_num)."""
    last_note = find_last_note(weekly_logs)
    if last_note is None:
        return ""
    m = _WEEK_STEM_RE.match(last_note.stem)
    if not m:
        return ""
    last_year, last_week = m.group(1), m.group(2)
    if f"{last_year}-W{last_week}" == f"{year}-W{week_num}":
        return ""
    try:
        last_monday = iso_monday(last_year, last_week)
    except ValueError:
        return ""
    gap_days = (monday - last_monday).days
    if gap_days > 7:
        gap_weeks = gap_days // 7
        return f"| [[gap]] | — | — | catch-up | Weeks skipped: {gap_weeks} (W{last_week} → W{week_num}) |"
    return ""


def update_master_index(master, gap_row, index_row, wikilink, log_dir):
    """Backup -> insert row(s) immediately before SENTINEL -> validate row
    count didn't drop and the sentinel is still present -> rollback on
    failure. Ported from monday_init.sh's update_master_index."""
    if not master.is_file():
        print(f"[monday_init] WARNING: Master Note not found at {master} — row NOT added.", file=sys.stderr)
        return
    text = master.read_text(encoding="utf-8")
    if SENTINEL not in text:
        print("[monday_init] WARNING: index sentinel not found in Master Note — row NOT added.", file=sys.stderr)
        return

    rows = ""
    if gap_row and "| [[gap]] |" not in text:
        rows += gap_row + "\n"
    if f"| {wikilink} |" not in text:
        rows += index_row + "\n"

    if not rows:
        print(f"[monday_init] Master Note already has a row for {wikilink} — not duplicating.")
        return

    pre_rows = len(re.findall(r'^\| \[\[', text, re.MULTILINE))
    log_dir.mkdir(parents=True, exist_ok=True)
    backup = log_dir / f"master.{int(time.time())}.bak"
    with open(backup, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)

    new_text = text.replace(SENTINEL, rows + SENTINEL, 1)
    post_rows = len(re.findall(r'^\| \[\[', new_text, re.MULTILINE))

    if SENTINEL not in new_text or post_rows < pre_rows:
        print(f"[monday_init] VALIDATION FAILED — rolled back from {backup}", file=sys.stderr)
        return

    _atomic_write(master, new_text)
    backup.unlink()
    print(f"[monday_init] Master Note index row(s) added for {wikilink}.")


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


def run(dry_run=False, today=None):
    """Core routine. Returns a process exit code. `today` is injectable for
    --self-test; production callers always pass None (real system date)."""
    ctx = compute_context(today)
    log_dir = config.LOG_DIR

    # Mirrors config.sh's automatic `source`-time side effects (resolve then
    # warn-only validate), which ran unconditionally, before bash's own
    # DRY_RUN check — monday_init itself never uses a provider, but every
    # script that sourced config.sh got this diagnostic for free.
    config.resolve_agent_provider()
    if not config.validate_config():
        print("config.py: configuration warnings above — some scripts may misbehave", file=sys.stderr)

    if dry_run:
        print(f"Would create: {ctx['note_file']}  (Monday-anchored: {ctx['date_start']} -> {ctx['date_end']})")
        print(f"  Sprint {ctx['sprint']} | Q{ctx['quarter']} | {ctx['week_label']}")
        print(f"Master Note row: {ctx['index_row']}")
        if ctx["note_file"].is_file():
            print("(note already exists - real run would skip re-templating)")
        print(f"Would create raw folder: {ctx['raw_dir']}")
        gap_row = gap_row_for(ctx["weekly_logs"], ctx["monday"], ctx["year"], ctx["week_num"])
        if gap_row:
            print(f"VACATION RECOVERY: would insert catch-up row: {gap_row}")
        else:
            print("VACATION RECOVERY: no gap > 7 days — skipped")
        return 0

    log_dir.mkdir(parents=True, exist_ok=True)
    lock_dir = log_dir / "monday_init.lock"
    with config.acquire_lock(lock_dir, max_age=600) as held:
        if not held:
            print(f"[monday_init] another run holds {lock_dir} — skipping", file=sys.stderr)
            return 0

        config.ensure_current_week_raw_folder()
        print(f"[monday_init] raw folder ready: raw/{ctx['year']}/W{ctx['week_num']} {ctx['week_label']}")

        gap_row = gap_row_for(ctx["weekly_logs"], ctx["monday"], ctx["year"], ctx["week_num"])

        if ctx["note_file"].is_file():
            print(f"[monday_init] Note already exists: {ctx['note_file']} — skipping note body.")
            update_master_index(ctx["master"], gap_row, ctx["index_row"], ctx["wikilink"], log_dir)
            print(f"[monday_init] Done — {time.strftime('%a %b %d %H:%M:%S %Y')}")
            return 0

        print(f"[monday_init] Initializing W{ctx['week_num']} {ctx['year']} — Sprint {ctx['sprint']}, Q{ctx['quarter']}")

        if not ctx["template"].is_file():
            print(f"[monday_init] FATAL: template not found: {ctx['template']}", file=sys.stderr)
            return 1

        ctx["year_dir"].mkdir(parents=True, exist_ok=True)
        text = ctx["template"].read_text(encoding="utf-8")
        for token, value in (
            ("{{WEEK_LABEL}}", ctx["week_label"]), ("{{DATE_START}}", ctx["date_start"]),
            ("{{DATE_END}}", ctx["date_end"]), ("{{WEEK_NUM}}", ctx["week_num"]),
            ("{{YEAR}}", ctx["year"]), ("{{SPRINT}}", str(ctx["sprint"])),
            ("{{QUARTER}}", str(ctx["quarter"])), ("{{INIT_DATE}}", ctx["init_date"]),
        ):
            text = text.replace(token, value)
        _atomic_write(ctx["note_file"], text)
        print(f"[monday_init] Note created: {ctx['note_file']}")

        update_master_index(ctx["master"], gap_row, ctx["index_row"], ctx["wikilink"], log_dir)
        print(f"[monday_init] Done — {time.strftime('%a %b %d %H:%M:%S %Y')}")
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

    # -- Pure date-math edge cases (config.week_info via compute_context) --
    ctx = compute_context(date(2026, 6, 28))  # a Sunday
    check("Sunday anchors back to Monday", ctx["monday"] == date(2026, 6, 22), ctx["monday"])
    check("Sunday week label", ctx["week_label"] == "Jun 22-26", ctx["week_label"])

    ctx = compute_context(date(2026, 7, 1))  # mid-week, month-crossing week
    check("month-crossing label", ctx["week_label"] == "Jun 29 - Jul 3", ctx["week_label"])
    check("month-crossing quarter uses Monday's month (Jun -> Q2)", ctx["quarter"] == 2, ctx["quarter"])

    ctx = compute_context(date(2025, 12, 29))  # ISO year rollover
    check("ISO rollover year", ctx["year"] == "2026", ctx["year"])
    check("ISO rollover week", ctx["week_num"] == "01", ctx["week_num"])
    check("ISO rollover quarter (December -> Q4)", ctx["quarter"] == 4, ctx["quarter"])
    check("ISO rollover master note name", ctx["master"].name == "2026 Master Note.md", ctx["master"].name)

    # -- Isolated temp workspace: real writes never touch the live brain/ --
    ws = Path(tempfile.mkdtemp(prefix="agentic-light-monday-init-test."))
    try:
        syscfg = ws / "System_Config"
        syscfg.mkdir()
        (ws / "brain" / "weekly_logs").mkdir(parents=True)
        shutil.copy(Path(__file__), syscfg / "monday_init.py")
        shutil.copy(Path(__file__).parent / "config.py", syscfg / "config.py")
        (ws / "brain" / "weekly_logs" / "Weekly_Note_Template.md").write_text(
            "# W{{WEEK_NUM}} {{YEAR}} — Sprint {{SPRINT}} Q{{QUARTER}}\n"
            "{{DATE_START}} to {{DATE_END}} ({{WEEK_LABEL}}), init {{INIT_DATE}}\n"
            "---\n\n## Agent Sessions\n\n---\n",
            encoding="utf-8",
        )
        year, week, _ = date.today().isocalendar()
        master = ws / "brain" / "weekly_logs" / f"{year} Master Note.md"
        master.write_text(f"# {year} Master Note\n\n| Week | Sprint | Q | Label | Summary |\n"
                           f"{SENTINEL}\n", encoding="utf-8")
        note = ws / "brain" / "weekly_logs" / f"{year}" / f"{year}-W{week:02d}.md"

        env = {**os.environ, "PYTHONUTF8": "1"}

        # Dry run: no writes.
        proc = subprocess.run([sys.executable, str(syscfg / "monday_init.py"), "--dry-run"],
                               cwd=str(ws), capture_output=True, encoding="utf-8", env=env)
        check("dry-run exits 0", proc.returncode == 0, proc.returncode)
        check("dry-run does not create the note", not note.is_file())
        check("dry-run mentions Would create", "Would create:" in proc.stdout, proc.stdout)

        # Real run: creates note + raw folder + Master Note row.
        proc = subprocess.run([sys.executable, str(syscfg / "monday_init.py")],
                               cwd=str(ws), capture_output=True, encoding="utf-8", env=env)
        check("real run exits 0", proc.returncode == 0, proc.stderr)
        check("note created", note.is_file())
        if note.is_file():
            text = note.read_text(encoding="utf-8")
            check("template placeholders substituted", "{{" not in text, text)
        check("raw folder created", (ws / "brain" / "raw" / f"{year}").is_dir())
        master_text = master.read_text(encoding="utf-8")
        check("Master Note row added", f"[[{year}-W{week:02d}]]" in master_text, master_text)

        # Idempotent re-run: no duplicate row, note body untouched.
        note_text_before = note.read_text(encoding="utf-8")
        proc = subprocess.run([sys.executable, str(syscfg / "monday_init.py")],
                               cwd=str(ws), capture_output=True, encoding="utf-8", env=env)
        check("idempotent re-run exits 0", proc.returncode == 0, proc.stderr)
        check("note body unchanged on re-run", note.read_text(encoding="utf-8") == note_text_before)
        master_text2 = master.read_text(encoding="utf-8")
        check("no duplicate Master Note row", master_text2.count(f"[[{year}-W{week:02d}]]") == 1, master_text2)

        # Vacation Recovery: seed a stale note 3 weeks back, drop the
        # current week's artifacts, confirm exactly one catch-up row lands.
        stale_monday, stale_year, stale_week, _ = config.week_info(date.today() - timedelta(weeks=3))
        stale_dir = ws / "brain" / "weekly_logs" / stale_year
        stale_dir.mkdir(parents=True, exist_ok=True)
        (stale_dir / f"{stale_year}-W{stale_week}.md").write_text("# stale\n", encoding="utf-8")
        note.unlink()
        master.write_text(f"# {year} Master Note\n\n| Week | Sprint | Q | Label | Summary |\n"
                           f"{SENTINEL}\n", encoding="utf-8")
        proc = subprocess.run([sys.executable, str(syscfg / "monday_init.py")],
                               cwd=str(ws), capture_output=True, encoding="utf-8", env=env)
        check("vacation-recovery run exits 0", proc.returncode == 0, proc.stderr)
        gap_text = master.read_text(encoding="utf-8")
        check("catch-up row inserted", "[[gap]]" in gap_text, gap_text)
        check("only one catch-up row", gap_text.count("[[gap]]") == 1, gap_text)

        # Missing template: FATAL, no note written.
        (ws / "brain" / "weekly_logs" / "Weekly_Note_Template.md").unlink()
        note.unlink()
        proc = subprocess.run([sys.executable, str(syscfg / "monday_init.py")],
                               cwd=str(ws), capture_output=True, encoding="utf-8", env=env)
        check("missing template exits 1", proc.returncode == 1, proc.returncode)
        check("missing template writes no note", not note.is_file())
    finally:
        from test_support import rmtree_force
        try:
            rmtree_force(ws)
        except OSError:
            pass

    if failures:
        print("monday_init: self-test FAILED:", file=sys.stderr)
        for f in failures:
            print(f"  {f}", file=sys.stderr)
        return 1
    print("self-test OK")
    return 0


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("-h", "--help", action="store_true")
    args = parser.parse_args()

    if args.help:
        print(f"Usage: {Path(sys.argv[0]).name} [--dry-run]", file=sys.stderr)
        print(f"       {Path(sys.argv[0]).name} --self-test", file=sys.stderr)
        return 0

    if args.self_test:
        return self_test()

    dry_run = args.dry_run or os.environ.get("DRY_RUN", "0") == "1"
    return run(dry_run=dry_run)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
