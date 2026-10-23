#!/usr/bin/env python3
"""test_brain_lock_adoption.py — proves every brain/ writer takes the ONE shared lock
(System_Config/brain_lock.py) in the right mode, by running the REAL scripts against a
throwaway workspace copy (brain_lock.py derives its lock dir from its own location, so a
copy is fully isolated) while a live process holds that copy's brain lock.

    skip : daily_ingest                       (repeatable; a skipped run just retries next schedule)
    wait : monday_init, friday_process        (BRAIN_LOCK_WAIT, then local notice + exit 75 WITHOUT writing)
    short: context_weekly, context_weekly_curate, context_auto_summary, context_intake,
           context_mempalace, context_curate, context_collect.sh   (BRAIN_LOCK_SHORT_WAIT, exit 75)
    hook : log_session                        (BRAIN_LOCK_HOOK_WAIT, then SPOOL to logs/log_session.pending, exit 0)

    python3 System_Config/test_brain_lock_adoption.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

HERE = Path(os.path.abspath(__file__)).parent
sys.path.insert(0, str(HERE))
from test_support import rmtree_force  # noqa: E402

WRITERS = ("daily_ingest", "monday_init", "friday_process", "log_session", "context_weekly",
           "context_weekly_curate", "context_auto_summary", "context_intake", "context_mempalace",
           "context_curate")
LEGACY_LOCKS = ("daily_ingest.lock", "friday_process.lock", "monday_init.lock")
TEMPLATE = ("# W{{WEEK_NUM}} {{YEAR}} — {{WEEK_LABEL}}\n---\n\n## Agent Sessions\n> Auto-appended after each launcher-completed session.\n\n---\n")
SENTINEL_MASTER = None


class Workspace(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp(prefix="brainlock-adopt.")).resolve()
        self.addCleanup(rmtree_force, self.ws)
        self.sys = self.ws / "System_Config"
        self.sys.mkdir()
        (self.sys / "logs").mkdir()
        for path in HERE.glob("*.py"):
            if not path.name.startswith("test_"):
                shutil.copy(str(path), str(self.sys / path.name))
        shutil.copy(str(HERE / "context_collect.sh"), str(self.sys / "context_collect.sh"))
        self.brain = self.ws / "brain"
        (self.brain / "weekly_logs" / "2026").mkdir(parents=True)
        (self.brain / "weekly_logs" / "Weekly_Note_Template.md").write_text(TEMPLATE, encoding="utf-8")
        (self.brain / "raw").mkdir()
        self.lock = self.sys / "logs" / "brain.lock.d"
        self.holders = []
        self.addCleanup(self.stop_holders)
        self.env = {**os.environ, "PYTHONUTF8": "1", "BRAIN_LOCK_WAIT": "1", "BRAIN_LOCK_SHORT_WAIT": "1",
                    "BRAIN_LOCK_HOOK_WAIT": "1", "BRAIN_LOCK_NO_NOTIFY": "1"}
        for key in ("BRAIN_LOCK_OWNER_PID", "BRAIN_LOCK_TEST", "BRAIN_LOCK_DIR", "LOG_SESSION_NOTE",
                    "LOG_SESSION_RECORDS_DIR", "AGENT_TYPE"):
            self.env.pop(key, None)

    def stop_holders(self):
        for proc in self.holders:
            proc.kill()
            proc.wait()

    def hold(self):
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        self.holders.append(proc)
        self.lock.mkdir()
        (self.lock / "pid").write_text(str(proc.pid), encoding="utf-8")
        return proc

    def unhold(self):
        proc = self.holders.pop()
        proc.kill()
        proc.wait()
        shutil.rmtree(str(self.lock), ignore_errors=True)

    def run_py(self, script, *args):
        return subprocess.run([sys.executable, str(self.sys / script), *args], cwd=str(self.ws), env=self.env,
                              capture_output=True, encoding="utf-8", timeout=15)

    def tree(self):
        return sorted(str(p.relative_to(self.ws)) for p in self.brain.rglob("*") if p.is_file())

    def assert_notice(self):
        marks = list((self.sys / "logs").glob(".brain-lock-notified-*"))
        self.assertEqual(len(marks), 1, "a local timeout notice (deduped marker) must be raised")


class EveryWriterUsesTheSharedLock(unittest.TestCase):
    def test_each_writer_references_brain_lock_and_none_keeps_a_private_brain_lock(self):
        for name in WRITERS:
            text = (HERE / (name + ".py")).read_text(encoding="utf-8")
            self.assertIn("brain_lock", text, name + " does not import brain_lock")
            for legacy in LEGACY_LOCKS:
                self.assertNotIn(legacy, text, name + " still names its private lock " + legacy)
            self.assertNotIn("acquire_lock(", text, name + " still uses config.acquire_lock for brain writes")

    def test_context_collect_wraps_itself_in_the_run_wrapper(self):
        text = (HERE / "context_collect.sh").read_text(encoding="utf-8")
        self.assertIn("context_collect.py", text)

    def test_every_self_test_workspace_copy_list_includes_brain_lock(self):
        for name in ("daily_ingest", "monday_init", "friday_process", "log_session"):
            text = (HERE / (name + ".py")).read_text(encoding="utf-8")
            self.assertIn("brain_lock.py", text.split("def self_test")[1], name + " self-test fixture misses brain_lock.py")


class MondayInit(Workspace):
    def test_wait_timeout_exits_75_without_writing_and_raises_a_local_notice(self):
        self.hold()
        before = self.tree()
        out = self.run_py("monday_init.py")
        self.assertEqual(out.returncode, 75, out.stderr)
        self.assertEqual(self.tree(), before)
        self.assertFalse((self.brain / "raw" / str(date.today().isocalendar()[0])).exists())
        self.assert_notice()

    def test_free_lock_runs_and_releases(self):
        out = self.run_py("monday_init.py")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(list((self.brain / "weekly_logs").rglob("20*-W*.md")))
        self.assertFalse(self.lock.exists())


class FridayProcess(Workspace):
    def fixture(self):
        note = self.brain / "weekly_logs" / "2026" / "2026-W10.md"
        note.write_text("# W10 2026\n---\n\n## Agent Sessions\n> auto\n\n---\n", encoding="utf-8")
        return note

    def test_wait_timeout_exits_75_and_the_context_cadence_does_not_run_unlocked(self):
        note = self.fixture()
        self.hold()
        before = note.read_text(encoding="utf-8")
        out = self.run_py("friday_process.py", "2026-W10")
        self.assertEqual(out.returncode, 75, out.stderr)
        self.assertEqual(note.read_text(encoding="utf-8"), before)
        self.assertFalse((self.brain / "context").exists())
        self.assert_notice()

    def test_free_lock_stamps_once_and_is_idempotent(self):
        note = self.fixture()
        for _ in range(2):
            out = self.run_py("friday_process.py", "2026-W10")
            self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(note.read_text(encoding="utf-8").count("Friday close-out"), 1)
        self.assertFalse(self.lock.exists())

    def test_dry_run_takes_no_lock(self):
        self.fixture()
        self.hold()
        out = self.run_py("friday_process.py", "--dry-run", "2026-W10")
        self.assertEqual(out.returncode, 0, out.stderr)


class DailyIngest(Workspace):
    def test_skip_mode_with_a_live_holder_exits_0_and_writes_nothing(self):
        self.hold()
        before = self.tree()
        out = self.run_py("daily_ingest.py")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.tree(), before)
        self.assertFalse((self.brain / "raw" / str(date.today().isocalendar()[0])).exists(),
                         "the raw/ week folder is created UNDER the lock, not before it")
        self.assertIn("skipping", (self.sys / "logs" / "daily_ingest.log").read_text(encoding="utf-8"))
        self.assertEqual(list((self.sys / "logs").glob(".brain-lock-notified-*")), [], "skip is quiet")


class LogSession(Workspace):
    def note(self):
        path = self.brain / "weekly_logs" / "2026" / "2026-W10.md"
        path.write_text("# W10\n---\n\n## Agent Sessions\n> auto\n\n---\n", encoding="utf-8")
        return path

    def call(self, note, status="0", *extra):
        return self.run_py("log_session.py", "--provider", "claude", "--role", "coder", "--status", status,
                           "--reason", "exit", "--note", str(note), *extra)

    def default_call(self):
        # Keep the production wait long: the subprocess timeout catches any
        # accidental nested child writer without hanging the suite for 900s.
        return subprocess.run(
            [sys.executable, str(self.sys / "log_session.py"), "--provider", "claude",
             "--role", "coder", "--status", "0", "--reason", "exit"],
            cwd=str(self.ws), env={**self.env, "BRAIN_LOCK_WAIT": "900"},
            capture_output=True, encoding="utf-8", timeout=8)

    def current_note(self):
        year, week, _ = date.today().isocalendar()
        return self.brain / "weekly_logs" / str(year) / f"{year}-W{week:02d}.md"

    def test_missing_default_note_is_created_under_the_logger_lock(self):
        self.assertFalse(self.current_note().exists())
        out = self.default_call()
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout, "")
        self.assertIn("claude / coder — exit 0 (exit)", self.current_note().read_text(encoding="utf-8"))
        self.assertIn("[monday_init]", out.stderr)
        self.assertNotIn("failed; continuing", out.stderr)
        self.assertFalse(self.lock.exists())

    def test_missing_template_skips_default_note_without_failing_logger(self):
        (self.brain / "weekly_logs" / "Weekly_Note_Template.md").unlink()
        out = self.default_call()
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout, "")
        self.assertIn("monday_init.py exited non-zero", out.stderr)
        self.assertIn("weekly note still missing", out.stderr)
        self.assertFalse(self.current_note().exists())
        self.assertFalse(self.lock.exists())

    def test_dry_run_environment_keeps_default_note_missing(self):
        self.env["DRY_RUN"] = "1"
        out = self.default_call()
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout, "")
        self.assertIn("Would create:", out.stderr)
        self.assertFalse(self.current_note().exists())
        self.assertFalse(self.lock.exists())

    def test_explicit_missing_note_never_runs_monday(self):
        out = self.call(self.ws / "missing.md")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertNotIn("running monday_init.py", out.stderr)
        self.assertFalse(self.current_note().exists())
        self.assertFalse(self.lock.exists())

    def test_busy_lock_spools_outside_brain_exits_0_and_the_next_run_flushes_in_order(self):
        note = self.note()
        self.hold()
        first = self.call(note, "11")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertNotIn("exit 11", note.read_text(encoding="utf-8"))
        pending = self.sys / "logs" / "log_session.pending"
        entries = [json.loads(path.read_text(encoding="utf-8")) for path in pending.parent.glob(pending.name + ".entry.*")]
        self.assertEqual(len(entries), 1)
        self.unhold()
        second = self.call(note, "22")
        self.assertEqual(second.returncode, 0, second.stderr)
        text = note.read_text(encoding="utf-8")
        self.assertIn("exit 11", text)
        self.assertIn("exit 22", text)
        self.assertLess(text.index("exit 11"), text.index("exit 22"), "spooled entry keeps its place")
        self.assertFalse(list(pending.parent.glob(pending.name + ".entry.*")))
        self.assertFalse(self.lock.exists())

    def test_busy_lock_spools_the_session_record_too(self):
        note = self.note()
        log = self.ws / "pipeline" / "logs" / "run.log"
        log.parent.mkdir(parents=True)
        log.write_text("log\n", encoding="utf-8")
        meta = ("--task", "t", "--target-repo", "/tmp/r", "--run-id", "run-1", "--branch", "b", "--log", str(log))
        self.hold()
        out = self.call(note, "0", *meta)
        self.assertEqual(out.returncode, 0, out.stderr)
        record = self.brain / "records" / "sessions" / "session-run-1.md"
        self.assertFalse(record.exists())
        self.unhold()
        out = self.call(note, "0", "--task", "t2", "--target-repo", "/tmp/r", "--run-id", "run-2",
                        "--branch", "b", "--log", str(log))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(record.is_file(), "spooled record written on the next locked run")
        self.assertIn("session-run-1", note.read_text(encoding="utf-8"))

    def test_free_lock_writes_immediately_and_releases(self):
        note = self.note()
        out = self.call(note, "5")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("exit 5", note.read_text(encoding="utf-8"))
        self.assertFalse(self.lock.exists())
        self.assertFalse((self.sys / "logs" / "log_session.pending").exists())

    def test_a_child_of_a_holder_spools_instead_of_bypassing(self):
        note = self.note()
        code = ("import subprocess, sys\n"
                "import brain_lock\n"
                "assert brain_lock.acquire('skip', 0) == 0\n"
                "r = subprocess.run([sys.executable, %r, '--provider', 'claude', '--role', 'coder', '--status', '9',"
                " '--reason', 'exit', '--note', %r])\n"
                "sys.exit(r.returncode)\n" % (str(self.sys / "log_session.py"), str(note)))
        out = subprocess.run([sys.executable, "-c", code], cwd=str(self.sys), env={**self.env, "PYTHONPATH": str(self.sys)},
                             capture_output=True, encoding="utf-8")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertNotIn("exit 9", note.read_text(encoding="utf-8"))
        self.assertTrue(list((self.sys / "logs").glob("log_session.pending.entry.*")))


class InProcessCadence(Workspace):
    def test_cadence_composes_nested_writers_under_one_owner(self):
        raw = self.ws / "source.jsonl"
        raw.write_text("fixture", encoding="utf-8")
        (self.sys / "context-sources.local.json").write_text(json.dumps({"sources": [
            {"provider": "codex", "root": str(raw), "suffix": ".jsonl", "age": "current",
             "classification": "work", "status": "captured"}]}), encoding="utf-8")
        note = self.brain / "weekly_logs/2026/2026-W10.md"
        note.write_text("# week\n## Agent Sessions\n", encoding="utf-8")
        code = ("import brain_lock, context_cadence, config\n"
                "from pathlib import Path\n"
                "with brain_lock.guard('outer', 'wait', 1) as held:\n"
                " assert held\n"
                " context_cadence.friday('2026-03-06','2026-W10', Path(%r), print)\n"
                " assert brain_lock.owned()\n" % str(note))
        out = subprocess.run([sys.executable, "-c", code], cwd=str(self.sys),
                             env={**self.env, "PYTHONPATH": str(self.sys)}, capture_output=True,
                             encoding="utf-8", timeout=8)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertNotIn("failed; continuing", out.stdout)
        self.assertTrue((self.brain / "context/weekly-sources/2026-W10.md").is_file())
        self.assertIn("weekly-sources", note.read_text(encoding="utf-8"))
        self.assertFalse(self.lock.exists())

    def test_composed_failures_keep_the_old_continue_contract(self):
        import context_cadence
        messages = []
        def nonzero():
            raise SystemExit(7)
        def exception():
            raise ValueError("fixture")
        self.assertFalse(context_cadence._composed(nonzero, messages.append, "fixture"))
        self.assertFalse(context_cadence._composed(exception, messages.append, "fixture"))
        self.assertEqual(len(messages), 2)


class SpoolFlush(Workspace):
    """A session line spooled while a long job held the lock must not wait for the next manual
    pipeline run: the scheduled writers flush it as soon as they hold the lock."""

    def spool(self, note):
        entry = {"provider": "claude", "role": "coder", "status": "7", "reason": "exit", "note": str(note),
                 "metadata": [], "ts": "2026-03-05 10:00:00"}
        (self.sys / "logs" / "log_session.pending").write_text(json.dumps(entry) + "\n", encoding="utf-8")

    def test_friday_process_flushes_spooled_entries_under_its_lock(self):
        note = self.brain / "weekly_logs" / "2026" / "2026-W10.md"
        note.write_text("# W10 2026\n---\n\n## Agent Sessions\n> auto\n\n---\n", encoding="utf-8")
        self.spool(note)
        out = self.run_py("friday_process.py", "2026-W10")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("2026-03-05 10:00:00: claude / coder — exit 7 (exit)", note.read_text(encoding="utf-8"))
        self.assertTrue((self.sys / "logs" / "log_session.pending.cursor").is_file())

    def test_daily_ingest_flushes_spooled_entries_even_with_nothing_to_ingest(self):
        note = self.brain / "weekly_logs" / "2026" / "2026-W10.md"
        note.write_text("# W10 2026\n---\n\n## Agent Sessions\n> auto\n\n---\n", encoding="utf-8")
        self.spool(note)
        out = self.run_py("daily_ingest.py")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("exit 7 (exit)", note.read_text(encoding="utf-8"))

    def test_a_busy_lock_leaves_the_spool_alone(self):
        note = self.brain / "weekly_logs" / "2026" / "2026-W10.md"
        note.write_text("# W10 2026\n---\n\n## Agent Sessions\n> auto\n\n---\n", encoding="utf-8")
        self.spool(note)
        self.hold()
        self.run_py("daily_ingest.py")
        self.assertTrue((self.sys / "logs" / "log_session.pending").is_file())
        self.assertNotIn("exit 7", note.read_text(encoding="utf-8"))


class ContextCli(Workspace):
    CASES = (
        ("context_weekly.py", ("--vault", "{brain}", "--week", "2026-W10")),
        ("context_weekly_curate.py", ("--vault", "{brain}", "--week", "2026-W10", "--summary", "{ws}/s.md")),
        ("context_auto_summary.py", ("--vault", "{brain}", "--week", "2026-W10")),
        ("context_intake.py", ("--vault", "{brain}", "--manifest", "{ws}/m.json", "--date", "2026-03-06")),
        ("context_mempalace.py", ("--vault", "{brain}", "--manifest", "{ws}/m.json")),
        ("context_curate.py", ("{brain}/records/x.md", "--root", "{ws}", "--apply")),
    )

    def test_each_context_writer_waits_briefly_then_exits_75_without_writing(self):
        self.hold()
        before = self.tree()
        for script, template in self.CASES:
            args = [a.format(brain=self.brain, ws=self.ws) for a in template]
            out = self.run_py(script, *args)
            self.assertEqual(out.returncode, 75, "%s: %s" % (script, out.stderr))
        self.assertEqual(self.tree(), before)

    def test_context_collect_wrapper_waits_then_exits_75(self):
        (self.sys / "context-sources.local.json").write_text("{}", encoding="utf-8")
        self.hold()
        out = subprocess.run(["bash", str(self.sys / "context_collect.sh"), "2026-03-06"], cwd=str(self.ws),
                             env=self.env, capture_output=True, encoding="utf-8")
        self.assertEqual(out.returncode, 75, out.stderr)

    def test_a_cli_under_a_holding_parent_is_refused(self):
        code = ("import subprocess, sys\n"
                "import brain_lock\n"
                "assert brain_lock.acquire('skip', 0) == 0\n"
                "r = subprocess.run([sys.executable, %r, '--vault', %r, '--week', '2026-W10'], capture_output=True, encoding='utf-8')\n"
                "print(r.returncode)\n" % (str(self.sys / "context_auto_summary.py"), str(self.brain)))
        out = subprocess.run([sys.executable, "-c", code], cwd=str(self.sys), env={**self.env, "PYTHONPATH": str(self.sys)},
                             capture_output=True, encoding="utf-8")
        self.assertEqual(out.stdout.strip(), "75", "a child must not inherit acquisition authority")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    unittest.main(verbosity=1)
