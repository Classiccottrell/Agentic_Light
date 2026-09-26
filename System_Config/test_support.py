#!/usr/bin/env python3
"""test_support.py — tiny shared helper for the test_*.py suites (not a
test itself, no --self-test). Python port of the equivalent ad hoc bash
idiom (`rm -rf`, which never had this problem on POSIX)."""
import os
import shutil
import stat
import subprocess
import sys


def rmtree_force(path):
    """shutil.rmtree, but recovers from read-only files/dirs. A real
    `git init`/`git commit` fixture leaves packed objects read-only on
    Windows (and occasionally on other platforms too); plain
    shutil.rmtree(path, ignore_errors=True) silently leaves those behind
    instead of raising. Every test fixture that creates a real git repo
    should clean it up with this, not a bare rmtree."""
    def onerror(func, target_path, exc_info):
        os.chmod(target_path, stat.S_IWRITE)
        func(target_path)
    shutil.rmtree(path, onerror=onerror)


def write_file(path, text):
    """Create parent dirs and write UTF-8 text with LF newlines (the
    `cat > file <<'EOF'` idiom the bash fixtures used)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def run_py(script, *args, env=None):
    """Run a Python script under this same interpreter, capturing UTF-8
    text output. Returns the CompletedProcess; callers check returncode."""
    full_env = None
    if env:
        full_env = {**os.environ, **env}
    return subprocess.run([sys.executable, str(script), *[str(a) for a in args]],
                          capture_output=True, text=True, encoding="utf-8", env=full_env)
