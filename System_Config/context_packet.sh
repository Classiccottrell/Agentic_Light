#!/usr/bin/env bash
# context_packet.sh — bounded, provider-neutral resume context.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MAX_LINES="${AGENTIC_LIGHT_CONTEXT_MAX_LINES:-120}"
MAX_BYTES="${AGENTIC_LIGHT_CONTEXT_MAX_BYTES:-12000}"
QUERY="${1:-${AGENTIC_LIGHT_CONTEXT_QUERY:-}}"

case "$MAX_LINES" in ''|*[!0-9]*) MAX_LINES=120 ;; esac
case "$MAX_BYTES" in ''|*[!0-9]*) MAX_BYTES=12000 ;; esac

packet="$( {
  echo "# Agentic Light Context Packet"
  echo "Generated: $(date '+%Y-%m-%d %H:%M:%S %Z' 2>/dev/null || date)"
  echo
  echo "## Roadmap"
  sed -n '1,80p' "$ROOT/ROADMAP.md" 2>/dev/null || echo "ROADMAP.md unavailable"
  echo
  echo "## Active Preset"
  if [ -f "$ROOT/System_Config/.active-preset" ]; then
    cat "$ROOT/System_Config/.active-preset"
  else
    echo "unspecialized"
  fi
  echo
  echo "## Recent Session Facts"
  latest="$(find "$ROOT/brain/weekly_logs" -type f -name '*.md' -print 2>/dev/null | sort | tail -1)"
  if [ -n "$latest" ]; then tail -25 "$latest"; else echo "No weekly log found"; fi
  if [ -n "$QUERY" ] && [ -f "$ROOT/System_Config/memory_search.py" ]; then
    echo
    echo "## Semantic Matches"
    python3 "$ROOT/System_Config/memory_search.py" "$QUERY" --top 3 2>/dev/null || echo "semantic search unavailable"
  fi
} )"
packet="$(printf '%s\n' "$packet" | awk -v max="$MAX_LINES" 'NR <= max { print }')"
# Byte-oriented truncation, not bash's character-count `${packet:0:N}` —
# under UTF-8 (e.g. this repo's own em dashes, 3 bytes each), a character
# slice can produce far more than N bytes, silently blowing the budget.
printf '%s' "$packet" | LC_ALL=C head -c "$MAX_BYTES"
