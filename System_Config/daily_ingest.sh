#!/usr/bin/env bash
# daily_ingest.sh — brain/ raw-clip ingestion
# Scans brain/raw/YYYY/Wnn label/*.md (two directory levels deep under
# raw/: YYYY/, then "Wnn label"/) for new .md clips and runs the agent CLI
# headlessly to wikify them
# (create/update brain/wiki/ pages, update wiki/index.md, log to the
# current weekly note). Processes ONE clip per agent call so a partial
# failure only retries that clip. Manual-trigger only.
#
#   Manual run:  bash System_Config/daily_ingest.sh
#   Preview:     DRY_RUN=1 bash System_Config/daily_ingest.sh

set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/config.sh"

# ── CONFIG ───────────────────────────────────────────────────────────────
LOG="$LOG_DIR/daily_ingest.log"
WEEKLY_LOGS="$BRAIN/weekly_logs"
MAX_SECONDS="${MAX_SECONDS:-180}"     # per-clip wall-clock watchdog (both providers)
MAX_BUDGET="${MAX_BUDGET:-1.00}"      # per-clip USD ceiling (claude only)
MAX_CLIPS_PER_RUN="${MAX_CLIPS_PER_RUN:-10}"

mkdir -p "$LOG_DIR"
ts() { date "+%Y-%m-%d %H:%M:%S"; }
log() { echo "[$(ts)] $*" >> "$LOG"; }

log "daily_ingest start (scanning: $RAW)"

YEAR=$(date +%G)
WEEK=$(date +%V)
TODAY=$(date +%Y-%m-%d)
WEEKLY_NOTE="weekly_logs/${YEAR}/${YEAR}-W${WEEK}.md"

# ── CONCURRENCY LOCK (atomic mkdir; released by the EXIT trap) ─────────────
LOCK_DIR="$LOG_DIR/daily_ingest.lock"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  log "another daily_ingest holds $LOCK_DIR — skipping"; exit 0
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT

if [[ ! -d "$RAW" ]]; then
  log "no raw dir at $RAW — nothing to ingest; exiting"
  exit 0
fi

# ── WARN on anything nested deeper than raw/YYYY/Wnn label/*.md (depth 3) ──
# YYYY/ is level 1, "Wnn label"/ is level 2, so clip files sit at depth 3
# under $RAW; anything at depth 4+ is nested one folder too deep.
DEEP_COUNT=$(find "$RAW" -mindepth 4 -type f -name '*.md' 2>/dev/null | wc -l | tr -d ' ')
if [[ "$DEEP_COUNT" -gt 0 ]]; then
  log "WARN: ${DEEP_COUNT} .md file(s) nested deeper than raw/YYYY/Wnn label/ — skipped (flatten to two levels to ingest)"
fi

# ── BOUNDED HEADLESS AGENT CALL ─────────────────────────────────────────────
source "$(dirname "${BASH_SOURCE[0]}")/run_agent.sh"

# ── FIND CANDIDATE CLIPS (raw/YYYY/Wnn label/*.md — depth 3 under raw/) ────
FOUND="$(mktemp)"
if ! find "$RAW" -mindepth 3 -maxdepth 3 -type f -name '*.md' > "$FOUND" 2>>"$LOG"; then
  log "FATAL: find failed scanning $RAW"
  rm -f "$FOUND"
  exit 0
fi

total_new=0
total_ingested=0
consecutive_bad=0
attempted=0
wall_hit=0

# manifest / failure log live at the top of raw/ (workspace-wide, single ledger).
MANIFEST="$RAW/.ingested.log"
FAILMF="$RAW/.failed.log"
touch "$MANIFEST"

name_seen() { awk -F'\t' -v n="$1" '$NF==n{f=1} END{exit !f}' "$MANIFEST"; }
hash_seen() { awk -F'\t' -v h="$1" 'NF>=2 && $1==h{f=1} END{exit !f}' "$MANIFEST"; }
attempts_of() { awk -F'\t' -v n="$1" '$2==n{print $1; exit}' "$FAILMF" 2>/dev/null || true; }
bump_fail() {
  local n="$1" c; c="$(attempts_of "$n")"; c=$(( ${c:-0} + 1 ))
  { [[ -f "$FAILMF" ]] && awk -F'\t' -v n="$n" '$2!=n' "$FAILMF"; printf '%s\t%s\n' "$c" "$n"; } > "$FAILMF.tmp"
  mv "$FAILMF.tmp" "$FAILMF"
}
clear_fail() {
  [[ -f "$FAILMF" ]] || return 0
  awk -F'\t' -v n="$1" '$2!=n' "$FAILMF" > "$FAILMF.tmp" && mv "$FAILMF.tmp" "$FAILMF"
}

NEW_LIST="$(mktemp)"
while IFS= read -r f; do
  rel="${f#"$RAW"/}"
  base="$(basename "$f")"
  case "$base" in
    _*|.*) continue ;;
  esac
  name_seen "$rel" && continue
  h="$(sha256sum "$f" | awk '{print $1}')"
  if hash_seen "$h"; then
    log "skip (duplicate content of an already-ingested clip): $rel [${h:0:12}]"
    printf '%s\t%s\n' "$h" "$rel" >> "$MANIFEST"
    continue
  fi
  echo "$rel" >> "$NEW_LIST"
done < "$FOUND"
rm -f "$FOUND"

total_new=$(wc -l < "$NEW_LIST" | tr -d ' ')
if [[ "$total_new" -eq 0 ]]; then
  log "no new clips in $RAW"
  rm -f "$NEW_LIST"
  exit 0
fi
log "new clips (${total_new}): $(tr '\n' ' ' < "$NEW_LIST")"

# ── DRY RUN ──────────────────────────────────────────────────────────────
if [[ "${DRY_RUN:-0}" == "1" ]]; then
  echo "── DRY RUN — would ingest ${total_new} clip(s) from $RAW, one agent call each ──"
  cat "$NEW_LIST"
  echo "── weekly note: ${WEEKLY_NOTE} ──"
  echo "── per-clip flags: --allowedTools Read,Write,Edit,Glob,Grep --disallowedTools Bash,... --permission-mode acceptEdits --max-budget-usd ${MAX_BUDGET} (watchdog ${MAX_SECONDS}s) ──"
  log "dry run — no agent call"
  rm -f "$NEW_LIST"
  exit 0
fi

# Lock raw/ notes read-only while agent calls run (restored on EXIT).
find "$RAW" -mindepth 3 -maxdepth 3 -type f -name '*.md' -exec chmod a-w {} + 2>/dev/null || true
restore_raw() { find "$RAW" -mindepth 3 -maxdepth 3 -type f -name '*.md' -exec chmod u+w {} + 2>/dev/null || true; }
trap 'restore_raw; rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT

# ── INGEST EACH CLIP INDEPENDENTLY ──────────────────────────────────────────
while IFS= read -r rel; do
  if [[ "$wall_hit" == "1" ]]; then break; fi
  if [[ "$attempted" -ge "$MAX_CLIPS_PER_RUN" ]]; then
    log "PER-RUN CLIP CAP reached (MAX_CLIPS_PER_RUN=${MAX_CLIPS_PER_RUN}) — stopping; remaining clips retry next run"
    break
  fi
  fc="$(attempts_of "$rel")"
  if [[ "${fc:-0}" -ge 3 ]]; then
    log "QUARANTINED (${fc} failed attempts): $rel — fix or remove the clip, then delete its line from raw/.failed.log"
    continue
  fi
  attempted=$((attempted + 1))
  src_link="raw/${rel%.md}"
  PROMPT="You are running headlessly to ingest ONE clip into the brain/ knowledge wiki.
First read CLAUDE.md for the wiki schema and conventions.

Clip to process: raw/${rel}

Steps:
1. Read raw/${rel}. Do NOT edit it — files in raw/ are immutable.
2. Identify the primary entity (project, person, technology, org, or concept) and create or update its page in wiki/ using the page format in CLAUDE.md.
   - IDEMPOTENCY: first check whether the target wiki page already contains a link to [[${src_link}]]. If it does, this clip was already ingested — make NO changes and stop.
   - If the page exists: APPEND new facts and add '- [[${src_link}]]' under its Sources section. Never rewrite or delete existing content.
   - If new: create it with the exact frontmatter + sections, including the [[${src_link}]] link.
   - Cross-link aggressively to existing wiki pages with [[wikilinks]].
3. Update wiki/index.md to list any new wiki page and the new source (skip if already listed).
4. Ensure ${WEEKLY_NOTE} exists. If not, create it from weekly_logs/Weekly_Note_Template.md (WEEK_NUM=${WEEK}, YEAR=${YEAR}).
5. Append exactly one line to its '## Claude Sessions' section: '- ${TODAY}: ingested ${rel} -> [[wiki/<page-slug>]]'.

Constraints: create-or-append only; never overwrite a page wholesale; never delete anything; stay within brain/."

  log "ingesting: $rel"
  log_offset="$(wc -c < "$LOG" | tr -d ' ')"
  if run_agent "$PROMPT"; then
    if grep -rqF "[[${src_link}]]" "$BRAIN/wiki/" 2>/dev/null; then
      h="$(sha256sum "$RAW/$rel" | awk '{print $1}')"
      printf '%s\t%s\n' "$h" "$rel" >> "$MANIFEST"
      total_ingested=$((total_ingested + 1))
      log "OK: $rel"
      consecutive_bad=0
      clear_fail "$rel"
    else
      log "NO-OP (exit 0 but no wiki link to ${src_link}): $rel — NOT recorded, will retry next run"
      consecutive_bad=$((consecutive_bad + 1))
      bump_fail "$rel"
    fi
  else
    rc=$?
    log "FAILED (rc=${rc}; may have timed out after ${MAX_SECONDS}s): $rel — NOT recorded, will retry next run"
    consecutive_bad=$((consecutive_bad + 1))
    bump_fail "$rel"
  fi

  if [[ "$consecutive_bad" -ge 2 ]]; then
    log "QUOTA/BUDGET WALL suspected after ${attempted} clips — stopping this run; remaining clips retry next run"
    wall_hit=1
    break
  fi
done < "$NEW_LIST"

rm -f "$NEW_LIST"
pending=$((total_new - total_ingested))
log "daily_ingest done — ingested ${total_ingested}/${total_new} clip(s); ${pending} still pending"
