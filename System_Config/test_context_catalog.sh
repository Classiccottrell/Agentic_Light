#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/brain/records/projects" "$TMP/brain/records/learnings" "$TMP/brain/wiki" "$TMP/brain/raw/2026/W39" "$TMP/brain/index"
cat > "$TMP/brain/records/projects/demo.md" <<'EOF'
---
id: demo-project
type: project
title: Demo Project
status: active
scope: project
projects: [demo]
tags: [test]
created: 2026-09-23
updated: 2026-09-23
author: human
source: [brain/raw/2026/W39/source.md]
related: []
---
## Summary
Demo project.
## Goals
- Test catalog.
## Status
Active.
## Links
EOF
printf '%s\n' '# immutable' > "$TMP/brain/raw/2026/W39/source.md"

python3 "$ROOT/System_Config/context_validate.py" validate "$TMP/brain/records/projects/demo.md" --root "$TMP"
python3 "$ROOT/System_Config/context_catalog.py" build --root "$TMP" --out-dir "$TMP/brain/index"
python3 - "$TMP" <<'PY'
import json, pathlib, sys
root = pathlib.Path(sys.argv[1])
catalog = json.loads((root / 'brain/index/catalog.json').read_text())
assert catalog['documents'][0]['id'] == 'demo-project'
assert catalog['documents'][0]['excerpt'].startswith('Demo project.')
assert (root / 'brain/raw/2026/W39/source.md').read_text() == '# immutable\n'
PY

cat > "$TMP/brain/records/learnings/broken.md" <<'EOF'
---
id: broken
type: learning
title: Broken
status: active
scope: workspace
created: 2026-09-23
updated: 2026-09-23
author: human
source: []
---
## Situation
Test.
## Insight
Broken.
## Evidence
None.
## Reuse When
Never.
EOF
if python3 "$ROOT/System_Config/context_validate.py" validate "$TMP/brain/records/learnings/broken.md" --root "$TMP"; then
  echo 'expected missing provenance failure' >&2
  exit 1
fi

cp "$TMP/brain/records/projects/demo.md" "$TMP/brain/records/projects/duplicate.md"
if python3 "$ROOT/System_Config/context_validate.py" validate "$TMP/brain" --root "$TMP"; then
  echo 'expected duplicate-id failure' >&2
  exit 1
fi

echo 'context catalog fixture: PASS'
