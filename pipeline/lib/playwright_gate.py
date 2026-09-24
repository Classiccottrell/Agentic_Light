#!/usr/bin/env python3
"""playwright_gate.py — WARN+skip if the target repo has no Playwright E2E
setup at all; hard-stop (propagate non-zero) if a config/script exists and
the run fails.
Usage: playwright_gate.py <target-repo-path>
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def extract_script(key, package_json_path):
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
    e2e_key = ""
    if package_json.is_file():
        for key in ("test:e2e", "e2e"):
            if extract_script(key, package_json):
                e2e_key = key
                break

    if e2e_key:
        print(f"[playwright_gate] package.json scripts.{e2e_key} found — running: npm run {e2e_key}")
        npm = shutil.which("npm")
        if npm is None:
            print(f"[playwright_gate] FAIL — scripts.{e2e_key} is defined but npm was not found on PATH")
            return 1
        proc = subprocess.run([npm, "run", e2e_key], cwd=str(target), encoding="utf-8")
        if proc.returncode == 0:
            print("[playwright_gate] PASS")
            return 0
        print(f"[playwright_gate] FAIL — {e2e_key} script exited {proc.returncode}")
        return proc.returncode

    if any(target.glob("playwright.config.*")):
        print("[playwright_gate] playwright.config found, no e2e script — running: npx playwright test")
        npx = shutil.which("npx")
        if npx is None:
            print("[playwright_gate] FAIL — playwright.config found but npx was not found on PATH")
            return 1
        proc = subprocess.run([npx, "playwright", "test"], cwd=str(target), encoding="utf-8")
        if proc.returncode == 0:
            print("[playwright_gate] PASS")
            return 0
        print(f"[playwright_gate] FAIL — npx playwright test exited {proc.returncode}")
        return proc.returncode

    print("[playwright_gate] WARN — no Playwright config or e2e script found; skipping")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
