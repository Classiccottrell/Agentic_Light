#!/usr/bin/env bash
#
# bootstrap.sh — one-command setup for Agentic Light.
#
# Operates IN PLACE at the location you cloned to. Idempotent and safe:
# never deletes or overwrites your data. Re-run it any time.
#
#   ./bootstrap.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

SYSCFG="$ROOT/System_Config"

# ---------------------------------------------------------------------------
# Argument handling — --check / --uninstall / --help run before normal setup.
# ---------------------------------------------------------------------------
case "${1:-}" in
  --help)
    echo "Usage: ./bootstrap.sh [--check|--check-deps|--uninstall|--help]"
    echo "  (no args)    run the interactive setup"
    echo "  --check      read-only doctor: report tool status"
    echo "  --check-deps alias for --check"
    echo "  --uninstall  explain there is no background automation to remove"
    exit 0
    ;;
  --check|--check-deps)
    echo "=================================================="
    echo " Agentic Light — check"
    echo "=================================================="
    echo
    echo "→ Tools:"
    for t in agy gemini claude gh node npx python3; do
      if p="$(command -v "$t" 2>/dev/null)"; then
        echo "  [ok] $t $p"
        if [ "$t" = "gh" ]; then
          if gh auth status >/dev/null 2>&1; then
            echo "       gh auth status: ok"
          else
            echo "       gh auth status: unauthenticated"
          fi
        fi
      else
        echo "  [--] $t missing"
      fi
    done
    echo
    echo "→ Automation:"
    echo "  No background automation (Agentic Light is manual-trigger only)."
    exit 0
    ;;
  --uninstall)
    echo "=================================================="
    echo " Agentic Light — uninstall"
    echo "=================================================="
    echo
    echo "Agentic Light has no background automation to remove; delete the"
    echo "Agentic_Light/ folder to uninstall."
    echo
    if [ ! -t 0 ]; then
      echo "Non-interactive session — nothing to confirm, exiting."
      exit 0
    fi
    printf "Acknowledge? [y/N]: "
    read -r UNINSTALL_REPLY || UNINSTALL_REPLY=""
    case "$UNINSTALL_REPLY" in
      [yY]*) echo "→ Nothing removed (no automation installed). Delete Agentic_Light/ manually to uninstall." ;;
      *)     echo "→ Aborted. No changes made." ;;
    esac
    exit 0
    ;;
  --*)
    echo "Unknown flag: ${1:-}"
    echo "Usage: ./bootstrap.sh [--check|--uninstall|--help]"
    echo "  (no args)    run the interactive setup"
    echo "  --check      read-only doctor: report tool status"
    echo "  --uninstall  explain there is no background automation to remove"
    exit 1
    ;;
esac

echo "=================================================="
echo " Agentic Light — bootstrap"
echo " Workspace: $ROOT"
echo "=================================================="
echo

# ---------------------------------------------------------------------------
# 1. Scaffold the directory tree (idempotent).
# ---------------------------------------------------------------------------
echo "→ Scaffolding directory tree…"
mkdir -p \
  "$ROOT/.obsidian" \
  "$ROOT/Projects/_TEMPLATE/active" \
  "$ROOT/Projects/_TEMPLATE/archive" \
  "$ROOT/System_Config/logs" \
  "$ROOT/microsite" \
  "$ROOT/brain/raw" \
  "$ROOT/brain/wiki" \
  "$ROOT/brain/weekly_logs/2026" \
  "$ROOT/pipeline/logs" \
  "$ROOT/pipeline/lib"

# ---------------------------------------------------------------------------
# 2. Make scripts executable.
# ---------------------------------------------------------------------------
echo "→ Making scripts executable…"
chmod +x "$ROOT/bootstrap.sh"
while IFS= read -r f; do
  chmod +x "$f"
done < <(find "$ROOT" -type f \( -name "*.sh" -o -name "*.py" \))

# ---------------------------------------------------------------------------
# 3. Seed .mcp.json from the example if absent (never overwrite an existing one).
# ---------------------------------------------------------------------------
if [ ! -f "$ROOT/.mcp.json" ] && [ -f "$SYSCFG/mcp.defaults.json" ]; then
  cp "$SYSCFG/mcp.defaults.json" "$ROOT/.mcp.json"
  echo "→ Created .mcp.json from System_Config/mcp.defaults.json."
elif [ -f "$ROOT/.mcp.json" ]; then
  echo "→ .mcp.json already present — leaving it untouched."
fi
echo

# ---------------------------------------------------------------------------
# 4. Provider auto-detection (agy → gemini → claude, env override).
# ---------------------------------------------------------------------------
echo "→ Detecting agent provider…"
if [ -n "${AGENT_TYPE:-}" ]; then
  echo "    [ok] AGENT_TYPE overridden via env: $AGENT_TYPE"
elif command -v agy >/dev/null 2>&1; then
  echo "    [ok] Provider detected: agy ($(command -v agy))"
elif command -v gemini >/dev/null 2>&1; then
  echo "    [ok] Provider detected: gemini ($(command -v gemini))"
elif command -v claude >/dev/null 2>&1; then
  echo "    [ok] Provider detected: claude ($(command -v claude))"
else
  echo "    [warn] No agent CLI found on PATH (need 'agy', 'gemini', or 'claude')."
fi

if command -v gh >/dev/null 2>&1; then
  echo "    [ok] gh found: $(command -v gh)"
  gh auth status >/dev/null 2>&1 || echo "         not authenticated — run: gh auth login"
else
  echo "    [opt] gh not found — needed by pipeline/run.sh for PR creation."
fi

echo
echo "=================================================="
echo " Done. Next steps:"
echo "=================================================="
echo " 1. Open Agentic_Light/brain/ in Obsidian."
echo " 2. Run bash Agentic_Light/System_Config/healthcheck.sh"
echo
