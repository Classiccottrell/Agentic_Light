#!/usr/bin/env python3
"""context.py — thin dispatcher: packet|validate|catalog|curate. Python port
of context.sh. context_validate.py/context_catalog.py/context_curate.py are
already Python (left untouched, invoked as separate processes exactly as
context.sh already did via `exec python3 ...`); context_packet.py is this
script's own sibling port. All four subcommands are dispatched uniformly via
subprocess (not imported), matching context.sh's own `exec`-to-a-separate-
script design — this file has no logic of its own beyond argument shuffling.
Usage: context.py [--root ROOT] packet|validate|catalog|curate ...
"""
import argparse
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--root", default=None)
    parser.add_argument("command", nargs="?", default="")
    parser.add_argument("rest", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    root = Path(args.root) if args.root else ROOT

    if args.command == "packet":
        argv = [sys.executable, str(SCRIPT_DIR / "context_packet.py"), "--root", str(root), *args.rest]
    elif args.command == "validate":
        target = args.rest[0] if args.rest else str(root / "brain" / "records")
        rest = args.rest[1:] if args.rest else []
        argv = [sys.executable, str(SCRIPT_DIR / "context_validate.py"), "validate", target, "--root", str(root), *rest]
    elif args.command == "catalog":
        argv = [sys.executable, str(SCRIPT_DIR / "context_catalog.py"), "build", "--root", str(root),
                "--out-dir", str(root / "brain" / "index"), *args.rest]
    elif args.command == "curate":
        file_arg = args.rest[0] if args.rest else ""
        rest = args.rest[1:] if args.rest else []
        argv = [sys.executable, str(SCRIPT_DIR / "context_curate.py"), file_arg, "--root", str(root), *rest]
    else:
        print("usage: context.py [--root ROOT] packet|validate|catalog|curate", file=sys.stderr)
        return 2

    proc = subprocess.run(argv)
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
