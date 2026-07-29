#!/usr/bin/env bash
# config.sh - shared, relocatable configuration. Source from every script.
WORKSPACE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BRAIN="$WORKSPACE/brain"
RAW="$BRAIN/raw"
LOG_DIR="$WORKSPACE/System_Config/logs"

export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
AGENT_CONFIG="$WORKSPACE/.agentic-light.conf"
LEGACY_AGENT_TYPE_OVERRIDE="${AGENT_TYPE:-}"

config_value() {
  local key="$1"
  [[ -r "$AGENT_CONFIG" ]] || return 0
  sed -n "s/^${key}=//p" "$AGENT_CONFIG" | tail -1
}

provider_command() {
  case "$1" in
    claude) command -v claude 2>/dev/null ;;
    gemini) command -v agy 2>/dev/null || command -v gemini 2>/dev/null ;;
    codex) command -v codex 2>/dev/null ;;
    ollama) command -v ollama 2>/dev/null ;;
  esac
}

validate_provider_lists() {
  local enabled="$1" priority="$2" item old_ifs
  case "$enabled,$priority" in
    *[!a-z,]*|,*|*,|*,,*) return 1 ;;
  esac
  old_ifs="$IFS"; IFS=,
  for item in $enabled; do
    IFS="$old_ifs"
    case "$item" in claude|gemini|codex|ollama) ;; *) return 1 ;; esac
    case ",$enabled," in *",$item,"*",$item,"*) return 1 ;; esac
    case ",$priority," in *",$item,"*) ;; *) return 1 ;; esac
    IFS=,
  done
  for item in $priority; do
    IFS="$old_ifs"
    case "$item" in claude|gemini|codex|ollama) ;; *) return 1 ;; esac
    case ",$priority," in *",$item,"*",$item,"*) return 1 ;; esac
    case ",$enabled," in *",$item,"*) ;; *) return 1 ;; esac
    IFS=,
  done
  IFS="$old_ifs"
  return 0
}

resolve_agent_provider() {
  local configured enabled provider old_ifs model_key
  enabled="${AGENTIC_LIGHT_PROVIDERS:-$(config_value PROVIDERS)}"
  configured="${AGENTIC_LIGHT_PRIORITY:-}"
  [[ -n "$configured" ]] || configured="$(config_value PRIORITY)"
  [[ -n "$configured" ]] || configured="$enabled"
  [[ -n "$enabled" ]] || enabled="claude,gemini,codex,ollama"
  [[ -n "$configured" ]] || configured="claude,gemini,codex,ollama"
  validate_provider_lists "$enabled" "$configured" || {
    echo "config.sh: invalid provider configuration (priority must be an exact ordering of enabled providers)" >&2
    return 1
  }
  if [[ -n "$LEGACY_AGENT_TYPE_OVERRIDE" ]]; then
    case ",$enabled," in
      *",$LEGACY_AGENT_TYPE_OVERRIDE,"*) configured="$LEGACY_AGENT_TYPE_OVERRIDE,$configured" ;;
      *) echo "config.sh: AGENT_TYPE is not enabled: $LEGACY_AGENT_TYPE_OVERRIDE" >&2; return 1 ;;
    esac
  fi

  old_ifs="$IFS"; IFS=,
  for provider in $configured; do
    IFS="$old_ifs"
    case "$provider" in claude|gemini|codex|ollama) ;; *) IFS=; continue ;; esac
    AGENT_COMMAND="$(provider_command "$provider" || true)"
    if [[ -n "$AGENT_COMMAND" ]]; then
      AGENT_PROVIDER="$provider"
      model_key="$(printf '%s' "$provider" | tr '[:lower:]' '[:upper:]')"
      case "$provider" in
        claude) AGENT_MODEL="${AGENTIC_LIGHT_MODEL_CLAUDE:-$(config_value MODEL_CLAUDE)}" ;;
        gemini) AGENT_MODEL="${AGENTIC_LIGHT_MODEL_GEMINI:-$(config_value MODEL_GEMINI)}" ;;
        codex) AGENT_MODEL="${AGENTIC_LIGHT_MODEL_CODEX:-$(config_value MODEL_CODEX)}" ;;
        ollama) AGENT_MODEL="${AGENTIC_LIGHT_MODEL_OLLAMA:-$(config_value MODEL_OLLAMA)}" ;;
      esac
      AGENT_TYPE="$provider"
      CLAUDE="$AGENT_COMMAND"
      export AGENT_PROVIDER AGENT_COMMAND AGENT_MODEL AGENT_TYPE CLAUDE
      IFS="$old_ifs"
      return 0
    fi
    IFS=,
  done
  IFS="$old_ifs"
  echo "config.sh: no enabled agent provider executable found ($configured)" >&2
  return 1
}

resolve_agent_provider || true

# validate_config — sanity-check the sourced config. Never exits; only
# returns 0/1, so callers decide whether to abort. bash 3.2 safe (no arrays).
validate_config() {
  local var val
  for var in WORKSPACE BRAIN RAW LOG_DIR AGENT_COMMAND AGENT_PROVIDER; do
    case "$var" in
      WORKSPACE) val="$WORKSPACE" ;; BRAIN) val="$BRAIN" ;; RAW) val="$RAW" ;;
      LOG_DIR) val="$LOG_DIR" ;; AGENT_COMMAND) val="${AGENT_COMMAND:-}" ;;
      AGENT_PROVIDER) val="${AGENT_PROVIDER:-}" ;;
    esac
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

# date_offset [YYYY-MM-DD] <days> <format> — BSD/GNU date arithmetic.
date_offset() {
  local base="$1" days="$2" format="$3" shift_arg
  case "$days" in -*) shift_arg="${days}d" ;; *) shift_arg="+${days}d" ;; esac
  if [[ "$(uname -s)" == "Darwin" ]]; then
    if [[ -n "$base" ]]; then
      date -j "-v${shift_arg}" -f "%Y-%m-%d" "$base" +"$format"
    else
      date "-v${shift_arg}" +"$format"
    fi
  elif [[ -n "$base" ]]; then
    date -d "$base $days days" +"$format"
  else
    date -d "$days days" +"$format"
  fi
}

# ensure_current_week_raw_folder — mkdir -p the current ISO week's
# brain/raw/YYYY/Wnn label/ folder so a note always has somewhere to land,
# regardless of whether monday_init.sh has run yet this week. Idempotent
# (mkdir -p). Mirrors the folder-path calc in monday_init.sh. bash 3.2 safe.
ensure_current_week_raw_folder() {
  local dow monday year week_num mon_abbr d_start end_mon d_end week_label raw_dir
  dow=$(date +%u)                                   # 1=Mon .. 7=Sun
  monday=$(date_offset "" "-$((dow-1))" %Y-%m-%d)
  year=$(date_offset "$monday" 0 %G)                  # ISO week-year (pairs with %V)
  week_num=$(date_offset "$monday" 0 %V)              # zero-padded ISO week
  mon_abbr=$(date_offset "$monday" 0 %b); d_start=$((10#$(date_offset "$monday" 0 %d)))
  end_mon=$(date_offset "$monday" 4 %b); d_end=$((10#$(date_offset "$monday" 4 %d)))
  if [[ "$end_mon" == "$mon_abbr" ]]; then
    week_label="${mon_abbr} ${d_start}-${d_end}"
  else
    week_label="${mon_abbr} ${d_start} - ${end_mon} ${d_end}"
  fi
  raw_dir="$RAW/${year}/W${week_num} ${week_label}"
  mkdir -p "$raw_dir"
}

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
