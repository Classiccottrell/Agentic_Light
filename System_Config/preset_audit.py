#!/usr/bin/env python3
"""Validate preset rosters without adding a runtime dependency."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRESETS = ROOT / "System_Config" / "presets.json"
AGENTS = ROOT / "agents"
SKILLS = ROOT / "skills"
KNOWN_GATES = {"eslint", "playwright", "axe"}
KNOWN_CAPABILITIES = {"read", "write", "shell", "delegate"}
KNOWN_ROLES = {p.stem for p in AGENTS.glob("*.md") if p.name != "README.md"}


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
        capabilities = preset.get("capabilities", {})
        if not isinstance(capabilities, dict):
            errors.append(f"{name}: capabilities must be an object")
        else:
            for role, granted in capabilities.items():
                if role not in (roles or []):
                    errors.append(f"{name}: capabilities contains inactive role {role}")
                if not isinstance(granted, list) or not granted or len(granted) != len(set(granted)):
                    errors.append(f"{name}: capabilities.{role} must be a non-empty unique list")
                elif any(cap not in KNOWN_CAPABILITIES for cap in granted):
                    errors.append(f"{name}: capabilities.{role} has unknown capability")
        handoff = preset.get("handoff", [])
        if not isinstance(handoff, list):
            errors.append(f"{name}: handoff must be a list")
        for item in handoff if isinstance(handoff, list) else []:
            if not isinstance(item, dict) or item.get("from") not in (roles or []) or item.get("to") not in (roles or []):
                errors.append(f"{name}: handoff entries must connect active roles")
            elif not isinstance(item.get("scope"), list) or not item["scope"]:
                errors.append(f"{name}: handoff scope must be a non-empty list")
        for role in preset.get("role_notes", {}):
            if role not in (roles or []):
                errors.append(f"{name}: role_notes contains inactive role {role}")
        if name in {"design-harness", "wcag-harness"}:
            missing = set(roles or []) - set(preset.get("role_notes", {})) - {"coder"}
            if missing:
                errors.append(f"{name}: missing focused role_notes for {sorted(missing)}")
            missing_caps = set(roles or []) - set(capabilities if isinstance(capabilities, dict) else {})
            if missing_caps:
                errors.append(f"{name}: missing focused capabilities for {sorted(missing_caps)}")
            if not handoff:
                errors.append(f"{name}: focused preset requires handoff contracts")
    if errors:
        for error in errors:
            print(f"preset_audit: FAIL: {error}", file=sys.stderr)
        return 1
    print(f"preset_audit: PASS: {len(presets)} presets; focused rosters valid")
    return 0


if __name__ == "__main__":
    sys.exit(audit())
