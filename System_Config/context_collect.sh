#!/usr/bin/env bash
# Manual-only composition of explicit context discovery and private vault intake.
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="$(cd "$SCRIPT_DIR/.." && pwd)"
VAULT="${CONTEXT_VAULT:-$WORKSPACE/brain}"
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

python3 "$SCRIPT_DIR/context_discover.py" --config "$CONFIG" --out "$MANIFEST" --date "$RUN_DATE" || exit $?
python3 "$SCRIPT_DIR/context_intake.py" --vault "$VAULT" --manifest "$MANIFEST" --date "$RUN_DATE" || exit $?
WEEK="$(python3 -c 'import datetime, sys; value = datetime.date.fromisoformat(sys.argv[1]).isocalendar(); print(f"{value.year}-W{value.week:02d}")' "$RUN_DATE")" || exit $?
YEAR="${WEEK%%-W*}"
NOTE="$VAULT/weekly_logs/$YEAR/$WEEK.md"
if [ -f "$NOTE" ] && [ ! -L "$NOTE" ]; then
  python3 "$SCRIPT_DIR/context_weekly.py" --vault "$VAULT" --week "$WEEK" --note "$NOTE"
else
  python3 "$SCRIPT_DIR/context_weekly.py" --vault "$VAULT" --week "$WEEK"
fi

