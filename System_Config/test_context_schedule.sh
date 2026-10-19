#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
out="$(bash "$ROOT/System_Config/install_context_cadence.sh" --dry-run)"
grep -Fq "daily-ingest:" <<<"$out"
grep -Fq "at 7:0" <<<"$out"
grep -Fq "monday-init:" <<<"$out"
grep -Fq "weekday 2" <<<"$out"
grep -Fq "friday-process:" <<<"$out"
grep -Fq "weekday 6" <<<"$out"
echo "context schedule test: PASS"
