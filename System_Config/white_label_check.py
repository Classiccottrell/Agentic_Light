#!/usr/bin/env python3
"""Audit a specialized fork after white-label pruning."""
import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

from test_support import rmtree_force

REAL_ROOT = Path(__file__).resolve().parent.parent
GENERATORS = ["gen_governance.py", "gen_site.py", "gen_preset_pages.py"]


def _check_generated_output(root):
    """Shell out to each generator's own --check mode inside the audited
    fork. Each script resolves its own root via __file__, so this needs no
    cwd gymnastics — just the fork's own copy of the script. All three
    --check modes are read-only (writes are gated `if not check_mode and not
    dry_run` in each script), so this never mutates the audited fork. A
    missing generator script is itself a finding, not a silent skip.
    """
    root = Path(root)
    errors = []
    for name in GENERATORS:
        script = root / "System_Config" / name
        if not script.is_file():
            errors.append(f"missing generator script: System_Config/{name}")
            continue
        proc = subprocess.run(
            [sys.executable, str(script), "--check"],
            capture_output=True, text=True, encoding="utf-8",
        )
        if proc.returncode != 0:
            detail = (proc.stdout + proc.stderr).strip().splitlines()
            summary = detail[0] if detail else f"exited {proc.returncode}"
            errors.append(f"generated output stale ({name}): {summary}")
    return errors


def audit(root, name, preset, old_name="Agentic Light"):
    root = Path(root)
    errors = []
    config = root / "System_Config"
    try:
        roster = json.loads((config / "agent-roster.json").read_text(encoding="utf-8"))
        presets = json.loads((config / "presets.json").read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"cannot read specialized config: {exc}"]
    active = {role for role, data in roster.get("roles", {}).items() if data.get("active")}
    expected = set(presets.get(preset, {}).get("roles", []))
    if active != expected:
        errors.append(f"active roster {sorted(active)} != preset roster {sorted(expected)}")
    files = {p.stem for p in (root / "agents").glob("*.md") if p.name != "README.md"}
    if files != active:
        errors.append(f"agent files {sorted(files)} != active roster {sorted(active)}")
    selected_path = config / "skills-selected.json"
    if selected_path.exists():
        selected = set(json.loads(selected_path.read_text(encoding="utf-8")).get("selected", []))
        on_disk = {p.name for p in (root / "skills").iterdir() if p.is_dir() and (p / "SKILL.md").exists()}
        if selected != on_disk:
            errors.append(f"selected skills {sorted(selected)} != on-disk skills {sorted(on_disk)}")
    generated = [root / "README.md", root / "CLAUDE.md", root / "GOVERNANCE.md", root / "microsite"]
    for path in generated:
        paths = [path] if path.is_file() else list(path.rglob("*.html"))
        for file in paths:
            text = file.read_text(encoding="utf-8", errors="replace")
            if old_name in text:
                errors.append(f"old identity remains in {file.relative_to(root)}")
            if name not in text:
                errors.append(f"new identity missing from {file.relative_to(root)}")
    errors.extend(_check_generated_output(root))
    return errors


def _build_clean_fork(tmp, fixture_name, preset_name, roles=None):
    """Build a real-enough white-labeled fork under `tmp`.

    Copies this repo's own generator scripts + microsite/template.html and
    renames the literal "Agentic Light" string baked into their *source*
    (a naive white-label pass that only swept generated *output*, not
    generator source, would always fail the old-name check below — see
    presets.json/gen_governance.py/gen_preset_pages.py/template.html).
    Writes a minimal-but-real presets.json (the live preset entry from this
    repo's own System_Config/presets.json, not a hand-copied paraphrase —
    this also exercises the role_capabilities/role_handoff overlay on
    design-harness/wcag-harness) / agent-roster.json / agents/*.md /
    microsite/index.html / microsite/dashboard.html (a minimal stand-in
    with gen_site.py's 3 marker pairs, not a copy of the real prose-heavy
    dashboard.html), then actually runs all 3 generators.

    `roles`, if given, overrides the live preset's own `roles` list — written
    into the fork's own copy of presets.json (not just the roster), so
    audit()'s "active roster == preset roster" check (which reads the
    preset's roles back out of the fork's presets.json, not the real one)
    stays consistent with a smaller/different active roster than this
    workspace's own preset ships. Default (`None`) uses the live roster
    as-is. Returns the fork's root Path.
    """
    root = Path(tmp) / (fixture_name.lower().replace(" ", "-") + "-" + preset_name)
    (root / "System_Config").mkdir(parents=True)
    (root / "agents").mkdir()
    (root / "microsite" / "presets").mkdir(parents=True)
    (root / "skills").mkdir()

    for rel in ("System_Config/gen_governance.py", "System_Config/gen_site.py",
                "System_Config/gen_preset_pages.py", "microsite/template.html"):
        src = (REAL_ROOT / rel).read_text(encoding="utf-8")
        (root / rel).write_text(src.replace("Agentic Light", fixture_name), encoding="utf-8")

    (root / "System_Config" / "agent-roster.schema.json").write_text(
        (REAL_ROOT / "System_Config" / "agent-roster.schema.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    real_presets = json.loads((REAL_ROOT / "System_Config" / "presets.json").read_text(encoding="utf-8"))
    preset = dict(real_presets[preset_name])
    if roles is not None:
        preset["roles"] = roles
    roles = preset.get("roles", [])
    (root / "System_Config" / "presets.json").write_text(
        json.dumps({preset_name: preset}, indent=2), encoding="utf-8"
    )

    all_roles = ("architect", "coder", "creative-director", "curator", "eng-manager", "qa")
    roster = {"roles": {r: {"active": r in roles} for r in all_roles}}
    (root / "System_Config" / "agent-roster.json").write_text(json.dumps(roster, indent=2), encoding="utf-8")
    (root / "System_Config" / ".active-preset").write_text(preset_name, encoding="utf-8")

    for role in roles:
        (root / "agents" / f"{role}.md").write_text(
            "---\n"
            f"name: {role}\n"
            f"description: {role} role for {fixture_name}'s {preset_name} harness.\n"
            "tools: Read, Write\n"
            "---\n"
            f"# {role}\n",
            encoding="utf-8",
        )

    (root / "microsite" / "index.html").write_text(
        "<html><head><title>" + fixture_name + "</title></head><body>\n"
        "<h3>Core Agents</h3>\n"
        "<!-- gen:agents-start -->\n<!-- gen:agents-end -->\n"
        "<!-- gen:agent-count -->0<!-- /gen:agent-count -->\n"
        "<h3>Skills</h3>\n"
        "<!-- gen:skills-start -->\n<!-- gen:skills-end -->\n"
        "<!-- gen:skills-count -->0<!-- /gen:skills-count -->\n"
        "<h3>Presets</h3>\n"
        "<!-- gen:presets-start -->\n<!-- gen:presets-end -->\n"
        "</body></html>\n",
        encoding="utf-8",
    )

    # gen_site.py requires microsite/dashboard.html to already exist (it
    # opens it in place and rewrites only the marker blocks below) — this
    # fixture is not copied+renamed from REAL_ROOT like the generator
    # scripts/template.html above because the real dashboard.html carries a
    # lot of static prose; a minimal stand-in with the same 3 marker pairs
    # is enough for gen_site.py to run and for audit()'s identity check
    # (fixture_name in the title, no old_name text) to hold.
    (root / "microsite" / "dashboard.html").write_text(
        "<html><head><title>Dashboard — " + fixture_name + "</title></head><body>\n"
        "<div class=\"preset-grid\">\n"
        "            <!-- gen:dashboard-presets-start -->\n<!-- gen:dashboard-presets-end -->\n"
        "</div>\n"
        "<table><thead><tr>\n"
        "              <!-- gen:dashboard-roster-head-start -->\n<!-- gen:dashboard-roster-head-end -->\n"
        "</tr></thead><tbody>\n"
        "              <!-- gen:dashboard-roster-body-start -->\n<!-- gen:dashboard-roster-body-end -->\n"
        "</tbody></table>\n"
        "</body></html>\n",
        encoding="utf-8",
    )

    (root / "README.md").write_text(fixture_name + " — README.\n", encoding="utf-8")
    (root / "CLAUDE.md").write_text(fixture_name + " — CLAUDE context.\n", encoding="utf-8")

    for name in GENERATORS:
        proc = subprocess.run(
            [sys.executable, str(root / "System_Config" / name)],
            capture_output=True, text=True, encoding="utf-8",
        )
        if proc.returncode != 0:
            raise RuntimeError(f"_build_clean_fork: {name} failed: {proc.stdout}{proc.stderr}")

    return root


# ---------------------------------------------------------------------------
# Acceptance mode (--acceptance): a fresh, fully white-labeled fork that
# actually runs. Where _build_clean_fork() above is a generator-only stand-in,
# _build_acceptance_fork() copies this repo's real tracked tree and walks the
# documented white-label procedure (microsite/whitelabel.html): specialize,
# delete inactive role files and unselected skill dirs, prune presets.json,
# rename the identity layer, regenerate. The fork's own pipeline/run.py is
# then driven end to end against a scratch target repo — fake `codex`
# provider, fake `gh`, auto-approved human gate under test mode, never a real
# provider or network.

IDENTITY_VARIANTS = ("Agentic Light", "agentic-light", "Agentic_Light")
ACCEPTANCE_PRESETS = ("design-harness", "wcag-harness", "cli-tool")
ACCEPTANCE_NAME = "Northwind Harness"
ACCEPTANCE_TASK = "Add a one-line status note to NOTES.md"
# Runtime identifiers a rename pass must NOT touch: the code still reads them
# under these exact names, so renaming them in docs would make the docs wrong.
# Left in place, they surface as identity findings instead.
PROTECTED_TOKENS = (".agentic-light.conf",)
COPY_EXCLUDE = re.compile(r"^(pipeline/logs/.+.(log|jsonl)|brain/records/sessions/.*|microsite/status.(json|js))$")
PROVIDER_MIRRORS_NOTE = ("provider mirrors: not implemented (role contract reaches providers via the "
                         "prompt-assembly contract instead)")

# Findings the acceptance check is known to surface today, keyed by
# (kind, surface) — never by run-id text. --self-test fails on any finding NOT
# listed here; a listed finding that disappears (fixed) is fine.
_BRANCH_CAUSE = ('pipeline/run.py hardcodes the branch prefix (branch_name = f"agentic-light/{run_id}"); '
                 "the branch name is then recorded verbatim")
KNOWN_FINDINGS = {
    ("identity", "target repo branch names"): _BRANCH_CAUSE,
    ("identity", "pipeline/logs/<run-id>.events.jsonl"): _BRANCH_CAUSE + " in the run_start event",
    ("identity", "brain/records/sessions/<run-id>.md"): _BRANCH_CAUSE + " in the session record's Branch line",
    ("identity", "target repo commit messages"):
        'pipeline/run.py hardcodes the commit message prefix (git commit -m f"Agentic Light: {task_desc}")',
    ("identity", "run.py console output"):
        'pipeline/run.py prints a hardcoded " Agentic Light Pipeline — run <id>" banner, plus the branch name; '
        'pipeline/lib/vpat_lint_gate.py (and axe_gate.py on a failure) print a hardcoded '
        '"(in the Agentic Light workspace)" manual reference',
    ("identity", "pipeline/logs/<run-id>.log"):
        "the run log tees run.py's console output (hardcoded banner, branch name, gate manual references)",
    ("identity", "specialize.py console output"):
        'System_Config/specialize.py prints a hardcoded " Agentic Light — specialize" banner',
    ("identity", "gh pr create argv"):
        "pipeline/lib/pr_create.py's default --body (\"Generated by Agentic Light pipeline/run.py ...\"); "
        "run.py never passes a body",
    ("identity", "context packet"):
        'System_Config/context_packet.py hardcodes "# Agentic Light Context Packet" for the default profile '
        '(and run.py/context_packet.py default the profile name to "agentic-light")',
    ("identity", "coder prompt"):
        "the context packet's hardcoded header is injected into the CONTEXT PACKET section",
    ("identity", "runtime filename .agentic-light.conf"):
        "System_Config/config.py reads WORKSPACE/.agentic-light.conf by that literal name, so docs, "
        ".gitignore and gen_governance.py's STATIC_TEMPLATE must keep it (renaming them would make them wrong)",
    ("capability", "coder@claude"):
        "System_Config/agent-roster.example.json gives coder [read, write, shell]; specialize.py copies that "
        "into every preset without a coder overlay, and the claude/gemini adapters do not grant shell "
        "(pending owner sign-off on the example-roster data change)",
}


def _identity_hits(text, variants=IDENTITY_VARIANTS):
    """Case-sensitive on purpose: AGENTIC_LIGHT_* env var names are mechanism,
    not identity, and must not register."""
    return [v for v in variants if v in text]


def _slug(name):
    return name.lower().replace(" ", "-")


def _rename_identity(text, name):
    for i, tok in enumerate(PROTECTED_TOKENS):
        text = text.replace(tok, f"\x00PROTECTED{i}\x00")
    text = (text.replace("Agentic Light", name)
                .replace("agentic-light", _slug(name))
                .replace("Agentic_Light", name.replace(" ", "_")))
    for i, tok in enumerate(PROTECTED_TOKENS):
        text = text.replace(f"\x00PROTECTED{i}\x00", tok)
    return text


def _tracked_files(root):
    try:
        proc = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True,
                              encoding="utf-8", errors="replace")
        if proc.returncode == 0 and proc.stdout:
            return [f for f in proc.stdout.split("\0") if f]
    except OSError:
        pass
    return [p.relative_to(root).as_posix() for p in root.rglob("*")
            if p.is_file() and not ({".git", "__pycache__"} & set(p.relative_to(root).parts))]


def _clean_env(extra=None):
    """Inherited env minus anything that could steer a fork-side run toward a
    real provider/config or a test override from the calling shell."""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("AGENTIC_LIGHT_", "PIPELINE_")) and k not in ("AGENT_TYPE", "AGENT_PROVIDER", "LOG_SESSION_NOTE")}
    env.update({"PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"})
    env.update(extra or {})
    return env


def _fork_py(root, code, env=None):
    """Run `code` with the fork's own System_Config/ first on sys.path, in a
    child process — so `import specialize` inside prompt_assembly resolves to
    the fork's copy, never this process's already-imported modules."""
    prelude = f"import sys; sys.path.insert(0, {str(root / 'System_Config')!r})\n"
    return subprocess.run([sys.executable, "-c", prelude + code], capture_output=True, encoding="utf-8",
                          errors="replace", cwd=str(root), env=env or _clean_env(), timeout=60)


def _build_acceptance_fork(tmp, name, preset):
    """Returns (fork root, step-1 checks, specialize.py console output).
    Raises RuntimeError only when the
    fork cannot be built at all."""
    checks = []
    root = Path(tmp) / f"{_slug(name)}-{preset}"
    for rel in _tracked_files(REAL_ROOT):
        if COPY_EXCLUDE.match(rel) or "__pycache__" in rel:
            continue
        src = REAL_ROOT / rel
        if not src.is_file():
            continue
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    proc = subprocess.run([sys.executable, str(root / "System_Config" / "specialize.py"), "--preset", preset],
                          capture_output=True, encoding="utf-8", errors="replace", cwd=str(root),
                          env=_clean_env(), stdin=subprocess.DEVNULL, timeout=60)
    checks.append(("specialize", f"specialize.py --preset {preset} rc 0", proc.returncode == 0,
                   (proc.stdout + proc.stderr).strip()[-400:]))
    specialize_out = proc.stdout + proc.stderr
    if proc.returncode != 0:
        raise RuntimeError(f"specialize.py --preset {preset} failed: {proc.stderr.strip()}")

    preset_def = json.loads((REAL_ROOT / "System_Config" / "presets.json").read_text(encoding="utf-8"))[preset]
    val = _fork_py(root, (
        "import json, specialize\n"
        "r = json.load(open(specialize.ROSTER_OUT, encoding='utf-8'))\n"
        "g = json.load(open(specialize.GATE_OUT, encoding='utf-8'))\n"
        "s = json.load(open(specialize.ROSTER_SCHEMA, encoding='utf-8'))\n"
        "print(json.dumps({'roster_errors': specialize.validate_roster(r, s),\n"
        "  'gate_errors': specialize.validate_gate_entries(g['gates'], specialize.load_known_gates()),\n"
        "  'active': sorted(k for k, v in r['roles'].items() if v['active']), 'gates': g['gates']}))\n"))
    try:
        v = json.loads(val.stdout)
    except ValueError:
        v = {"roster_errors": [val.stderr.strip()], "gate_errors": [], "active": [], "gates": []}
    checks.append(("specialize", "agent-roster.json valid against schema", not v["roster_errors"], v["roster_errors"]))
    checks.append(("specialize", "gate-config.json valid", not v["gate_errors"], v["gate_errors"]))
    checks.append(("specialize", "active roster == preset roles",
                   v["active"] == sorted(preset_def["roles"]), v["active"]))
    checks.append(("specialize", "gate-config gates == preset gates", v["gates"] == preset_def["gates"], v["gates"]))

    # Strip, don't deselect (whitelabel.html checklist).
    for f in (root / "agents").glob("*.md"):
        if f.name != "README.md" and f.stem not in preset_def["roles"]:
            f.unlink()
    selected = set(json.loads((root / "System_Config" / "skills-selected.json").read_text(encoding="utf-8"))["selected"])
    for d in (root / "skills").iterdir():
        if d.is_dir() and d.name not in selected:
            rmtree_force(d)
    presets_path = root / "System_Config" / "presets.json"
    presets_path.write_text(json.dumps({preset: json.loads(presets_path.read_text(encoding="utf-8"))[preset]},
                                       indent=2) + "\n", encoding="utf-8")

    # Rename pass: the whole non-code layer (docs, agents, skills, microsite,
    # brain, JSON) plus the generator scripts' identity prose — the
    # documented procedure. Mechanism (.py) is deliberately left alone,
    # except the generators: gen_preset_pages.py literal-replaces
    # template.html's wordmark, so the two must be renamed identically or the
    # replace silently no-ops; gen_governance.py's STATIC_TEMPLATE title is
    # where the docs say governance is renamed.
    for f in sorted(root.rglob("*")):
        if not f.is_file() or f.suffix == ".py":
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        new = _rename_identity(text, name)
        if new != text:
            f.write_text(new, encoding="utf-8", newline="")
    for gen in ("gen_governance.py", "gen_site.py"):
        f = root / "System_Config" / gen
        f.write_text(f.read_text(encoding="utf-8").replace("Agentic Light", name), encoding="utf-8", newline="")
    f = root / "System_Config" / "gen_preset_pages.py"
    f.write_text(_rename_identity(f.read_text(encoding="utf-8"), name), encoding="utf-8", newline="")

    for gen in GENERATORS:
        proc = subprocess.run([sys.executable, str(root / "System_Config" / gen)], capture_output=True,
                              encoding="utf-8", errors="replace", cwd=str(root), env=_clean_env(), timeout=120)
        checks.append(("specialize", f"{gen} regenerates in the fork", proc.returncode == 0,
                       (proc.stdout + proc.stderr).strip()[-400:]))
    errors = audit(root, name, preset)
    checks.append(("specialize", "audit() passes after white-label + regeneration", errors == [], errors))
    return root, checks, specialize_out


def _write_path_fake(bin_dir, name, body):
    """PATH-discoverable fake (shebang + .cmd wrapper), same shape as
    pipeline/test_pipeline.py's write_path_fake()."""
    path = bin_dir / name
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(f"#!{sys.executable}\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    with open(bin_dir / f"{name}.cmd", "w", encoding="utf-8", newline="") as f:
        f.write(f'@echo off\r\n"{sys.executable}" "%~dp0{name}" %*\r\n')


def _git(args, cwd, env=None):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, encoding="utf-8",
                          errors="replace", env=env)


def _normalize_surface(rel, run_id):
    rel = rel.replace(run_id, "<run-id>") if run_id else rel
    return re.sub(r"brain/weekly_logs/\d{4}/\d{4}-W\d{2}\.md$", "brain/weekly_logs/<week>.md", rel)


def acceptance(preset, name=ACCEPTANCE_NAME, tmp_parent=None):
    """Run the acceptance fixture for one preset. Returns a result dict:
    {"preset", "checks": [(step, label, ok, detail)], "findings":
    [{"kind", "surface", "detail"}], "info": [str]}. Never raises for a
    failing assertion — those become checks/findings."""
    result = {"preset": preset, "checks": [], "findings": [], "info": []}
    checks, findings, info = result["checks"], result["findings"], result["info"]
    tmp = Path(tempfile.mkdtemp(prefix="white-label-acceptance.", dir=tmp_parent))
    try:
        try:
            root, step1, specialize_out = _build_acceptance_fork(tmp, name, preset)
            checks.extend(step1)
        except (RuntimeError, OSError, subprocess.SubprocessError) as e:
            checks.append(("specialize", "fork builds", False, str(e)))
            return result
        preset_def = json.loads((root / "System_Config" / "presets.json").read_text(encoding="utf-8"))[preset]

        # --- step 2: run the fork's own pipeline ----------------------------
        bin_dir = tmp / "fakebin"
        bin_dir.mkdir()
        prompt_file, gh_calls = tmp / "codex_prompt.txt", tmp / "gh_calls.txt"
        _write_path_fake(bin_dir, "codex", (
            "import os, sys\n"
            "with open(os.environ['WL_PROMPT_CAPTURE'], 'w', encoding='utf-8', newline='') as f:\n"
            "    f.write(sys.argv[-1])\n"
            "with open('NOTES.md', 'a', encoding='utf-8', newline='\\n') as f:\n"
            "    f.write('status: ok\\n')\n"))
        _write_path_fake(bin_dir, "gh", (
            "import os, sys\n"
            "with open(os.environ['WL_GH_CALLS'], 'a', encoding='utf-8', newline='') as f:\n"
            "    f.write(' '.join(sys.argv[1:]) + '\\n')\n"
            "sys.exit(0)\n"))
        approve = tmp / "approve_stub.py"
        approve.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")

        git_env = _clean_env({"GIT_AUTHOR_NAME": "Acceptance", "GIT_AUTHOR_EMAIL": "acceptance@example.invalid",
                              "GIT_COMMITTER_NAME": "Acceptance", "GIT_COMMITTER_EMAIL": "acceptance@example.invalid"})
        target = tmp / "target-repo"
        target.mkdir()
        _git(["init", "-q", "-b", "main"], target, git_env)
        (target / "NOTES.md").write_text("# Notes\n", encoding="utf-8")
        _git(["add", "NOTES.md"], target, git_env)
        _git(["commit", "-q", "-m", "seed"], target, git_env)

        run_env = dict(git_env)
        run_env.update({
            "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            "AGENTIC_LIGHT_PROVIDERS": "codex", "AGENTIC_LIGHT_PRIORITY": "codex",
            "AGENTIC_LIGHT_TEST_MODE": "1", "PIPELINE_HUMAN_GATE_CMD": str(approve),
            "AGENTIC_LIGHT_CONTEXT_PACKET": "1", "MAX_SECONDS": "60",
            "WL_PROMPT_CAPTURE": str(prompt_file), "WL_GH_CALLS": str(gh_calls),
        })
        proc = subprocess.run([sys.executable, str(root / "pipeline" / "run.py"), ACCEPTANCE_TASK, str(target)],
                              capture_output=True, encoding="utf-8", errors="replace", env=run_env,
                              stdin=subprocess.DEVNULL, timeout=300)
        run_out = proc.stdout + proc.stderr
        checks.append(("run", "pipeline/run.py exits 0", proc.returncode == 0, run_out.strip()[-600:]))

        event_files = sorted((root / "pipeline" / "logs").glob("*.events.jsonl"))
        checks.append(("run", "exactly one events file", len(event_files) == 1, [p.name for p in event_files]))
        events = [json.loads(l) for l in event_files[0].read_text(encoding="utf-8").splitlines()
                  if l.strip()] if event_files else []
        run_id = events[0]["run_id"] if events else ""
        by = {}
        for e in events:
            by.setdefault(e["event"], []).append(e)
        pre = [e for e in by.get("preflight", []) if e.get("result") == "pass"]
        cap = pre[0].get("roster", {}).get("capability_check") if pre else None
        checks.append(("run", "launch-time roster/capability check passes (provider codex)", cap == "pass",
                       by.get("preflight")))
        launch = (by.get("coder_launch") or [{}])[0]
        checks.append(("run", "coder launched via run_agent on the fake codex provider",
                       launch.get("via") == "run_agent" and launch.get("provider") == "codex", launch))
        ran = [g["gate"] for g in by.get("gate", [])]
        checks.append(("run", f"configured gates ran {preset_def['gates']}", ran == preset_def["gates"], ran))
        checks.append(("run", "all gates passed", all(g["result"] == "pass" for g in by.get("gate", [])),
                       by.get("gate")))
        verdicts = [l.strip() for l in run_out.splitlines() if re.match(r"\s*\[\w+_gate\] (PASS|WARN|FAIL)", l)]
        info.append("gate verdicts: " + ("; ".join(verdicts) if verdicts else "none (preset configures no gates)"))
        end = (by.get("run_end") or [{}])[-1]
        checks.append(("run", "run_end status pass", end.get("status") == "pass", end))

        prompt = prompt_file.read_text(encoding="utf-8") if prompt_file.is_file() else ""
        coder_md = (root / "agents" / "coder.md").read_text(encoding="utf-8")
        body = coder_md.split("\n---", 1)[1].split("\n", 1)[1].strip() if coder_md.startswith("---") else coder_md.strip()
        rc_at, task_at = prompt.find("----- BEGIN ROLE CONTRACT -----"), prompt.find("----- BEGIN TASK -----")
        checks.append(("run", "prompt has ROLE CONTRACT then TASK", 0 <= rc_at < task_at, (rc_at, task_at)))
        lines = [l for l in body.splitlines() if l.strip()]
        checks.append(("run", "ROLE CONTRACT carries the fork's renamed agents/coder.md body",
                       bool(lines) and lines[0] in prompt[rc_at:task_at] and lines[-1] in prompt[rc_at:task_at]
                       and name in body, lines[:1]))
        checks.append(("run", "TASK section carries the task", ACCEPTANCE_TASK in prompt[task_at:],
                       prompt[task_at:task_at + 200]))

        # Capability check against claude, evaluated directly (the run above
        # used codex, which grants shell). Also confirms a PIPELINE_CODER_CMD
        # run (provider=None) only skips the capability half — note that
        # override path never assembles a prompt at all, so it cannot carry
        # the role-contract assertion above.
        roster_path = root / "System_Config" / "agent-roster.json"
        schema_path = root / "System_Config" / "agent-roster.schema.json"
        cl = _fork_py(root, (
            "import json, prompt_assembly as pa\n"
            "out = {}\n"
            f"for prov in ('claude', None):\n"
            f"    try:\n"
            f"        out[str(prov)] = pa.check_launch('coder', prov, {str(roster_path)!r}, {str(schema_path)!r})\n"
            f"    except ValueError as e:\n"
            f"        out[str(prov)] = {{'error': str(e)}}\n"
            "print(json.dumps(out))\n"))
        try:
            launch_checks = json.loads(cl.stdout)
        except ValueError:
            launch_checks = {"claude": {"error": cl.stderr.strip()}, "None": {"error": cl.stderr.strip()}}
        skipped = launch_checks.get("None", {}).get("capability_check", "")
        checks.append(("run", "PIPELINE_CODER_CMD-style launch (provider None) skips only the capability check",
                       skipped.startswith("skipped"), launch_checks.get("None")))
        claude = launch_checks.get("claude", {})
        if "error" in claude:
            findings.append({"kind": "capability", "surface": "coder@claude", "detail": claude["error"]})

        # --- step 3: context packet built in the fork ------------------------
        pk = subprocess.run([sys.executable, str(root / "System_Config" / "context_packet.py")], capture_output=True,
                            cwd=str(root), env=_clean_env(), timeout=60)
        packet = pk.stdout.decode("utf-8", errors="replace")
        checks.append(("packet", "context_packet.py builds in the fork (default profile, as run.py uses)",
                       pk.returncode == 0 and bool(packet.strip()), pk.stderr.decode("utf-8", errors="replace")[-300:]))
        checks.append(("packet", "within default budget (12000 bytes / 120 lines)",
                       len(pk.stdout) <= 12000 and len(packet.splitlines()) <= 120,
                       (len(pk.stdout), len(packet.splitlines()))))
        info.append(f"context packet: {len(pk.stdout)} bytes, {len(packet.splitlines())} lines")

        # --- step 4: session record -----------------------------------------
        records = sorted((root / "brain" / "records" / "sessions").glob("*.md"))
        checks.append(("session", "exactly one session record", len(records) == 1, [p.name for p in records]))
        if records:
            rec = records[0]
            vp = subprocess.run([sys.executable, str(root / "System_Config" / "context_validate.py"), "validate",
                                 str(rec), "--root", str(root), "--json"], capture_output=True, encoding="utf-8",
                                errors="replace", cwd=str(root), env=_clean_env(), timeout=60)
            try:
                valid = json.loads(vp.stdout)
            except ValueError:
                valid = {"valid": False, "findings": [vp.stderr.strip()]}
            checks.append(("session", "record validates with the fork's context_validate.py",
                           valid.get("valid") is True, valid.get("findings")))
            text = rec.read_text(encoding="utf-8")
            m = re.search(r"^source: \[(.*)\]$", text, re.MULTILINE)
            sources = [s.strip() for s in m.group(1).split(",")] if m else []
            missing = [s for s in sources if not (root / s).is_file()]
            checks.append(("session", "provenance paths exist in the fork", bool(sources) and not missing,
                           missing or sources))
            checks.append(("session", "record id matches the run", f"id: session-{run_id}" in text, run_id))

        # --- step 5: no identity --------------------------------------------
        errors = audit(root, name, preset)
        checks.append(("identity", "audit() still passes after the run", errors == [], errors))
        branches = _git(["for-each-ref", "--format=%(refname:short)", "refs/heads"], target).stdout
        commits = _git(["log", "--all", "--format=%B"], target).stdout
        gh_text = gh_calls.read_text(encoding="utf-8") if gh_calls.is_file() else ""
        surfaces = [("target repo branch names", branches), ("target repo commit messages", commits),
                    ("gh pr create argv", gh_text), ("coder prompt", prompt), ("context packet", packet),
                    ("run.py console output", run_out), ("specialize.py console output", specialize_out)]
        py_hits = []
        for f in sorted(root.rglob("*")):
            if not f.is_file() or "__pycache__" in f.parts:
                continue
            try:
                text = f.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            rel = f.relative_to(root).as_posix()
            if f.suffix == ".py":
                if _identity_hits(text):
                    py_hits.append(rel)
                continue
            surfaces.append((_normalize_surface(rel, run_id), text))
        protected_only = []
        for surface, text in surfaces:
            hits = _identity_hits(text)
            if not hits:
                continue
            stripped = text
            for tok in PROTECTED_TOKENS:
                stripped = stripped.replace(tok, "")
            if not _identity_hits(stripped):
                protected_only.append(surface)  # grouped below: one cause, many docs
                continue
            samples = []
            for l in stripped.splitlines():
                l = (l.replace(run_id, "<run-id>") if run_id else l).strip()
                if _identity_hits(l) and l[:160] not in samples:
                    samples.append(l[:160])
            findings.append({"kind": "identity", "surface": surface,
                             "detail": f"{hits}: " + " | ".join(samples[:4]) + (" | …" if len(samples) > 4 else "")})
        if protected_only:
            findings.append({"kind": "identity", "surface": "runtime filename " + "/".join(PROTECTED_TOKENS),
                             "detail": f"referenced in {len(protected_only)} file(s): {', '.join(protected_only)}"})
        info.append(f"identity in .py source (informational — whitelabel.html says leave pipeline/generator "
                    f"mechanism alone): {len(py_hits)} file(s), e.g. {', '.join(py_hits[:4])}")

        # --- step 6: provider mirrors ---------------------------------------
        info.append(PROVIDER_MIRRORS_NOTE + "; substitute assertion: ROLE CONTRACT in the captured prompt (step 2)")
        return result
    finally:
        rmtree_force(tmp)


def report_acceptance(result, known=None):
    """Print one preset's result. Returns (failing checks, unknown findings,
    known findings)."""
    known = KNOWN_FINDINGS if known is None else known
    print(f"white_label_check: acceptance: {result['preset']} (fork \"{ACCEPTANCE_NAME}\")")
    names = {"specialize": "1 specialize", "run": "2 run agent+gates", "packet": "3 context packet",
             "session": "4 session record", "identity": "5 no identity"}
    failing = []
    for step, label, ok, detail in result["checks"]:
        print(f"  [{'PASS' if ok else 'FAIL'}] {names.get(step, step)}: {label}" + ("" if ok else f" — {detail}"))
        if not ok:
            failing.append((step, label))
    unknown, seen_known = [], []
    for f in result["findings"]:
        key = (f["kind"], f["surface"])
        cause = known.get(key)
        tag = "FINDING (known)" if cause else "FINDING"
        print(f"  [{tag}] {f['kind']} @ {f['surface']}: {f['detail']}")
        if cause:
            print(f"      cause: {cause}")
            seen_known.append(key)
        else:
            unknown.append(key)
    for line in result["info"]:
        print(f"  [INFO] {line}")
    return failing, unknown, seen_known


def run_acceptance(presets, known=None):
    """--acceptance entry point: exit 1 while any check fails or any finding
    (known or not) exists — known findings are still real failures."""
    bad = False
    for preset in presets:
        failing, unknown, seen_known = report_acceptance(acceptance(preset), known)
        bad = bad or bool(failing or unknown or seen_known)
    print(f"white_label_check: acceptance {'FAIL' if bad else 'PASS'}")
    return 1 if bad else 0



def self_test():
    failures = []

    def check(label, cond, detail=""):
        if not cond:
            failures.append(f"{label}: {detail}")
        else:
            print(f"white_label_check: self-test fixture ok: {label}")

    with tempfile.TemporaryDirectory() as tmp:
        # Fixture 1: clean fork, wcag-harness with a single active role
        # (roles overridden down to just `coder`, written into the fork's
        # own presets.json so the roster/preset-mismatch check stays
        # self-consistent) — a genuinely smaller roster than fixture 2, not
        # just a same-shaped fork under a different preset name.
        root1 = _build_clean_fork(tmp, "CleanOne", "wcag-harness", roles=["coder"])
        errors1 = audit(root1, "CleanOne", "wcag-harness")
        check("clean fork (wcag-harness, coder only)", errors1 == [], errors1)

        # Fixture 2: clean fork, design-harness (same overlay, different
        # gate/skill/role_notes content).
        root2 = _build_clean_fork(tmp, "CleanFour", "design-harness")
        errors2 = audit(root2, "CleanFour", "design-harness")
        check("clean fork (design-harness)", errors2 == [], errors2)

        # Fixture 3: deliberately-stale old-name text (a rename pass that
        # missed one file) must be caught.
        root3 = _build_clean_fork(tmp, "StaleName", "wcag-harness")
        (root3 / "README.md").write_text("StaleName — leftover Agentic Light reference.\n", encoding="utf-8")
        errors3 = audit(root3, "StaleName", "wcag-harness")
        check(
            "stale old-name text is caught",
            any("old identity remains in README.md" in e for e in errors3),
            errors3,
        )

        # Fixture 4: roster/preset mismatch (an extra active role not in
        # the preset's own roster) must be caught.
        root4 = _build_clean_fork(tmp, "RosterMismatch", "wcag-harness")
        roster4 = json.loads((root4 / "System_Config" / "agent-roster.json").read_text(encoding="utf-8"))
        roster4["roles"]["curator"]["active"] = True
        (root4 / "System_Config" / "agent-roster.json").write_text(json.dumps(roster4, indent=2), encoding="utf-8")
        (root4 / "agents" / "curator.md").write_text(
            "---\nname: curator\ndescription: curator for RosterMismatch.\ntools: Read\n---\n# curator\n",
            encoding="utf-8",
        )
        errors4 = audit(root4, "RosterMismatch", "wcag-harness")
        check(
            "roster/preset mismatch is caught",
            any("active roster" in e and "!= preset roster" in e for e in errors4),
            errors4,
        )

        # Fixture 5: generated-output staleness (the preset's own
        # description: edited post-generation, so the already-rendered
        # dashboard.html preset card disagrees with presets.json) must be
        # caught by _check_generated_output's gen_site.py --check call.
        # (Not an agents/*.md edit: gen_site.py's dashboard build no longer
        # reads per-agent descriptions -- that table moved to
        # gen_governance.py's GOVERNANCE.md -- so mutating coder.md would
        # only flip gen_governance.py stale, not gen_site.py.)
        root5 = _build_clean_fork(tmp, "StaleOutput", "wcag-harness")
        presets5 = json.loads((root5 / "System_Config" / "presets.json").read_text(encoding="utf-8"))
        presets5["wcag-harness"]["description"] = "a materially different description now."
        (root5 / "System_Config" / "presets.json").write_text(json.dumps(presets5, indent=2), encoding="utf-8")
        errors5 = audit(root5, "StaleOutput", "wcag-harness")
        check(
            "generated-output staleness is caught",
            any("generated output stale (gen_site.py)" in e for e in errors5),
            errors5,
        )

    # Scan/rename helpers, pure: env var names are not identity, the
    # lowercase slug is, and runtime filenames survive the rename pass.
    check("identity scan ignores AGENTIC_LIGHT_* env names", _identity_hits("AGENTIC_LIGHT_TEST_MODE") == [])
    check("identity scan catches the lowercase slug", _identity_hits("x agentic-light") == ["agentic-light"])
    renamed = _rename_identity("Agentic Light reads .agentic-light.conf", "Acme")
    check("rename pass protects runtime filenames", renamed == "Acme reads .agentic-light.conf", renamed)

    # Acceptance fixtures: a real white-labeled fork per in-focus preset,
    # run end to end. Every non-identity check must pass; findings must all
    # be listed in KNOWN_FINDINGS (they are still reported, and --acceptance
    # still exits 1 on them — the self-test only guards against new ones).
    for preset in ACCEPTANCE_PRESETS:
        failing, unknown, _ = report_acceptance(acceptance(preset))
        check(f"acceptance ({preset}): all checks pass", not failing, failing)
        check(f"acceptance ({preset}): no findings outside KNOWN_FINDINGS", not unknown, unknown)

    if failures:
        print("white_label_check: self-test FAILED:")
        for f in failures:
            print(f"  {f}")
        sys.exit(1)
    print("white_label_check: self-test OK")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--name")
    parser.add_argument("--preset")
    parser.add_argument("--old-name", default="Agentic Light")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--acceptance", action="store_true",
                        help="build a white-labeled fork per preset (--preset, else "
                             + ", ".join(ACCEPTANCE_PRESETS) + ") and run it end to end")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.acceptance:
        return run_acceptance([args.preset] if args.preset else list(ACCEPTANCE_PRESETS))
    if not args.name or not args.preset:
        parser.error("--name and --preset are required unless --self-test is used")
    errors = audit(args.root, args.name, args.preset, args.old_name)
    if errors:
        for error in errors:
            print(f"white_label_check: FAIL: {error}")
        return 1
    print(f"white_label_check: PASS: {args.preset} white-label contract valid")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
