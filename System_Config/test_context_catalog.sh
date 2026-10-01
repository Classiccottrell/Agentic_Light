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

rm "$TMP/brain/records/learnings/broken.md"

# Provenance must point at something real: a missing raw file, a path
# escaping the workspace, and a dangling `related:` link (block-list form,
# which used to parse as a nested list and never get checked) all fail.
# A URL source is accepted as-is.
record() {  # record <file> <id> <source> <related-block>
  cat > "$1" <<EOF
---
id: $2
type: learning
title: $2
status: active
scope: workspace
created: 2026-09-23
updated: 2026-09-23
author: human
source: [$3]
related:
$4
---
## Situation
x
## Insight
x
## Evidence
x
## Reuse When
x
EOF
}
expect_fail() {  # expect_fail <file> <finding-substring>
  if OUT="$(python3 "$ROOT/System_Config/context_validate.py" validate "$1" --root "$TMP" 2>&1)"; then
    echo "expected failure for $1" >&2; exit 1
  fi
  case "$OUT" in *"$2"*) : ;; *) echo "expected '$2' in: $OUT" >&2; exit 1 ;; esac
  rm "$1"
}
L="$TMP/brain/records/learnings"
record "$L/missing-source.md" missing-source brain/raw/2026/W39/nope.md '  - [[demo-project]]'
expect_fail "$L/missing-source.md" 'source not found: brain/raw/2026/W39/nope.md'
record "$L/escaping-source.md" escaping-source ../outside.md '  - [[demo-project]]'
expect_fail "$L/escaping-source.md" 'source escapes the workspace: ../outside.md'
record "$L/dangling-related.md" dangling-related brain/raw/2026/W39/source.md '  - [[no-such-record]]'
expect_fail "$L/dangling-related.md" 'broken related link: no-such-record'
record "$L/good.md" good-record https://example.com/paper '  - [[demo-project|the demo]]'
python3 "$ROOT/System_Config/context_validate.py" validate "$L/good.md" --root "$TMP"
python3 "$ROOT/System_Config/context_catalog.py" build --root "$TMP" --out-dir "$TMP/brain/index"
python3 - "$TMP" <<'PY'
import json, pathlib, sys
links = json.loads((pathlib.Path(sys.argv[1]) / 'brain/index/links.json').read_text())['links']
assert any(l['relation'] == 'related' and l['target'] == 'brain/records/projects/demo.md' and l['confidence'] == 1.0 for l in links), links
PY
rm "$L/good.md"

cp "$TMP/brain/records/projects/demo.md" "$TMP/brain/records/projects/duplicate.md"
if python3 "$ROOT/System_Config/context_validate.py" validate "$TMP/brain" --root "$TMP"; then
  echo 'expected duplicate-id failure' >&2
  exit 1
fi

echo 'context catalog fixture: PASS'
