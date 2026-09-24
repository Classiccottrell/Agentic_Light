#!/usr/bin/env python3
"""axe_gate.py — accessibility gate. Runs the target repo's own a11y script
(package.json scripts["test:a11y"|"a11y"]) and hard-stops (propagates
non-zero) if it fails. No script -> WARN+skip: never invents a URL, never
drives a browser, never installs anything.
Usage: axe_gate.py <target-repo-path>
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

MANUAL_REF = "skills/wcag-audit/references/running-axe.md (in the Agentic Light workspace)"


def extract_script(key, package_json_path):
    try:
        data = json.loads(package_json_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return (data.get("scripts") or {}).get(key) or ""


def has_dep(name, package_json_path):
    try:
        data = json.loads(package_json_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    deps = dict(data.get("dependencies") or {})
    deps.update(data.get("devDependencies") or {})
    return name in deps


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("target_repo")
    args = parser.parse_args()
    target = Path(args.target_repo)

    package_json = target / "package.json"
    a11y_key = ""
    a11y_dep = ""
    if package_json.is_file():
        for key in ("test:a11y", "a11y"):
            if extract_script(key, package_json):
                a11y_key = key
                break
        if not a11y_key:
            for dep in ("@axe-core/cli", "@axe-core/playwright", "pa11y"):
                if has_dep(dep, package_json):
                    a11y_dep = dep
                    break

    if a11y_key:
        print(f"[axe_gate] package.json scripts.{a11y_key} found — running: npm run {a11y_key}")
        npm = shutil.which("npm")
        if npm is None:
            print(f"[axe_gate] FAIL — scripts.{a11y_key} is defined but npm was not found on PATH")
            return 1
        proc = subprocess.run([npm, "run", a11y_key], cwd=str(target), encoding="utf-8")
        if proc.returncode == 0:
            print("[axe_gate] PASS (automated checks catch roughly a third of WCAG AA failures — not a conformance claim)")
            return 0
        print(f"[axe_gate] FAIL — {a11y_key} script exited {proc.returncode}")
        return proc.returncode

    if a11y_dep:
        # @axe-core/cli and pa11y need a URL to scan; @axe-core/playwright is
        # a library called from the repo's own specs (the playwright gate
        # runs those). The repo knows its own URL/server — this gate
        # doesn't guess.
        print(f"[axe_gate] WARN — {a11y_dep} is listed in package.json but there is no scripts.test:a11y or scripts.a11y to run it; no automated accessibility check ran.")
        print(f"[axe_gate]   Add a test:a11y script that starts/targets the app and runs {a11y_dep}, or see {MANUAL_REF} for the manual path. Skipping.")
        return 0

    print("[axe_gate] WARN — no automated accessibility check ran: no scripts.test:a11y/a11y and no @axe-core/cli, @axe-core/playwright, or pa11y dependency found.")
    print(f"[axe_gate]   See {MANUAL_REF} for the manual path. Skipping.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
