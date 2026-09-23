#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/brain/records/learnings" "$TMP/brain/records/projects" "$TMP/brain/records/sessions" "$TMP/brain/raw"
printf '%s\n' 'immutable source' > "$TMP/brain/raw/source.md"
cat > "$TMP/brain/records/projects/deployment.md" <<'EOF'
---
id: deployment-pipeline
type: project
title: Deployment Pipeline
status: active
scope: project
created: 2026-09-23
updated: 2026-09-23
author: human
source: [brain/raw/source.md]
---
## Summary
The deployment pipeline ships verified releases.
## Goals
- Keep deployment pipeline reliable.
## Status
Active.
## Links
EOF
cat > "$TMP/brain/records/projects/archive.md" <<'EOF'
---
id: archive-project
type: project
title: Archive
status: stale
scope: project
created: 2026-09-23
updated: 2026-09-23
author: human
source: [brain/raw/source.md]
---
## Summary
Archive.
## Goals
- Preserve history.
## Status
Stale.
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
The deployment pipeline is slow.
## Insight
The deployment pipeline needs a smaller verification pass.
## Evidence
Human observation.
## Reuse When
Pipeline work repeats.
EOF

SOURCE_HASH="$(shasum -a 256 "$TMP/brain/records/learnings/human.md" | awk '{print $1}')"
SUGGEST="$(bash "$ROOT/System_Config/context.sh" --root "$TMP" curate "$TMP/brain/records/learnings/human.md" --suggest)"
echo "$SUGGEST" | grep -q 'deployment-pipeline'
test "$SOURCE_HASH" = "$(shasum -a 256 "$TMP/brain/records/learnings/human.md" | awk '{print $1}')"

bash "$ROOT/System_Config/context.sh" --root "$TMP" curate "$TMP/brain/records/learnings/human.md" --apply >/dev/null
grep -q '\[\[deployment-pipeline\]\]' "$TMP/brain/records/learnings/human.md"
SUGGEST_AFTER="$(bash "$ROOT/System_Config/context.sh" --root "$TMP" curate "$TMP/brain/records/learnings/human.md" --suggest)"
if echo "$SUGGEST_AFTER" | grep -q 'curation-'; then
  echo 'curation session appeared as a candidate' >&2
  exit 1
fi
if grep -q '\[\[archive-project\]\]' "$TMP/brain/records/learnings/human.md"; then
  echo 'low-confidence link was applied' >&2
  exit 1
fi
test -n "$(find "$TMP/brain/records/sessions" -type f -name '*.md' -print -quit)"
test "$(cat "$TMP/brain/raw/source.md")" = 'immutable source'

echo 'context curation fixture: PASS'
