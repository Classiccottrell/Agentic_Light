#!/usr/bin/env python3
"""Validate preset rosters without adding a runtime dependency."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRESETS = ROOT / "System_Config" / "presets.json"
AGENTS = ROOT / "agents"
SKILLS = ROOT / "skills"
ROSTER_SCHEMA = ROOT / "System_Config" / "agent-roster.schema.json"
KNOWN_GATES = {"eslint", "playwright", "axe", "vpat-lint"}
KNOWN_ROLES = {p.stem for p in AGENTS.glob("*.md") if p.name != "README.md"}
FALLBACK_CAPABILITIES = {"read", "write", "shell", "delegate"}


def known_capabilities():
    """Live from agent-roster.schema.json's capability enum; fall back to the
    hardcoded 4 if the schema is missing/unreadable rather than hard-failing
    every preset check on an unrelated schema problem."""
    try:
        schema = json.loads(ROSTER_SCHEMA.read_text())
        return set(schema["definitions"]["role"]["properties"]["capabilities"]["items"]["enum"])
    except Exception:
        return set(FALLBACK_CAPABILITIES)


def fail(message):
    print(f"preset_audit: FAIL: {message}", file=sys.stderr)
    return 1


def audit():
    try:
        presets = json.loads(PRESETS.read_text())
    except Exception as exc:
        return fail(f"cannot read presets.json: {exc}")
    errors = []
    for name, preset in presets.items():
        roles = preset.get("roles")
        if not isinstance(roles, list) or not roles or len(roles) != len(set(roles)):
            errors.append(f"{name}: roles must be a non-empty unique list")
        for role in roles or []:
            if role not in KNOWN_ROLES:
                errors.append(f"{name}: unknown role {role}")
        for gate in preset.get("gates", []):
            gate_name = gate if isinstance(gate, str) else gate.get("name")
            if gate_name not in KNOWN_GATES and gate_name != "custom":
                errors.append(f"{name}: unknown gate {gate_name}")
        for skill in preset.get("skills", []):
            if skill != "*" and not (SKILLS / skill / "SKILL.md").is_file():
                errors.append(f"{name}: missing skill {skill}")
        for role in preset.get("role_notes", {}):
            if role not in (roles or []):
                errors.append(f"{name}: role_notes contains inactive role {role}")
        for role in preset.get("role_capabilities", {}):
            if role not in (roles or []):
                errors.append(f"{name}: role_capabilities contains inactive role {role}")
        for role in preset.get("role_handoff", {}):
            if role not in (roles or []):
                errors.append(f"{name}: role_handoff contains inactive role {role}")
        if name in {"design-harness", "wcag-harness"}:
            missing = set(roles or []) - set(preset.get("role_notes", {})) - {"coder"}
            if missing:
                errors.append(f"{name}: missing focused role_notes for {sorted(missing)}")
            note_keys = set(preset.get("role_notes", {}))
            caps_keys = set(preset.get("role_capabilities", {}))
            handoff_keys = set(preset.get("role_handoff", {}))
            if caps_keys != note_keys:
                errors.append(f"{name}: role_capabilities keys {sorted(caps_keys)} != role_notes keys {sorted(note_keys)}")
            if handoff_keys != note_keys:
                errors.append(f"{name}: role_handoff keys {sorted(handoff_keys)} != role_notes keys {sorted(note_keys)}")
            cap_enum = known_capabilities()
            for role, caps in preset.get("role_capabilities", {}).items():
                if not isinstance(caps, list) or not caps:
                    errors.append(f"{name}: role_capabilities[{role}] must be a non-empty list")
                    continue
                if len(caps) != len(set(caps)):
                    errors.append(f"{name}: role_capabilities[{role}] has duplicate entries")
                unknown_caps = set(caps) - cap_enum
                if unknown_caps:
                    errors.append(f"{name}: role_capabilities[{role}] has unknown capabilities {sorted(unknown_caps)}")
            active_roles = set(roles or [])
            for role, target in preset.get("role_handoff", {}).items():
                if target != "orchestrator" and target not in active_roles:
                    errors.append(f"{name}: role_handoff[{role}] targets {target!r}, not an active role or \"orchestrator\"")
    if errors:
        for error in errors:
            print(f"preset_audit: FAIL: {error}", file=sys.stderr)
        return 1
    print(f"preset_audit: PASS: {len(presets)} presets; focused rosters valid")
    return 0


if __name__ == "__main__":
    sys.exit(audit())
