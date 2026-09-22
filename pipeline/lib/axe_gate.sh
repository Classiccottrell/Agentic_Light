#!/usr/bin/env bash
# axe_gate.sh — accessibility gate. Runs the target repo's own a11y script
# (package.json scripts["test:a11y"|"a11y"]) and hard-stops (propagates
# non-zero) if it fails. No script → WARN+skip: never invents a URL, never
# drives a browser, never installs anything.
# Usage: axe_gate.sh <target-repo-path>
set -euo pipefail

TARGET="${1:?usage: axe_gate.sh <target-repo-path>}"
cd "$TARGET"

MANUAL_REF="skills/wcag-audit/references/running-axe.md (in the Agentic Light workspace)"

# extract_script <key> <package.json> — prints scripts[<key>] or empty.
extract_script() {
  local key="$1" file="$2"
  if command -v jq >/dev/null 2>&1; then
    jq -r --arg k "$key" '.scripts[$k] // empty' "$file" 2>/dev/null
  else
    grep -o "\"$key\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" "$file" 2>/dev/null \
      | head -1 | sed -E 's/.*:[[:space:]]*"([^"]*)"$/\1/'
  fi
}

# has_dep <name> <package.json> — true if <name> is in dependencies or
# devDependencies.
has_dep() {
  local name="$1" file="$2"
  if command -v jq >/dev/null 2>&1; then
    jq -e --arg n "$name" '(.dependencies // {}) + (.devDependencies // {}) | has($n)' "$file" >/dev/null 2>&1
  else
    grep -q "\"$name\"[[:space:]]*:" "$file" 2>/dev/null
  fi
}

A11Y_KEY=""
A11Y_DEP=""
if [ -f package.json ]; then
  for key in test:a11y a11y; do
    if [ -n "$(extract_script "$key" package.json || true)" ]; then
      A11Y_KEY="$key"
      break
    fi
  done
  if [ -z "$A11Y_KEY" ]; then
    for dep in @axe-core/cli @axe-core/playwright pa11y; do
      if has_dep "$dep" package.json; then
        A11Y_DEP="$dep"
        break
      fi
    done
  fi
fi

if [ -n "$A11Y_KEY" ]; then
  echo "[axe_gate] package.json scripts.$A11Y_KEY found — running: npm run $A11Y_KEY"
  if npm run "$A11Y_KEY"; then
    echo "[axe_gate] PASS (automated checks catch roughly a third of WCAG AA failures — not a conformance claim)"
    exit 0
  else
    rc=$?
    echo "[axe_gate] FAIL — $A11Y_KEY script exited $rc"
    exit "$rc"
  fi
elif [ -n "$A11Y_DEP" ]; then
  # @axe-core/cli and pa11y need a URL to scan; @axe-core/playwright is a
  # library called from the repo's own specs (the playwright gate runs
  # those). The repo knows its own URL/server — this gate doesn't guess.
  echo "[axe_gate] WARN — $A11Y_DEP is listed in package.json but there is no scripts.test:a11y or scripts.a11y to run it; no automated accessibility check ran."
  echo "[axe_gate]   Add a test:a11y script that starts/targets the app and runs $A11Y_DEP, or see $MANUAL_REF for the manual path. Skipping."
  exit 0
else
  echo "[axe_gate] WARN — no automated accessibility check ran: no scripts.test:a11y/a11y and no @axe-core/cli, @axe-core/playwright, or pa11y dependency found."
  echo "[axe_gate]   See $MANUAL_REF for the manual path. Skipping."
  exit 0
fi
