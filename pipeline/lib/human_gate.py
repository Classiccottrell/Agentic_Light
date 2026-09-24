#!/usr/bin/env python3
"""human_gate.py — render a summary/diff and block on interactive [y/N].
Mirrors bootstrap's --uninstall TTY-check pattern: never auto-approves.
Usage: human_gate.py "<summary text>"   (falls back to stdin if no arg)
Exit codes: 0 approved | 1 declined | 2 pending (non-interactive)

decide() holds the core y/N decision logic behind an injectable is_tty flag
and an injectable line-reader, so it's callable directly from a test without
a real pty (blueprint §2) — main() wires it to the real terminal.
"""
import argparse
import sys


def decide(read_line):
    """Interactive-only decision (caller has already confirmed is_tty). Never
    raises: read_line() raising EOFError is treated as an empty reply
    (declined), matching bash's `read -r || REPLY=""`."""
    print("Approve and create PR? [y/N]: ", end="")
    sys.stdout.flush()
    try:
        reply = read_line()
    except EOFError:
        reply = ""
    if reply[:1] in ("y", "Y"):
        print("-> Approved.")
        return 0
    print("-> Declined. No PR will be created.")
    return 1


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("summary", nargs="?", default="")
    args, _ = parser.parse_known_args()

    is_tty = sys.stdin.isatty()
    summary = args.summary
    if not summary and not is_tty:
        summary = sys.stdin.read()

    print("=" * 50)
    print(" Human Gate — review before PR creation")
    print("=" * 50)
    print()
    print(summary or "<no summary provided>")
    print()
    print("=" * 50)

    if not is_tty:
        print("Non-interactive session — cannot prompt for approval. Pending human review.")
        return 2

    return decide(input)


if __name__ == "__main__":
    sys.exit(main())
