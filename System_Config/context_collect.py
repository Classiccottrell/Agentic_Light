#!/usr/bin/env python3
"""Collect explicit context sources with one process-owned shared brain lock."""
import argparse
from datetime import date
import os
from pathlib import Path
import sys

import brain_lock
import context_discover
import context_intake
import context_weekly

ROOT = Path(__file__).resolve().parent.parent


def main(argv=None, root=None, vault=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("day", nargs="?", default=date.today().isoformat())
    args = parser.parse_args(argv)
    try:
        day = date.fromisoformat(args.day)
    except ValueError:
        print("context collect: invalid date", file=sys.stderr)
        return 1
    root = Path(root) if root is not None else ROOT
    vault = Path(vault) if vault is not None else Path(os.environ.get("CONTEXT_VAULT", str(root / "brain")))
    config = Path(os.environ.get("CONTEXT_SOURCES_CONFIG", str(root / "System_Config/context-sources.local.json")))
    manifest = Path(os.environ.get("CONTEXT_MANIFEST", str(root / "System_Config/context-manifest.local.json")))
    if not config.is_absolute() or not manifest.is_absolute():
        print("context collect: private config and manifest must be absolute", file=sys.stderr)
        return 1
    if not config.is_file() or config.is_symlink():
        print("context collect: private config missing", file=sys.stderr)
        return 1
    with brain_lock.guard("context_collect", "wait", brain_lock.short_wait_seconds()) as held:
        if not held:
            return 75
        rc = context_discover.main(["--config", str(config), "--out", str(manifest), "--date", args.day])
        if rc:
            return rc
        rc = context_intake.main(["--vault", str(vault), "--manifest", str(manifest), "--date", args.day])
        if rc:
            return rc
        year, week, _unused = day.isocalendar()
        tag = "%d-W%02d" % (year, week)
        note = vault / "weekly_logs" / str(year) / (tag + ".md")
        weekly_args = ["--vault", str(vault), "--week", tag]
        if note.is_file() and not note.is_symlink():
            weekly_args.extend(["--note", str(note)])
        return context_weekly.main(weekly_args)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
