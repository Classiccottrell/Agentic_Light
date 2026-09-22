#!/usr/bin/env python3
"""Audit a specialized fork after white-label pruning."""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

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
            capture_output=True, text=True,
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
        roster = json.loads((config / "agent-roster.json").read_text())
        presets = json.loads((config / "presets.json").read_text())
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
        selected = set(json.loads(selected_path.read_text()).get("selected", []))
        on_disk = {p.name for p in (root / "skills").iterdir() if p.is_dir() and (p / "SKILL.md").exists()}
        if selected != on_disk:
            errors.append(f"selected skills {sorted(selected)} != on-disk skills {sorted(on_disk)}")
    generated = [root / "README.md", root / "CLAUDE.md", root / "GOVERNANCE.md", root / "microsite"]
    for path in generated:
        paths = [path] if path.is_file() else list(path.rglob("*.html"))
        for file in paths:
            text = file.read_text(errors="replace")
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
    microsite/index.html, then actually runs all 3 generators.

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
        src = (REAL_ROOT / rel).read_text()
        (root / rel).write_text(src.replace("Agentic Light", fixture_name))

    (root / "System_Config" / "agent-roster.schema.json").write_text(
        (REAL_ROOT / "System_Config" / "agent-roster.schema.json").read_text()
    )

    real_presets = json.loads((REAL_ROOT / "System_Config" / "presets.json").read_text())
    preset = dict(real_presets[preset_name])
    if roles is not None:
        preset["roles"] = roles
    roles = preset.get("roles", [])
    (root / "System_Config" / "presets.json").write_text(
        json.dumps({preset_name: preset}, indent=2)
    )

    all_roles = ("architect", "coder", "creative-director", "curator", "eng-manager", "qa")
    roster = {"roles": {r: {"active": r in roles} for r in all_roles}}
    (root / "System_Config" / "agent-roster.json").write_text(json.dumps(roster, indent=2))
    (root / "System_Config" / ".active-preset").write_text(preset_name)

    for role in roles:
        (root / "agents" / f"{role}.md").write_text(
            "---\n"
            f"name: {role}\n"
            f"description: {role} role for {fixture_name}'s {preset_name} harness.\n"
            "tools: Read, Write\n"
            "---\n"
            f"# {role}\n"
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
        "</body></html>\n"
    )

    (root / "README.md").write_text(fixture_name + " — README.\n")
    (root / "CLAUDE.md").write_text(fixture_name + " — CLAUDE context.\n")

    for name in GENERATORS:
        proc = subprocess.run(
            [sys.executable, str(root / "System_Config" / name)],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"_build_clean_fork: {name} failed: {proc.stdout}{proc.stderr}")

    return root


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
        (root3 / "README.md").write_text("StaleName — leftover Agentic Light reference.\n")
        errors3 = audit(root3, "StaleName", "wcag-harness")
        check(
            "stale old-name text is caught",
            any("old identity remains in README.md" in e for e in errors3),
            errors3,
        )

        # Fixture 4: roster/preset mismatch (an extra active role not in
        # the preset's own roster) must be caught.
        root4 = _build_clean_fork(tmp, "RosterMismatch", "wcag-harness")
        roster4 = json.loads((root4 / "System_Config" / "agent-roster.json").read_text())
        roster4["roles"]["curator"]["active"] = True
        (root4 / "System_Config" / "agent-roster.json").write_text(json.dumps(roster4, indent=2))
        (root4 / "agents" / "curator.md").write_text(
            "---\nname: curator\ndescription: curator for RosterMismatch.\ntools: Read\n---\n# curator\n"
        )
        errors4 = audit(root4, "RosterMismatch", "wcag-harness")
        check(
            "roster/preset mismatch is caught",
            any("active roster" in e and "!= preset roster" in e for e in errors4),
            errors4,
        )

        # Fixture 5: generated-output staleness (an agent's description:
        # edited post-generation, so the already-rendered index.html
        # disagrees with agents/*.md) must be caught by
        # _check_generated_output's gen_site.py --check call.
        root5 = _build_clean_fork(tmp, "StaleOutput", "wcag-harness")
        (root5 / "agents" / "coder.md").write_text(
            "---\nname: coder\ndescription: a materially different description now.\ntools: Read, Write\n---\n# coder\n"
        )
        errors5 = audit(root5, "StaleOutput", "wcag-harness")
        check(
            "generated-output staleness is caught",
            any("generated output stale (gen_site.py)" in e for e in errors5),
            errors5,
        )

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
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
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
    raise SystemExit(main())
