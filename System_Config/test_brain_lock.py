#!/usr/bin/env python3
"""test_brain_lock.py — fixtures for System_Config/brain_lock.py, the ONE shared
brain/ write lock. Standalone unittest file (run directly, no pytest needed):

    python3 System_Config/test_brain_lock.py

Covers acquire/release, skip/wait, timeout, live-holder-not-reclaimed,
dead-holder-reclaimed, empty-pid grace, stale-copy sweep, re-entrancy (with
the ancestor check and its no-ancestor-walk fallback), release-only-if-ours,
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


class Reclaim(LockCase):
    def test_dead_holder_is_reclaimed(self):
        dead = dead_pid()
        self.plant(dead)
        self.assertEqual(brain_lock.acquire("skip", 0), 0)
        self.assertEqual(self.pid_file(), str(os.getpid()))
        self.assertEqual(list(self.tmp.glob("brain.lock.d.stale.*")), [])

    def test_on_reclaim_hook_sees_the_dead_pid(self):
        dead = dead_pid()
        self.plant(dead)
        seen = []
        brain_lock.on_reclaim = seen.append
        self.addCleanup(setattr, brain_lock, "on_reclaim", None)
        self.assertEqual(brain_lock.acquire("skip", 0), 0)
        self.assertEqual(seen, [str(dead)])

    def test_empty_pid_gets_a_three_tick_grace_before_reclaim(self):
        self.plant(None)
        start = time.monotonic()
        self.assertEqual(brain_lock.acquire("skip", 0), 0)
        self.assertGreaterEqual(time.monotonic() - start, 0.09)   # >= 2 poll ticks of 0.05s
        self.assertEqual(self.pid_file(), str(os.getpid()))

    def test_empty_pid_that_fills_in_during_grace_is_not_reclaimed(self):
        self.plant(None)
        with LiveHolder() as pid:
            import threading
            threading.Timer(0.06, lambda: (self.lock / "pid").write_text(str(pid), encoding="utf-8")).start()
            self.assertEqual(brain_lock.acquire("skip", 0), 1)
            self.assertEqual(self.pid_file(), str(pid))

    def test_sweep_removes_old_stale_copies_only(self):
        old = self.tmp / "brain.lock.d.stale.1.1"
        fresh = self.tmp / "brain.lock.d.stale.2.2"
        odd = self.tmp / "brain.lock.d.stale.3.3"
        for d in (old, fresh, odd):
            d.mkdir()
            (d / "pid").write_text("999999", encoding="utf-8")
        (odd / "surprise.txt").write_text("not ours", encoding="utf-8")
        long_ago = time.time() - 61 * 60
        for d in (old, odd):
            os.utime(str(d), (long_ago, long_ago))
        self.assertEqual(brain_lock.acquire("skip", 0), 0)
        self.assertFalse(old.exists(), "stale copy older than 60 min is swept")
        self.assertTrue(fresh.exists(), "young stale copy is kept")
        self.assertTrue(odd.exists(), "a dir holding anything but `pid` is never removed")

    def test_a_stale_copy_holding_an_unexpected_entry_is_kept_never_deleted(self):
        dead = dead_pid()
        self.plant(dead)
        (self.lock / "surprise.txt").write_text("not ours", encoding="utf-8")
        self.assertEqual(brain_lock.acquire("skip", 0), 0)
        kept = list(self.tmp.glob("brain.lock.d.stale.*"))
        self.assertEqual(len(kept), 1)
        self.assertTrue((kept[0] / "surprise.txt").exists())


class ReclaimMutex(LockCase):
    def test_an_abandoned_reclaim_mutex_does_not_block_reclaim_forever(self):
        self.plant(dead_pid())
        mutex = self.tmp / "brain.lock.d.reclaim"
        mutex.mkdir()
        (mutex / "pid").write_text(str(dead_pid()), encoding="utf-8")
        self.assertEqual(brain_lock.acquire("wait", 10), 0)
        self.assertEqual(self.pid_file(), str(os.getpid()))
        self.assertFalse(mutex.exists())

    def test_a_live_reclaimer_blocks_a_second_reclaim_and_the_lock_is_left_alone(self):
        dead = dead_pid()
        self.plant(dead)
        with LiveHolder() as pid:
            mutex = self.tmp / "brain.lock.d.reclaim"
            mutex.mkdir()
            (mutex / "pid").write_text(str(pid), encoding="utf-8")
            self.assertEqual(brain_lock.acquire("skip", 0), 1)
            self.assertEqual(self.pid_file(), str(dead))
            self.assertEqual((mutex / "pid").read_text(encoding="utf-8"), str(pid))

    def test_reclaim_that_finds_a_fresh_live_lock_under_the_mutex_does_not_touch_it(self):
        with LiveHolder() as pid:
            self.plant(pid)
            self.assertFalse(brain_lock._reclaim(self.lock, "99999999"))   # we "saw" a dead pid, but it changed
            self.assertEqual(self.pid_file(), str(pid))
            self.assertFalse((self.tmp / "brain.lock.d.reclaim").exists())


class ReleaseOnlyIfOurs(LockCase):
    def test_release_leaves_a_lock_that_someone_else_now_owns(self):
        self.assertEqual(brain_lock.acquire("skip", 0), 0)
        with LiveHolder() as pid:
            (self.lock / "pid").write_text(str(pid), encoding="utf-8")   # reclaimed + re-taken by another
            brain_lock.release()
            self.assertEqual(self.pid_file(), str(pid))


class Reentrancy(LockCase):
    CHILD = ("import sys, brain_lock\n"
             "rc = brain_lock.acquire('wait', 1)\n"
             "print(rc, flush=True)\n"
             "brain_lock.release()\n"
             "sys.exit(0)\n")

    def run_child(self, extra_env=None, code=None):
        out = subprocess.run([sys.executable, "-c", code or self.CHILD], env=child_env(extra_env),
                             capture_output=True, encoding="utf-8")
        return out.stdout.strip()

    def test_child_of_the_holder_reenters_and_its_release_keeps_the_lock(self):
        self.assertEqual(brain_lock.acquire("skip", 0), 0)
        self.assertEqual(os.environ.get("BRAIN_LOCK_OWNER_PID"), str(os.getpid()))
        self.assertEqual(self.run_child(), "0")
        self.assertEqual(self.pid_file(), str(os.getpid()), "child release must not drop the parent's lock")

    def test_grandchild_reenters(self):
        self.assertEqual(brain_lock.acquire("skip", 0), 0)
        code = ("import subprocess, sys\n"
                "print(subprocess.run([sys.executable, '-c', %r], capture_output=True, encoding='utf-8').stdout.strip())\n"
                % self.CHILD)
        self.assertEqual(self.run_child(code=code), "0")

    def test_a_bare_env_var_does_not_bypass_the_lock(self):
        with LiveHolder() as pid:
            self.plant(pid)
            # the holder is alive and named in the env, but is NOT an ancestor of the child
            self.assertEqual(self.run_child({"BRAIN_LOCK_OWNER_PID": str(pid)}), "2")

    def test_release_clears_the_owner_env_var(self):
        self.assertEqual(brain_lock.acquire("skip", 0), 0)
        brain_lock.release()
        self.assertNotIn("BRAIN_LOCK_OWNER_PID", os.environ)

    def test_when_the_ancestor_walk_is_unavailable_a_direct_child_still_reenters(self):
        # No `ps` / toolhelp: walk raises. A child must not deadlock against its own parent until timeout.
        code = ("import sys, brain_lock\n"
                "def boom(pid):\n"
                "    raise OSError('no ancestor walk here')\n"
                "brain_lock._ppid_of = boom\n"
                "print(brain_lock.acquire('wait', 1), flush=True)\n")
        self.assertEqual(brain_lock.acquire("skip", 0), 0)
        self.assertEqual(self.run_child(code=code), "0")

    def test_when_the_ancestor_walk_is_unavailable_a_stranger_is_still_refused(self):
        code = ("import brain_lock\n"
                "def boom(pid):\n"
                "    raise OSError('no ancestor walk here')\n"
                "brain_lock._ppid_of = boom\n"
                "print(brain_lock.acquire('skip', 0), flush=True)\n")
        with LiveHolder() as pid:
            self.plant(pid)
            self.assertEqual(self.run_child({"BRAIN_LOCK_OWNER_PID": str(pid)}, code=code), "1")


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
                 "print(open(os.environ['BRAIN_LOCK_DIR'] + '/pid').read().strip() == os.environ['BRAIN_LOCK_OWNER_PID']); "
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


class ReclaimRace(LockCase):
    WORKERS = 4

    def one_round(self, iteration, jitter):
        if self.lock.exists():
            shutil.rmtree(str(self.lock))
        self.plant(dead_pid())
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

    def test_two_plus_reclaimers_never_double_hold_at_natural_timing(self):
        rounds = int(os.environ.get("BRAIN_LOCK_RACE_ROUNDS", "40"))
        for i in range(rounds):
            codes, overlap, entered = self.one_round(i, jitter=False)
            self.assertEqual(codes, [0] * self.WORKERS, "round %d: a worker failed to acquire" % i)
            self.assertEqual(entered, self.WORKERS)
            self.assertFalse(overlap, "round %d: two processes held the lock at once" % i)
            self.assertFalse(self.lock.exists(), "round %d: lock leaked" % i)
            self.assertEqual(list(self.tmp.glob("brain.lock.d.stale.*")), [], "round %d: stale copy leaked" % i)
            self.assertFalse((self.tmp / "brain.lock.d.reclaim").exists(), "round %d: reclaim mutex leaked" % i)

    def test_widened_race_windows_still_never_double_hold_or_leak(self):
        rounds = int(os.environ.get("BRAIN_LOCK_RACE_ROUNDS_JITTER", "20"))
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
