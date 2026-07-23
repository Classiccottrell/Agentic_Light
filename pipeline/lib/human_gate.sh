#!/usr/bin/env bash
# human_gate.sh — render a summary/diff and block on interactive [y/N].
# Mirrors bootstrap.sh --uninstall's TTY-check pattern: never auto-approves.
# Usage: human_gate.sh "<summary text>"   (falls back to stdin if no arg)
# Exit codes: 0 approved | 1 declined | 2 pending (non-interactive)
#
# No -e here on purpose: this script's job is to return a specific exit code
# per branch (0/1/2), including from a `read` that can legitimately fail at
# EOF — that must not be treated as a fatal script error.
set -uo pipefail

SUMMARY="${1:-}"
if [ -z "$SUMMARY" ] && [ ! -t 0 ]; then
  SUMMARY="$(cat)"
fi

echo "=================================================="
echo " Human Gate — review before PR creation"
echo "=================================================="
echo
echo "${SUMMARY:-<no summary provided>}"
echo
echo "=================================================="

if [ ! -t 0 ]; then
  echo "Non-interactive session — cannot prompt for approval. Pending human review."
  exit 2
fi

printf "Approve and create PR? [y/N]: "
read -r REPLY || REPLY=""
case "$REPLY" in
  [yY]*) echo "-> Approved."; exit 0 ;;
  *)     echo "-> Declined. No PR will be created."; exit 1 ;;
esac
