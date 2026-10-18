#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/brain/records"/{projects,decisions,learnings,sessions} "$TMP/brain/raw" "$TMP/brain/wiki" "$TMP/brain/index" "$TMP/brain/other" "$TMP/System_Config/context_profiles"
cat > "$TMP/System_Config/context_profiles/other.json" <<'EOF'
{"name":"other","context_root":"brain/other","include_paths":[]}
EOF
printf '%s\n' 'immutable raw source' > "$TMP/brain/raw/source.md"
cat > "$TMP/brain/records/projects/light.md" <<'EOF'
---
id: light-project
type: project
title: Agentic Light
status: active
scope: project
created: 2026-09-23
updated: 2026-09-23
author: human
source: [brain/raw/source.md]
related: [[[human-learning]]]
---
## Summary
Agentic Light keeps context portable.
## Goals
- Keep context searchable.
## Status
Active.
## Links
EOF
cat > "$TMP/brain/records/learnings/human.md" <<'EOF'
---
id: human-learning
type: learning
title: Human Learning
status: active
scope: workspace
created: 2026-09-23
updated: 2026-09-23
author: human
source: [brain/raw/source.md]
---
## Situation
The context layer needs app-agnostic records.
## Insight
Human records for Agentic Light should be linked by the agent.
## Evidence
The project needs searchable memory.
## Reuse When
Building a new harness.
EOF
cat > "$TMP/brain/records/decisions/search.md" <<'EOF'
---
id: search-decision
type: decision
title: Search Decision
status: active
scope: workspace
created: 2026-09-23
updated: 2026-09-23
author: agent
source: [brain/raw/source.md]
---
## Decision
Use SQLite FTS5 as the offline index.
## Alternatives
Hosted vector service.
## Rationale
The source must stay local and rebuildable.
## Consequences
Semantic search remains optional.
EOF
cat > "$TMP/brain/wiki/context.md" <<'EOF'
---
title: Context Wiki
---
The context layer is searchable.
EOF

HASH="$(shasum -a 256 "$TMP/brain/raw/source.md" | awk '{print $1}')"
python3 "$ROOT/System_Config/context.py" --root "$TMP" validate >/dev/null
python3 "$ROOT/System_Config/context.py" --root "$TMP" catalog >/dev/null
grep -q '"relation": "related"' "$TMP/brain/index/links.json"
grep -q 'brain/records/learnings/human.md' "$TMP/brain/index/links.json"

SUGGEST="$(python3 "$ROOT/System_Config/context.py" --root "$TMP" curate "$TMP/brain/records/learnings/human.md" --suggest)"
echo "$SUGGEST" | grep -q 'light-project'
python3 "$ROOT/System_Config/context.py" --root "$TMP" curate "$TMP/brain/records/learnings/human.md" --apply >/dev/null
grep -q '\[\[light-project\]\]' "$TMP/brain/records/learnings/human.md"
test "$HASH" = "$(shasum -a 256 "$TMP/brain/raw/source.md" | awk '{print $1}')"

python3 "$ROOT/System_Config/memory_index.py" --root "$TMP" >/dev/null
RESULT="$(python3 "$ROOT/System_Config/memory_search.py" --root "$TMP" --json 'context layer')"
echo "$RESULT" | grep -q 'human-learning'
PACKET="$(python3 "$ROOT/System_Config/context.py" --root "$TMP" packet --profile other --max-bytes 1200)"
test "${#PACKET}" -le 1200
! echo "$PACKET" | grep -q 'Agentic Light'

cp -R "$TMP" "$TMP-invalid"
printf '%s\n' '[[missing-record]]' >> "$TMP-invalid/brain/records/learnings/human.md"
if python3 "$ROOT/System_Config/context.py" --root "$TMP-invalid" validate >/dev/null 2>&1; then exit 1; fi
cp "$TMP/brain/records/projects/light.md" "$TMP/brain/records/projects/duplicate.md"
if python3 "$ROOT/System_Config/context.py" --root "$TMP" validate >/dev/null 2>&1; then exit 1; fi

python3 - "$TMP/brain/index/memory.sqlite3" "$ROOT/System_Config" <<'PY'
import sqlite3, sys
from pathlib import Path
sys.path.insert(0, sys.argv[2])
from memory_index import fake_embed, open_db
from memory_search import search
db = open_db(Path(sys.argv[1]))
db.execute("UPDATE pages SET dim = dim + 1")
db.commit()
assert all(path != "brain/wiki/context.md" for path, _ in search(db, fake_embed("context layer"), 10))
PY
python3 "$ROOT/System_Config/memory_index.py" --root "$TMP" --semantic >/dev/null 2>"$TMP/ollama.err"
grep -Eq 'Ollama|semantic indexing skipped|lexical index ready' "$TMP/ollama.err"

printf '—%.0s' {1..4000} > "$TMP/ROADMAP.md"
AGENTIC_LIGHT_CONTEXT_MAX_BYTES=256 python3 "$ROOT/System_Config/context_packet.py" --root "$TMP" > "$TMP/packet.txt"
test "$(wc -c < "$TMP/packet.txt" | tr -d ' ')" -le 256

echo 'context layer fixture: PASS'
