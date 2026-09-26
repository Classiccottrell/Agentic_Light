#!/usr/bin/env python3
"""eslint_gate.py — WARN+skip if the target repo has no ESLint setup at all;
hard-stop (propagate non-zero) if a lint config/script exists and fails.
Usage: eslint_gate.py <target-repo-path>
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def extract_script(key, package_json_path):
    """scripts[<key>] from package.json, or "" — native json.load, no jq
    dependency (bash's jq-or-grep/sed fallback is no longer needed)."""
    try:
        data = json.loads(package_json_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return (data.get("scripts") or {}).get(key) or ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("target_repo")
    args = parser.parse_args()
    target = Path(args.target_repo)

    package_json = target / "package.json"
    lint_script = extract_script("lint", package_json) if package_json.is_file() else ""

    if lint_script:
        print("[eslint_gate] package.json scripts.lint found — running: npm run lint")
        npm = shutil.which("npm")
        if npm is None:
            print("[eslint_gate] FAIL — scripts.lint is defined but npm was not found on PATH")
            return 1
        proc = subprocess.run([npm, "run", "lint"], cwd=str(target), encoding="utf-8")
        if proc.returncode == 0:
            print("[eslint_gate] PASS")
            return 0
        print(f"[eslint_gate] FAIL — lint script exited {proc.returncode}")
        return proc.returncode

    if any(target.glob(".eslintrc*")) or any(target.glob("eslint.config.*")):
        print("[eslint_gate] ESLint config found, no lint script — running: npx eslint .")
        npx = shutil.which("npx")
        if npx is None:
            print("[eslint_gate] FAIL — ESLint config found but npx was not found on PATH")
            return 1
        proc = subprocess.run([npx, "eslint", "."], cwd=str(target), encoding="utf-8")
        if proc.returncode == 0:
            print("[eslint_gate] PASS")
            return 0
        print(f"[eslint_gate] FAIL — npx eslint exited {proc.returncode}")
        return proc.returncode

    print("[eslint_gate] WARN — no ESLint config or lint script found; skipping")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
