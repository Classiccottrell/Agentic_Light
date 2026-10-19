"""Private context hooks shared by Agentic Light's daily, Monday, and Friday jobs."""
import os
import subprocess
import sys
from pathlib import Path

import config


def _run(args, log):
    result = subprocess.run(args, cwd=str(config.WORKSPACE), capture_output=True,
                            encoding="utf-8", env={**os.environ, "PYTHONUTF8": "1"})
    if result.returncode:
        log("WARN: " + Path(args[1]).name + " failed; continuing")
    return result.returncode == 0


def collect(day, log):
    source_config = config.WORKSPACE / "System_Config" / "context-sources.local.json"
    if not source_config.is_file() or source_config.is_symlink():
        return False
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
