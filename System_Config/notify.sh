#!/usr/bin/env bash
# notify.sh — minimal notification dispatch: Slack and/or Google Chat
# webhook, plus an opt-in local macOS banner fallback.
#
# Deliberately smaller than a flag-based/severity/dedup design: Agentic
# Light has no recurring scheduled jobs, so there's no repeat-alert to
# suppress and nothing to dedup against.
#
#   bash notify.sh "<title>" "<body>"
#
# Config: System_Config/.notify.env (git-ignored, mode 600), sourced if
# present. Recognized keys: SLACK_WEBHOOK_URL, GCHAT_WEBHOOK_URL,
# GCHAT_FALLBACK_LOCAL (1 = also try a local macOS banner via osascript;
# no-op if osascript isn't on PATH). Both webhook vars may be set at once —
# each is attempted independently; any one succeeding counts as delivered.
#
# Contract: never fails the caller for delivery reasons — exit 0 on any
# successful delivery (a webhook 2xx or the local banner) and on a
# deliberate no-config no-op; exit 1 only if delivery was attempted
# somewhere and failed everywhere. Every attempt is logged to
# System_Config/logs/notify.log.
set -uo pipefail   # not -e: one channel's curl failing must not abort before we try the next channel / log it

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT/System_Config/logs"
LOG="$LOG_DIR/notify.log"
ENV_FILE="$ROOT/System_Config/.notify.env"

if [ $# -lt 1 ]; then
  echo 'Usage: bash notify.sh "<title>" "<body>"' >&2
  exit 1
fi
TITLE="$1"
BODY="${2:-}"

# shellcheck disable=SC1090
[ -r "$ENV_FILE" ] && source "$ENV_FILE"

mkdir -p "$LOG_DIR"
log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" >> "$LOG"; }

json_esc() { printf '%s' "$1" | tr '\n\r\t' '   ' | sed 's/\\/\\\\/g; s/"/\\"/g'; }
applescript_esc() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }

PAYLOAD="{\"text\": \"*$(json_esc "$TITLE")*\n$(json_esc "$BODY")\"}"

# send_webhook <name> <url> — pipes the URL to curl via stdin config so it
# never appears as a bare argument (keeps the secret out of `ps` output).
send_webhook() {
  local name="$1" url="$2" code
  code="$(printf 'url = "%s"\n' "$url" | curl --config - -sS -o /dev/null -w '%{http_code}' --max-time 20 \
    -X POST -H 'Content-Type: application/json; charset=UTF-8' -d "$PAYLOAD" 2>>"$LOG")"
  case "$code" in
    2??) log "[ok] $name webhook delivered (http $code)"; return 0 ;;
    *)   log "[fail] $name webhook http=$code"; return 1 ;;
  esac
}

ATTEMPTED=0
DELIVERED=0

if [ -n "${SLACK_WEBHOOK_URL:-}" ]; then
  ATTEMPTED=1
  send_webhook "Slack" "$SLACK_WEBHOOK_URL" && DELIVERED=1
fi

if [ -n "${GCHAT_WEBHOOK_URL:-}" ]; then
  ATTEMPTED=1
  send_webhook "Google Chat" "$GCHAT_WEBHOOK_URL" && DELIVERED=1
fi

if [ "${GCHAT_FALLBACK_LOCAL:-0}" = "1" ]; then
  ATTEMPTED=1
  if command -v osascript >/dev/null 2>&1; then
    if osascript -e "display notification \"$(applescript_esc "$BODY")\" with title \"$(applescript_esc "$TITLE")\"" >>"$LOG" 2>&1; then
      log "[ok] local macOS notification delivered"
      DELIVERED=1
    else
      log "[fail] local macOS notification failed"
    fi
  else
    log "[skip] GCHAT_FALLBACK_LOCAL=1 but osascript not found (non-macOS)"
  fi
fi

if [ "$ATTEMPTED" -eq 0 ]; then
  log "[noop] no channel configured (SLACK_WEBHOOK_URL / GCHAT_WEBHOOK_URL / GCHAT_FALLBACK_LOCAL all unset)"
  exit 0
fi

[ "$DELIVERED" -eq 1 ] && exit 0
exit 1
