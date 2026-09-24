#!/usr/bin/env python3
"""route_skill.py — deterministic, provider-neutral skill router. Python
port of route_skill.sh. Scans skills/*/SKILL.md frontmatter and keyword/
substring-matches a task description against each skill's `description`
field. No LLM call, no ranking model — intentionally basic; smarter matching
is a later concern, not this step's job.

If System_Config/skills-selected.json (written by specialize.py) exists,
the scan is restricted to only its "selected" skill dirs. Missing file =
scan all of skills/ (unrestricted).

route() returns the list of matched skill directories (stdout, in main());
--verbose diagnostic notes ("declares requires: ...", "mentions
unverifiable dependency ...") are a stderr side effect of route() itself,
mirroring the bash version's dual-channel output.

Usage: route_skill.py "<task description>"      (single-arg form)
       echo "<task description>" | route_skill.py   (stdin form)
       route_skill.py [--verbose] [--skills-dir <path>] "<task>"
       route_skill.py --self-test
"""
import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SKILLS_DIR = ROOT / "skills"
SKILLS_SELECTED_FILE = ROOT / "System_Config" / "skills-selected.json"

# Deliberately small, hardcoded list of tool/MCP names this router cannot
# confirm are available — not a general capability-detection system.
UNVERIFIABLE_TERMS = ("figma", "mcp")

_FRONTMATTER_DELIM = re.compile(r'^---\s*$')


def frontmatter_field(path, key):
    """Value of a "key: value" line inside the leading --- ... --- block.
    Only name/description/requires are ever read — Claude-specific fields
    like `disable-model-invocation` are not this router's concern."""
    key_re = re.compile(rf'^{re.escape(key)}:\s*(.*)$')
    depth = 0
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    for line in text.splitlines():
        if _FRONTMATTER_DELIM.match(line):
            depth += 1
            if depth >= 2:
                break
            continue
        if depth == 1:
            m = key_re.match(line)
            if m:
                return m.group(1).strip()
    return ""


def unverifiable_deps(desc_lc):
    return ",".join(term for term in UNVERIFIABLE_TERMS if term in desc_lc)


def normalize_requires(raw):
    """Strip an optional [ ] wrapper and surrounding whitespace/quotes
    around each comma-separated entry."""
    raw = raw.strip().strip("\"'").strip()
    if raw.startswith("["):
        raw = raw[1:]
    if raw.endswith("]"):
        raw = raw[:-1]
    raw = raw.strip().strip("\"'").strip()
    items = [item.strip().strip("\"'").strip() for item in raw.split(",")]
    return ",".join(item for item in items if item)


def selected_skill_names():
    """None if skills-selected.json is absent (no restriction). Proper JSON
    parsing — the bash version's sed/grep line-scrape of the same file was a
    fragile stand-in for having a JSON parser at all."""
    if not SKILLS_SELECTED_FILE.is_file():
        return None
    try:
        data = json.loads(SKILLS_SELECTED_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return list(data.get("selected", []))


def matches_keyword(task_lc, desc_lc):
    """True if any whitespace-delimited word (len > 3, skips noise like
    "the"/"and") in the task appears as a substring of the description."""
    if not desc_lc:
        return False
    return any(len(word) > 3 and word in desc_lc for word in task_lc.split())


def route(task, skills_dir=None, verbose=False):
    skills_dir = Path(skills_dir) if skills_dir else DEFAULT_SKILLS_DIR
    task_lc = task.lower()
    selected = selected_skill_names()

    matched = []
    for smd in sorted(skills_dir.glob("*/SKILL.md")):
        skill_dir = smd.parent
        if selected is not None and skill_dir.name not in selected:
            continue
        name = frontmatter_field(smd, "name") or skill_dir.name
        desc = frontmatter_field(smd, "description")
        desc_lc = desc.lower()

        if (desc_lc and name.lower() in task_lc) or matches_keyword(task_lc, desc_lc):
            matched.append(skill_dir)
            if verbose:
                requires = normalize_requires(frontmatter_field(smd, "requires"))
                if requires:
                    print(f"[route_skill] {skill_dir}: declares requires: {requires}", file=sys.stderr)
                else:
                    deps = unverifiable_deps(desc_lc)
                    if deps:
                        print(f"[route_skill] {skill_dir}: description mentions unverifiable dependency ({deps}) — cannot confirm tool/MCP availability", file=sys.stderr)
    return matched


def self_test():
    failures = []

    def check(label, cond, detail=""):
        if not cond:
            failures.append(f"{label}: {detail}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "alpha-skill").mkdir()
        (tmp / "alpha-skill" / "SKILL.md").write_text(
            '---\nname: alpha-skill\ndescription: "Handles Figma design export and MCP-based screenshot capture."\ndisable-model-invocation: false\n---\n# Alpha\n',
            encoding="utf-8",
        )
        (tmp / "beta-skill").mkdir()
        (tmp / "beta-skill" / "SKILL.md").write_text(
            '---\nname: beta-skill\ndescription: "Writes unit tests for a codebase."\n---\n# Beta\n',
            encoding="utf-8",
        )
        (tmp / "gamma-skill").mkdir()
        (tmp / "gamma-skill" / "SKILL.md").write_text(
            '---\nname: gamma-skill\ndescription: "Exports gamma design assets for review."\nrequires: figma-mcp\n---\n# Gamma\n',
            encoding="utf-8",
        )

        out = [p.name for p in route("figma export design", tmp)]
        check("alpha-skill matched by name substring", "alpha-skill" in out, out)

        out = [p.name for p in route("please write unit tests for this module", tmp)]
        check("beta-skill matched by keyword", "beta-skill" in out, out)
        check("alpha-skill not matched by unrelated task", "alpha-skill" not in out, out)

        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            route("figma export design", tmp, verbose=True)
        err = buf.getvalue()
        check("--verbose notes unverifiable figma dependency", "figma" in err, err)

        # gamma-skill declares requires: figma-mcp explicitly and its
        # description contains neither "figma" nor "mcp" — proves the
        # explicit requires: path is distinct from (and takes precedence
        # over) the substring-sniff fallback.
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            route("review gamma assets", tmp, verbose=True)
        err = buf.getvalue()
        check("--verbose reports explicit requires: for gamma-skill", "declares requires: figma-mcp" in err, err)
        check("gamma-skill uses explicit requires:, not the substring-sniff fallback", "mentions unverifiable dependency" not in err, err)

        # Selection-file-present case.
        global SKILLS_SELECTED_FILE
        real_selfile = SKILLS_SELECTED_FILE
        selfile = tmp / "skills-selected.json"
        selfile.write_text(json.dumps({"selected": ["beta-skill"]}, indent=2), encoding="utf-8")
        SKILLS_SELECTED_FILE = selfile
        out = [p.name for p in route("figma export design", tmp)]
        SKILLS_SELECTED_FILE = real_selfile
        check("skills-selected.json excludes deselected alpha-skill", "alpha-skill" not in out, out)

        nr = normalize_requires('"[a, b]"')
        check("normalize_requires strips quotes and brackets", nr == "a,b", nr)

    if failures:
        print("route_skill: self-test FAILED:", file=sys.stderr)
        for f in failures:
            print(f"  {f}", file=sys.stderr)
        return 1
    print("self-test OK")
    return 0


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("task", nargs="?", default=None)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--skills-dir", default=None)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("-h", "--help", action="store_true")
    args = parser.parse_args()

    if args.help:
        print(f"Usage: {Path(sys.argv[0]).name} [--verbose] [--skills-dir <path>] \"<task description>\"", file=sys.stderr)
        print(f"       echo \"<task>\" | {Path(sys.argv[0]).name} [--verbose]", file=sys.stderr)
        print(f"       {Path(sys.argv[0]).name} --self-test", file=sys.stderr)
        return 0

    if args.self_test:
        return self_test()

    task = args.task
    if not task and not sys.stdin.isatty():
        task = sys.stdin.read()
    if not task:
        print(f"Usage: {Path(sys.argv[0]).name} [--verbose] [--skills-dir <path>] \"<task description>\"", file=sys.stderr)
        return 1

    skills_dir = Path(args.skills_dir) if args.skills_dir else DEFAULT_SKILLS_DIR
    if not skills_dir.is_dir():
        print(f"route_skill.py: no such skills dir: {skills_dir}", file=sys.stderr)
        return 1

    for skill_dir in route(task, skills_dir, verbose=args.verbose):
        print(skill_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
