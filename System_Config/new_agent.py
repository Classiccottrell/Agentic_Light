#!/usr/bin/env python3
"""new_agent.py — scaffold a new agents/<name>.md from the roster pattern.
Python port of new_agent.sh.

Usage: python3 System_Config/new_agent.py <name> "<scope one-liner>" [--write]
       python3 System_Config/new_agent.py --self-test

Deliberately independent of config.py (matches new_agent.sh, which sourced
config.sh only for the WORKSPACE constant — recomputed directly here
instead, same reasoning route_skill.py/log_session.py already document for
their own ROOT).

No argparse (a deliberate blueprint §2 deviation — that convention calls
for argparse on any script with a --flag): a `<scope one-liner>` is
free-form prose and routinely starts with "-" (e.g. "- Reviews PRs" or
"Not a general rewrite"); argparse would parse a leading-hyphen positional
as an unrecognized option and reject it outright, which no caller of this
script's documented usage (`<name> "<scope>" [--write]`) would expect.
Positional argv slicing (`argv[0]`, `argv[1]`, scan `argv[2:]` for the
literal token "--write") reproduces bash's own `$1`/`$2`/`"${@:3}"`
contract exactly, including that --write is only recognized from position
3 onward (bash's own scan does not look at position 1 or 2 either).
"""
import os
import re
import sys
from pathlib import Path

ROOT = Path(os.path.abspath(__file__)).parent.parent

SLUG_RE = re.compile(r'[a-z][a-z0-9]*(-[a-z0-9]+)*')

USAGE = 'usage: new_agent.py <name> "<scope one-liner>" [--write]'


def build_agent_body(name, scope):
    """Byte-identical to new_agent.sh's AGENT_BODY: bash's
    `read -r -d '' AGENT_BODY <<EOF` strips the heredoc's final trailing
    newline, and `printf '%s'` adds nothing back — confirmed by diffing
    this port's --write output against the .sh original's. The LAST line
    below deliberately has no trailing "\\n" to reproduce that; every
    other line does."""
    description = f"{scope}. Authority limited to its scope."
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        "tools: Read, Glob, Grep, Edit, Write\n"
        "model: inherit\n"
        "---\n"
        "\n"
        f"You are the {name} agent for this multi-agent workspace.\n"
        "\n"
        f"Role: {scope}. Authority limited to its scope.\n"
        "\n"
        "Rules:\n"
        "- Read existing files to deduce stack and conventions before acting. Do not ask.\n"
        "- Stay strictly within your scope; hand off anything outside it back to the orchestrator.\n"
        "- Never overwrite or delete files outside your assigned scope.\n"
        "\n"
        "Response style (Caveman Protocol): no filler, no preamble/postamble, no narration of tool use. Omit markdown explanation of code unless asked.\n"
        "\n"
        "Your final message is your deliverable to the orchestrator — return the diff/result, not a chat reply."
    )


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    name = argv[0] if len(argv) > 0 else ""
    scope = argv[1] if len(argv) > 1 else ""
    write = any(a == "--write" for a in argv[2:])

    if not name or not scope:
        print(USAGE, file=sys.stderr)
        return 1

    if not SLUG_RE.fullmatch(name):
        print(f"new_agent.py: name must be a lowercase-hyphen slug (e.g. 'data-migrator'): {name}", file=sys.stderr)
        return 1

    agent_md = ROOT / "agents" / f"{name}.md"

    if agent_md.exists():
        print(f"new_agent.py: refusing to overwrite existing file: {agent_md}", file=sys.stderr)
        return 1

    agent_body = build_agent_body(name, scope)

    if not write:
        print("DRY RUN — would create:")
        print(f"  {agent_md}")
        print()
        print(f"--- {agent_md} ---")
        print(agent_body)
        print()
        print("Run again with --write to create.")
        return 0

    agent_md.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive create ("x"), not a plain overwrite — a strictly safer
    # narrowing of bash's plain `>` redirect: the existence check above
    # already refuses a pre-existing file, this just closes the narrow
    # time-of-check-to-time-of-use gap rather than silently truncating if
    # something raced in between. No atomic mkstemp+replace here — that
    # convention is scoped (per this port's task) to specialize.py's
    # config outputs, not this scaffold file.
    with open(agent_md, "x", encoding="utf-8", newline="\n") as f:
        f.write(agent_body)

    print("Created:")
    print(f"  {agent_md}")
    print(f"Register {name} in agents/README.md's roster table — not automated.")
    return 0


def self_test():
    import shutil
    import subprocess
    import tempfile

    failures = []

    def check(label, cond, detail=""):
        if not cond:
            failures.append(f"{label}: {detail}")
        else:
            print(f"new_agent: self-test fixture ok: {label}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "System_Config").mkdir()
        (tmp / "agents").mkdir()
        shutil.copy(Path(__file__), tmp / "System_Config" / "new_agent.py")

        def run(*args):
            env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTIC_LIGHT_")}
            env["PYTHONUTF8"] = "1"
            return subprocess.run(
                [sys.executable, str(tmp / "System_Config" / "new_agent.py"), *args],
                capture_output=True, encoding="utf-8", cwd=str(tmp),
                stdin=subprocess.DEVNULL, timeout=15, env=env,
            )

        # Fixture 1: no args at all -> usage error, rc 1.
        proc = run()
        check("no args: rc == 1", proc.returncode == 1, proc.returncode)
        check("no args: usage message", "usage:" in proc.stderr, proc.stderr)

        # Fixture 2: missing scope -> usage error, rc 1.
        proc = run("onlyname")
        check("missing scope: rc == 1", proc.returncode == 1, proc.returncode)

        # Fixture 3: invalid slug -> rc 1, explains the slug rule.
        proc = run("Data_Migrator", "bad name")
        check("invalid slug: rc == 1", proc.returncode == 1, proc.returncode)
        check("invalid slug: message", "lowercase-hyphen slug" in proc.stderr, proc.stderr)

        # Fixture 4: dry run — no file created, preview shown, rc 0.
        proc = run("data-migrator", "Moves data between systems")
        check("dry-run: rc == 0", proc.returncode == 0, proc.returncode)
        check("dry-run: says DRY RUN", "DRY RUN" in proc.stdout, proc.stdout)
        agent_md = tmp / "agents" / "data-migrator.md"
        check("dry-run: creates no file", not agent_md.exists())

        # Fixture 5: --write — real scaffold; matches agents/*.md
        # frontmatter shape (name/description/tools/model), no trailing
        # newline (byte-parity with the .sh original's heredoc strip).
        proc = run("data-migrator", "Moves data between systems", "--write")
        check("write: rc == 0", proc.returncode == 0, proc.returncode)
        check("write: file created", agent_md.is_file())
        if agent_md.is_file():
            data = agent_md.read_bytes()
            text = data.decode("utf-8")
            check("write: frontmatter opens with ---", text.startswith("---\n"), text[:10])
            check("write: name field", "name: data-migrator" in text, text)
            check("write: description field", "description: Moves data between systems. Authority limited to its scope." in text, text)
            check("write: tools field", "tools: Read, Glob, Grep, Edit, Write" in text, text)
            check("write: model field", "model: inherit" in text, text)
            check("write: no trailing newline", not data.endswith(b"\n"), data[-10:])

        # Fixture 6: refuses to overwrite an existing file — true in BOTH
        # dry-run and --write mode (the existence check runs before either
        # branch), and the file's content is untouched afterward.
        proc = run("data-migrator", "a different scope now")
        check("refuse existing (dry-run): rc == 1", proc.returncode == 1, proc.returncode)
        check("refuse existing (dry-run): message", "refusing to overwrite" in proc.stderr, proc.stderr)
        proc = run("data-migrator", "a different scope now", "--write")
        check("refuse existing (write): rc == 1", proc.returncode == 1, proc.returncode)
        check("refuse existing: original content intact", "Moves data between systems" in agent_md.read_text(encoding="utf-8"))

        # Fixture 7: --write scans for the literal token anywhere from
        # position 3 onward (bash's `for arg in "${@:3}"`) — a stray extra
        # positional ahead of it is tolerated, not an error.
        proc = run("other-agent", "Does other things", "ignored-extra", "--write")
        check("--write after a stray positional: rc == 0", proc.returncode == 0, proc.returncode)
        check("--write after a stray positional: file created", (tmp / "agents" / "other-agent.md").is_file())

    if failures:
        print("new_agent: self-test FAILED:", file=sys.stderr)
        for f in failures:
            print(f"  {f}", file=sys.stderr)
        return 1
    print("self-test OK")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        sys.exit(self_test())
    sys.exit(main())
