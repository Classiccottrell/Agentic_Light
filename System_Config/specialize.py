#!/usr/bin/env python3
"""specialize.py — one-time fork specialization for Agentic Light. Python
port of specialize.sh.

Run once per fork, after bootstrap. Prompts for which roles, gates, and
skill dirs this fork keeps, writes canonical config to
System_Config/agent-roster.json, pipeline/gate-config.json,
System_Config/skills-selected.json, and System_Config/.active-preset (read
by gen_governance.py/gen_preset_pages.py/preset_audit.py/route_skill.py —
those 5 scripts are the ground truth for these shapes and are untouched by
this port). Idempotent: re-running overwrites those files cleanly.

  python3 System_Config/specialize.py
  python3 System_Config/specialize.py --preset web-app|cli-tool|data-pipeline|design-harness|server-harness|wcag-harness
  python3 System_Config/specialize.py --self-test

Tier 2 (depends on Tier 0 only, per the porting blueprint's phasing plan) —
this module deliberately does NOT import pipeline/run.py, even though its
gate-config validation logic is conceptually the same; each keeps its own
copy, same as specialize.sh/run.sh never shared that heredoc either.

role_capabilities/role_handoff note: role_capabilities is folded into each
active role's "capabilities" field in agent-roster.json (overlay over
agent-roster.example.json's defaults). role_handoff is NEVER written into
agent-roster.json — it stays in presets.json only, looked up directly by
gen_governance.py/gen_preset_pages.py via .active-preset. That is existing,
confirmed-correct behavior in specialize.sh; this port does not change it.

No `command -v python3` check (specialize.sh's own guard) — structurally
impossible to trigger now that this script IS the python3 process.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath

ROOT = Path(os.path.abspath(__file__)).parent.parent
SYSCFG = ROOT / "System_Config"
PRESETS_FILE = SYSCFG / "presets.json"
ROSTER_SCHEMA = SYSCFG / "agent-roster.schema.json"
GATE_SCHEMA = SYSCFG / "gate-config.schema.json"
ROSTER_EXAMPLE = SYSCFG / "agent-roster.example.json"
ROSTER_OUT = SYSCFG / "agent-roster.json"
GATE_OUT = ROOT / "pipeline" / "gate-config.json"
SKILLS_OUT = SYSCFG / "skills-selected.json"
ACTIVE_PRESET_OUT = SYSCFG / ".active-preset"

A11Y_GATES = ("axe", "vpat-lint")

HELP_TEXT = """Usage: python3 System_Config/specialize.py [--preset web-app|cli-tool|data-pipeline|design-harness|server-harness|wcag-harness]
  (no args)        interactive checkbox prompts
  --preset <name>  non-interactive, expand a named preset from System_Config/presets.json
                   web-app: full team + eslint/playwright gates + react-doctor/shadcn skills
                   cli-tool: coder+qa, no gates, systematic-debugging/managing-python-dependencies skills
                   data-pipeline: architect+coder+qa, no default gate, curated data skills
                   design-harness: architect+coder+creative-director+qa, playwright gate, all skills
                   server-harness: architect+coder+qa, no default gates, server-review skill
                   wcag-harness: architect+coder+creative-director+qa, playwright+axe+vpat-lint gates, wcag-audit+vpat-authoring skills
  --help           this message

Env overrides (non-interactive): AGENTIC_LIGHT_ROLES, AGENTIC_LIGHT_GATES,
AGENTIC_LIGHT_SKILLS — comma-separated. AGENTIC_LIGHT_GATES entries are gate
names (eslint, playwright, axe, vpat-lint); a custom gate cannot be expressed via env override."""


def is_repo_relative(value):
    """False for any POSIX- or Windows-shaped absolute path, regardless of
    the OS actually running (blueprint §2) — gate-config.json is portable
    JSON that may be authored on one OS and consumed on another. Strictly
    wider than specialize.sh's own `script.startswith("/")` check (a
    deliberate, blueprint-directed improvement, not a parity break: no
    caller of this port relies on a Windows-absolute custom-gate path
    slipping through)."""
    return not (PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute())


def _atomic_write_text(path, text):
    """mkstemp+os.replace, same helper shape as log_session.py's
    _atomic_write — never os.rename (fails on Windows if destination
    exists)."""
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


def load_all_roles(schema_path=None):
    schema = json.loads((schema_path or ROSTER_SCHEMA).read_text(encoding="utf-8"))
    return list(schema["properties"]["roles"]["properties"].keys())


def load_known_gates(schema_path=None):
    schema = json.loads((schema_path or GATE_SCHEMA).read_text(encoding="utf-8"))
    return tuple(schema["definitions"]["gate"]["oneOf"][0]["enum"])


def skill_dirs_present(root=None):
    skills_root = (root or ROOT) / "skills"
    if not skills_root.is_dir():
        return []
    return sorted(p.name for p in skills_root.iterdir() if p.is_dir())


def default_capabilities_map(example_path=None):
    """role -> capabilities list, from agent-roster.example.json. Empty dict
    if the file is missing or unreadable — mirrors specialize.sh's own
    `except FileNotFoundError: pass`."""
    path = example_path or ROSTER_EXAMPLE
    if not path.is_file():
        return {}
    try:
        example = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {role: val.get("capabilities", []) for role, val in example.get("roles", {}).items()}


def build_roster(all_roles, sel_roles, role_caps_overlay, example_path=None):
    """sel_roles: any container supporting `in`. role_caps_overlay: preset's
    own role_capabilities dict (may be empty — every non-preset path passes
    {} here, which makes every role fall through to default_caps, i.e.
    today's flat default-capabilities behavior, unchanged)."""
    default_caps = default_capabilities_map(example_path)
    roster = {"roles": {}}
    for role in all_roles:
        entry = {"active": role in sel_roles}
        caps = role_caps_overlay.get(role, default_caps.get(role))
        if caps is not None:
            entry["capabilities"] = caps
        roster["roles"][role] = entry
    return roster


def validate_roster(data, schema):
    """Direct transliteration of specialize.sh's agent-roster.json
    structural-validation heredoc. Returns a list of error strings (empty =
    valid) — derived from the schema's own fields, not a hand-maintained
    second copy of its rules."""
    errors = []
    if not isinstance(data, dict):
        return ["agent-roster.json must be an object"]
    top_props = set(schema["properties"].keys())
    unknown_top = set(data.keys()) - top_props
    if unknown_top:
        errors.append(f"agent-roster.json has unknown top-level keys: {sorted(unknown_top)}")
    for req in schema.get("required", []):
        if req not in data:
            errors.append(f"agent-roster.json missing required key {req!r}")

    roles_schema = schema["properties"]["roles"]["properties"]
    role_def = schema["definitions"]["role"]
    cap_enum = set(role_def["properties"]["capabilities"]["items"]["enum"])

    roles = data.get("roles", {})
    if not isinstance(roles, dict):
        errors.append('agent-roster.json "roles" must be an object')
        return errors
    unknown = set(roles.keys()) - set(roles_schema.keys())
    if unknown:
        errors.append(f"agent-roster.json roles has unknown keys: {sorted(unknown)}")
    for role, entry in roles.items():
        if not isinstance(entry, dict):
            errors.append(f"agent-roster.json roles.{role} must be an object")
            continue
        extra = set(entry.keys()) - {"active", "capabilities"}
        if extra:
            errors.append(f"agent-roster.json roles.{role} has unknown fields: {sorted(extra)}")
        if "active" not in entry or not isinstance(entry["active"], bool):
            errors.append(f"agent-roster.json roles.{role}.active must be a boolean")
        if "capabilities" in entry:
            caps = entry["capabilities"]
            if not isinstance(caps, list) or not all(c in cap_enum for c in caps):
                errors.append(f"agent-roster.json roles.{role}.capabilities must be an array of {sorted(cap_enum)}")
            elif len(caps) != len(set(caps)):
                errors.append(f"agent-roster.json roles.{role}.capabilities must have unique entries")
    return errors


def has_empty_custom_gate_script(gates):
    """Refuse to write a custom gate with a known-empty "script" — it
    passes schema validation (script just has to be a string) but fails
    pipeline/run.py's own runtime preflight the first time it actually
    runs. Same policy specialize.sh applied to every resolution path
    (preset, env-override, interactive)."""
    for g in gates:
        if isinstance(g, dict) and g.get("name") == "custom":
            script = g.get("script", "")
            if not isinstance(script, str) or not script.strip():
                return True
    return False


def validate_gate_entries(gates, known_gates):
    """Direct transliteration of specialize.sh's generated-gate-config
    validation heredoc, plus the repo-relocatability check (reject
    absolute script/cwd) neither run.sh/run.py nor the JSON Schema itself
    enforces structurally. Returns a list of error strings (empty =
    valid)."""
    errors = []
    if not isinstance(gates, list):
        return ['generated gate-config "gates" must be an array']
    for i, gate in enumerate(gates):
        if isinstance(gate, str):
            if gate not in known_gates:
                errors.append(f"gates[{i}] unknown gate name {gate!r} (expected one of {known_gates} or a custom object)")
            continue
        if isinstance(gate, dict):
            if gate.get("name") != "custom":
                errors.append(f'gates[{i}] object gate must have "name": "custom"')
                continue
            script = gate.get("script")
            if not isinstance(script, str) or not script:
                errors.append(f'gates[{i}] custom gate missing required string "script"')
            elif not is_repo_relative(script):
                errors.append(f'gates[{i}] custom gate "script" must be repo-root-relative, not absolute: {script!r}')
            cwd = gate.get("cwd", ".")
            if not isinstance(cwd, str):
                errors.append(f'gates[{i}] custom gate "cwd" must be a string')
            elif not is_repo_relative(cwd):
                errors.append(f'gates[{i}] custom gate "cwd" must be repo-root-relative, not absolute: {cwd!r}')
            args = gate.get("args", [])
            if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
                errors.append(f'gates[{i}] custom gate "args" must be an array of strings')
            extra = set(gate.keys()) - {"name", "script", "cwd", "args"}
            if extra:
                errors.append(f"gates[{i}] custom gate has unknown fields: {sorted(extra)}")
            continue
        errors.append(f"gates[{i}] must be a known gate name or a custom gate object")
    return errors


def run_interactive(all_roles, known_gates, skill_dirs, read_line):
    """Core interactive-checkbox logic, fully injectable (a zero-arg
    read_line callable) so a test can exercise every branch without a real
    TTY (same shape as human_gate.decide()'s injectable reader).
    read_line() raising EOFError is treated as an empty reply, matching
    bash's `read -r || reply=""`.

    Bash parity traps, deliberately preserved: `read -r` trims surrounding
    whitespace (verified empirically against real bash — not assumed), and
    bash `case` is case-sensitive, so only the literal strings n/N/no/NO
    decline a [Y/n] prompt and only y/Y/yes/YES accept a [y/N] prompt —
    e.g. "No" (mixed case) is NOT a decline, it falls through to accept.
    """
    def ask(prompt, default_yes):
        print(prompt, end="")
        sys.stdout.flush()
        try:
            reply = read_line()
        except EOFError:
            reply = ""
        reply = reply.strip()
        if default_yes:
            return reply not in ("n", "N", "no", "NO")
        return reply in ("y", "Y", "yes", "YES")

    print("→ Roles — keep which of the 6 roles in this fork?")
    sel_roles = [r for r in all_roles if ask(f"  [x] Enable {r}? [Y/n]: ", True)]
    print()

    print("→ Gates — which apply after the coder step?")
    gate_entries = []
    for gate in known_gates:
        if gate in A11Y_GATES:
            if ask(f"  [ ] Enable {gate} gate? [y/N]: ", False):
                gate_entries.append(gate)
            continue
        if ask(f"  [x] Enable {gate} gate? [Y/n]: ", True):
            gate_entries.append(gate)

    custom = None
    if ask("  [ ] Add one custom gate? [y/N]: ", False):
        print("    Script (repo-root-relative to target repo, blank to fill in later): ", end="")
        sys.stdout.flush()
        try:
            cscript = read_line()
        except EOFError:
            cscript = ""
        cscript = cscript.strip()
        print("    Working dir (repo-root-relative, default .): ", end="")
        sys.stdout.flush()
        try:
            ccwd = read_line()
        except EOFError:
            ccwd = ""
        ccwd = ccwd.strip() or "."
        custom = {"name": "custom", "script": cscript, "cwd": ccwd, "args": []}
    if custom is not None:
        gate_entries.append(custom)
    print()

    print("→ Skills — which skill dirs under skills/ to keep? (config-only gate; files are never deleted)")
    sel_skills = [s for s in skill_dirs if ask(f"  [x] Enable {s}? [Y/n]: ", True)]

    return sel_roles, gate_entries, sel_skills


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv

    if not argv:
        preset = ""
    elif argv[0] == "--help":
        print(HELP_TEXT)
        return 0
    elif argv[0] == "--preset":
        if len(argv) < 2:
            print("usage: specialize.py --preset <name>", file=sys.stderr)
            return 1
        preset = argv[1]
    elif argv[0].startswith("--"):
        print(f"Unknown flag: {argv[0]}", file=sys.stderr)
        print(HELP_TEXT.splitlines()[0], file=sys.stderr)
        return 1
    else:
        # specialize.sh has no catch-all case branch here either — a bare
        # non-flag positional crashes it (`PRESET: unbound variable` under
        # set -u; confirmed empirically, rc=1). This port refuses the same
        # invocation just as loudly, with a clearer message, same rc.
        print(f"specialize.py: unexpected argument: {argv[0]!r} (expected --preset <name> or no arguments)", file=sys.stderr)
        return 1

    # Clear the preset marker before writing anything else: if this run
    # fails partway, gen_governance.py falls back to no role_notes overlay
    # instead of applying a previous preset's notes to a new roster.
    try:
        ACTIVE_PRESET_OUT.unlink()
    except FileNotFoundError:
        pass

    all_roles = load_all_roles()
    known_gates = load_known_gates()
    skill_dirs = skill_dirs_present()

    print("=" * 50)
    print(" Agentic Light — specialize")
    print(f" Workspace: {ROOT}")
    print("=" * 50)
    print()

    sel_roles = []
    sel_gates = []
    sel_skills = []

    if preset:
        if not PRESETS_FILE.is_file():
            print(f"FAILED: {PRESETS_FILE} not found", file=sys.stderr)
            return 1
        presets = json.loads(PRESETS_FILE.read_text(encoding="utf-8"))
        if preset not in presets:
            print(f"FAILED: unknown preset {preset!r} (known: {', '.join(sorted(presets))})", file=sys.stderr)
            return 1
        p = presets[preset]
        sel_roles = list(p.get("roles", []))
        sel_gates = list(p.get("gates", []))
        skills = p.get("skills", [])
        sel_skills = list(skill_dirs) if skills == "*" else list(skills)
        skills_gap_note = p.get("skills_gap_note", "")
        preset_requires = list(p.get("requires", []))
        role_caps_overlay = dict(p.get("role_capabilities", {}))
        print(f"→ Using preset: {preset}")
        if skills_gap_note:
            print(f"Note: this preset ships no skill content yet ({skills_gap_note}) — agents will work from base instructions only.")
        if preset_requires:
            print(f"Note: this preset's skills require: {', '.join(preset_requires)} — make sure your provider has it configured (not detected or checked here).")
    elif os.environ.get("AGENTIC_LIGHT_ROLES") or os.environ.get("AGENTIC_LIGHT_GATES") or os.environ.get("AGENTIC_LIGHT_SKILLS"):
        # Roles/skills: comma -> space, then whitespace-split (mirrors bash
        # `tr ',' ' '` + unquoted word-splitting — collapses runs, drops
        # empties). Gates: split(",") only, empties dropped, NOT stripped —
        # a real bash-parity trap: "eslint, playwright" (space after comma)
        # yields ["eslint", " playwright"] with the leading space intact,
        # same as the bash heredoc's `'...'.split(',')`.
        sel_roles = os.environ.get("AGENTIC_LIGHT_ROLES", "").replace(",", " ").split()
        sel_skills = os.environ.get("AGENTIC_LIGHT_SKILLS", "").replace(",", " ").split()
        gates_env = os.environ.get("AGENTIC_LIGHT_GATES", "")
        sel_gates = [g for g in gates_env.split(",") if g] if gates_env else []
        role_caps_overlay = {}
        print("→ Using env overrides.")
    elif sys.stdin.isatty():
        sel_roles, sel_gates, sel_skills = run_interactive(all_roles, known_gates, skill_dirs, input)
        role_caps_overlay = {}
    else:
        print("FAILED: non-interactive session with no --preset and no AGENTIC_LIGHT_* overrides.", file=sys.stderr)
        return 1

    if has_empty_custom_gate_script(sel_gates):
        print('FAILED: custom gate has an empty "script" field.', file=sys.stderr)
        print("pipeline/run.py will fail this gate the first time it actually runs.", file=sys.stderr)
        print("Fix: supply a script path now (rerun with a filled-in custom gate),", file=sys.stderr)
        print("or choose a preset/gate list without a custom gate.", file=sys.stderr)
        return 1

    for role in sel_roles:
        if role not in all_roles:
            print(f"FAILED: unknown role {role!r} — must be one of: {all_roles}", file=sys.stderr)
            return 1

    # agent-roster.json
    schema = json.loads(ROSTER_SCHEMA.read_text(encoding="utf-8"))
    roster = build_roster(all_roles, set(sel_roles), role_caps_overlay)
    errors = validate_roster(roster, schema)
    if errors:
        for e in errors:
            print(f"FAILED: {e}", file=sys.stderr)
        return 1
    _atomic_write_text(ROSTER_OUT, json.dumps(roster, indent=2) + "\n")
    print(f"→ Wrote {ROSTER_OUT}")

    # pipeline/gate-config.json
    gate_errors = validate_gate_entries(sel_gates, known_gates)
    if gate_errors:
        for e in gate_errors:
            print(f"FAILED: {e}", file=sys.stderr)
        return 1
    _atomic_write_text(GATE_OUT, json.dumps({"gates": sel_gates}, indent=2) + "\n")
    print(f"→ Wrote {GATE_OUT}")

    # System_Config/skills-selected.json — route_skill.py restricts its scan
    # to these dirs; files under skills/ are never deleted.
    _atomic_write_text(SKILLS_OUT, json.dumps({"selected": sorted(sel_skills)}, indent=2) + "\n")
    print(f"→ Wrote {SKILLS_OUT} (route_skill.py restricts its scan to these dirs)")

    # System_Config/.active-preset — only for the --preset path, written
    # last, after every other output has succeeded. No trailing newline
    # (matches specialize.sh's `printf '%s' "$PRESET"`).
    if preset:
        _atomic_write_text(ACTIVE_PRESET_OUT, preset)
        print(f"→ Wrote {ACTIVE_PRESET_OUT}")

    print()
    print("=" * 50)
    print(" Done.")
    print("=" * 50)
    print(f" Roles:  {' '.join(sel_roles) if sel_roles else '<none>'}")
    print(f" Gates:  {json.dumps(sel_gates)}")
    print(f" Skills: {' '.join(sorted(sel_skills)) if sel_skills else '<none>'}")
    return 0


def _build_workspace(tmp, fixture_name, skill_names=None):
    """Real-enough temp workspace: this repo's own presets.json/schemas/
    example (copied verbatim — white_label_check.py's own precedent is to
    use the live preset entry, not a hand-copied paraphrase) plus empty
    skill dirs (specialize.py only ever reads skill *directory names*, never
    SKILL.md content, so an empty dir is sufficient) and a copy of this
    script itself so its __file__-relative ROOT resolves inside `tmp`
    (same strategy as log_session.py's self-test). Returns the workspace
    root Path.
    """
    root = Path(tmp) / fixture_name
    (root / "System_Config").mkdir(parents=True)
    (root / "pipeline").mkdir()
    (root / "skills").mkdir()
    shutil.copy(Path(__file__), root / "System_Config" / "specialize.py")
    for name in ("presets.json", "agent-roster.schema.json", "gate-config.schema.json", "agent-roster.example.json"):
        shutil.copy(SYSCFG / name, root / "System_Config" / name)
    for skill in (skill_names if skill_names is not None else skill_dirs_present()):
        (root / "skills" / skill).mkdir()
    return root


def _run_in(root, args, input_text=None, extra_env=None):
    """Subprocess invocation of the copied specialize.py inside `root`,
    stripped of any AGENTIC_LIGHT_* env leakage from the real shell (a
    stray override would silently change a fixture's resolution path) and
    guarded with a hard timeout + non-blocking stdin (the prior dispatch
    attempt on this exact task stalled with no output for 10 minutes,
    almost certainly an unguarded interactive prompt)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTIC_LIGHT_")}
    env["PYTHONUTF8"] = "1"
    if extra_env:
        env.update(extra_env)
    kwargs = dict(capture_output=True, encoding="utf-8", cwd=str(root), env=env, timeout=15)
    if input_text is not None:
        kwargs["input"] = input_text
    else:
        kwargs["stdin"] = subprocess.DEVNULL
    return subprocess.run([sys.executable, str(root / "System_Config" / "specialize.py"), *args], **kwargs)


def self_test():
    failures = []

    def check(label, cond, detail=""):
        if not cond:
            failures.append(f"{label}: {detail}")
        else:
            print(f"specialize: self-test fixture ok: {label}")

    example_caps = default_capabilities_map()
    real_presets = json.loads(PRESETS_FILE.read_text(encoding="utf-8"))

    with tempfile.TemporaryDirectory() as tmp:
        # Fixtures 1/2: --preset design-harness / wcag-harness — proves the
        # role_capabilities overlay actually lands in the written
        # agent-roster.json (not just accepted and discarded), that a role
        # the overlay doesn't mention (coder) falls back to the example's
        # defaults, that roles outside the preset are present but inactive,
        # and that role_handoff — which stays in presets.json only — never
        # appears in agent-roster.json's own text.
        for preset_name in ("design-harness", "wcag-harness"):
            root = _build_workspace(tmp, f"fixture-{preset_name}")
            proc = _run_in(root, ["--preset", preset_name])
            check(f"{preset_name}: rc == 0", proc.returncode == 0, proc.stdout + proc.stderr)
            roster_path = root / "System_Config" / "agent-roster.json"
            check(f"{preset_name}: agent-roster.json written", roster_path.is_file())
            if not roster_path.is_file():
                continue
            roster_text = roster_path.read_text(encoding="utf-8")
            roster = json.loads(roster_text)
            overlay = real_presets[preset_name]["role_capabilities"]
            for role, caps in overlay.items():
                got = roster["roles"][role].get("capabilities")
                check(f"{preset_name}: {role} capabilities from overlay", got == caps, got)
            check(f"{preset_name}: creative-director overlay differs from example default",
                  roster["roles"]["creative-director"]["capabilities"] != example_caps.get("creative-director"),
                  roster["roles"]["creative-director"]["capabilities"])
            check(f"{preset_name}: coder (not in overlay) falls back to example default",
                  roster["roles"]["coder"].get("capabilities") == example_caps.get("coder"),
                  roster["roles"]["coder"].get("capabilities"))
            for inactive_role in ("curator", "eng-manager"):
                check(f"{preset_name}: {inactive_role} present but inactive",
                      roster["roles"][inactive_role]["active"] is False,
                      roster["roles"][inactive_role])
            check(f"{preset_name}: role_handoff never written into agent-roster.json",
                  "role_handoff" not in roster_text, roster_text)
            active_path = root / "System_Config" / ".active-preset"
            check(f"{preset_name}: .active-preset written with no trailing newline",
                  active_path.is_file() and active_path.read_bytes() == preset_name.encode("utf-8"),
                  active_path.read_bytes() if active_path.is_file() else None)
            gate_path = root / "pipeline" / "gate-config.json"
            check(f"{preset_name}: gate-config.json written", gate_path.is_file())

        # Fixture 3: unknown preset name fails cleanly — nonzero exit,
        # explanatory stderr, and NOT ONE output file written (the
        # .active-preset clear happens before the lookup, per
        # specialize.sh's own ordering — ported verbatim).
        root = _build_workspace(tmp, "fixture-unknown-preset")
        proc = _run_in(root, ["--preset", "not-a-real-preset"])
        check("unknown preset: rc == 1", proc.returncode == 1, proc.returncode)
        check("unknown preset: stderr mentions unknown preset", "unknown preset" in proc.stderr, proc.stderr)
        for out in ("System_Config/agent-roster.json", "pipeline/gate-config.json",
                    "System_Config/skills-selected.json", "System_Config/.active-preset"):
            check(f"unknown preset: {out} not written", not (root / out).exists())

        # Fixture 4: env-override roles with an embedded space after the
        # comma — bash parity trap (tr ',' ' ' + word-splitting collapses
        # it; a naive split(",") would leave a stray leading space).
        root = _build_workspace(tmp, "fixture-env-override")
        proc = _run_in(root, [], extra_env={"AGENTIC_LIGHT_ROLES": "coder, qa", "AGENTIC_LIGHT_GATES": "", "AGENTIC_LIGHT_SKILLS": ""})
        check("env-override: rc == 0", proc.returncode == 0, proc.stdout + proc.stderr)
        roster = json.loads((root / "System_Config" / "agent-roster.json").read_text(encoding="utf-8"))
        active = {r for r, v in roster["roles"].items() if v["active"]}
        check("env-override: 'coder, qa' (embedded space) resolves to exactly {coder, qa}", active == {"coder", "qa"}, active)
        check("env-override: no .active-preset written (not a named preset)", not (root / "System_Config" / ".active-preset").exists())

        # Fixture 5: unknown role via env-override fails cleanly.
        root = _build_workspace(tmp, "fixture-unknown-role")
        proc = _run_in(root, [], extra_env={"AGENTIC_LIGHT_ROLES": "not-a-real-role", "AGENTIC_LIGHT_GATES": "", "AGENTIC_LIGHT_SKILLS": ""})
        check("unknown role: rc == 1", proc.returncode == 1, proc.returncode)
        check("unknown role: stderr mentions unknown role", "unknown role" in proc.stderr, proc.stderr)

        # Fixture 6: non-interactive session, no preset, no env overrides —
        # must fail cleanly, not hang (stdin=DEVNULL makes isatty() False).
        root = _build_workspace(tmp, "fixture-non-interactive")
        proc = _run_in(root, [])
        check("non-interactive no-args: rc == 1", proc.returncode == 1, proc.returncode)
        check("non-interactive no-args: explains why", "non-interactive session" in proc.stderr, proc.stderr)

        # Fixture 7: unknown flag exits 1 (not swallowed, not argparse's
        # own exit-2 "unrecognized arguments").
        root = _build_workspace(tmp, "fixture-unknown-flag")
        proc = _run_in(root, ["--bogus"])
        check("unknown flag: rc == 1", proc.returncode == 1, proc.returncode)
        check("unknown flag: message names the flag", "Unknown flag: --bogus" in proc.stderr, proc.stderr)

        # Fixture 8: --help exits 0 with usage text, touches nothing.
        root = _build_workspace(tmp, "fixture-help")
        proc = _run_in(root, ["--help"])
        check("--help: rc == 0", proc.returncode == 0, proc.returncode)
        check("--help: usage text", "Usage:" in proc.stdout, proc.stdout)

    # Fixture 9: custom gate with an empty script is rejected (pure
    # function, no subprocess needed).
    check("empty custom-gate script detected", has_empty_custom_gate_script([{"name": "custom", "script": ""}]))
    check("filled custom-gate script not flagged", not has_empty_custom_gate_script([{"name": "custom", "script": "tools/gate.py"}]))
    check("known gate name not flagged", not has_empty_custom_gate_script(["eslint"]))

    # Fixture 10: absolute-path rejection, both POSIX and Windows shapes,
    # regardless of host OS (blueprint §2).
    check("is_repo_relative: relative path", is_repo_relative("tools/gate.py"))
    check("is_repo_relative: POSIX absolute rejected", not is_repo_relative("/etc/passwd"))
    check("is_repo_relative: Windows absolute rejected", not is_repo_relative("C:\\Windows\\gate.py"))
    check("is_repo_relative: UNC-style rejected", not is_repo_relative("\\\\server\\share\\gate.py"))
    gate_errors = validate_gate_entries([{"name": "custom", "script": "/etc/passwd"}], ("eslint",))
    check("validate_gate_entries flags absolute script", any("not absolute" in e for e in gate_errors), gate_errors)

    # Fixture 11: interactive path, injectable reader — no real TTY. Covers
    # EOFError-as-empty-reply (bash `read -r || reply=""`) and the
    # case-sensitive bash `case` quirk: "No" (mixed case) is NOT one of the
    # literal n/N/no/NO patterns, so it falls through to accept, same as a
    # real bash run (verified empirically against the .sh original).
    all_roles = load_all_roles()
    known_gates = load_known_gates()
    replies = iter(["No", "n", "N", "no", "NO"])  # only 4 of these actually decline
    sel_roles, sel_gates, sel_skills = run_interactive(all_roles, known_gates, ["skill-a", "skill-b"], lambda: next(replies, ""))
    check("interactive: 'No' (mixed case) does not decline", "architect" in sel_roles, sel_roles)
    check("interactive: exact n/N/no/NO all decline", len(sel_roles) < len(all_roles), sel_roles)

    def eof_reader():
        raise EOFError
    sel_roles2, sel_gates2, sel_skills2 = run_interactive(all_roles, known_gates, ["skill-a"], eof_reader)
    check("interactive EOF: [Y/n] prompts default to yes (all roles kept)", set(sel_roles2) == set(all_roles), sel_roles2)
    check("interactive EOF: [y/N] a11y gates default to no", not any(g in A11Y_GATES for g in sel_gates2 if isinstance(g, str)), sel_gates2)
    check("interactive EOF: custom-gate-add defaults to no", not any(isinstance(g, dict) for g in sel_gates2), sel_gates2)
    check("interactive EOF: [Y/n] skills default to yes", set(sel_skills2) == {"skill-a"}, sel_skills2)

    if failures:
        print("specialize: self-test FAILED:", file=sys.stderr)
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
