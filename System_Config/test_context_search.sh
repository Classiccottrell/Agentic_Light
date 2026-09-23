#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/brain/records/learnings" "$TMP/brain/records/projects" "$TMP/brain/wiki" "$TMP/brain/weekly_logs/2026" "$TMP/brain/index"

cat > "$TMP/brain/records/learnings/retrieval.md" <<'EOF'
---
id: retrieval-learning
type: learning
title: Retrieval Learning
status: active
scope: workspace
created: 2026-09-23
updated: 2026-09-23
author: human
source: [brain/raw/source.md]
---
## Situation
Context retrieval needs a lexical fallback.
## Insight
FTS excerpts keep the packet useful when embeddings are unavailable.
## Evidence
Fixture.
## Reuse When
Local model is offline.
EOF
cat > "$TMP/brain/records/projects/other.md" <<'EOF'
---
id: other-project
type: project
title: Other Project
status: active
scope: project
created: 2026-09-23
updated: 2026-09-23
author: human
source: [brain/raw/source.md]
---
## Summary
Unrelated project.
## Goals
- Test indexing.
## Status
Active.
## Links
EOF
printf '%s\n' 'Wiki page' > "$TMP/brain/wiki/context.md"
printf '%s\n' 'Weekly project retrieval note' > "$TMP/brain/weekly_logs/2026/2026-W39.md"

python3 "$ROOT/System_Config/context_catalog.py" build --root "$TMP" --out-dir "$TMP/brain/index"
python3 "$ROOT/System_Config/memory_index.py" --root "$TMP"
RESULT="$(python3 "$ROOT/System_Config/memory_search.py" 'FTS excerpts' --root "$TMP" --json)"
python3 -c 'import json,sys; r=json.load(sys.stdin); assert r[0]["type"] == "learning"; assert "FTS excerpts" in r[0]["excerpt"]' <<< "$RESULT"
python3 "$ROOT/System_Config/memory_search.py" 'FTS excerpts' --root "$TMP" >/dev/null
echo 'context search fixture: PASS'
