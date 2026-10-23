#!/usr/bin/env python3
"""One shared write lock for brain/, using Python 3.9+ standard library only.

acquire(skip|wait, timeout) returns 0 acquired, 1 busy in skip mode, 2 timed
out, or 3 configuration error. Existing locks are NEVER automatically moved,
reclaimed or swept, even for dead/missing PIDs. Quiesce all writers and inspect
ownership before manual recovery. Age and PID probes cannot authorize removal.

Only same-process, same-thread nesting is reentrant. Descendant processes and
sibling threads must wait/skip; BRAIN_LOCK_OWNER_PID confers no authority.
Known nested writers are composed in-process, not launched under a held lock.
The run CLI holds the mutex for an external command; that command must not
invoke another lock-taking writer (it would wait/skip, never bypass).

Directory System_Config/logs/brain.lock.d contains a PID file. Callers own
failure behavior; guard() releases on exceptions. SIGKILL/power loss leaves a
lock for deliberate recovery. Test overrides are restricted to a temp directory.
This coordinates cooperating writers, not malicious same-user code.
"""
import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
import stat
import threading
from pathlib import Path

HERE = Path(os.path.abspath(__file__)).parent
LOCK_NAME = "brain.lock.d"
# Optional hooks (set by callers before acquire).
log_hook = None      # callable(str); default = stderr

_HAVE = False
_DEPTH = 0   # in-process nesting (daily_ingest calls monday_init.run() while holding it)
_DIR = None
_holder = ""
_OWNER_PID = None
_OWNER_THREAD = None
_IDENTITY = None
_STATE_LOCK = threading.RLock()
_STATE_PID = os.getpid()


def _process_lock():
    global _STATE_LOCK, _STATE_PID
    if _STATE_PID != os.getpid():
        _STATE_LOCK = threading.RLock()
        _STATE_PID = os.getpid()
        _reset()
    return _STATE_LOCK


def _reset():
    """Forget in-process state (tests only; does not touch the filesystem)."""
    global _HAVE, _DEPTH, _DIR, _holder, _OWNER_PID, _OWNER_THREAD, _IDENTITY
    _HAVE, _DEPTH, _DIR, _holder = False, 0, None, ""
    _OWNER_PID, _OWNER_THREAD, _IDENTITY = None, None, None


def _after_fork():
    # Called before child user code/threads: do not inherit a potentially locked
    # thread mutex or let several new child threads race lazy replacement.
    global _STATE_LOCK, _STATE_PID
    _STATE_LOCK = threading.RLock()
    _STATE_PID = os.getpid()
    _reset()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_after_fork)


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
    path = Path(directory) / "pid"
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_size > 24:
            return ""
        fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, encoding="utf-8") as handle:
            after = os.fstat(handle.fileno())
            if not stat.S_ISREG(after.st_mode) or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                return ""
            value = handle.read(25).strip()
        return value if value.isascii() and value.isdigit() else ""
    except (OSError, UnicodeError):
        return ""


def _write_pid(directory, value):
    fd = os.open(str(Path(directory) / "pid"), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
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


def _identity(directory):
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise OSError("lock path is not a real directory")
    return info.st_dev, info.st_ino


def owned():
    """True only for the actual owning process/thread and original directory."""
    with _process_lock():
        if not _HAVE or _OWNER_PID != os.getpid() or _OWNER_THREAD != threading.get_ident():
            return False
        try:
            return _identity(_DIR) == _IDENTITY and _read_pid(_DIR) == str(os.getpid())
        except OSError:
            return False


def acquire(mode, timeout):
    global _HAVE, _DEPTH, _DIR, _holder, _OWNER_PID, _OWNER_THREAD, _IDENTITY
    if mode not in ("skip", "wait") or isinstance(timeout, bool):
        return 3
    try:
        timeout = int(timeout)
        if timeout < 0:
            return 3
    except (TypeError, ValueError):
        return 3
    directory = lock_path()
    if directory is None:
        return 3
    with _process_lock():
        if owned():
            if directory != _DIR:
                _log("cannot change lock directory during a nested hold")
                return 3
            _DEPTH += 1
            return 0
    try:
        directory.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        _log("cannot create lock parent: %s" % error)
        return 3
    deadline = time.monotonic() + timeout
    _holder = ""
    while True:
        with _process_lock():
            try:
                directory.mkdir(mode=0o700)
            except FileExistsError:
                try:
                    _identity(directory)
                except OSError:
                    if not os.path.lexists(str(directory)):
                        continue
                    _log("invalid lock path: " + str(directory))
                    return 3
            except OSError as error:
                _log("cannot create lock: %s" % error)
                return 3
            else:
                try:
                    _write_pid(directory, os.getpid())
                    identity = _identity(directory)
                except OSError as error:
                    _log("cannot publish lock ownership; retain it for manual recovery: %s" % error)
                    return 3
                _HAVE, _DEPTH, _DIR = True, 1, directory
                _OWNER_PID, _OWNER_THREAD = os.getpid(), threading.get_ident()
                _IDENTITY = identity
                return 0
        _holder = _read_pid(directory)
        if mode == "skip":
            return 1
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _log("existing lock retained; no automatic stale reclamation: " + str(directory))
            return 2
        time.sleep(min(max(_poll(), 0.001), remaining))


def release():
    global _HAVE, _DEPTH
    with _process_lock():
        if not owned():
            return
        if _DEPTH > 1:
            _DEPTH -= 1
            return
        try:
            if {entry.name for entry in _DIR.iterdir()} != {"pid"}:
                _log("unexpected lock entries; retain it for manual recovery")
                return
            (_DIR / "pid").unlink()
            _DIR.rmdir()
        except OSError as error:
            _log("lock release failed; manual recovery required: %s" % error)
        finally:
            _HAVE, _DEPTH = False, 0


@contextlib.contextmanager
def hold(mode, timeout):
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
    """acquire + report + release. Yields True when the lock is held by this process/thread;
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
