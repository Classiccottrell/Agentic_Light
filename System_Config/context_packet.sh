#!/usr/bin/env bash
# Profile-driven, bounded context packet. Markdown remains the source of truth.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROFILE="agentic-light"
PROFILE_EXPLICIT=0
QUERY="${AGENTIC_LIGHT_CONTEXT_QUERY:-}"
TOP=5
MAX_LINES="${AGENTIC_LIGHT_CONTEXT_MAX_LINES:-120}"
MAX_BYTES="${AGENTIC_LIGHT_CONTEXT_MAX_BYTES:-12000}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root) ROOT="$2"; shift 2;;
    --profile) PROFILE="$2"; PROFILE_EXPLICIT=1; shift 2;;
    --query) QUERY="$2"; shift 2;;
    --top) TOP="$2"; shift 2;;
    --max-lines) MAX_LINES="$2"; shift 2;;
    --max-bytes) MAX_BYTES="$2"; shift 2;;
    -*) echo "context_packet: unknown option $1" >&2; exit 2;;
    *) [[ -z "$QUERY" ]] && QUERY="$1"; shift;;
  esac
done

PROFILE_PATH="$ROOT/System_Config/context_profiles/$PROFILE.json"
if [[ ! -f "$PROFILE_PATH" && "$PROFILE_EXPLICIT" == "1" ]]; then
  echo "context_packet: profile not found: $PROFILE_PATH" >&2
  exit 1
fi
if [[ -f "$PROFILE_PATH" ]]; then
  PROFILE_DATA="$(python3 - "$PROFILE_PATH" <<'PY'
import json, sys
data = json.load(open(sys.argv[1], encoding='utf-8'))
print('\t'.join([data.get('name', 'unnamed'), data.get('context_root', 'brain'), data.get('roadmap', ''), '\x1f'.join(data.get('include_paths', []))]))
PY
  )"
else
  PROFILE_DATA=$'agentic-light\tbrain\tROADMAP.md\tROADMAP.md'
fi
IFS=$'\t' read -r NAME CONTEXT_ROOT ROADMAP INCLUDE_PATHS <<< "$PROFILE_DATA"
INCLUDE_PATHS="${INCLUDE_PATHS//$'\x1f'/$'\n'}"
CONTEXT_DIR="$ROOT/$CONTEXT_ROOT"
[[ -d "$CONTEXT_DIR" ]] || { echo "context_packet: context root not found: $CONTEXT_DIR" >&2; exit 1; }

case "$MAX_LINES" in ''|*[!0-9]*) MAX_LINES=120;; esac
case "$MAX_BYTES" in ''|*[!0-9]*) MAX_BYTES=12000;; esac
case "$TOP" in ''|*[!0-9]*) TOP=5;; esac

{
  if [[ "$PROFILE_EXPLICIT" == "0" ]]; then
    echo "# Agentic Light Context Packet"
  else
    echo "# Context Packet"
    echo "Profile: $NAME"
  fi
  echo "Generated: $(date '+%Y-%m-%d %H:%M:%S %Z' 2>/dev/null || date)"
  echo
  if [[ "$PROFILE_EXPLICIT" == "0" ]]; then
    echo "## Roadmap"
    [[ -f "$ROOT/ROADMAP.md" ]] && sed -n '1,80p' "$ROOT/ROADMAP.md" || echo "ROADMAP.md unavailable"
    echo
    echo "## Active Preset"
    [[ -f "$ROOT/System_Config/.active-preset" ]] && cat "$ROOT/System_Config/.active-preset" || echo "unspecialized"
    echo
    echo "## Recent Session Facts"
    latest="$(find "$ROOT/brain/weekly_logs" -type f -name '*.md' -print 2>/dev/null | sort | tail -1)"
    [[ -n "$latest" ]] && tail -25 "$latest" || echo "No weekly log found"
  elif [[ -n "$INCLUDE_PATHS" ]]; then
    while IFS=$'\t' read -r include; do
      [[ -z "$include" ]] && continue
      path="$ROOT/$include"
      [[ -f "$path" ]] || continue
      echo "## Profile Include: $include"
      sed -n '1,80p' "$path"
      echo
    done <<< "$INCLUDE_PATHS"
  fi
  echo "## Context Matches"
  matches=()
  if [[ -n "$QUERY" ]]; then
    while IFS= read -r match; do matches+=("$match"); done < <(rg -i -l --glob '*.md' -- "$QUERY" "$CONTEXT_DIR" 2>/dev/null | sort | head -n "$TOP")
  else
    while IFS= read -r match; do matches+=("$match"); done < <(find "$CONTEXT_DIR" -type f -name '*.md' -print | sort | tail -n "$TOP")
  fi
  if [[ "${#matches[@]}" -eq 0 ]]; then
    echo "No matching context records."
  else
    for match in "${matches[@]}"; do
      rel="${match#"$ROOT"/}"
      echo "### $rel"
      sed -n '1,80p' "$match"
      echo
    done
  fi
} | awk -v max="$MAX_LINES" 'NR <= max { print }' | LC_ALL=C head -c "$MAX_BYTES"
