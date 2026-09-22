#!/usr/bin/env bash
# test_context_packet.sh — fixture tests for System_Config/context_packet.sh.
# Pattern mirrors test_providers.sh: plain bash assertions under
# set -euo pipefail, mktemp -d scratch, EXIT trap. Uses POSIX `[ ]` rather
# than `[[ ]]` for numeric assertions — verified empirically that this
# system's bash 3.2.57 does NOT abort under `set -e` on a failing bare
# `[[ ]]` command (a real, reproducible interpreter quirk here), so `[[ ]]`
# alone would silently pass a broken fixture. `[ ]` does abort correctly.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/agentic-light-context-packet-test.XXXXXX")"
trap 'rm -rf "$TMP_ROOT"' EXIT

# Fixture workspace: context_packet.sh resolves its own ROOT from
# $(dirname "${BASH_SOURCE[0]}")/.. , so copying it into a fresh
# System_Config/ naturally scopes it to this temp tree — no env override
# of ROOT needed.
FAKE_ROOT="$TMP_ROOT/fake-root"
mkdir -p "$FAKE_ROOT/System_Config" "$FAKE_ROOT/brain/weekly_logs/2024/W10"
cp "$ROOT/System_Config/context_packet.sh" "$FAKE_ROOT/System_Config/context_packet.sh"

# Line 1 of ROADMAP.md is packed with 60 em dashes (3 bytes each in UTF-8) —
# lands as line 5 of the packet under AGENTIC_LIGHT_CONTEXT_MAX_LINES=5
# below (packet lines 1-4 are the fixed header/Generated/blank/## Roadmap).
# Chosen so the packet's total CHARACTER count stays under MAX_BYTES=200
# (so a naive `${s:0:200}` character slice does not truncate at all and
# silently emits well over 200 bytes) while its total BYTE count exceeds
# 200 — this is exactly the scenario that proves the byte-slice fix, not
# just exercises it. A fixture with plain ASCII content could pass on the
# old buggy line too.
python3 -c "print('—' * 60)" > "$FAKE_ROOT/ROADMAP.md"
printf '## Agent Sessions\n- did a thing\n' > "$FAKE_ROOT/brain/weekly_logs/2024/W10/2024-W10.md"

SCRIPT="$FAKE_ROOT/System_Config/context_packet.sh"

# ---------------------------------------------------------------------------
# Fixture 1: a tiny byte budget with a dense multi-byte first ROADMAP line
# still respects both AGENTIC_LIGHT_CONTEXT_MAX_LINES and
# AGENTIC_LIGHT_CONTEXT_MAX_BYTES, and still contains the Generated: line
# (proves the budget didn't just clip mid multi-byte character or blow
# past MAX_BYTES). Output captured to a file, not `$(...)`, so a trailing
# newline isn't silently stripped before the byte count.
# ---------------------------------------------------------------------------
OUT1_FILE="$TMP_ROOT/out1"
AGENTIC_LIGHT_CONTEXT_MAX_LINES=5 AGENTIC_LIGHT_CONTEXT_MAX_BYTES=200 bash "$SCRIPT" > "$OUT1_FILE"
# errors='replace': the byte-exact truncation below can legitimately land
# mid multi-byte character at the 200-byte boundary — this check only
# cares about the untruncated packet's character count (the sanity check
# below re-derives it from the full, untruncated packet).
FULL_CHARS1=$(AGENTIC_LIGHT_CONTEXT_MAX_LINES=5 bash "$SCRIPT" | python3 -c "import sys; print(len(sys.stdin.buffer.read().decode('utf-8', 'replace')))")
BYTES1=$(wc -c < "$OUT1_FILE" | tr -d ' ')
[ "$FULL_CHARS1" -le 200 ]   # sanity: total chars fits in 200 too, so an
                              # untruncated char-sliced packet would still
                              # slip through under the old buggy line.
[ "$BYTES1" -le 200 ]        # the fix: real byte budget is actually held.
grep -q "^Generated:" "$OUT1_FILE"
echo "fixture 1 (tiny byte budget respected with dense multi-byte content): PASS"

# ---------------------------------------------------------------------------
# Fixture 2: default budget contains all provenance headers.
# ---------------------------------------------------------------------------
OUT2="$(bash "$SCRIPT")"
echo "$OUT2" | grep -q "^# Agentic Light Context Packet$"
echo "$OUT2" | grep -q "^Generated:"
echo "$OUT2" | grep -q "^## Roadmap$"
echo "$OUT2" | grep -q "^## Active Preset$"
echo "$OUT2" | grep -q "^## Recent Session Facts$"
echo "fixture 2 (default budget contains all provenance headers): PASS"

echo "context packet test: PASS"
