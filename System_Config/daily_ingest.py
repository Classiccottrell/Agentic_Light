#!/usr/bin/env python3
"""daily_ingest.py — brain/ raw-clip ingestion. Python port of
daily_ingest.sh.

Scans brain/raw/YYYY/Wnn label/*.md (two directory levels deep under
raw/: YYYY/, then "Wnn label"/) for new .md clips and runs the agent CLI
headlessly to wikify them (create/update brain/wiki/ pages, update
wiki/index.md, log to the current weekly note). Processes ONE clip per
agent call so a partial failure only retries that clip. Manual-trigger
only.

Usage: python3 System_Config/daily_ingest.py
       python3 System_Config/daily_ingest.py --dry-run   (or DRY_RUN=1)
"""
import argparse
import hashlib
import os
import stat
import subprocess
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

import config

# daily_ingest's OWN defaults (180s / $1.00) differ from run_agent.py's
# (300s / $2.00) — run_agent captures MAX_SECONDS/MAX_BUDGET from
# os.environ at IMPORT TIME (module-level, once per process), so these
# must be set before `import run_agent` or every clip would silently get
# run_agent's own watchdog/budget instead of daily_ingest's.
os.environ.setdefault("MAX_SECONDS", "180")
os.environ.setdefault("MAX_BUDGET", "1.00")

import run_agent as ra  # noqa: E402

MAX_CLIPS_PER_RUN = int(os.environ.get("MAX_CLIPS_PER_RUN", "10"))


def _ts():
    return time.strftime("%Y-%m-%d %H:%M:%S")


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


def find_candidate_clips(raw_dir):
    """raw/YYYY/Wnn label/*.md — exactly depth 3 under raw/ (mindepth 3
    maxdepth 3 in the original find). Sorted for determinism — bash's
    plain `find` had arbitrary filesystem order; dedup/quarantine logic
    below doesn't depend on order, so this is a harmless, testable
    improvement, not a parity break."""
    if not raw_dir.is_dir():
        return []
    return sorted(
        (p for p in raw_dir.rglob("*.md") if p.is_file() and len(p.relative_to(raw_dir).parts) == 3),
        key=str,
    )


def count_deep_files(raw_dir):
    """.md files nested deeper than raw/YYYY/Wnn label/ (depth 4+)."""
    if not raw_dir.is_dir():
        return 0
    return sum(1 for p in raw_dir.rglob("*.md") if p.is_file() and len(p.relative_to(raw_dir).parts) >= 4)


def manifest_name_seen(manifest_path, rel):
    if not manifest_path.is_file():
        return False
    for line in manifest_path.read_text(encoding="utf-8", errors="replace").splitlines():
        fields = line.split("\t")
        if fields and fields[-1] == rel:
            return True
    return False


def manifest_hash_seen(manifest_path, h):
    if not manifest_path.is_file():
        return False
    for line in manifest_path.read_text(encoding="utf-8", errors="replace").splitlines():
        fields = line.split("\t")
        if len(fields) >= 2 and fields[0] == h:
            return True
    return False


def manifest_append(manifest_path, h, rel):
    with open(manifest_path, "a", encoding="utf-8", newline="\n") as f:
        f.write(f"{h}\t{rel}\n")


def fail_attempts_of(fail_path, rel):
    if not fail_path.is_file():
        return 0
    for line in fail_path.read_text(encoding="utf-8", errors="replace").splitlines():
        fields = line.split("\t")
        if len(fields) >= 2 and fields[1] == rel:
            try:
                return int(fields[0])
            except ValueError:
                return 0
    return 0


def _fail_rewrite(fail_path, rel, new_line):
    lines = []
    if fail_path.is_file():
        for line in fail_path.read_text(encoding="utf-8", errors="replace").splitlines():
            fields = line.split("\t")
            if len(fields) >= 2 and fields[1] == rel:
                continue
            lines.append(line)
    if new_line is not None:
        lines.append(new_line)
    _atomic_write(fail_path, ("\n".join(lines) + "\n") if lines else "")


def fail_bump(fail_path, rel):
    count = fail_attempts_of(fail_path, rel) + 1
    _fail_rewrite(fail_path, rel, f"{count}\t{rel}")


def fail_clear(fail_path, rel):
    if fail_path.is_file():
        _fail_rewrite(fail_path, rel, None)


def wiki_has_link(wiki_dir, needle):
    if not wiki_dir.is_dir():
        return False
    for p in sorted(wiki_dir.rglob("*.md"), key=str):
        try:
            if needle in p.read_text(encoding="utf-8", errors="replace"):
                return True
        except OSError:
            continue
    return False


def curate_new_wiki_pages(root, src_link, log_path):
    """After a successful ingest adds [[src_link]] to one or more wiki
    pages, run context.py's `curate --apply` on each so cross-links get
    suggested/applied. Subprocess, not import — context.py's own contract
    is "log the output, a failed page never stops the ingest loop", the
    opposite of route_skill/context_packet's clean importable functions.

    daily_ingest.sh referenced "$ROOT" here with no matching definition
    anywhere it sourced (config.sh only ever defined WORKSPACE) — under
    bash's `set -u` this would abort the instant a real ingest ever
    matched a wikilink, so curation was, in practice, dead code in
    daily_ingest.sh. This port uses config.WORKSPACE (clearly the intended
    value) and is the first version where curation actually runs; expect
    it to be the first to write '## Related Context' sections and
    brain/records/sessions/curation-*.md."""
    wiki_dir = root / "brain" / "wiki"
    needle = f"[[{src_link}]]"
    pages = []
    if wiki_dir.is_dir():
        for p in sorted(wiki_dir.rglob("*.md"), key=str):
            try:
                if needle in p.read_text(encoding="utf-8", errors="replace"):
                    pages.append(p)
            except OSError:
                continue
    context_py = root / "System_Config" / "context.py"
    for page in pages:
        proc = subprocess.run(
            [sys.executable, str(context_py), "--root", str(root), "curate", str(page), "--apply"],
            capture_output=True, encoding="utf-8", env={**os.environ, "PYTHONUTF8": "1"},
        )
        with open(log_path, "a", encoding="utf-8", newline="\n") as f:
            if proc.stdout:
                f.write(proc.stdout)
            if proc.stderr:
                f.write(proc.stderr)
        if proc.returncode != 0:
            with open(log_path, "a", encoding="utf-8", newline="\n") as f:
                f.write(f"[{_ts()}] WARN: curation failed for {page} — ingest remains recorded\n")


def build_prompt(rel, src_link, weekly_note, year, week, today):
    return (
        "You are running headlessly to ingest ONE clip into the brain/ knowledge wiki.\n"
        "First read CLAUDE.md for the wiki schema and conventions.\n\n"
        f"Clip to process: raw/{rel}\n\n"
        "Steps:\n"
        f"1. Read raw/{rel}. Do NOT edit it — files in raw/ are immutable.\n"
        "2. Identify the primary entity (project, person, technology, org, or concept) and create or update its page in wiki/ using the page format in CLAUDE.md.\n"
        f"   - IDEMPOTENCY: first check whether the target wiki page already contains a link to [[{src_link}]]. If it does, this clip was already ingested — make NO changes and stop.\n"
        f"   - If the page exists: APPEND new facts and add '- [[{src_link}]]' under its Sources section. Never rewrite or delete existing content.\n"
        f"   - If new: create it with the exact frontmatter + sections, including the [[{src_link}]] link.\n"
        "   - Cross-link aggressively to existing wiki pages with [[wikilinks]].\n"
        "3. Update wiki/index.md to list any new wiki page and the new source (skip if already listed).\n"
        f"4. Ensure {weekly_note} exists. If not, create it from weekly_logs/Weekly_Note_Template.md (WEEK_NUM={week}, YEAR={year}).\n"
        f"5. Append exactly one line to its '## Agent Sessions' section (use '## Claude Sessions' instead if that's the heading already present in this note): '- {today}: ingested {rel} -> [[wiki/<page-slug>]]'.\n\n"
        "Constraints: create-or-append only; never overwrite a page wholesale; never delete anything; stay within brain/."
    )


def run(dry_run=False, run_agent_fn=None):
    """Core routine. `run_agent_fn` is injectable (default ra.run_agent) so
    --self-test can simulate agent outcomes without a real provider call or
    spending any budget."""
    run_agent_fn = run_agent_fn or ra.run_agent
    log_dir = config.LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "daily_ingest.log"

    def log(msg):
        with open(log_path, "a", encoding="utf-8", newline="\n") as f:
            f.write(f"[{_ts()}] {msg}\n")

    # Mirrors config.sh's automatic `source`-time side effects (resolve then
    # warn-only validate), which ran unconditionally for every script that
    # sourced config.sh — daily_ingest genuinely does need a provider
    # (run_agent_fn below), so this also gives an early, explicit signal if
    # none is configured, rather than discovering it mid-loop on the first clip.
    config.resolve_agent_provider()
    if not config.validate_config():
        print("config.py: configuration warnings above — some scripts may misbehave", file=sys.stderr)

    log(f"daily_ingest start (scanning: {config.RAW})")

    iso_year, iso_week, _unused = date.today().isocalendar()
    year, week = f"{iso_year:04d}", f"{iso_week:02d}"
    today = date.today().isoformat()
    weekly_note = f"weekly_logs/{year}/{year}-W{week}.md"

    config.ensure_current_week_raw_folder()

    lock_dir = log_dir / "daily_ingest.lock"
    lock_max_age = (int(os.environ.get("MAX_SECONDS", ra.MAX_SECONDS)) + 30) * MAX_CLIPS_PER_RUN + 300
    with config.acquire_lock(lock_dir, max_age=lock_max_age) as held:
        if not held:
            log(f"another daily_ingest holds {lock_dir} — skipping")
            return 0

        if not config.RAW.is_dir():
            log(f"no raw dir at {config.RAW} — nothing to ingest; exiting")
            return 0

        deep_count = count_deep_files(config.RAW)
        if deep_count > 0:
            log(f"WARN: {deep_count} .md file(s) nested deeper than raw/YYYY/Wnn label/ — skipped (flatten to two levels to ingest)")

        manifest = config.RAW / ".ingested.log"
        failmf = config.RAW / ".failed.log"
        manifest.touch(exist_ok=True)

        new_list = []
        for f in find_candidate_clips(config.RAW):
            rel = f.relative_to(config.RAW).as_posix()
            base = f.name
            if base.startswith("_") or base.startswith("."):
                continue
            if manifest_name_seen(manifest, rel):
                continue
            h = hashlib.sha256(f.read_bytes()).hexdigest()
            if manifest_hash_seen(manifest, h):
                log(f"skip (duplicate content of an already-ingested clip): {rel} [{h[:12]}]")
                manifest_append(manifest, h, rel)
                continue
            new_list.append(rel)

        total_new = len(new_list)
        if total_new == 0:
            log(f"no new clips in {config.RAW}")
            return 0
        log(f"new clips ({total_new}): {' '.join(new_list)}")

        if dry_run:
            print(f"── DRY RUN — would ingest {total_new} clip(s) from {config.RAW}, one agent call each ──")
            for rel in new_list:
                print(rel)
            print(f"── weekly note: {weekly_note} ──")
            print(f"── per-clip flags: --allowedTools Read,Write,Edit,Glob,Grep --disallowedTools Bash,... "
                  f"--permission-mode acceptEdits --max-budget-usd {ra.MAX_BUDGET} (watchdog {ra.MAX_SECONDS}s) ──")
            log("dry run — no agent call")
            return 0

        # Lock raw/ notes read-only while agent calls run (restored below,
        # always, even on an exception mid-loop).
        candidates = find_candidate_clips(config.RAW)
        for p in candidates:
            try:
                p.chmod(p.stat().st_mode & ~stat.S_IWUSR & ~stat.S_IWGRP & ~stat.S_IWOTH)
            except OSError:
                pass

        try:
            total_ingested = 0
            consecutive_bad = 0
            attempted = 0
            wall_hit = False

            for rel in new_list:
                if wall_hit:
                    break
                if attempted >= MAX_CLIPS_PER_RUN:
                    log(f"PER-RUN CLIP CAP reached (MAX_CLIPS_PER_RUN={MAX_CLIPS_PER_RUN}) — stopping; remaining clips retry next run")
                    break
                fc = fail_attempts_of(failmf, rel)
                if fc >= 3:
                    log(f"QUARANTINED ({fc} failed attempts): {rel} — fix or remove the clip, then delete its line from raw/.failed.log")
                    continue
                attempted += 1
                src_link = f"raw/{rel.removesuffix('.md')}"
                prompt = build_prompt(rel, src_link, weekly_note, year, week, today)

                log(f"ingesting: {rel}")
                rc = run_agent_fn(prompt, log=str(log_path), brain=str(config.BRAIN))
                if rc == 0:
                    if wiki_has_link(config.BRAIN / "wiki", f"[[{src_link}]]"):
                        curate_new_wiki_pages(config.WORKSPACE, src_link, log_path)
                        h = hashlib.sha256((config.RAW / rel).read_bytes()).hexdigest()
                        manifest_append(manifest, h, rel)
                        total_ingested += 1
                        log(f"OK: {rel}")
                        consecutive_bad = 0
                        fail_clear(failmf, rel)
                    else:
                        log(f"NO-OP (exit 0 but no wiki link to {src_link}): {rel} — NOT recorded, will retry next run")
                        consecutive_bad += 1
                        fail_bump(failmf, rel)
                else:
                    log(f"FAILED (rc={rc}; may have timed out after {ra.MAX_SECONDS}s): {rel} — NOT recorded, will retry next run")
                    consecutive_bad += 1
                    fail_bump(failmf, rel)

                if consecutive_bad >= 2:
                    log(f"QUOTA/BUDGET WALL suspected after {attempted} clips — stopping this run; remaining clips retry next run")
                    wall_hit = True
                    break

            pending = total_new - total_ingested
            log(f"daily_ingest done — ingested {total_ingested}/{total_new} clip(s); {pending} still pending")
            return 0
        finally:
            for p in candidates:
                try:
                    p.chmod(p.stat().st_mode | stat.S_IWUSR)
                except OSError:
                    pass


def self_test():
    import shutil

    failures = []

    def check(label, cond, detail=""):
        if not cond:
            failures.append(f"{label}: {detail}")
            print(f"FAIL: {label}: {detail}", file=sys.stderr)

    ws = Path(tempfile.mkdtemp(prefix="agentic-light-daily-ingest-test."))
    try:
        (ws / "brain" / "wiki").mkdir(parents=True)
        (ws / "brain" / "weekly_logs").mkdir(parents=True)
        raw_week = ws / "brain" / "raw" / "2026" / "W01 Jan 5-9"
        raw_week.mkdir(parents=True)

        # Real context.py + its dependencies, so the curate --apply
        # subprocess this test's fake_agent_ok path triggers genuinely runs
        # (not just "didn't crash the harness" — a real WARN-and-continue
        # failure here would otherwise be invisible; see the checks below).
        syscfg = ws / "System_Config"
        syscfg.mkdir(exist_ok=True)
        for name in ("context.py", "context_curate.py", "context_catalog.py", "context_validate.py"):
            shutil.copy(Path(__file__).parent / name, syscfg / name)

        import config as _cfg  # same cached module object as the top-level import
        orig = (_cfg.WORKSPACE, _cfg.BRAIN, _cfg.RAW, _cfg.LOG_DIR)
        _cfg.WORKSPACE = ws
        _cfg.BRAIN = ws / "brain"
        _cfg.RAW = raw_week.parent.parent
        _cfg.LOG_DIR = ws / "System_Config" / "logs"

        clip_a = raw_week / "clip-a.md"
        clip_a.write_text("Clip A content.", encoding="utf-8")
        clip_b = raw_week / "clip-b.md"
        clip_b.write_text("Clip B content.", encoding="utf-8")
        deep_dir = raw_week / "nested"
        deep_dir.mkdir()
        (deep_dir / "too-deep.md").write_text("x", encoding="utf-8")

        calls = []

        def fake_agent_ok(prompt, log=None, brain=None):
            calls.append(prompt)
            # Simulate the coder having written a wiki page linking the clip.
            src_line = [l for l in prompt.splitlines() if l.startswith("Clip to process:")][0]
            rel = src_line.split("raw/", 1)[1]
            link = f"raw/{rel.removesuffix('.md')}"
            (_cfg.BRAIN / "wiki" / f"{Path(rel).stem}.md").write_text(f"# Page\n- [[{link}]]\n", encoding="utf-8")
            return 0

        def fake_agent_noop(prompt, log=None, brain=None):
            calls.append(prompt)
            return 0  # exit 0 but never wrote a wiki link

        def fake_agent_fail(prompt, log=None, brain=None):
            calls.append(prompt)
            return 1

        # Dry run: lists both candidates, no agent calls, no writes.
        rc = run(dry_run=True, run_agent_fn=fake_agent_ok)
        check("dry-run returns 0", rc == 0, rc)
        check("dry-run makes no agent calls", len(calls) == 0, len(calls))

        # Real run with a successful agent: both clips ingested, curated.
        rc = run(dry_run=False, run_agent_fn=fake_agent_ok)
        check("real run returns 0", rc == 0, rc)
        check("both clips triggered an agent call", len(calls) == 2, len(calls))
        manifest = _cfg.RAW / ".ingested.log"
        check("manifest has 2 entries", len(manifest.read_text(encoding="utf-8").splitlines()) == 2)

        # Curation actually ran (the $ROOT-bug fix, see build_prompt/
        # curate_new_wiki_pages docstring) — a WARN-and-continue subprocess
        # failure would otherwise be invisible; assert its real effect.
        ingest_log = (_cfg.LOG_DIR / "daily_ingest.log").read_text(encoding="utf-8")
        check("no curation failure logged", "curation failed" not in ingest_log, ingest_log)
        curation_records = list((ws / "brain" / "records" / "sessions").glob("curation-*.md"))
        check("curation wrote at least one session record", len(curation_records) >= 1, curation_records)

        # Re-run: nothing new (name-seen dedup), no additional agent calls.
        calls.clear()
        rc = run(dry_run=False, run_agent_fn=fake_agent_ok)
        check("idempotent re-run returns 0", rc == 0, rc)
        check("idempotent re-run makes no agent calls", len(calls) == 0, len(calls))

        # Duplicate-content clip: same bytes as clip_a under a new name -> hash-dedup skip.
        clip_c = raw_week / "clip-c.md"
        clip_c.write_text("Clip A content.", encoding="utf-8")
        calls.clear()
        rc = run(dry_run=False, run_agent_fn=fake_agent_ok)
        check("duplicate-content clip triggers no agent call", len(calls) == 0, len(calls))
        check("duplicate-content clip recorded in manifest", manifest_name_seen(manifest, "2026/W01 Jan 5-9/clip-c.md"))

        # Failure path: quarantine after 3 attempts, wall after 2 consecutive.
        raw_week2 = _cfg.RAW / "2026" / "W02 Jan 12-16"
        raw_week2.mkdir(parents=True)
        bad1 = raw_week2 / "bad1.md"
        bad1.write_text("bad1", encoding="utf-8")
        bad2 = raw_week2 / "bad2.md"
        bad2.write_text("bad2", encoding="utf-8")
        calls.clear()
        rc = run(dry_run=False, run_agent_fn=fake_agent_fail)
        check("failure run returns 0 (never raises)", rc == 0, rc)
        check("wall stops after 2 consecutive failures", len(calls) == 2, len(calls))
        check("bad1 recorded one failed attempt", fail_attempts_of(_cfg.RAW / ".failed.log", "2026/W02 Jan 12-16/bad1.md") == 1)

        calls.clear()
        rc = run(dry_run=False, run_agent_fn=fake_agent_fail)
        rc = run(dry_run=False, run_agent_fn=fake_agent_fail)
        fc = fail_attempts_of(_cfg.RAW / ".failed.log", "2026/W02 Jan 12-16/bad1.md")
        check("bad1 attempts accumulate across runs", fc >= 3, fc)

        # NO-OP path: exit 0 but no wikilink written -> counted as a failure, not ingested.
        raw_week3 = _cfg.RAW / "2026" / "W03 Jan 19-23"
        raw_week3.mkdir(parents=True)
        noop_clip = raw_week3 / "noop.md"
        noop_clip.write_text("noop", encoding="utf-8")
        calls.clear()
        rc = run(dry_run=False, run_agent_fn=fake_agent_noop)
        check("no-op clip not recorded as ingested",
              not manifest_name_seen(manifest, "2026/W03 Jan 19-23/noop.md"))

        # Deep-nesting warning: too-deep.md never gets scanned as a candidate.
        check("nested-too-deep file excluded from candidates",
              all("too-deep" not in c.name for c in find_candidate_clips(_cfg.RAW)))
    finally:
        _cfg.WORKSPACE, _cfg.BRAIN, _cfg.RAW, _cfg.LOG_DIR = orig
        from test_support import rmtree_force
        try:
            rmtree_force(ws)
        except OSError:
            pass

    if failures:
        print("daily_ingest: self-test FAILED:", file=sys.stderr)
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
