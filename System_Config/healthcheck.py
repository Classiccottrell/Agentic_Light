#!/usr/bin/env python3
"""healthcheck.py — Agentic Light health check → microsite/status.{json,js}.
Python port of healthcheck.sh.

Probes directory layout, agent/skill roster completeness, brain
scaffolding, pipeline log recency, and doc currency. On a stale microsite
(Layer F), self-heals by invoking gen_site.py/gen_preset_pages.py/
gen_governance.py for real so the microsite never drifts from the roster.

Deliberately does not raise on a failing probe — a failing probe is a
result to REPORT, not a reason to abort (mirrors healthcheck.sh's
`set -uo pipefail` without `-e`). Always returns 0. No GitHub Pages
publish step — local files only.

  Manual run:  python3 System_Config/healthcheck.py
  View:        open microsite/health.html

Self-heal import deviation (intentional, per the porting blueprint's §7):
healthcheck.sh subprocessed `python3 gen_site.py`/`gen_preset_pages.py`/
`gen_governance.py` because bash has no import mechanism. This port calls
their main() functions in-process instead — 6 subprocess round-trips
(3 --check + 3 write, in the common self-heal path) collapse to 6 plain
function calls. Those 3 generator modules read flags from module-global
sys.argv directly and call sys.exit() on their already-current/--check/
--dry-run paths (raising SystemExit) but fall through with an implicit
`return None` after an actual successful write — _call_gen_main() below
normalizes both shapes to an (exit_code, captured_stdout) pair, the same
contract a `subprocess.run(..., capture_output=True)` call would have
produced.

Self-referential glob note (per §7): every place this layer globs the
project's own script surface for staleness/secret-scanning now globs
System_Config/*.py instead of *.sh — this script IS one of those *.py
files now, and the old *.sh glob would silently stop covering the very
scripts this layer means to watch. Tier 4 scripts (monday_init.sh,
friday_process.sh, daily_ingest.sh) are still bash and are referenced by
exact name where doc_check needs them, not through this glob.
"""
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

import config
import gen_governance
import gen_preset_pages
import gen_site

WORKSPACE = config.WORKSPACE
BRAIN = config.BRAIN
SYSCFG = WORKSPACE / "System_Config"
AGENTS = WORKSPACE / "agents"
SKILLS = WORKSPACE / "skills"
MICROSITE = WORKSPACE / "microsite"
PIPELINE = WORKSPACE / "pipeline"
OUT_JSON = MICROSITE / "status.json"
OUT_JS = MICROSITE / "status.js"
CLAUDE_MD = WORKSPACE / "CLAUDE.md"

REQUIRED_DIRS = [
    ".obsidian",
    "System_Config",
    "System_Config/logs",
    "agents",
    "skills",
    "microsite",
    "brain",
    "brain/raw",
    "brain/wiki",
    "brain/weekly_logs",
    "pipeline",
    "pipeline/lib",
    "pipeline/logs",
    "Projects/_TEMPLATE",
    "Projects/_TEMPLATE/active",
    "Projects/_TEMPLATE/archive",
]

_FRONTMATTER_DELIM = re.compile(r'^---\s*$')
_NAME_FIELD = re.compile(r'^name:\s*\S')
_DESC_FIELD = re.compile(r'^description:\s*\S')
_EXT_RE = re.compile(r'\.(sh|py|json)$')


class Report:
    """Accumulates check results + renders the same [STATUS] name — detail
    lines healthcheck.sh printed, plus the JSON `checks` array. Mirrors
    healthcheck.sh's TOTAL/PASS_N/WARN_N/FAIL_N/OVERALL/JSON_ITEMS globals
    as instance state instead — same behavior, no module-level mutation."""

    def __init__(self):
        self.total = 0
        self.pass_n = 0
        self.warn_n = 0
        self.fail_n = 0
        self.overall = "PASS"
        self.section = ""
        self.sec_pass = self.sec_warn = self.sec_fail = 0
        self.items = []

    def begin_section(self, name):
        self.section = name
        self.sec_pass = self.sec_warn = self.sec_fail = 0
        print(f"== {name} ==")

    def end_section(self):
        print(f"-- {self.section}: {self.sec_pass} pass / {self.sec_warn} warn / {self.sec_fail} fail --")
        print()

    def check(self, status, name, detail):
        if status not in ("PASS", "WARN", "FAIL"):
            status = "WARN"
        self.total += 1
        if status == "PASS":
            self.pass_n += 1
            self.sec_pass += 1
        elif status == "WARN":
            self.warn_n += 1
            self.sec_warn += 1
            if self.overall == "PASS":
                self.overall = "WARN"
        else:
            self.fail_n += 1
            self.sec_fail += 1
            self.overall = "FAIL"
        self.items.append({"layer": self.section, "status": status, "name": name, "detail": detail})
        print(f"  [{status}] {name} — {detail}")
        return status


def frontmatter_ok(path):
    """True iff the first frontmatter block (between the first two `---`
    lines) has both a non-blank `name:` and `description:` field. Direct
    transliteration of healthcheck.sh's awk one-liner: a file with only ONE
    `---` line is treated as frontmatter-until-EOF (matches awk's `n==1`
    state never advancing to `n>=2`), not an error."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    delim_count = 0
    has_name = has_desc = False
    for line in lines:
        if _FRONTMATTER_DELIM.match(line):
            delim_count += 1
            if delim_count >= 2:
                break
            continue
        if delim_count == 1:
            if _NAME_FIELD.match(line):
                has_name = True
            if _DESC_FIELD.match(line):
                has_desc = True
    return has_name and has_desc


def doc_check(report, name, readme, documented):
    """WARN if any path in `documented` changed AFTER `readme` was last
    touched; PASS otherwise. WARN (not FAIL) if `readme` is missing/empty."""
    if not readme.is_file() or readme.stat().st_size == 0:
        report.check("WARN", f"Doc: {name}", "README missing or empty")
        return
    rmt = readme.stat().st_mtime
    srct = 0.0
    for p in documented:
        if p.exists():
            t = p.stat().st_mtime
            if t > srct:
                srct = t
    if srct > rmt:
        age = int((srct - rmt) / 3600)
        report.check("WARN", f"Doc: {name}", f"stale — documented file changed {age}h after the README; review & update")
    else:
        report.check("PASS", f"Doc: {name}", "up to date")


def _call_gen_main(module, args):
    """Invoke a gen_*.py module's main() in-process — see this module's
    docstring for why both the SystemExit-raising and the plain-return
    shapes of that function need normalizing here. Returns
    (exit_code, captured_stdout)."""
    old_argv = sys.argv
    sys.argv = [str(getattr(module, "__file__", module.__name__))] + list(args)
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            module.main()
        rc = 0
    except SystemExit as exc:
        if exc.code is None:
            rc = 0
        elif isinstance(exc.code, int):
            rc = exc.code
        else:
            rc = 1
    finally:
        sys.argv = old_argv
    return rc, buf.getvalue()


def _claude_md_system_config_tokens(text):
    """Tokenize the fenced tree's `System_Config/` block (from its own
    `├── System_Config/` header up to, not including, the next top-level
    `├── ` entry), keep only .sh/.py/.json-suffixed tokens. Direct
    transliteration of healthcheck.sh's `awk ... | tr -cs ... | grep -E`
    pipeline."""
    collecting = False
    collected = []
    for line in text.splitlines():
        if re.match(r'^├── System_Config/', line):
            collecting = True
            continue
        if collecting and re.match(r'^├── [A-Za-z]', line):
            break
        if collecting:
            collected.append(line)
    tokens = re.findall(r'[A-Za-z0-9._-]+', "\n".join(collected))
    return sorted(set(t for t in tokens if _EXT_RE.search(t)))


def _disk_system_config_tokens():
    """Every .sh/.py/.json filename directly under System_Config/, minus
    agent-roster.json (a runtime-written, per-fork artifact never listed
    in the map on purpose — matches healthcheck.sh's `grep -vx`)."""
    names = [
        p.name for p in SYSCFG.iterdir()
        if p.is_file() and _EXT_RE.search(p.name) and p.name != "agent-roster.json"
    ]
    return sorted(set(names))


def _git_check_ignore(git_bin, path):
    """True iff `path` is covered by .gitignore. If git isn't resolvable at
    all, treat as "not ignored" — the same result bash's `command -v git`
    guard implicitly produced when git was missing (check-ignore never ran,
    so the WORKSPACE-relative `if` was always false)."""
    if git_bin is None:
        return False
    try:
        return subprocess.run(
            [git_bin, "-C", str(WORKSPACE), "check-ignore", "-q", str(path)],
            encoding="utf-8",
        ).returncode == 0
    except OSError:
        return False


def _atomic_write_text(path, text):
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp_name, str(path))
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def run(report):
    # ═══════════════════════════════════════════════════════════════════
    # LAYER A — Directory layout
    # ═══════════════════════════════════════════════════════════════════
    report.begin_section("Directory Layout")
    for d in REQUIRED_DIRS:
        if (WORKSPACE / d).is_dir():
            report.check("PASS", f"Dir: {d}/", "present")
        else:
            report.check("FAIL", f"Dir: {d}/", "MISSING")
    report.end_section()

    # ═══════════════════════════════════════════════════════════════════
    # LAYER B — Roster completeness (agents + skills frontmatter)
    # ═══════════════════════════════════════════════════════════════════
    report.begin_section("Roster Completeness")
    for f in sorted(AGENTS.glob("*.md")):
        if f.name == "README.md":
            continue
        if frontmatter_ok(f):
            report.check("PASS", f"Agent: {f.name}", "frontmatter valid (name + description)")
        else:
            report.check("FAIL", f"Agent: {f.name}", "missing name/description in frontmatter")
    for f in sorted(SKILLS.glob("*/SKILL.md")):
        label = f"{f.parent.name}/SKILL.md"
        if frontmatter_ok(f):
            report.check("PASS", f"Skill: {label}", "frontmatter valid (name + description)")
        else:
            report.check("FAIL", f"Skill: {label}", "missing name/description in frontmatter")
    report.end_section()

    # ═══════════════════════════════════════════════════════════════════
    # LAYER C — Brain scaffolding
    # ═══════════════════════════════════════════════════════════════════
    report.begin_section("Brain Scaffolding")
    wiki_index = BRAIN / "wiki" / "index.md"
    if wiki_index.is_file() and wiki_index.stat().st_size > 0:
        report.check("PASS", "Wiki index", "brain/wiki/index.md present")
    else:
        report.check("FAIL", "Wiki index", "brain/wiki/index.md missing or empty")

    iso_year, iso_week, _ = date.today().isocalendar()
    week_note = BRAIN / "weekly_logs" / f"{iso_year}" / f"{iso_year}-W{iso_week:02d}.md"
    if week_note.is_file() and week_note.stat().st_size > 0:
        report.check("PASS", "Current weekly note", f"{iso_year}-W{iso_week:02d}.md present")
    else:
        report.check("WARN", "Current weekly note", f"{iso_year}-W{iso_week:02d}.md missing (run monday_init.sh)")

    master_note = BRAIN / "weekly_logs" / f"{iso_year} Master Note.md"
    if master_note.is_file() and master_note.stat().st_size > 0:
        text = master_note.read_text(encoding="utf-8")
        if "<!-- WEEKLY-INDEX-INSERT -->" in text:
            report.check("PASS", "Master Note sentinel", f"<!-- WEEKLY-INDEX-INSERT --> present in {iso_year} Master Note.md")
        else:
            report.check("FAIL", "Master Note sentinel", f"<!-- WEEKLY-INDEX-INSERT --> missing from {iso_year} Master Note.md")
    else:
        report.check("FAIL", "Master Note", f"{iso_year} Master Note.md missing or empty")
    report.end_section()

    # ═══════════════════════════════════════════════════════════════════
    # LAYER D — Provider configuration (read-only)
    # ═══════════════════════════════════════════════════════════════════
    report.begin_section("Provider Configuration")
    enabled = os.environ.get("AGENTIC_LIGHT_PROVIDERS") or config.config_value("PROVIDERS") or "claude,gemini,codex,ollama"
    priority = os.environ.get("AGENTIC_LIGHT_PRIORITY") or config.config_value("PRIORITY") or enabled
    if config.validate_provider_lists(enabled, priority):
        report.check("PASS", "Provider lists", "priority is an exact ordering of enabled providers")
        if config.resolve_agent_provider():
            report.check("PASS", "Provider executable", f"{config.AGENT_PROVIDER}: {config.AGENT_COMMAND}")
        else:
            report.check("FAIL", "Provider executable", "no enabled provider executable found")
    else:
        report.check("FAIL", "Provider lists", "unknown, duplicate, or mismatched enabled/priority entries")
    report.end_section()

    # ═══════════════════════════════════════════════════════════════════
    # LAYER E — Pipeline log recency (informational — fresh scaffold has none yet)
    # ═══════════════════════════════════════════════════════════════════
    report.begin_section("Pipeline Logs")
    plogs = PIPELINE / "logs"
    if plogs.is_dir():
        lcount = len([p for p in plogs.glob("*.log") if p.is_file()])
        if lcount == 0:
            report.check("WARN", "Pipeline run logs", "no .log files yet in pipeline/logs/ — expected on a fresh scaffold, run pipeline/run.py")
        else:
            report.check("PASS", "Pipeline run logs", f"{lcount} log file(s) present")
    else:
        report.check("FAIL", "Pipeline logs dir", "pipeline/logs/ missing")
    report.end_section()

    # ═══════════════════════════════════════════════════════════════════
    # PRESET — role/gate/skill contract checks (kept as a real subprocess —
    # preset_audit.py is a standalone validator, not part of the Layer F
    # self-heal set the blueprint calls out for in-process conversion).
    # ═══════════════════════════════════════════════════════════════════
    report.begin_section("Preset Contracts")
    proc = subprocess.run(
        [sys.executable, str(SYSCFG / "preset_audit.py")],
        capture_output=True, encoding="utf-8",
        env={**os.environ, "PYTHONUTF8": "1"},
    )
    output = " ".join(((proc.stdout or "") + (proc.stderr or "")).split())
    if proc.returncode == 0:
        report.check("PASS", "Preset contracts", output)
    else:
        report.check("FAIL", "Preset contracts", output)
    report.end_section()

    # ═══════════════════════════════════════════════════════════════════
    # LAYER F — Doc currency (self-heals the microsite via gen_site.py etc.)
    # ═══════════════════════════════════════════════════════════════════
    report.begin_section("Documentation Currency")
    pre_warn, pre_fail = report.warn_n, report.fail_n
    doc_check(report, "System_Config/README", SYSCFG / "README.md", sorted(SYSCFG.glob("*.py")))
    doc_check(report, "brain/README", BRAIN / "README.md",
              [BRAIN / "CLAUDE.md", SYSCFG / "monday_init.sh", SYSCFG / "friday_process.sh", SYSCFG / "daily_ingest.sh"])

    rc, _ = _call_gen_main(gen_site, ["--check"])
    if rc == 0:
        report.check("PASS", "microsite/index.html", "up to date with agents/skills frontmatter")
    else:
        report.check("WARN", "microsite/index.html", "stale vs agents/skills frontmatter")

    rc, _ = _call_gen_main(gen_preset_pages, ["--check"])
    if rc == 0:
        report.check("PASS", "microsite/presets/*.html", "up to date with presets.json")
    else:
        report.check("WARN", "microsite/presets/*.html", "stale vs presets.json")

    rc, _ = _call_gen_main(gen_governance, ["--check"])
    if rc == 0:
        report.check("PASS", "GOVERNANCE.md", "up to date with agents/*.md, agent-roster.json, gate-config.json")
    else:
        report.check("WARN", "GOVERNANCE.md", "stale vs agents/*.md, agent-roster.json, or gate-config.json")

    if report.warn_n > pre_warn or report.fail_n > pre_fail:
        rc, out = _call_gen_main(gen_site, [])
        detail = " ".join(out.split())
        if rc == 0:
            report.check("PASS", "Self-heal: gen_site.py", detail)
        else:
            report.check("FAIL", "Self-heal: gen_site.py", f"regeneration failed: {detail}")

        rc, out = _call_gen_main(gen_preset_pages, [])
        detail = " ".join(out.split())
        if rc == 0:
            report.check("PASS", "Self-heal: gen_preset_pages.py", detail)
        else:
            report.check("FAIL", "Self-heal: gen_preset_pages.py", f"regeneration failed: {detail}")

        rc, out = _call_gen_main(gen_governance, [])
        detail = " ".join(out.split())
        if rc == 0:
            report.check("PASS", "Self-heal: gen_governance.py", detail)
        else:
            report.check("FAIL", "Self-heal: gen_governance.py", f"regeneration failed: {detail}")

    map_tokens = _claude_md_system_config_tokens(CLAUDE_MD.read_text(encoding="utf-8")) if CLAUDE_MD.is_file() else []
    disk_tokens = _disk_system_config_tokens()
    drift = sorted(set(disk_tokens) ^ set(map_tokens))
    if drift:
        report.check("WARN", "CLAUDE.md Directory Map", f"System_Config/ drift vs disk: {' '.join(drift)}")
    else:
        report.check("PASS", "CLAUDE.md Directory Map", "matches System_Config/ contents")
    report.end_section()

    # ═══════════════════════════════════════════════════════════════════
    # LAYER G — Config security scan (AgentShield-lite, heads-up only)
    # ═══════════════════════════════════════════════════════════════════
    report.begin_section("Config Security Scan")

    # The project's own config surface: *.py/*.json under System_Config/
    # plus .mcp.json — *.sh dropped here per the porting blueprint's
    # explicit self-referential-glob update (Tier 4's still-bash scripts
    # get their own scan coverage once ported). *.example/*.defaults.json
    # are templates by convention (placeholder values, meant to be
    # committed) and stay excluded.
    scan_files = []
    seen = set()

    def _add_scan_file(f):
        if f.name.endswith(".example") or f.name.endswith(".defaults.json"):
            return
        if f in seen:
            return
        seen.add(f)
        scan_files.append(f)

    for pattern in ("*.py", "*.json"):
        for f in sorted(SYSCFG.glob(pattern)):
            if f.is_file():
                _add_scan_file(f)
    mcp = WORKSPACE / ".mcp.json"
    if mcp.is_file():
        _add_scan_file(mcp)
    for pattern in (".env*", "*/.env*"):
        for f in sorted(WORKSPACE.glob(pattern)):
            if f.is_file():
                _add_scan_file(f)
    conf = WORKSPACE / ".agentic-light.conf"
    if conf.is_file():
        _add_scan_file(conf)

    git_bin = shutil.which("git")

    secret_hits = 0
    for f in scan_files:
        rel = f.relative_to(WORKSPACE)
        if _git_check_ignore(git_bin, f):
            continue
        hits = config.looks_like_secret(f, shaped_only=False)
        if hits:
            secret_hits += 1
            report.check("WARN", f"Possible secret: {rel}", hits[0][:120])
    if secret_hits == 0:
        report.check("PASS", "Config secret scan", "no likely-exposed secrets in tracked config surface")

    local_only_files = (".mcp.json", ".agentic-light.conf", "System_Config/.notify.env")
    for rel in local_only_files:
        f = WORKSPACE / rel
        if _git_check_ignore(git_bin, f):
            report.check("PASS", f"Gitignore: {rel}", "covered by .gitignore")
        else:
            report.check("WARN", f"Gitignore: {rel}", "documented as local-only but NOT covered by .gitignore")
    report.end_section()


def main(argv=None):
    report = Report()
    now_human = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

    run(report)

    MICROSITE.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated": now_human,
        "overall": report.overall,
        "pass": report.pass_n,
        "warn": report.warn_n,
        "fail": report.fail_n,
        "checks": report.items,
    }
    payload_json = json.dumps(payload)
    _atomic_write_text(OUT_JSON, payload_json + "\n")
    _atomic_write_text(OUT_JS, "window.__STATUS__ = " + payload_json + ";\n")

    print("================================================")
    print(f"Status: {report.overall} — {report.pass_n} pass / {report.warn_n} warn / {report.fail_n} fail (of {report.total})")
    print(f"Wrote {OUT_JSON}")
    print(f"Wrote {OUT_JS}")
    print(f"View: open {MICROSITE}/health.html")

    # Notify only on a non-clean result — a banner on every all-clear manual
    # run would just be noise. notify.py no-ops quietly if no channel is
    # configured. Kept as a real subprocess (not an in-process import) —
    # same reasoning as the gate scripts in pipeline/run.py: this is a real,
    # independently invocable process boundary, not a self-heal call.
    if report.overall != "PASS":
        notify_py = SYSCFG / "notify.py"
        if notify_py.is_file():
            try:
                subprocess.run(
                    [sys.executable, str(notify_py), f"Healthcheck: {report.overall}",
                     f"{report.pass_n} pass / {report.warn_n} warn / {report.fail_n} fail (of {report.total})"],
                    encoding="utf-8", env={**os.environ, "PYTHONUTF8": "1"},
                )
            except OSError:
                pass
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
