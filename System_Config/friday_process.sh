#!/usr/bin/env bash
# friday_process.sh — Weekly close-out
# Locates brain/weekly_logs/${YEAR}/${WEEK_TAG}.md, appends a close-out
# entry to its '## Claude Sessions' section, and fills the Master Note
# row's Summary cell for this week (backup → awk rewrite → validate →
# rollback). Manual-trigger only — no launchd/cron in Agentic Light.
#
#   Manual run:  bash System_Config/friday_process.sh [YYYY-Www]
#   Preview:     DRY_RUN=1 bash System_Config/friday_process.sh

set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/config.sh"

# ── CONFIG ───────────────────────────────────────────────────────────────
WEEKLY_LOGS="$BRAIN/weekly_logs"
LOG="$LOG_DIR/friday_process.log"
LOCK_DIR="$LOG_DIR/friday_process.lock"
SENTINEL="<!-- WEEKLY-INDEX-INSERT -->"

mkdir -p "$LOG_DIR"
ts() { date "+%Y-%m-%d %H:%M:%S"; }
log() { echo "[$(ts)] $*" >> "$LOG"; }

log "friday_process start"

# ── LOCATE THE TARGET WEEK'S NOTE ───────────────────────────────────────────
# Optional arg 1: explicit week tag (YYYY-Www) to close out. Defaults to
# today's ISO week.
TODAY=$(date +%Y-%m-%d)
if [[ -n "${1:-}" ]]; then
  WEEK_TAG="$1"
  if [[ ! "$WEEK_TAG" =~ ^[0-9][0-9][0-9][0-9]-W[0-9][0-9]$ ]]; then
    log "FATAL: invalid week arg '$WEEK_TAG' — expected YYYY-Www"; exit 1
  fi
  YEAR="${WEEK_TAG%%-W*}"; WEEK="${WEEK_TAG##*-W}"
else
  YEAR=$(date +%G); WEEK=$(date +%V)
  WEEK_TAG="${YEAR}-W${WEEK}"
fi
NOTE_ABS="$WEEKLY_LOGS/${YEAR}/${WEEK_TAG}.md"
MASTER="$WEEKLY_LOGS/${YEAR} Master Note.md"

if [[ ! -d "$BRAIN" ]]; then
  log "FATAL: brain dir missing: $BRAIN — aborting"; exit 1
fi
if [[ ! -f "$NOTE_ABS" ]]; then
  log "no weekly note for $WEEK_TAG at $NOTE_ABS — nothing to process; exiting"; exit 0
fi

# ── IDEMPOTENCY GUARD ────────────────────────────────────────────────────
if grep -qF "${TODAY}: Friday close-out" "$NOTE_ABS"; then
  log "already closed out for ${TODAY} — nothing to do; exiting"; exit 0
fi

# ── DRY RUN ──────────────────────────────────────────────────────────────
if [[ "${DRY_RUN:-0}" == "1" ]]; then
  echo "── DRY RUN — would process weekly_logs/${YEAR}/${WEEK_TAG}.md ──"
  echo "  -> append close-out line to '## Claude Sessions'"
  echo "  -> fill the Master Note row's Summary cell for [[${WEEK_TAG}]] (backup + validate + rollback)"
  log "dry run"; exit 0
fi

# ── CONCURRENCY LOCK (atomic mkdir; released by the EXIT trap) ─────────────
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  log "another friday_process holds $LOCK_DIR — skipping"; exit 0
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT

# ── STAMP CLOSE-OUT into the note's Claude Sessions (deterministic) ────────
CLOSEOUT="- ${TODAY}: Friday close-out — week closed out"
if awk -v line="$CLOSEOUT" '
  $0=="## Claude Sessions" { incs=1 }
  incs && /^---[[:space:]]*$/ && !done { print line; done=1; incs=0 }
  { print }
  END { if (!done) print line }
' "$NOTE_ABS" > "$NOTE_ABS.tmp"; then
  mv "$NOTE_ABS.tmp" "$NOTE_ABS"
  log "close-out stamped into ${WEEK_TAG}.md"
else
  rm -f "$NOTE_ABS.tmp"
  log "WARNING: failed to stamp close-out into ${WEEK_TAG}.md"
fi

# ── DETERMINISTIC MASTER NOTE EDIT (backup → awk row rewrite → validate → rollback) ─
SUMMARY="Week closed out ${TODAY}."
if [[ -f "$MASTER" ]]; then
  BACKUP="$LOG_DIR/master.$(date +%s).bak"
  cp "$MASTER" "$BACKUP"
  pre_rows=$(grep -cE '^\| \[\[' "$MASTER" || true)

  # Rewrite ONLY field 6 of the row whose trimmed first cell == [[WEEK_TAG]].
  set +e
  awk -F'|' -v tag="[[${WEEK_TAG}]]" -v sum=" ${SUMMARY} " '
    BEGIN { OFS="|" }
    { c2=$2; gsub(/^[ \t]+|[ \t]+$/,"",c2)
      if (c2==tag && NF>=6) { $6=sum; hit=1 }
      print }
    END { exit (hit?0:3) }
  ' "$MASTER" > "$MASTER.tmp"
  awk_rc=$?
  set -e

  post_rows=$(grep -cE '^\| \[\[' "$MASTER.tmp" 2>/dev/null || true)
  if [[ $awk_rc -ne 0 ]]; then
    rm -f "$MASTER.tmp"
    log "WARNING: no Master Note row matched [[${WEEK_TAG}]] (awk_rc=$awk_rc) — summary not written; backup at $BACKUP"
  elif ! grep -Fq "$SENTINEL" "$MASTER.tmp" || [[ "$post_rows" -ne "$pre_rows" ]]; then
    rm -f "$MASTER.tmp"
    log "VALIDATION FAILED — sentinel missing or row count ${pre_rows}->${post_rows}; Master Note left unchanged (backup $BACKUP)"
  else
    mv "$MASTER.tmp" "$MASTER"
    rm -f "$BACKUP"
    log "Master Note summary written for $WEEK_TAG"
  fi
else
  log "WARNING: Master Note not found at $MASTER — summary not written"
fi

log "friday_process done — $WEEK_TAG closed out OK"
