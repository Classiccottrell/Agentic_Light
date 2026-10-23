"""Private context hooks shared by Agentic Light's daily, Monday, and Friday jobs."""
import os
import contextlib
import io
import subprocess
import sys
from pathlib import Path

import config
import brain_lock


def _composed(call, log, name):
    """Match subprocess failure isolation without passing lock authority to children."""
    output = io.StringIO()
    try:
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            try:
                rc = call()
            except SystemExit as error:
                rc = error.code if isinstance(error.code, int) else (0 if error.code is None else 1)
    except Exception:
        rc = 1
    if rc:
        log("WARN: " + name + " failed; continuing")
    return not rc


def _run(args, log):
    if brain_lock.owned():
        # Fixed registry only: never import a module chosen by external data.
        target = Path(args[1])
        known = {"context_auto_summary.py", "context_mempalace.py", "context_weekly.py"}
        if args[0] != sys.executable or target.parent != config.WORKSPACE / "System_Config" or target.name not in known:
            log("WARN: unknown nested context command refused")
            return False
        def call():
            if target.name == "context_auto_summary.py":
                import context_auto_summary
                return context_auto_summary.main(args[2:])
            if target.name == "context_mempalace.py":
                import context_mempalace
                return context_mempalace.main(args[2:])
            import context_weekly
            return context_weekly.main(args[2:])
        return _composed(call, log, target.name)
    result = subprocess.run(args, cwd=str(config.WORKSPACE), capture_output=True,
                            encoding="utf-8", env={**os.environ, "PYTHONUTF8": "1"})
    if result.returncode:
        log("WARN: " + Path(args[1]).name + " failed; continuing")
    return result.returncode == 0


def collect(day, log):
    source_config = config.WORKSPACE / "System_Config" / "context-sources.local.json"
    if not source_config.is_file() or source_config.is_symlink():
        return False
    if brain_lock.owned():
        import context_collect
        return _composed(lambda: context_collect.main([day], root=config.WORKSPACE, vault=config.BRAIN), log, "context_collect.py")
    return _run(["/bin/bash", str(config.WORKSPACE / "System_Config" / "context_collect.sh"), day], log)


def link_week(week, note, log):
    return _run([sys.executable, str(config.WORKSPACE / "System_Config" / "context_weekly.py"),
                 "--vault", str(config.BRAIN), "--week", week, "--note", str(note)], log)


def friday(day, week, note, log):
    collect(day, log)
    manifest = config.WORKSPACE / "System_Config" / "context-manifest.local.json"
    binary = os.environ.get("CONTEXT_MEMPALACE_BIN", "")
    if binary and manifest.is_file() and not manifest.is_symlink():
        _run([sys.executable, str(config.WORKSPACE / "System_Config" / "context_mempalace.py"),
              "--vault", str(config.BRAIN), "--manifest", str(manifest), "--bin", binary], log)
    _run([sys.executable, str(config.WORKSPACE / "System_Config" / "context_auto_summary.py"),
          "--vault", str(config.BRAIN), "--week", week], log)
    link_week(week, note, log)
