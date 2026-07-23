#!/usr/bin/env bash
# config.sh - shared, relocatable configuration. Source from every script.
WORKSPACE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BRAIN="$WORKSPACE/brain"
RAW="$BRAIN/raw"
LOG_DIR="$WORKSPACE/System_Config/logs"

# Resolve the agent CLI (prioritizing agy/gemini, falling back to claude).
# Env override: export AGENT_TYPE=claude|gemini before sourcing to force it.
# An unrecognized override is ignored (with a warning) rather than left to
# fall through the case with $CLAUDE unset — that used to surface only much
# later as a confusing "unbound variable" deep inside run_agent().
if [[ -n "${AGENT_TYPE:-}" && "$AGENT_TYPE" != "claude" && "$AGENT_TYPE" != "gemini" ]]; then
  echo "config.sh: unknown AGENT_TYPE='$AGENT_TYPE' (expected claude|gemini) — ignoring override, auto-detecting" >&2
  unset AGENT_TYPE
fi

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
validate_config || echo "config.sh: configuration warnings above — some scripts may misbehave" >&2

# acquire_lock <lock_dir> [max_age_seconds] — atomic mkdir lock. If the lock
# is already held, checks its mtime: a lock older than max_age_seconds (default
# 3600) is assumed abandoned by a killed/crashed run and is reclaimed once
# (the reclaim mkdir is still atomic, so a genuine concurrent holder always
# wins the race). Registers an EXIT trap to release the lock; a caller that
# sets its own EXIT trap afterward should fold in the same rmdir.
# Returns 0 (lock held) or 1 (still held by a live run — caller decides what
# to do, typically skip/exit 0). bash 3.2 safe.
acquire_lock() {
  local lock_dir="$1" max_age="${2:-3600}" lock_mtime now age
  if mkdir "$lock_dir" 2>/dev/null; then
    trap "rmdir '$lock_dir' 2>/dev/null || true" EXIT
    return 0
  fi
  lock_mtime="$(stat -c %Y "$lock_dir" 2>/dev/null || stat -f %m "$lock_dir" 2>/dev/null || echo "")"
  [[ -n "$lock_mtime" ]] || return 1
  now="$(date +%s)"
  age=$(( now - lock_mtime ))
  if [[ "$age" -gt "$max_age" ]]; then
    echo "acquire_lock: reclaiming stale lock (${age}s old, >${max_age}s): $lock_dir" >&2
    rmdir "$lock_dir" 2>/dev/null || true
    if mkdir "$lock_dir" 2>/dev/null; then
      trap "rmdir '$lock_dir' 2>/dev/null || true" EXIT
      return 0
    fi
  fi
  return 1
}
