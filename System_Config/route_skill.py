#!/usr/bin/env python3
"""route_skill.py — deterministic, provider-neutral skill router. Python
port of route_skill.sh. Scans skills/*/SKILL.md frontmatter and ranks
each skill against a task description by token relevance: task tokens that
hit a skill's own name (frontmatter `name` or dir name) weigh most;
description hits are weighted by inverse document frequency across the
scanned skill set, so a word every Figma skill shares counts for little and
a rare domain word ("wcag", "dbt") counts for a lot. Results are sorted by
score descending, ties by dir name — callers capping to the first N (run.py's
AGENTIC_LIGHT_SKILL_MATCH_LIMIT) keep the most relevant N. Deterministic,
stdlib-only, no LLM call.

If System_Config/skills-selected.json (written by specialize.py) exists,
the scan is restricted to only its "selected" skill dirs. Missing file =
scan all of skills/ (unrestricted).

route() returns the ranked list of matched skill directories (stdout, in
main()); --verbose diagnostic notes (each match's score, "declares
requires: ...", "mentions unverifiable dependency ...") are a stderr side
effect of route() itself,
mirroring the bash version's dual-channel output.

Usage: route_skill.py "<task description>"      (single-arg form)
       echo "<task description>" | route_skill.py   (stdin form)
       route_skill.py [--verbose] [--skills-dir <path>] "<task>"
       route_skill.py --self-test
"""
import argparse
import json
import math
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


# Generic words with no domain signal: English function words plus the
# task verbs/nouns nearly every task sentence and skill description uses.
# Matched AFTER stemming, so "writes"/"creates" drop too.
STOPWORDS = frozenset("""
    an and any are as at be by can do does for from get how if in into is it
    me my need new no not of on or our please should so that the these this to
    want we what when with you your
    add build change create fix make update use write
    page file skill user
""".split())

NAME_MULT = 3.0        # name-token hit = NAME_MULT x that token's IDF
FULL_NAME_BONUS = 5.0  # whole skill name appears verbatim in the task
MIN_SCORE = 1.0        # below this a match is noise, not routed ...
MIN_SCORE_SET = 4      # ... but only once this many skills are scanned: a
                       # token shared by all n skills always scores ln 2
                       # (< MIN_SCORE), so a tiny skills-selected.json fork
                       # (1-3 skills) would otherwise drop real matches

_TOKEN_SPLIT = re.compile(r'[^a-z0-9]+')


def _stem(tok):
    """Light suffix folding only — plurals (models->model,
    dependencies->dependency) and -ing (debugging->debug, auditing->audit);
    guarded so short tokens like "css"/"js"/"ui"/"string" survive untouched."""
    if tok.endswith("ing") and len(tok) - 3 >= 4:
        tok = tok[:-3]
        if tok[-1] == tok[-2] and tok[-1] not in "aeiouls":
            tok = tok[:-1]
        return tok
    if len(tok) > 4 and tok.endswith("ies"):
        return tok[:-3] + "y"
    if len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss"):
        return tok[:-1]
    return tok


def tokens(text):
    """Lowercase, split on non-alphanumerics, stem, drop stopwords and
    1-char tokens. Returns a set — repeats don't add score."""
    out = set()
    for raw in _TOKEN_SPLIT.split(text.lower()):
        if len(raw) < 2:
            continue
        tok = _stem(raw)
        if tok not in STOPWORDS:
            out.add(tok)
    return out


def route_scored(task, skills_dir=None, verbose=False):
    """[(skill_dir, score)] for skills scoring >= MIN_SCORE, sorted by score
    descending, ties by dir name. Two passes: read every scanned skill's
    frontmatter, then score against document frequencies computed over that
    (post-skills-selected.json) set."""
    skills_dir = Path(skills_dir) if skills_dir else DEFAULT_SKILLS_DIR
    task_lc = task.lower()
    task_toks = tokens(task)
    selected = selected_skill_names()

    skills = []
    for smd in sorted(skills_dir.glob("*/SKILL.md"), key=str):
        skill_dir = smd.parent
        if selected is not None and skill_dir.name not in selected:
            continue
        name = frontmatter_field(smd, "name") or skill_dir.name
        desc = frontmatter_field(smd, "description")
        if not desc:
            continue
        name_toks = tokens(name) | tokens(skill_dir.name)
        desc_toks = tokens(desc)
        skills.append((smd, skill_dir, name.lower(), desc.lower(), name_toks, name_toks | desc_toks))

    n = len(skills)
    df = {}
    for *_, all_toks in skills:
        for tok in all_toks:
            df[tok] = df.get(tok, 0) + 1

    def idf(tok):
        return math.log(1 + n / df[tok])

    min_score = MIN_SCORE if n >= MIN_SCORE_SET else 1e-9
    scored = []
    for smd, skill_dir, name_lc, desc_lc, name_toks, all_toks in skills:
        score = 0.0
        for tok in task_toks & all_toks:
            score += idf(tok) * (NAME_MULT if tok in name_toks else 1.0)
        if name_lc in task_lc or skill_dir.name.lower() in task_lc:
            score += FULL_NAME_BONUS
        if score >= min_score:
            scored.append((smd, skill_dir, desc_lc, score))

    scored.sort(key=lambda r: (-r[3], r[1].name))
    if verbose:
        for smd, skill_dir, desc_lc, score in scored:
            print(f"[route_skill] {skill_dir}: score {score:.2f}", file=sys.stderr)
            requires = normalize_requires(frontmatter_field(smd, "requires"))
            if requires:
                print(f"[route_skill] {skill_dir}: declares requires: {requires}", file=sys.stderr)
            else:
                deps = unverifiable_deps(desc_lc)
                if deps:
                    print(f"[route_skill] {skill_dir}: description mentions unverifiable dependency ({deps}) — cannot confirm tool/MCP availability", file=sys.stderr)
    return [(skill_dir, score) for _, skill_dir, _, score in scored]


def route(task, skills_dir=None, verbose=False):
    """Matched skill dirs, most relevant first (see route_scored)."""
    return [skill_dir for skill_dir, _ in route_scored(task, skills_dir, verbose)]


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
        check("skills-selected.json excludes deselected alpha-skill", "alpha-skill" not in out, out)
        # One-skill fork: a single shared description word must still route
        # (IDF of a token in every scanned skill is only ln 2 < MIN_SCORE).
        out = [p.name for p in route("write tests", tmp)]
        SKILLS_SELECTED_FILE = real_selfile
        check("one-skill selection still routes a one-keyword match", out == ["beta-skill"], out)

        nr = normalize_requires('"[a, b]"')
        check("normalize_requires strips quotes and brackets", nr == "a,b", nr)

    # Ranking fixtures — separate dir so these "figma-ish" skills can't
    # leak into the gamma-skill stderr assertions above. Names chosen so
    # alphabetical order gives the WRONG answer: the domain skills sort last.
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        generic = "Write and build design files, create pages and models, update text and layout for the user."
        fixtures = {
            "aa-design-one": generic,
            "ab-design-two": generic + " Audit components.",
            "ac-design-three": generic + " Accessibility notes.",
            "ad-design-four": generic,
            "zx-a11y": "Audit any page for WCAG 2.2 AA accessibility: contrast, alt text, focus.",
            "zz-warehouse": "Creates and optimizes dbt pipelines for the warehouse.",
        }
        for name, desc in fixtures.items():
            (tmp / name).mkdir()
            (tmp / name / "SKILL.md").write_text(
                f'---\nname: {name}\ndescription: "{desc}"\n---\n# {name}\n', encoding="utf-8")

        out = [p.name for p in route("audit this page for WCAG accessibility", tmp)]
        check("domain skill ranks first over shared-generic-word skills", out[:1] == ["zx-a11y"], out)

        out = [p.name for p in route("fix the contrast and alt text on the signup form", tmp)]
        check("generic task words don't route to design skills", out == ["zx-a11y"], out)

        out = [p.name for p in route("write a dbt model", tmp)]
        check("3-letter domain token 'dbt' matches", out[:1] == ["zz-warehouse"], out)

        scored = route_scored("audit accessibility", tmp)
        scores = [s for _, s in scored]
        check("results sorted by score descending", scores == sorted(scores, reverse=True), scored)
        check("ranking is by relevance, not name", [p.name for p, _ in scored][:1] == ["zx-a11y"], scored)

        check("stem folds plurals and -ing", tokens("models dependencies debugging css") == {"model", "dependency", "debug", "css"}, tokens("models dependencies debugging css"))

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
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
