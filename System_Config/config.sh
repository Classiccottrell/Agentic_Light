#!/usr/bin/env bash
# config.sh - shared, relocatable configuration. Source from every script.
WORKSPACE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BRAIN="$WORKSPACE/brain"
RAW="$BRAIN/raw"
LOG_DIR="$WORKSPACE/System_Config/logs"

# Resolve the agent CLI (prioritizing agy/gemini, falling back to claude).
# Env override: export AGENT_TYPE=claude|gemini before sourcing to force it.
if [[ -n "${AGENT_TYPE:-}" ]]; then
  case "$AGENT_TYPE" in
    claude) CLAUDE="$(command -v claude || echo "$HOME/.local/bin/claude")" ;;
    gemini) CLAUDE="$(command -v agy || command -v gemini || echo "$HOME/.local/bin/agy")" ;;
  esac
elif command -v agy >/dev/null 2>&1; then
  CLAUDE="$(command -v agy)"
  AGENT_TYPE="gemini"
elif [[ -x "$HOME/.local/bin/agy" ]]; then
  CLAUDE="$HOME/.local/bin/agy"
  AGENT_TYPE="gemini"
elif command -v gemini >/dev/null 2>&1; then
  CLAUDE="$(command -v gemini)"
  AGENT_TYPE="gemini"
else
  CLAUDE="$(command -v claude || echo "$HOME/.local/bin/claude")"
  AGENT_TYPE="claude"
fi
export AGENT_TYPE
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

# validate_config — sanity-check the sourced config. Never exits; only
# returns 0/1, so callers decide whether to abort. bash 3.2 safe (no arrays).
validate_config() {
  local var val
  for var in WORKSPACE BRAIN RAW LOG_DIR CLAUDE AGENT_TYPE; do
    eval "val=\"\${$var:-}\""
    if [[ -z "$val" ]]; then
      echo "config.sh: $var is unset/empty" >&2
      return 1
    fi
  done

  [[ -d "$WORKSPACE" ]] || { echo "config.sh: WORKSPACE dir missing: $WORKSPACE" >&2; return 1; }
  [[ -d "$BRAIN" ]] || echo "config.sh: warning: BRAIN dir missing: $BRAIN" >&2

  return 0
}
