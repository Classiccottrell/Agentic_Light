#!/usr/bin/env python3
"""test_support.py — tiny shared helper for the test_*.py suites (not a
test itself, no --self-test). Python port of the equivalent ad hoc bash
idiom (`rm -rf`, which never had this problem on POSIX)."""
import os
import shutil
import stat


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
