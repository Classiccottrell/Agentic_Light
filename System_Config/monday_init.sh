#!/usr/bin/env bash
# monday_init.sh — Weekly Workspace Initializer
# Creates this week's note from the template (filling Sprint + Quarter),
# creates this week's brain/raw/ folder, and adds a row to the Master
# Note's Weekly Index. Idempotent: if the note already exists, skips
# re-templating but still backfills a missing Master Note row.
# Dates are anchored to the MONDAY of the current ISO week, so the note is
# correct no matter which weekday the script runs.
#
# Vacation Recovery: if the most recent logged week is more than 7 days
# behind the current week, insert exactly ONE synthetic catch-up row into
# the Master Note's Weekly Index (no per-week backfill), then proceed
# normally.
#
#   Run manually:  bash System_Config/monday_init.sh
#   Preview:       DRY_RUN=1 bash System_Config/monday_init.sh

set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/config.sh"

# ── CONFIG ────────────────────────────────────────────────────────────────
WEEKLY_LOGS="$BRAIN/weekly_logs"
LOCK_DIR="$LOG_DIR/monday_init.lock"

# ── DATE CALCULATION (anchored to Monday of the current ISO week) ──────────
DOW=$(date +%u)                                              # 1=Mon .. 7=Sun
MONDAY=$(date -d "-$((DOW-1)) days" +%Y-%m-%d)
fmt() { date -d "$MONDAY +$1 days" +"$2"; }

YEAR=$(fmt 0 %G)                  # ISO week-year (pairs with %V)
WEEK_NUM=$(fmt 0 %V)              # zero-padded ISO week
WEEK_N=$((10#$WEEK_NUM))
MONTH_N=$((10#$(fmt 0 %m)))
DATE_START=$MONDAY
DATE_END=$(fmt 4 %Y-%m-%d)        # Friday
INIT_DATE=$(date +%Y-%m-%d)       # actual run date

# Sprint = ceil(ISO week / 2)
SPRINT=$(( (WEEK_N + 1) / 2 ))

case "$MONTH_N" in
  1|2|3)    QUARTER=1 ;;
  4|5|6)    QUARTER=2 ;;
  7|8|9)    QUARTER=3 ;;
  10|11|12) QUARTER=4 ;;
  *)        QUARTER="?" ;;
esac

# Human label, e.g. "Jul 20-24" (or "Jun 30-Jul 4" across a month edge)
MON_ABBR=$(fmt 0 %b); D_START=$((10#$(fmt 0 %d)))
END_MON=$(fmt 4 %b);  D_END=$((10#$(fmt 4 %d)))
if [[ "$END_MON" == "$MON_ABBR" ]]; then
  WEEK_LABEL="${MON_ABBR} ${D_START}-${D_END}"
else
  WEEK_LABEL="${MON_ABBR} ${D_START} - ${END_MON} ${D_END}"
fi

YEAR_DIR="$WEEKLY_LOGS/$YEAR"
NOTE_FILE="$YEAR_DIR/${YEAR}-W${WEEK_NUM}.md"
MASTER="$WEEKLY_LOGS/${YEAR} Master Note.md"
TEMPLATE="$WEEKLY_LOGS/Weekly_Note_Template.md"
INDEX_SENTINEL="<!-- WEEKLY-INDEX-INSERT -->"
WIKILINK="[[${YEAR}-W${WEEK_NUM}]]"
INDEX_ROW="| ${WIKILINK} | ${SPRINT} | Q${QUARTER} | ${WEEK_LABEL} | _pending Friday summary_ |"
RAW_DIR="$RAW/${YEAR}/W${WEEK_NUM} ${WEEK_LABEL}"

# ── VACATION RECOVERY — compute gap vs. the most recent logged week ────────
# GNU date has no direct "YYYY-Www-D" input parser, so derive the Monday of
# an arbitrary ISO year+week from Jan 4 (always in week 1) + offset.
iso_monday() {
  local y="$1" w="$2" jan4 jan4dow week1mon
  jan4=$(date -d "${y}-01-04" +%Y-%m-%d) || return 1
  jan4dow=$(date -d "$jan4" +%u)
  week1mon=$(date -d "$jan4 -$((jan4dow-1)) days" +%Y-%m-%d)
  date -d "$week1mon +$(( (10#$w-1)*7 )) days" +%Y-%m-%d
}

# Find the most recently logged week note (excluding Master Notes/template),
# lexically latest under weekly_logs/*/*.md (YYYY-Www.md sorts correctly).
LAST_NOTE=""
if [[ -d "$WEEKLY_LOGS" ]]; then
  LAST_NOTE=$(find "$WEEKLY_LOGS" -mindepth 2 -maxdepth 2 -type f -name '*.md' 2>/dev/null | sort | tail -1 || true)
fi

GAP_ROW=""
if [[ -n "$LAST_NOTE" ]]; then
  LAST_BASE=$(basename "$LAST_NOTE" .md)                     # e.g. 2026-W30
  if [[ "$LAST_BASE" =~ ^([0-9]{4})-W([0-9]{2})$ ]]; then
    LAST_YEAR="${BASH_REMATCH[1]}"
    LAST_WEEK="${BASH_REMATCH[2]}"
    if [[ "${LAST_YEAR}-W${LAST_WEEK}" != "${YEAR}-W${WEEK_NUM}" ]]; then
      # Monday of the last-logged ISO week.
      LAST_MONDAY=$(iso_monday "$LAST_YEAR" "$LAST_WEEK" 2>/dev/null || true)
      if [[ -n "$LAST_MONDAY" ]]; then
        LAST_EPOCH=$(date -d "$LAST_MONDAY" +%s)
        CUR_EPOCH=$(date -d "$MONDAY" +%s)
        GAP_DAYS=$(( (CUR_EPOCH - LAST_EPOCH) / 86400 ))
        if [[ "$GAP_DAYS" -gt 7 ]]; then
          GAP_WEEKS=$(( GAP_DAYS / 7 ))
          GAP_ROW="| [[gap]] | — | — | catch-up | Weeks skipped: ${GAP_WEEKS} (W${LAST_WEEK} → W${WEEK_NUM}) |"
        fi
      fi
    fi
  fi
fi

# ── DRY RUN ──────────────────────────────────────────────────────────────
if [[ "${DRY_RUN:-0}" == "1" ]]; then
  echo "Would create: $NOTE_FILE  (Monday-anchored: $MONDAY -> $DATE_END)"
  echo "  Sprint $SPRINT | Q$QUARTER | $WEEK_LABEL"
  echo "Master Note row: $INDEX_ROW"
  [[ -f "$NOTE_FILE" ]] && echo "(note already exists - real run would skip re-templating)"
  echo "Would create raw folder: $RAW_DIR"
  if [[ -n "$GAP_ROW" ]]; then
    echo "VACATION RECOVERY: would insert catch-up row: $GAP_ROW"
  else
    echo "VACATION RECOVERY: no gap > 7 days — skipped"
  fi
  exit 0
fi

# ── CONCURRENCY LOCK (atomic mkdir; released by the EXIT trap) ─────────────
mkdir -p "$LOG_DIR"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "[monday_init] another run holds $LOCK_DIR — skipping" >&2
  exit 0
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT

# ── CREATE brain/raw WEEK FOLDER (always, idempotent) ───────────────────────
mkdir -p "$RAW_DIR"
echo "[monday_init] raw folder ready: raw/${YEAR}/W${WEEK_NUM} ${WEEK_LABEL}"

# ── UPDATE MASTER NOTE WEEKLY INDEX (backup → edit → validate → rollback) ──
update_master_index() {
  if [[ ! -f "$MASTER" ]]; then
    echo "[monday_init] WARNING: Master Note not found at $MASTER — row NOT added." >&2
    return
  fi
  if ! grep -Fq "$INDEX_SENTINEL" "$MASTER"; then
    echo "[monday_init] WARNING: index sentinel not found in Master Note — row NOT added." >&2
    return
  fi

  local BACKUP pre_rows post_rows
  BACKUP="$LOG_DIR/master.$(date +%s).bak"
  cp "$MASTER" "$BACKUP"
  pre_rows=$(grep -cE '^\| \[\[' "$MASTER" || true)

  # Build the row(s) to insert: an optional single catch-up row (once, guarded
  # against re-insertion) followed by this week's row (skip if already present).
  local ROWS=""
  if [[ -n "$GAP_ROW" ]] && ! grep -Fq "| [[gap]] |" "$MASTER"; then
    ROWS="${GAP_ROW}"$'\n'
  fi
  if ! grep -Fq "| ${WIKILINK} |" "$MASTER"; then
    ROWS="${ROWS}${INDEX_ROW}"$'\n'
  fi

  if [[ -z "$ROWS" ]]; then
    echo "[monday_init] Master Note already has a row for $WIKILINK — not duplicating."
    rm -f "$BACKUP"
    return
  fi

  if awk -v rows="$ROWS" -v sent="$INDEX_SENTINEL" '
        index($0, sent) && !done { printf "%s", rows; done=1 } { print }
      ' "$MASTER" > "$MASTER.tmp"; then
    post_rows=$(grep -cE '^\| \[\[' "$MASTER.tmp" 2>/dev/null || true)
    if ! grep -Fq "$INDEX_SENTINEL" "$MASTER.tmp" || [[ "$post_rows" -lt "$pre_rows" ]]; then
      rm -f "$MASTER.tmp"
      cp "$BACKUP" "$MASTER"
      echo "[monday_init] VALIDATION FAILED — rolled back from $BACKUP" >&2
    else
      mv "$MASTER.tmp" "$MASTER"
      rm -f "$BACKUP"
      echo "[monday_init] Master Note index row(s) added for $WIKILINK."
    fi
  else
    rm -f "$MASTER.tmp"
    cp "$BACKUP" "$MASTER"
    echo "[monday_init] WARNING: index update failed — rolled back from $BACKUP" >&2
  fi
}

# ── GUARD: note already exists — backfill index row(s), else skip body ─────
if [[ -f "$NOTE_FILE" ]]; then
  echo "[monday_init] Note already exists: $NOTE_FILE — skipping note body."
  update_master_index
  echo "[monday_init] Done — $(date)"
  exit 0
fi

echo "[monday_init] Initializing W${WEEK_NUM} ${YEAR} — Sprint ${SPRINT}, Q${QUARTER}"

# ── GENERATE NEW NOTE FROM TEMPLATE ─────────────────────────────────────────
if [[ ! -f "$TEMPLATE" ]]; then
  echo "[monday_init] FATAL: template not found: $TEMPLATE" >&2
  exit 1
fi
mkdir -p "$YEAR_DIR"
sed \
  -e "s|{{WEEK_LABEL}}|${WEEK_LABEL}|g" \
  -e "s|{{DATE_START}}|${DATE_START}|g" \
  -e "s|{{DATE_END}}|${DATE_END}|g" \
  -e "s|{{WEEK_NUM}}|${WEEK_NUM}|g" \
  -e "s|{{YEAR}}|${YEAR}|g" \
  -e "s|{{SPRINT}}|${SPRINT}|g" \
  -e "s|{{QUARTER}}|${QUARTER}|g" \
  -e "s|{{INIT_DATE}}|${INIT_DATE}|g" \
  "$TEMPLATE" > "$NOTE_FILE"

echo "[monday_init] Note created: $NOTE_FILE"

# ── UPDATE MASTER NOTE WEEKLY INDEX ─────────────────────────────────────────
update_master_index
echo "[monday_init] Done — $(date)"
