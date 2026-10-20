#!/usr/bin/env python3
"""brain_lock.py — the ONE shared write lock for brain/. Stdlib only, no
dependency on config.py (log_session.py is deliberately config-independent).

    import brain_lock
    rc = brain_lock.acquire("skip", 0)     # 0 got it · 1 held by a live pid
    rc = brain_lock.acquire("wait", 900)   # 0 got it · 2 timed out · (3 = config error, both modes)
    brain_lock.release()                   # no-op unless the lock is ours

    with brain_lock.guard("daily_ingest", "skip", 0) as held:   # acquire + log/notify + release
        if not held:
            return 0

Shell scripts cannot hold the lock across separate calls (the pid would belong
to a Python process that dies at once), so they wrap a command instead:

    python3 System_Config/brain_lock.py run --mode wait --timeout 900 -- <command> [args...]

`run` holds the lock for the command's lifetime and exits with its exit code
(skip + live holder -> exit 0 without running it; wait timeout -> exit 75;
usage/config error -> exit 2). Children of the holder inherit
BRAIN_LOCK_OWNER_PID and re-enter, so nested scripts never self-deadlock.

Lock = directory System_Config/logs/brain.lock.d holding one file, `pid`.
Callers (not this module) own exit codes and what to do on a miss. Modes:
skip = return 1 at once if a LIVE pid holds it; wait = poll once a second up to
<timeout_s>, then return 2. Both: a dead holder is reclaimed atomically (rename
the dir aside, re-check the moved copy, only then discard it); an empty/missing
pid file gets a 3-tick grace first (a live holder can sit between its mkdir and
its pid write). `<lock>.stale.*` leftovers older than 60 min are swept.

Re-entrancy: acquire exports BRAIN_LOCK_OWNER_PID=<our pid>. A child that finds
the lock's pid equal to that value, alive, and an ANCESTOR of itself (parent
walk, so a bare env var cannot bypass the lock) treats the lock as already
held: acquire returns 0 and release is a no-op. Where the parent walk is
unavailable (no `ps`, no toolhelp), only the DIRECT parent is accepted (a
grandchild of the holder then waits/skips instead of re-entering).

Test override (honoured ONLY when BRAIN_LOCK_TEST=1): BRAIN_LOCK_DIR=<dir named
*.lock.d>, parent must already exist strictly under the system temp dir; a bad
override is REFUSED (rc 3, nothing created), never silently falling back to the
real lock. Without BRAIN_LOCK_TEST=1 the variable is ignored with a warning.
BRAIN_LOCK_TEST_POLL (seconds) and BRAIN_LOCK_TEST_JITTER=1 are likewise
test-only.

Reclaim safety: reclaimers are serialised by a second mkdir mutex (<lock>.reclaim, pid inside; a dead
or abandoned one is cleared and the caller retries). While one holds it nobody else can remove the lock dir,
so the dead pid it read cannot be swapped for a fresh LIVE lock before its rename (the double-reclaim race the
bash helpers accept; measured here at 0 double-holds / 0 leaked copies in 450 four-process rounds, with and
without 0-40ms jitter in the reclaim windows). RESIDUAL (accepted): the empty-pid case — if a holder stalls
between its mkdir and its pid write for >3 ticks, a reclaimer moves its dir aside; the holder's pid write then
fails and it retries, or, if the write landed first, the reclaimer puts the lock back, and for that gap the
slot is vacant. A put-back that loses its slot leaves the moved copy at <lock>.stale.<pid>.<n> (never deleted;
swept after 60 min). A live lock is never deleted. mkdir + pid file is not a true mutex. Do not "fix" it with
rmtree.
"""
import contextlib
import itertools
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(os.path.abspath(__file__)).parent
LOCK_NAME = "brain.lock.d"
STALE_COPY_MAX_AGE_S = 60 * 60
RECLAIM_MUTEX_GRACE_S = 10   # an empty reclaim-mutex dir older than this is abandoned
MAX_RECLAIMS = 5   # per acquire call: bounded, but a put-back can legitimately leave a dead lock behind

# Optional hooks (set by callers before acquire).
log_hook = None      # callable(str); default = stderr
on_reclaim = None    # callable(str) after a successful reclaim; failures ignored

_HAVE = False
_DEPTH = 0   # in-process nesting (daily_ingest calls monday_init.run() while holding it)
_DIR = None
_holder = ""
_counter = itertools.count()


def _reset():
    """Forget in-process state (tests only; does not touch the filesystem)."""
    global _HAVE, _DEPTH, _DIR, _holder
    _HAVE, _DEPTH, _DIR, _holder = False, 0, None, ""


def _log(message):
    if log_hook is not None:
        try:
            log_hook(message)
            return
        except Exception:
            pass
    print("[brain_lock] " + message, file=sys.stderr)


def _int_env(name, default):
    try:
        value = int(os.environ.get(name, ""))
        return value if value >= 0 else default
    except ValueError:
        return default


def wait_seconds():
    """Weekly-job wait (BRAIN_LOCK_WAIT, default 900s)."""
    return _int_env("BRAIN_LOCK_WAIT", 900)


def short_wait_seconds():
    """Hand-run context CLIs (BRAIN_LOCK_SHORT_WAIT, default 60s)."""
    return _int_env("BRAIN_LOCK_SHORT_WAIT", 60)


def hook_wait_seconds():
    """Session-hook style callers (BRAIN_LOCK_HOOK_WAIT, default 5s)."""
    return _int_env("BRAIN_LOCK_HOOK_WAIT", 5)


def _testing():
    return os.environ.get("BRAIN_LOCK_TEST") == "1"


def _poll():
    if _testing():
        try:
            return float(os.environ.get("BRAIN_LOCK_TEST_POLL", "") or 1.0)
        except ValueError:
            return 1.0
    return 1.0


def _jitter():
    if _testing() and os.environ.get("BRAIN_LOCK_TEST_JITTER") == "1":
        time.sleep(random.randrange(5) * 0.01)


def lock_path():
    """Resolved lock dir, or None when a test override is refused."""
    override = os.environ.get("BRAIN_LOCK_DIR", "")
    if _testing() and override:
        target = Path(override)
        if not target.name.endswith(".lock.d"):
            _log("BRAIN_LOCK_TEST lock dir name must end in .lock.d: " + override)
            return None
        tmp = Path(os.path.realpath(tempfile.gettempdir()))
        try:
            parent = Path(os.path.realpath(str(target.parent)))
        except OSError:
            parent = None
        if parent is None or not parent.is_dir():
            _log("BRAIN_LOCK_TEST lock dir parent is missing: " + override)
            return None
        if tmp == Path(tmp.anchor) or tmp not in parent.parents and parent != tmp:
            _log("BRAIN_LOCK_TEST lock dir parent %s is not under %s — refused" % (parent, tmp))
            return None
        return parent / target.name
    if override:
        _log("WARN: BRAIN_LOCK_DIR is ignored (test-only override; needs BRAIN_LOCK_TEST=1)")
    return HERE / "logs" / LOCK_NAME


def holder():
    """Pid seen when the last acquire returned 1/2."""
    return _holder


def _read_pid(directory):
    try:
        with open(str(Path(directory) / "pid"), encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def _write_pid(directory, value):
    with open(str(Path(directory) / "pid"), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(str(value) + "\n")


def _kernel32():
    """kernel32 with explicit prototypes: default c_int restypes truncate 64-bit HANDLEs, and
    ctypes.get_last_error() is only meaningful on a DLL loaded with use_last_error=True. (Windows only.)"""
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.GetExitCodeProcess.restype = wintypes.BOOL
    k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k32.CloseHandle.restype = wintypes.BOOL
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k32.Process32FirstW.restype = wintypes.BOOL
    k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    k32.Process32NextW.restype = wintypes.BOOL
    k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    return k32


def _alive(pid):
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        # os.kill(pid, 0) TERMINATES the process on Windows — never use it there.
        import ctypes
        from ctypes import wintypes
        k32 = _kernel32()
        handle = k32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.get_last_error() == 5   # ERROR_ACCESS_DENIED: exists, not ours to open = alive
        try:
            code = wintypes.DWORD()
            if not k32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == 259   # STILL_ACTIVE
        finally:
            k32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _ppid_of(pid):
    """Parent pid of <pid>; raises OSError/ValueError when it cannot be found."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class ProcessEntry(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                        ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                        ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]

        k32 = _kernel32()
        snapshot = k32.CreateToolhelp32Snapshot(0x2, 0)   # TH32CS_SNAPPROCESS
        if not snapshot or snapshot == ctypes.c_void_p(-1).value:
            raise OSError("process snapshot failed")
        try:
            entry = ProcessEntry()
            entry.dwSize = ctypes.sizeof(ProcessEntry)
            ok = k32.Process32FirstW(snapshot, ctypes.byref(entry))
            while ok:
                if entry.th32ProcessID == pid:
                    return int(entry.th32ParentProcessID)
                ok = k32.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            k32.CloseHandle(snapshot)
        raise OSError("pid not found: %d" % pid)
    result = subprocess.run(["ps", "-o", "ppid=", "-p", str(pid)], capture_output=True, encoding="utf-8")
    text = result.stdout.strip()
    if result.returncode or not text:
        raise OSError("ps could not find pid %d" % pid)
    return int(text)


def _is_ancestor(target):
    """True/False, or None when the parent walk is unavailable."""
    try:
        target = int(target)
        current = os.getpid()
        for _unused in range(64):
            current = _ppid_of(current)
            if current == target:
                return True
            if current <= 1:
                return False
        return False
    except (OSError, ValueError):
        return None


def _rm_lock_dir(directory):
    """Remove a dir holding NOTHING but a `pid` file (an unexpected entry means it is not ours)."""
    directory = Path(directory)
    try:
        with os.scandir(str(directory)) as entries:
            for entry in entries:
                if entry.name != "pid":
                    _log("WARN: lock dir %s holds unexpected entry '%s' — not removing" % (directory, entry.name))
                    return False
        with contextlib.suppress(FileNotFoundError):
            os.unlink(str(directory / "pid"))
        os.rmdir(str(directory))
        return True
    except OSError:
        return False


def _sweep_stale(directory):
    for copy in directory.parent.glob(directory.name + ".stale.*"):
        try:
            if copy.is_symlink() or not copy.is_dir():
                continue
            if time.time() - copy.stat().st_mtime < STALE_COPY_MAX_AGE_S:
                continue
        except OSError:
            continue
        if _rm_lock_dir(copy):
            _log("swept leaked stale lock copy " + str(copy))


def _take_reclaim_mutex(mutex):
    """Serialise reclaimers. While one holds this, nobody else can remove the lock dir, so what it read
    (a dead pid) cannot be swapped for a fresh live lock before its rename. The mutex itself is mkdir + pid;
    a dead/abandoned one is cleared (only the mutex — never the lock) and the caller simply retries."""
    try:
        os.mkdir(str(mutex))
    except FileExistsError:
        pid = _read_pid(mutex)
        try:
            age = time.time() - mutex.stat().st_mtime
        except OSError:
            return False
        if (pid and not _alive(pid)) or (not pid and age > RECLAIM_MUTEX_GRACE_S):
            gone = mutex.with_name("%s.stale.%d.%d" % (mutex.name, os.getpid(), next(_counter)))
            try:
                os.rename(str(mutex), str(gone))
                _rm_lock_dir(gone)
            except OSError:
                pass
        return False
    except OSError:
        return False
    try:
        _write_pid(mutex, os.getpid())
    except OSError:
        pass
    return True


def _drop_reclaim_mutex(mutex):
    if _read_pid(mutex) == str(os.getpid()):
        _rm_lock_dir(mutex)


def _reclaim(directory, seen):
    """Atomic stale reclaim. Under the reclaim mutex: re-read the lock (still the stale one we saw?), rename it
    aside (only the process whose rename succeeds proceeds), re-check the moved copy, then discard it —
    otherwise put it back."""
    mutex = directory.with_name(directory.name + ".reclaim")
    if not _take_reclaim_mutex(mutex):
        return False
    try:
        if _read_pid(directory) != seen or (seen and _alive(seen)):
            return False   # changed while we waited for the mutex: no longer the stale lock we saw
        return _reclaim_locked(directory, seen)
    finally:
        _drop_reclaim_mutex(mutex)


def _reclaim_locked(directory, seen):
    moved = directory.with_name("%s.stale.%d.%d" % (directory.name, os.getpid(), next(_counter)))
    if os.path.lexists(str(moved)):
        return False
    _jitter()
    try:
        os.rename(str(directory), str(moved))
    except OSError:
        return False   # lost the race (or the lock vanished): not ours to reclaim
    _jitter()
    now = _read_pid(moved)
    if now != seen or (seen and _alive(seen)):
        # A holder finished its mkdir -> pid write while we were moving it (the empty-pid case). Put it back
        # with an atomic mkdir (never rename: POSIX rename onto an empty dir would clobber a fresh holder).
        try:
            os.mkdir(str(directory))
        except OSError:
            _log("WARN: lock changed during reclaim (pid %s) and could not be put back; left at %s (not removed)" % (now or "none", moved))
            return False
        if now:
            try:
                _write_pid(directory, now)
            except OSError:
                pass
        _rm_lock_dir(moved)
        _log("WARN: lock changed during reclaim (pid %s); put it back" % (now or "none"))
        return False
    if not _rm_lock_dir(moved):
        _log("WARN: stale lock copy kept at " + str(moved))
    return True


def _reentrant(directory):
    owner = os.environ.get("BRAIN_LOCK_OWNER_PID", "")
    if not owner or _read_pid(directory) != owner or not _alive(owner):
        return False
    if owner == str(os.getpid()):
        return True
    ancestor = _is_ancestor(owner)
    if ancestor is None:
        return owner == str(os.getppid())   # walk unavailable: accept only the direct parent
    return ancestor


def acquire(mode, timeout):
    """See module docstring. Returns 0 got it / 1 skip-held / 2 wait-timeout / 3 config error."""
    global _HAVE, _DEPTH, _DIR, _holder
    _holder = ""
    if mode not in ("skip", "wait"):
        _log("acquire: bad mode %r (skip|wait)" % (mode,))
        return 3
    try:
        timeout = int(timeout)
        if timeout < 0 or isinstance(timeout, bool):
            raise ValueError
    except (TypeError, ValueError):
        _log("acquire: timeout must be a non-negative integer, got %r" % (timeout,))
        return 3
    directory = lock_path()
    if directory is None:
        return 3
    if not _testing() or not os.environ.get("BRAIN_LOCK_DIR"):
        try:
            directory.parent.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            _log("cannot create lock parent %s: %s" % (directory.parent, error))
            return 3
    _DIR = directory

    me = str(os.getpid())
    pid = _read_pid(directory)
    if _HAVE and pid == me:
        _DEPTH += 1
        return 0   # already ours (in-process nesting: only the outermost release drops it)
    if _reentrant(directory):
        return 0   # a parent holds it

    _sweep_stale(directory)
    deadline = time.monotonic() + timeout
    empty = tries = reclaims = 0
    while True:
        tries += 1
        try:
            os.mkdir(str(directory))
        except FileExistsError:
            pass
        except OSError as error:
            _log("cannot create lock %s: %s" % (directory, error))
            return 3
        else:
            try:
                _write_pid(directory, me)
                mine = _read_pid(directory) == me
            except OSError:
                mine = False   # our dir was moved aside by a reclaimer before the pid write: retry
            if mine:
                _HAVE, _DEPTH = True, 1
                os.environ["BRAIN_LOCK_OWNER_PID"] = me
                return 0
            continue
        pid = _read_pid(directory)
        if pid:
            empty = 0
            if _alive(pid):
                if mode == "skip":
                    _holder = pid
                    return 1
            elif reclaims < MAX_RECLAIMS:
                _log("stale lock (holder %s gone) — reclaiming %s" % (pid, directory))
                if _reclaim(directory, pid):
                    reclaims += 1
                    _call_on_reclaim(pid)
                    continue
        else:
            empty += 1   # a live holder may be between mkdir and its pid write — wait a few ticks first
            if empty >= 3 and reclaims < MAX_RECLAIMS:
                _log("stale lock (no pid after %d ticks) — reclaiming %s" % (empty, directory))
                if _reclaim(directory, ""):
                    reclaims += 1
                    _call_on_reclaim("")
                    continue
        _holder = pid
        if mode == "skip":
            if tries >= 10:
                return 1   # bounded: a lost reclaim race re-checks, never spins
            if not pid and empty < 3:
                time.sleep(_poll())   # grace tick
        else:
            if time.monotonic() >= deadline:
                return 2
            time.sleep(_poll())


def _call_on_reclaim(pid):
    if on_reclaim is not None:
        try:
            on_reclaim(pid)
        except Exception:
            pass


def release():
    """Release only if the pid file is ours (never delete a lock that was reclaimed and re-taken)."""
    global _HAVE, _DEPTH
    if _HAVE and _DEPTH > 1:
        _DEPTH -= 1
        return
    if _HAVE and _DIR is not None:
        if _read_pid(_DIR) == str(os.getpid()):
            _rm_lock_dir(_DIR)
        if os.environ.get("BRAIN_LOCK_OWNER_PID") == str(os.getpid()):
            os.environ.pop("BRAIN_LOCK_OWNER_PID", None)
    _HAVE, _DEPTH = False, 0


@contextlib.contextmanager
def hold(mode, timeout):
    """Acquire; yield the rc; release on exit (a no-op unless rc == 0 and the lock is ours)."""
    rc = acquire(mode, timeout)
    try:
        yield rc
    finally:
        if rc == 0:
            release()


def _desktop_notice(title, body):
    """Local desktop notification only (never a webhook). Best effort; silent where unavailable."""
    try:
        if sys.platform == "darwin" and shutil.which("osascript"):
            def esc(text):
                return str(text).replace("\\", "\\\\").replace('"', '\\"')
            subprocess.run(["osascript", "-e", 'display notification "%s" with title "%s"' % (esc(body), esc(title))],
                           capture_output=True, timeout=10)
        elif sys.platform.startswith("linux") and shutil.which("notify-send"):
            subprocess.run(["notify-send", title, body], capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        pass


def _notice_dir():
    return Path(os.environ.get("BRAIN_LOCK_NOTIFY_DIR") or (HERE / "logs"))


def _notify_timeout(name, waited):
    """One local notice per hour (a dedup marker file), never a webhook."""
    title = "Brain lock timeout: " + name
    body = "%s waited %ss for the brain lock (holder %s) and exited WITHOUT writing. Check for a hung ingest: %s" % (
        name, waited, _holder or "unknown", lock_path())
    _log(body)
    try:
        directory = _notice_dir()
        directory.mkdir(parents=True, exist_ok=True)
        marker = directory / (".brain-lock-notified-" + time.strftime("%Y%m%d%H"))
        os.close(os.open(str(marker), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
        for old in directory.glob(".brain-lock-notified-*"):
            if old != marker and time.time() - old.stat().st_mtime > 24 * 3600:
                with contextlib.suppress(OSError):
                    old.unlink()
    except FileExistsError:
        return
    except OSError:
        pass
    if not _testing() and not os.environ.get("BRAIN_LOCK_NO_NOTIFY"):
        _desktop_notice(title, body)
    elif _desktop_notice is not _ORIGINAL_DESKTOP_NOTICE:
        _desktop_notice(title, body)   # a test replaced it: let it observe the call


_ORIGINAL_DESKTOP_NOTICE = _desktop_notice


@contextlib.contextmanager
def guard(name, mode, timeout):
    """acquire + report + release. Yields True when the lock is held (or re-entered);
    on False the caller must exit WITHOUT writing. skip + live holder is quiet; a wait
    timeout logs and raises one local notice per hour; a config error is logged."""
    rc = acquire(mode, timeout)
    try:
        if rc == 0:
            yield True
        else:
            if rc == 1:
                _log("%s: another run holds %s (pid %s) — skipping" % (name, lock_path(), _holder or "?"))
            elif rc == 2:
                _notify_timeout(name, timeout)
            else:
                _log("%s: brain lock configuration error — not writing" % name)
            yield False
    finally:
        if rc == 0:
            release()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    usage = "usage: brain_lock.py run [--mode skip|wait] [--timeout SECONDS] [--name LABEL] -- <command> [args...]"
    if not argv or argv[0] != "run":
        print(usage, file=sys.stderr)
        return 2
    rest = argv[1:]
    if "--" not in rest:
        print(usage, file=sys.stderr)
        return 2
    split = rest.index("--")
    options, command = rest[:split], rest[split + 1:]
    mode, timeout, name = "wait", wait_seconds(), "brain_lock run"
    index = 0
    while index < len(options):
        flag = options[index]
        if flag in ("--mode", "--timeout", "--name") and index + 1 < len(options):
            if flag == "--mode":
                mode = options[index + 1]
            elif flag == "--name":
                name = options[index + 1]
            else:
                try:
                    timeout = int(options[index + 1])
                except ValueError:
                    print(usage, file=sys.stderr)
                    return 2
            index += 2
        else:
            print(usage, file=sys.stderr)
            return 2
    if not command or mode not in ("skip", "wait"):
        print(usage, file=sys.stderr)
        return 2
    rc = acquire(mode, timeout)
    try:
        if rc == 1:
            _log("%s: another run holds the brain lock (pid %s) — skipping" % (name, _holder or "?"))
            return 0
        if rc == 2:
            _notify_timeout(name, timeout)
            return 75
        if rc != 0:
            return 2
        try:
            result = subprocess.run(command)
        except OSError as error:
            print("brain_lock run: cannot start %s: %s" % (command[0], error), file=sys.stderr)
            return 127
        return result.returncode if result.returncode >= 0 else 128 - result.returncode
    finally:
        if rc == 0:
            release()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
