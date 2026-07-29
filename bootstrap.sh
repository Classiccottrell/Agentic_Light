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
    for t in claude agy gemini codex ollama gh node npx python3; do
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
    if [ -r "$ROOT/.agentic-light.conf" ]; then
      echo
      echo "→ Provider config:"
      sed -n 's/^PROVIDERS=/  enabled: /p; s/^PRIORITY=/  priority: /p' "$ROOT/.agentic-light.conf"
    else
      echo
      echo "→ Provider config: not created (run ./bootstrap.sh)"
    fi
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
# Scoped to the dirs that actually own Agentic Light's own scripts —
# deliberately excludes Projects/ (holds externally cloned target repos per
# pipeline/run.sh) and brain/ so re-running bootstrap never flips the
# executable bit on scripts that aren't ours.
while IFS= read -r f; do
  chmod +x "$f"
done < <(find "$ROOT/System_Config" "$ROOT/pipeline" "$ROOT/skills" \
             -type f \( -name "*.sh" -o -name "*.py" \) 2>/dev/null)

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
# 4. Provider configuration.
# ---------------------------------------------------------------------------
echo "→ Configuring agent providers…"
CONFIG_FILE="$ROOT/.agentic-light.conf"
PROVIDERS="${AGENTIC_LIGHT_PROVIDERS:-}"
PRIORITY="${AGENTIC_LIGHT_PRIORITY:-}"
if [ -z "$PROVIDERS" ] && [ -t 0 ]; then
  for provider in claude gemini codex ollama; do
    binary="$provider"; [ "$provider" = gemini ] && command -v agy >/dev/null 2>&1 && binary=agy
    if command -v "$binary" >/dev/null 2>&1; then
      mark=x; default=Y
    else
      mark=" "; default=N
    fi
    printf "  [%s] Enable %s? [%s]: " "$mark" "$provider" "$default"
    read -r reply || reply=""
    case "${reply:-$default}" in
      y|Y|yes|YES) PROVIDERS="${PROVIDERS:+$PROVIDERS,}$provider" ;;
    esac
  done
  printf "  Priority, comma-separated [%s]: " "$PROVIDERS"
  read -r PRIORITY || PRIORITY=""
  PRIORITY="${PRIORITY:-$PROVIDERS}"
  for provider in $(printf '%s' "$PROVIDERS" | tr ',' ' '); do
    printf "  Optional %s model [default]: " "$provider"
    read -r model || model=""
    case "$provider" in
      claude) MODEL_CLAUDE="$model" ;; gemini) MODEL_GEMINI="$model" ;;
      codex) MODEL_CODEX="$model" ;; ollama) MODEL_OLLAMA="$model" ;;
    esac
  done
else
  PROVIDERS="${PROVIDERS:-${AGENT_TYPE:-claude,gemini,codex,ollama}}"
  PRIORITY="${PRIORITY:-$PROVIDERS}"
fi

valid_list() {
  case ",$1," in
    *[!a-z,]*|*,claude,claude,*|*,gemini,gemini,*|*,codex,codex,*|*,ollama,ollama,*) return 1 ;;
  esac
  for item in $(printf '%s' "$1" | tr ',' ' '); do
    case "$item" in claude|gemini|codex|ollama) ;; *) return 1 ;; esac
  done
  [ -n "$1" ]
}
valid_list "$PROVIDERS" && valid_list "$PRIORITY" || { echo "Invalid provider list." >&2; exit 1; }

CONFIG_TMP="$(mktemp "${TMPDIR:-/tmp}/agentic-light.XXXXXX")"
{
  printf 'PROVIDERS=%s\nPRIORITY=%s\n' "$PROVIDERS" "$PRIORITY"
  for provider in claude gemini codex ollama; do
    model_key="MODEL_$(printf '%s' "$provider" | tr '[:lower:]' '[:upper:]')"
    case "$provider" in
      claude) model="${AGENTIC_LIGHT_MODEL_CLAUDE:-${MODEL_CLAUDE:-}}" ;;
      gemini) model="${AGENTIC_LIGHT_MODEL_GEMINI:-${MODEL_GEMINI:-}}" ;;
      codex) model="${AGENTIC_LIGHT_MODEL_CODEX:-${MODEL_CODEX:-}}" ;;
      ollama) model="${AGENTIC_LIGHT_MODEL_OLLAMA:-${MODEL_OLLAMA:-}}" ;;
    esac
    case "$model" in *$'\n'*|*=*) echo "Invalid model name." >&2; rm -f "$CONFIG_TMP"; exit 1 ;; esac
    printf '%s=%s\n' "$model_key" "$model"
  done
} > "$CONFIG_TMP"
chmod 600 "$CONFIG_TMP"
mv "$CONFIG_TMP" "$CONFIG_FILE"
echo "    [ok] Enabled: $PROVIDERS"
echo "    [ok] Priority: $PRIORITY"

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
echo " 1. Open Agentic_Light/ in Obsidian (the folder containing .obsidian/)."
echo " 2. Run bash Agentic_Light/System_Config/healthcheck.sh"
echo
