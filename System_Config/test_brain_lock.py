#!/usr/bin/env python3
"""test_brain_lock.py — fixtures for System_Config/brain_lock.py, the ONE shared
brain/ write lock. Standalone unittest file (run directly, no pytest needed):

    python3 System_Config/test_brain_lock.py

Covers acquire/release, skip/wait, timeout, live-holder-not-reclaimed,
fail-closed stale/missing/special PID entries, process/thread ownership, release-only-if-ours,
the test-only override gate, the `run` CLI wrapper, the local-only timeout
notice, and a multi-process reclaim race (many iterations).
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(os.path.abspath(__file__)).parent
sys.path.insert(0, str(HERE))
import brain_lock  # noqa: E402

TMPR = Path(os.path.realpath(tempfile.gettempdir()))
CHILD_ENV_KEYS = ("BRAIN_LOCK_NOTIFY_DIR", "BRAIN_LOCK_TEST", "BRAIN_LOCK_DIR", "BRAIN_LOCK_TEST_POLL", "BRAIN_LOCK_TEST_JITTER",
                  "BRAIN_LOCK_OWNER_PID")


def dead_pid():
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


class LiveHolder:
    """A real, live, unrelated process whose pid we can put in a lock file."""
    def __enter__(self):
        self.proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        return self.proc.pid

    def __exit__(self, *exc):
        self.proc.kill()
        self.proc.wait()


def child_env(extra=None):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(HERE)
    env["PYTHONUTF8"] = "1"
    if extra:
        env.update(extra)
    return env


class LockCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="brainlock.", dir=str(TMPR)))
        self.addCleanup(shutil.rmtree, str(self.tmp), True)
        self.lock = self.tmp / "brain.lock.d"
        self.saved = {k: os.environ.get(k) for k in CHILD_ENV_KEYS + ("BRAIN_LOCK_NO_NOTIFY",)}
        os.environ["BRAIN_LOCK_TEST"] = "1"
        os.environ["BRAIN_LOCK_DIR"] = str(self.lock)
        os.environ["BRAIN_LOCK_TEST_POLL"] = "0.05"
        os.environ["BRAIN_LOCK_NOTIFY_DIR"] = str(self.tmp / "notice")   # never write notice markers into the real logs/
        os.environ.pop("BRAIN_LOCK_OWNER_PID", None)
        os.environ.pop("BRAIN_LOCK_TEST_JITTER", None)
        brain_lock._reset()
        self.addCleanup(self.restore)

    def restore(self):
        brain_lock.release()
        brain_lock._reset()
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def plant(self, pid):
        self.lock.mkdir()
        if pid is not None:
            (self.lock / "pid").write_text(str(pid), encoding="utf-8")

    def pid_file(self):
        try:
            return (self.lock / "pid").read_text(encoding="utf-8").strip()
        except OSError:
            return None


class AcquireRelease(LockCase):
    def test_acquire_writes_our_pid_and_release_removes_the_dir(self):
        self.assertEqual(brain_lock.acquire("skip", 0), 0)
        self.assertEqual(self.pid_file(), str(os.getpid()))
        brain_lock.release()
        self.assertFalse(self.lock.exists())

    def test_release_without_acquire_is_a_noop(self):
        with LiveHolder() as pid:
            self.plant(pid)
            brain_lock.release()
            self.assertEqual(self.pid_file(), str(pid))

    def test_double_release_is_safe(self):
        self.assertEqual(brain_lock.acquire("skip", 0), 0)
        brain_lock.release()
        brain_lock.release()
        self.assertFalse(self.lock.exists())

    def test_acquire_twice_in_one_process_is_already_ours(self):
        self.assertEqual(brain_lock.acquire("skip", 0), 0)
        self.assertEqual(brain_lock.acquire("skip", 0), 0)
        self.assertEqual(self.pid_file(), str(os.getpid()))

    def test_in_process_nesting_only_drops_the_lock_at_the_outermost_release(self):
        self.assertEqual(brain_lock.acquire("skip", 0), 0)
        self.assertEqual(brain_lock.acquire("wait", 1), 0)   # e.g. daily_ingest -> monday_init.run()
        brain_lock.release()
        self.assertEqual(self.pid_file(), str(os.getpid()), "inner release must not drop the outer lock")
        brain_lock.release()
        self.assertFalse(self.lock.exists())

    def test_hold_context_manager_releases(self):
        with brain_lock.hold("skip", 0) as rc:
            self.assertEqual(rc, 0)
            self.assertTrue(self.lock.is_dir())
        self.assertFalse(self.lock.exists())

    def test_bad_mode_and_timeout_are_config_errors(self):
        self.assertEqual(brain_lock.acquire("shout", 0), 3)
        self.assertEqual(brain_lock.acquire("wait", "x"), 3)
        self.assertEqual(brain_lock.acquire("wait", -1), 3)
        self.assertFalse(self.lock.exists())


class SkipWaitTimeout(LockCase):
    def test_skip_returns_1_for_a_live_holder_and_leaves_it_alone(self):
        with LiveHolder() as pid:
            self.plant(pid)
            self.assertEqual(brain_lock.acquire("skip", 0), 1)
            self.assertEqual(brain_lock.holder(), str(pid))
            self.assertEqual(self.pid_file(), str(pid))

    def test_wait_times_out_with_2_and_does_not_reclaim_a_live_holder(self):
        with LiveHolder() as pid:
            self.plant(pid)
            start = time.monotonic()
            self.assertEqual(brain_lock.acquire("wait", 1), 2)
            self.assertGreaterEqual(time.monotonic() - start, 0.9)
            self.assertEqual(self.pid_file(), str(pid))

    def test_wait_succeeds_once_the_holder_releases(self):
        code = ("import sys, time, brain_lock\n"
                "assert brain_lock.acquire('skip', 0) == 0\n"
                "print('held', flush=True)\n"
                "time.sleep(0.4)\n"
                "brain_lock.release()\n")
        proc = subprocess.Popen([sys.executable, "-c", code], env=child_env(), stdout=subprocess.PIPE, encoding="utf-8")
        self.assertEqual(proc.stdout.readline().strip(), "held")
        self.assertEqual(brain_lock.acquire("wait", 10), 0)
        proc.wait()
        proc.stdout.close()
        self.assertEqual(self.pid_file(), str(os.getpid()))


class FailClosed(LockCase):
    def test_dead_holder_is_retained(self):
        pid = dead_pid()
        self.plant(pid)
        self.assertEqual(brain_lock.acquire("skip", 0), 1)
        self.assertEqual(self.pid_file(), str(pid))

    def test_missing_pid_is_retained_without_grace_reclaim(self):
        self.plant(None)
        self.assertEqual(brain_lock.acquire("wait", 1), 2)
        self.assertTrue(self.lock.is_dir())

    def test_malformed_pid_and_extra_entries_are_untouched(self):
        self.plant("malformed")
        (self.lock / "extra").write_text("keep", encoding="utf-8")
        self.assertEqual(brain_lock.acquire("skip", 0), 1)
        self.assertEqual((self.lock / "extra").read_text(encoding="utf-8"), "keep")

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFO fixture")
    def test_fifo_pid_cannot_block_timeout(self):
        self.lock.mkdir()
        os.mkfifo(str(self.lock / "pid"))
        self.assertEqual(brain_lock.acquire("wait", 1), 2)

    def test_stale_leftovers_are_never_swept(self):
        stale = self.lock.with_name(self.lock.name + ".stale.old")
        stale.mkdir()
        self.assertEqual(brain_lock.acquire("skip", 0), 0)
        self.assertTrue(stale.is_dir())

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink fixture")
    def test_symlink_lock_is_refused(self):
        other = self.tmp / "other"
        other.mkdir()
        try:
            self.lock.symlink_to(other, target_is_directory=True)
        except OSError:
            self.skipTest("symlink creation requires privileges")
        self.assertEqual(brain_lock.acquire("skip", 0), 3)
        self.assertTrue(self.lock.is_symlink())


class ReleaseOnlyIfOurs(LockCase):
    def test_release_leaves_a_lock_that_someone_else_now_owns(self):
        self.assertEqual(brain_lock.acquire("skip", 0), 0)
        with LiveHolder() as pid:
            (self.lock / "pid").write_text(str(pid), encoding="utf-8")   # reclaimed + re-taken by another
            brain_lock.release()
            self.assertEqual(self.pid_file(), str(pid))


class OwnershipBoundaries(LockCase):
    def test_exported_parent_claim_never_grants_child_acquisition(self):
        self.assertEqual(brain_lock.acquire("skip", 0), 0)
        code = "import brain_lock; print(brain_lock.acquire('skip', 0)); brain_lock.release()"
        env = child_env({"BRAIN_LOCK_OWNER_PID": str(os.getpid())})
        result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, encoding="utf-8")
        self.assertEqual(result.stdout.strip(), "1")
        self.assertEqual(self.pid_file(), str(os.getpid()))

    def test_sibling_threads_cannot_acquire_or_release_the_owner_lock(self):
        import threading
        self.assertEqual(brain_lock.acquire("skip", 0), 0)
        values = []
        def other():
            values.append(brain_lock.acquire("skip", 0))
            brain_lock.release()
        worker = threading.Thread(target=other)
        worker.start()
        worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(values, [1])
        self.assertTrue(brain_lock.owned())

    @unittest.skipUnless(hasattr(os, "fork"), "POSIX fork fixture")
    def test_fork_cannot_inherit_or_release_ownership(self):
        self.assertEqual(brain_lock.acquire("skip", 0), 0)
        pid = os.fork()
        if pid == 0:
            try:
                rc = brain_lock.acquire("skip", 0)
                brain_lock.release()
                os._exit(0 if rc == 1 else 1)
            except BaseException:
                os._exit(2)
        _pid, status = os.waitpid(pid, 0)
        self.assertEqual(os.WEXITSTATUS(status), 0)
        self.assertEqual(self.pid_file(), str(os.getpid()))


class ForkMutexReset(LockCase):
    @unittest.skipUnless(hasattr(os, "fork"), "POSIX fork fixture")
    def test_child_resets_mutex_held_by_another_parent_thread(self):
        import threading
        ready, unblock = threading.Event(), threading.Event()
        self.assertEqual(brain_lock.acquire("skip", 0), 0)
        def parent_thread():
            with brain_lock._process_lock():
                ready.set()
                unblock.wait(5)
        thread = threading.Thread(target=parent_thread)
        thread.start()
        self.assertTrue(ready.wait(2))
        pid = os.fork()
        if pid == 0:
            try:
                rc = brain_lock.acquire("skip", 0)
                brain_lock.release()
                os._exit(0 if rc == 1 else 1)
            except BaseException:
                os._exit(2)
        deadline = time.monotonic() + 3
        result, status = 0, 0
        try:
            while time.monotonic() < deadline:
                result, status = os.waitpid(pid, os.WNOHANG)
                if result:
                    break
                time.sleep(0.01)
            if not result:
                os.kill(pid, 9)
                os.waitpid(pid, 0)
                self.fail("child inherited a locked mutex")
            self.assertEqual(os.WEXITSTATUS(status), 0)
        finally:
            unblock.set()
            thread.join(3)
        self.assertTrue(brain_lock.owned())


class ThreadPublication(LockCase):
    def test_release_and_new_thread_publication_are_serialized(self):
        import threading
        from unittest import mock
        removed, attempted, published = (threading.Event() for _ in range(3))
        original_rmdir, original_write = Path.rmdir, brain_lock._write_pid
        owner_thread = [None]
        outcomes = []
        def delayed_rmdir(path):
            original_rmdir(path)
            if threading.get_ident() == owner_thread[0] and path == self.lock:
                removed.set()
                self.assertTrue(attempted.wait(2))
                self.assertFalse(published.wait(0.1), "new owner published before old state was cleared")
        def observe_write(directory, pid):
            original_write(directory, pid)
            if threading.get_ident() != owner_thread[0]:
                published.set()
        def owner():
            owner_thread[0] = threading.get_ident()
            self.assertEqual(brain_lock.acquire("wait", 2), 0)
            brain_lock.release()
        def contender():
            self.assertTrue(removed.wait(2))
            attempted.set()
            rc = brain_lock.acquire("wait", 2)
            outcomes.append((rc, brain_lock.owned()))
            brain_lock.release()
        with mock.patch.object(Path, "rmdir", delayed_rmdir), mock.patch.object(brain_lock, "_write_pid", observe_write):
            first, second = threading.Thread(target=owner), threading.Thread(target=contender)
            second.start()
            first.start()
            first.join(5)
            second.join(5)
            self.assertFalse(first.is_alive() or second.is_alive())
        self.assertEqual(outcomes, [(0, True)])
        self.assertFalse(self.lock.exists())


class OverrideGate(LockCase):
    def test_override_outside_tmpdir_is_refused_with_3_and_creates_nothing(self):
        home = Path(os.path.realpath(str(HERE.parent)))
        os.environ["BRAIN_LOCK_DIR"] = str(home / "System_Config" / "logs" / "evil.lock.d")
        self.assertEqual(brain_lock.acquire("skip", 0), 3)
        self.assertFalse((home / "System_Config" / "logs" / "evil.lock.d").exists())

    def test_override_with_a_wrong_basename_is_refused(self):
        os.environ["BRAIN_LOCK_DIR"] = str(self.tmp / "something-else")
        self.assertEqual(brain_lock.acquire("skip", 0), 3)

    def test_override_with_a_missing_parent_is_refused(self):
        os.environ["BRAIN_LOCK_DIR"] = str(self.tmp / "nope" / "brain.lock.d")
        self.assertEqual(brain_lock.acquire("skip", 0), 3)

    def test_override_is_ignored_without_the_test_flag(self):
        del os.environ["BRAIN_LOCK_TEST"]
        brain_lock._reset()
        want = Path(os.path.realpath(str(HERE))) / "logs" / "brain.lock.d"
        self.assertEqual(Path(os.path.realpath(str(brain_lock.lock_path()))), want)
        self.assertNotEqual(Path(brain_lock.lock_path()), self.lock)


class RunWrapper(LockCase):
    def run_cli(self, *args, extra_env=None):
        return subprocess.run([sys.executable, str(HERE / "brain_lock.py"), "run", *args],
                              env=child_env(extra_env), capture_output=True, encoding="utf-8")

    def test_runs_the_command_with_the_lock_held_and_propagates_its_exit_code(self):
        probe = ("import os, sys; "
                 "print(open(os.environ['BRAIN_LOCK_DIR'] + '/pid').read().strip() == str(os.getppid())); "
                 "sys.exit(7)")
        out = self.run_cli("--mode", "wait", "--timeout", "5", "--", sys.executable, "-c", probe)
        self.assertEqual(out.returncode, 7, out.stderr)
        self.assertEqual(out.stdout.strip(), "True")
        self.assertFalse(self.lock.exists(), "lock released after the command")

    def test_skip_mode_with_a_live_holder_exits_0_without_running_the_command(self):
        with LiveHolder() as pid:
            self.plant(pid)
            out = self.run_cli("--mode", "skip", "--", sys.executable, "-c", "print('RAN')")
            self.assertEqual(out.returncode, 0)
            self.assertNotIn("RAN", out.stdout)

    def test_wait_timeout_exits_75_without_running_the_command(self):
        with LiveHolder() as pid:
            self.plant(pid)
            out = self.run_cli("--mode", "wait", "--timeout", "1", "--", sys.executable, "-c", "print('RAN')")
            self.assertEqual(out.returncode, 75)
            self.assertNotIn("RAN", out.stdout)

    def test_missing_command_is_a_usage_error(self):
        out = self.run_cli("--mode", "wait", "--timeout", "1")
        self.assertEqual(out.returncode, 2)


class TimeoutNotice(LockCase):
    def test_guard_failure_is_logged_and_local_notice_is_deduped_per_hour(self):
        logs = Path(os.environ["BRAIN_LOCK_NOTIFY_DIR"])
        sent = []
        brain_lock._desktop_notice = lambda title, body: sent.append((title, body))
        self.addCleanup(setattr, brain_lock, "_desktop_notice", brain_lock._desktop_notice)
        with LiveHolder() as pid:
            self.plant(pid)
            for _ in range(2):
                with brain_lock.guard("friday_process", "wait", 1) as held:
                    self.assertFalse(held)
        self.assertEqual(len(sent), 1, "second timeout in the same hour is deduped")
        self.assertIn("friday_process", sent[0][1])

    def test_guard_yields_true_and_releases_on_success(self):
        with brain_lock.guard("daily_ingest", "skip", 0) as held:
            self.assertTrue(held)
            self.assertTrue(self.lock.is_dir())
        self.assertFalse(self.lock.exists())

    def test_guard_skip_with_live_holder_is_quiet_no_notice(self):
        sent = []
        brain_lock._desktop_notice = lambda title, body: sent.append(title)
        self.addCleanup(setattr, brain_lock, "_desktop_notice", brain_lock._desktop_notice)
        with LiveHolder() as pid:
            self.plant(pid)
            with brain_lock.guard("daily_ingest", "skip", 0) as held:
                self.assertFalse(held)
        self.assertEqual(sent, [])


class Liveness(unittest.TestCase):
    def test_alive_and_dead(self):
        self.assertTrue(brain_lock._alive(os.getpid()))
        self.assertFalse(brain_lock._alive(dead_pid()))
        self.assertFalse(brain_lock._alive(0))
        self.assertFalse(brain_lock._alive(-5))


RACE_WORKER = r"""
import os, sys, time
import brain_lock
log = sys.argv[1]
rc = brain_lock.acquire('wait', 30)
if rc != 0:
    os.write(os.open(log, os.O_WRONLY | os.O_APPEND | os.O_CREAT), ('F %d %d\n' % (os.getpid(), rc)).encode())
    sys.exit(1)
fd = os.open(log, os.O_WRONLY | os.O_APPEND | os.O_CREAT)
os.write(fd, ('S %d %d\n' % (os.getpid(), time.time_ns())).encode())
time.sleep(0.004)
os.write(fd, ('E %d %d\n' % (os.getpid(), time.time_ns())).encode())
os.close(fd)
brain_lock.release()
"""


class ContentionRace(LockCase):
    WORKERS = 4

    def one_round(self, iteration, jitter):
        if self.lock.exists():
            shutil.rmtree(str(self.lock))
        log = self.tmp / ("race-%d.log" % iteration)
        env = child_env({"BRAIN_LOCK_TEST_JITTER": "1"} if jitter else None)
        procs = [subprocess.Popen([sys.executable, "-c", RACE_WORKER, str(log)], env=env) for _ in range(self.WORKERS)]
        # reap EVERY worker promptly: an unreaped dead worker is a zombie, which kill(pid, 0) reports as alive
        while [p.poll() for p in procs].count(None):
            time.sleep(0.002)
        codes = [p.returncode for p in procs]
        events = []
        for line in log.read_text(encoding="utf-8").splitlines():
            kind, pid, stamp = line.split()
            events.append((int(stamp), kind, pid))
        events.sort()
        overlap = False
        inside = None
        for _stamp, kind, pid in events:
            if kind == "S":
                if inside is not None:
                    overlap = True
                inside = pid
            elif kind == "E":
                inside = None
        return codes, overlap, sum(1 for e in events if e[1] == "S")

    def test_contending_processes_never_double_hold(self):
        rounds = int(os.environ.get("BRAIN_LOCK_RACE_ROUNDS", "8"))
        for i in range(rounds):
            codes, overlap, entered = self.one_round(i, jitter=False)
            self.assertEqual(codes, [0] * self.WORKERS, "round %d: a worker failed to acquire" % i)
            self.assertEqual(entered, self.WORKERS)
            self.assertFalse(overlap, "round %d: two processes held the lock at once" % i)
            self.assertFalse(self.lock.exists(), "round %d: lock leaked" % i)
            self.assertEqual(list(self.tmp.glob("brain.lock.d.stale.*")), [], "round %d: stale copy leaked" % i)
            self.assertFalse((self.tmp / "brain.lock.d.reclaim").exists(), "round %d: reclaim mutex leaked" % i)

    def test_repeated_contention_leaves_no_lock(self):
        rounds = int(os.environ.get("BRAIN_LOCK_RACE_ROUNDS_JITTER", "4"))
        for i in range(rounds):
            codes, overlap, entered = self.one_round(1000 + i, jitter=True)
            self.assertEqual(codes, [0] * self.WORKERS, "jitter round %d: a worker failed to acquire" % i)
            self.assertFalse(self.lock.exists(), "jitter round %d: lock leaked" % i)
            self.assertFalse(overlap, "jitter round %d: two processes held the lock at once" % i)
            self.assertEqual(list(self.tmp.glob("brain.lock.d.stale.*")), [], "jitter round %d: stale copy leaked" % i)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    unittest.main(verbosity=1)
