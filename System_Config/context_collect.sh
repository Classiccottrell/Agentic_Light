#!/usr/bin/env bash
# Manual-only composition of explicit context discovery and private vault intake.
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="${CONTEXT_SOURCES_CONFIG:-$SCRIPT_DIR/context-sources.local.json}"
MANIFEST="${CONTEXT_MANIFEST:-$SCRIPT_DIR/context-manifest.local.json}"

if [ "$#" -gt 1 ]; then
  echo "usage: context_collect.sh [YYYY-MM-DD]" >&2
  exit 1
fi
RUN_DATE="${1:-$(date +%F)}"
if ! python3 -c 'import datetime, sys; datetime.date.fromisoformat(sys.argv[1])' "$RUN_DATE" >/dev/null 2>&1; then
  echo "context collect: invalid date" >&2
  exit 1
fi
case "$CONFIG" in
  /*) ;;
  *) echo "context collect: private config must be absolute" >&2; exit 1 ;;
esac
case "$MANIFEST" in
  /*) ;;
  *) echo "context collect: private manifest must be absolute" >&2; exit 1 ;;
esac
if [ ! -e "$CONFIG" ] && [ ! -L "$CONFIG" ]; then
  echo "context collect: private config missing" >&2
  exit 1
fi

# The Python composer holds the shared lock and invokes nested writer mains in
# the same process. No environment flag grants descendants acquisition rights.
exec python3 "$SCRIPT_DIR/context_collect.py" "$RUN_DATE"
