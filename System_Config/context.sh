#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
if [[ "${1:-}" == "--root" ]]; then ROOT="$2"; shift 2; fi
COMMAND="${1:-}"
shift || true
case "$COMMAND" in
  packet) exec "$SCRIPT_DIR/context_packet.sh" --root "$ROOT" "$@";;
  validate) exec python3 "$SCRIPT_DIR/context_validate.py" validate "${1:-$ROOT/brain/records}" --root "$ROOT";;
  catalog) exec python3 "$SCRIPT_DIR/context_catalog.py" build --root "$ROOT" --out-dir "$ROOT/brain/index";;
  curate) FILE="${1:-}"; shift || true; exec python3 "$SCRIPT_DIR/context_curate.py" "$FILE" --root "$ROOT" "$@";;
  *) echo "usage: context.sh [--root ROOT] packet|validate|catalog|curate" >&2; exit 2;;
esac
