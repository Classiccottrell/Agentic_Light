#!/usr/bin/env bash
# eslint_gate.sh — WARN+skip if the target repo has no ESLint setup at all;
# hard-stop (propagate non-zero) if a lint config/script exists and fails.
# Usage: eslint_gate.sh <target-repo-path>
set -euo pipefail

TARGET="${1:?usage: eslint_gate.sh <target-repo-path>}"
cd "$TARGET"

# extract_script <key> <package.json> — prints scripts[<key>] or empty.
# Uses jq if present, else a grep/sed fallback (no jq dependency assumed).
extract_script() {
  local key="$1" file="$2"
  if command -v jq >/dev/null 2>&1; then
    jq -r --arg k "$key" '.scripts[$k] // empty' "$file" 2>/dev/null
  else
    grep -o "\"$key\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" "$file" 2>/dev/null \
      | head -1 | sed -E 's/.*:[[:space:]]*"([^"]*)"$/\1/'
  fi
}

LINT_SCRIPT=""
if [ -f package.json ]; then
  LINT_SCRIPT="$(extract_script lint package.json || true)"
fi

if [ -n "$LINT_SCRIPT" ]; then
  echo "[eslint_gate] package.json scripts.lint found — running: npm run lint"
  if npm run lint; then
    echo "[eslint_gate] PASS"
    exit 0
  else
    rc=$?
    echo "[eslint_gate] FAIL — lint script exited $rc"
    exit "$rc"
  fi
elif ls .eslintrc* >/dev/null 2>&1 || ls eslint.config.* >/dev/null 2>&1; then
  echo "[eslint_gate] ESLint config found, no lint script — running: npx eslint ."
  if npx eslint .; then
    echo "[eslint_gate] PASS"
    exit 0
  else
    rc=$?
    echo "[eslint_gate] FAIL — npx eslint exited $rc"
    exit "$rc"
  fi
else
  echo "[eslint_gate] WARN — no ESLint config or lint script found; skipping"
  exit 0
fi
