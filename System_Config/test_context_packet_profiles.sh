#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/System_Config/context_profiles" "$TMP/app-context"
cat > "$TMP/System_Config/context_profiles/example-app.json" <<'EOF'
{"name":"example-app","context_root":"app-context","default_scopes":["learning"],"include_paths":["app-context/learning.md"]}
EOF
printf '%s\n' 'private workspace roadmap must not leak' > "$TMP/ROADMAP.md"
printf '%s\n' 'app learning: café, résumé, naïve, façade' > "$TMP/app-context/learning.md"

PACKET="$(bash "$ROOT/System_Config/context.sh" --root "$TMP" packet --profile example-app --query learning --max-bytes 300)"
case "$PACKET" in
  *'app learning'* ) : ;;
  * ) echo 'expected app record in packet' >&2; exit 1 ;;
esac
case "$PACKET" in
  *'private workspace roadmap'* ) echo 'profile leaked outside context_root' >&2; exit 1 ;;
esac

echo "$PACKET" | grep -q 'Profile Include: app-context/learning.md'
BYTES="$(printf '%s' "$PACKET" | wc -c | tr -d ' ')"
test "$BYTES" -le 300

printf '%s\n' 'context packet profile fixture: PASS'
