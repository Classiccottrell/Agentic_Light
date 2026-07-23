#!/usr/bin/env bash
# playwright_gate.sh — WARN+skip if the target repo has no Playwright E2E
# setup at all; hard-stop (propagate non-zero) if a config/script exists and
# the run fails.
# Usage: playwright_gate.sh <target-repo-path>
set -euo pipefail

TARGET="${1:?usage: playwright_gate.sh <target-repo-path>}"
cd "$TARGET"

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

E2E_KEY=""
if [ -f package.json ]; then
  for key in test:e2e e2e; do
    if [ -n "$(extract_script "$key" package.json || true)" ]; then
      E2E_KEY="$key"
      break
    fi
  done
fi

if [ -n "$E2E_KEY" ]; then
  echo "[playwright_gate] package.json scripts.$E2E_KEY found — running: npm run $E2E_KEY"
  if npm run "$E2E_KEY"; then
    echo "[playwright_gate] PASS"
    exit 0
  else
    rc=$?
    echo "[playwright_gate] FAIL — $E2E_KEY script exited $rc"
    exit "$rc"
  fi
elif ls playwright.config.* >/dev/null 2>&1; then
  echo "[playwright_gate] playwright.config found, no e2e script — running: npx playwright test"
  if npx playwright test; then
    echo "[playwright_gate] PASS"
    exit 0
  else
    rc=$?
    echo "[playwright_gate] FAIL — npx playwright test exited $rc"
    exit "$rc"
  fi
else
  echo "[playwright_gate] WARN — no Playwright config or e2e script found; skipping"
  exit 0
fi
