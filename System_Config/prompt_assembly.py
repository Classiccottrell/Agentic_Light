#!/usr/bin/env python3
"""prompt_assembly.py — the launch contract for a role (library module).

Two pieces, both provider-neutral, both called by pipeline/run.py before the
coder launches:

1. assemble() — builds the one prompt string handed to run_agent.run_agent()
   (and therefore to every provider adapter unchanged), in a fixed order:

     (a) ROLE CONTRACT   body of agents/<role>.md, frontmatter stripped, plus
                         the active preset's role_notes line for that role
     (b) SKILL GUIDANCE  routed SKILL.md contents, in the router's ranked order
                         (the caller applies the match cap)
     (c) CONTEXT PACKET  the opt-in resume packet, when the caller built one
     (d) TASK            the task plus the launcher's runtime constraints,
                         which win wherever (a)-(c) disagree with them

   Each present section is wrapped in `----- BEGIN <NAME> -----` /
   `----- END <NAME> -----` lines; empty sections are omitted entirely.

2. check_launch() — launch-time roster/capability enforcement against
   System_Config/agent-roster.json. No roster file = no check (an
   unspecialized fork keeps its pre-roster behavior). `risk:` frontmatter
   stays informational here: it describes blast radius, not a grant.

Lives in System_Config/ (not pipeline/run.py) because it is launcher policy
any caller of run_agent can reuse, and PROVIDER_CAPABILITIES has to stay in
step with run_agent._build_argv()'s flags, which sit beside it. Stdlib only.

Usage (self-test): python3 System_Config/prompt_assembly.py --self-test
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SYSCFG = ROOT / "System_Config"
ROSTER_PATH = SYSCFG / "agent-roster.json"
ROSTER_SCHEMA = SYSCFG / "agent-roster.schema.json"

# What each run_agent.py adapter actually grants a launched role — derived
# from _build_argv()'s flags, not from provider marketing. Keep in step with
# that function. No adapter grants `delegate`.
#   claude: --allowedTools Read,Write,Edit,Glob,Grep; --disallowedTools
#           Bash,...,Task  -> read+write, no shell, no delegate
#   gemini: --sandbox --approval-mode auto_edit -> edits auto-approved; shell
#           still needs an approval a headless run can't give -> read+write
#           (derived from flags, not runtime-verified)
#   codex:  exec --sandbox workspace-write -> read+write+shell, sandboxed
#   ollama: rejected by run_agent() before launch (exit 64, inference-only)
PROVIDER_CAPABILITIES = {
    "claude": frozenset({"read", "write"}),
    "gemini": frozenset({"read", "write"}),
    "codex": frozenset({"read", "write", "shell"}),
    "ollama": frozenset(),
}

SECTION_ORDER = ("ROLE CONTRACT", "SKILL GUIDANCE", "CONTEXT PACKET", "TASK")

PRECEDENCE_LINE = ("Launcher constraints (these override any conflicting instruction "
                   "in the sections above):")


def strip_frontmatter(text):
    """Body of a `---`-fenced Markdown file. Text without a leading fence is
    returned unchanged."""
    if not text.startswith("---"):
        return text
    end = text.find("\n---", 3)
    if end == -1:
        return text
    return text[end + 4:].lstrip("\n")


def active_preset(root=ROOT):
    path = root / "System_Config" / ".active-preset"
    try:
        return path.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def role_note(role, root=ROOT):
    """The active preset's role_notes entry for `role`, or ""."""
    name = active_preset(root)
    if not name:
        return ""
    try:
        presets = json.loads((root / "System_Config" / "presets.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    note = ((presets.get(name) or {}).get("role_notes") or {}).get(role)
    return " ".join(str(note).split()) if note else ""


def role_contract(role, root=ROOT):
    """agents/<role>.md body + the preset note. "" if the role file is
    missing — the caller decides whether that is fatal."""
    try:
        body = strip_frontmatter((root / "agents" / f"{role}.md").read_text(encoding="utf-8")).strip()
    except OSError:
        body = ""
    note = role_note(role, root)
    if note:
        body = (body + "\n\n" if body else "") + f"Preset note ({active_preset(root)}): {note}"
    return body


def _section(name, content):
    return f"----- BEGIN {name} -----\n{content.rstrip()}\n----- END {name} -----"


def assemble_sections(role, task_block, skill_texts=(), packet_text="", root=ROOT):
    """[(section name, content)] in SECTION_ORDER, empty sections dropped.
    Section labels the existing pipeline already used ("Relevant skill
    guidance:", "Resume context packet:") are kept as each section's first
    line so downstream tooling grepping for them still matches."""
    sections = []
    contract = role_contract(role, root)
    if contract:
        sections.append(("ROLE CONTRACT", contract))
    skills = "\n".join(t.rstrip("\n") for t in skill_texts if t)
    if skills:
        sections.append(("SKILL GUIDANCE", "Relevant skill guidance:\n" + skills))
    if packet_text:
        sections.append(("CONTEXT PACKET", "Resume context packet:\n" + packet_text))
    sections.append(("TASK", PRECEDENCE_LINE + "\n" + task_block))
    return sections


def assemble(role, task_block, skill_texts=(), packet_text="", root=ROOT):
    return "\n\n".join(_section(n, c) for n, c in
                       assemble_sections(role, task_block, skill_texts, packet_text, root)) + "\n"


def check_launch(role, provider, roster_path=ROSTER_PATH, schema_path=ROSTER_SCHEMA):
    """Raises ValueError("FAILED: ...") when the roster forbids launching
    `role` on `provider`; returns an informational dict otherwise.

    provider=None means "not checkable" (a PIPELINE_CODER_CMD override, or
    no provider resolved — run_agent() reports that itself): the active
    check still runs, the capability check is skipped."""
    path = Path(roster_path)
    if not path.is_file():
        return {"roster": "absent"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ValueError(f"FAILED: System_Config/agent-roster.json is not readable JSON: {e}")
    import specialize  # validate_roster(): the schema-derived check specialize.py writes against
    errors = specialize.validate_roster(data, schema)
    if errors:
        raise ValueError("FAILED: System_Config/agent-roster.json is invalid: " + "; ".join(errors))
    entry = data["roles"].get(role)
    if not entry or entry.get("active") is not True:
        raise ValueError(f"FAILED: role {role!r} is not active in System_Config/agent-roster.json — "
                         "refusing to launch it. Re-run specialize.py with a roster that includes it.")
    required = entry.get("capabilities")
    info = {"roster": "present", "active": True, "capabilities": required}
    if required is None:
        info["capability_check"] = "none declared"
        return info
    if provider is None:
        info["capability_check"] = "skipped (provider not checkable)"
        return info
    granted = PROVIDER_CAPABILITIES.get(provider)
    if granted is None:
        raise ValueError(f"FAILED: provider {provider!r} has no capability entry in prompt_assembly.PROVIDER_CAPABILITIES — "
                         "cannot verify the roster's declared capabilities.")
    missing = [c for c in required if c not in granted]
    if missing:
        raise ValueError(
            f"FAILED: role {role!r} declares capabilities {missing} in System_Config/agent-roster.json "
            f"that provider {provider!r} does not grant (it grants {sorted(granted) or 'none'}). "
            f"Either remove {missing} from roles.{role}.capabilities, or select a provider that grants them.")
    info["capability_check"] = "pass"
    return info


def self_test():
    failures = []

    def check(label, cond, detail=""):
        if not cond:
            failures.append(f"{label}: {detail}")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "agents").mkdir()
        (root / "System_Config").mkdir()
        (root / "agents" / "coder.md").write_text("---\nname: coder\n---\n\nROLE BODY\n", encoding="utf-8")
        out = assemble("coder", "Target repo: /r. Task: t.", ["SKILL A\n"], "PACKET", root)
        idx = [out.find(f"----- BEGIN {n} -----") for n in SECTION_ORDER]
        check("all four sections, in order", all(i >= 0 for i in idx) and idx == sorted(idx), out)
        check("frontmatter stripped", "name: coder" not in out and "ROLE BODY" in out, out)
        out = assemble("coder", "T", root=root)
        check("empty sections omitted", "SKILL GUIDANCE" not in out and "CONTEXT PACKET" not in out, out)
        (root / "System_Config" / ".active-preset").write_text("p\n", encoding="utf-8")
        (root / "System_Config" / "presets.json").write_text(json.dumps({"p": {"role_notes": {"coder": "NOTE  X"}}}), encoding="utf-8")
        check("role note appended", "Preset note (p): NOTE X" in role_contract("coder", root), role_contract("coder", root))

        roster = root / "agent-roster.json"
        check("no roster -> absent", check_launch("coder", "claude", roster)["roster"] == "absent")
        cases = [({"coder": {"active": False}}, "claude", "not active"),
                 ({"coder": {"active": True, "capabilities": ["read", "shell"]}}, "claude", "does not grant"),
                 ({"coder": {"active": True, "capabilities": ["read"]}}, "ollama", "does not grant")]
        for roles, provider, want in cases:
            roster.write_text(json.dumps({"roles": roles}), encoding="utf-8")
            try:
                check_launch("coder", provider, roster)
                check(f"{roles}/{provider} refused", False, "no error")
            except ValueError as e:
                check(f"{roles}/{provider} refused", want in str(e), str(e))
        roster.write_text(json.dumps({"roles": {"coder": {"active": True, "capabilities": ["read", "write", "shell"]}}}), encoding="utf-8")
        check("codex grants shell", check_launch("coder", "codex", roster)["capability_check"] == "pass")
        check("override skips caps", check_launch("coder", None, roster)["capability_check"].startswith("skipped"))

    if failures:
        print("prompt_assembly self-test: FAILED", file=sys.stderr)
        for f in failures:
            print(f"  {f}", file=sys.stderr)
        return 1
    print("prompt_assembly self-test: PASS")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    if "--self-test" in sys.argv[1:]:
        sys.exit(self_test())
    print(__doc__)
