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
SUGGEST="$(python3 "$ROOT/System_Config/context.py" --root "$TMP" curate "$TMP/brain/records/learnings/human.md" --suggest)"
echo "$SUGGEST" | grep -q 'deployment-pipeline'
test "$SOURCE_HASH" = "$(shasum -a 256 "$TMP/brain/records/learnings/human.md" | awk '{print $1}')"

python3 "$ROOT/System_Config/context.py" --root "$TMP" curate "$TMP/brain/records/learnings/human.md" --apply >/dev/null
if grep -q '\[\[deployment-pipeline\]\]' "$TMP/brain/records/learnings/human.md"; then
  echo 'human-authored record was changed by automatic curation' >&2
  exit 1
fi
SUGGEST_AFTER="$(python3 "$ROOT/System_Config/context.py" --root "$TMP" curate "$TMP/brain/records/learnings/human.md" --suggest)"
if echo "$SUGGEST_AFTER" | grep -q 'curation-'; then
  echo 'curation session appeared as a candidate' >&2
  exit 1
fi
if grep -q '\[\[archive-project\]\]' "$TMP/brain/records/learnings/human.md"; then
  echo 'low-confidence link was applied' >&2
  exit 1
fi

cat > "$TMP/brain/records/learnings/weak-agent-match.md" <<'EOF'
---
id: weak-agent-match
type: learning
title: Deployment Cache
status: active
scope: workspace
created: 2026-09-23
updated: 2026-09-23
author: ai
source: [brain/raw/source.md]
---
## Situation
Deployment pipeline verification needs a cache.
## Insight
Cache the deployment results.
## Evidence
Generated observation.
## Reuse When
Deployment work repeats.
EOF
python3 "$ROOT/System_Config/context.py" --root "$TMP" curate "$TMP/brain/records/learnings/weak-agent-match.md" --apply >/dev/null
if grep -q '\[\[deployment-pipeline\]\]' "$TMP/brain/records/learnings/weak-agent-match.md"; then
  echo 'weak agent match was applied' >&2
  exit 1
fi

cat > "$TMP/brain/records/learnings/agent-curation.md" <<'EOF'
---
id: agent-curation
type: learning
title: Deployment Pipeline
status: active
scope: workspace
created: 2026-09-23
updated: 2026-09-23
author: ai
source: [brain/raw/source.md]
---
## Situation
Deployment pipeline ships verified releases.
## Insight
Verified deployment pipeline releases need review.
## Evidence
Generated observation.
## Reuse When
Deployment work repeats.
EOF
BEFORE_SESSIONS="$(find "$TMP/brain/records/sessions" -type f | wc -l | tr -d ' ')"
python3 "$ROOT/System_Config/context.py" --root "$TMP" curate "$TMP/brain/records/learnings/agent-curation.md" --apply >/dev/null
cat > "$TMP/brain/records/projects/releases.md" <<'EOF'
---
id: verified-releases
type: project
title: Verified Releases
status: active
scope: project
created: 2026-09-23
updated: 2026-09-23
author: human
source: [brain/raw/source.md]
---
## Summary
Deployment pipeline ships verified releases.
## Goals
- Keep verified releases reliable.
## Status
Active.
## Links
EOF
python3 "$ROOT/System_Config/context.py" --root "$TMP" curate "$TMP/brain/records/learnings/agent-curation.md" --apply >/dev/null
grep -q '\[\[verified-releases\]\]' "$TMP/brain/records/learnings/agent-curation.md"
test "$(grep -c '^## Related Context$' "$TMP/brain/records/learnings/agent-curation.md")" -eq 1
AFTER_SESSIONS="$(find "$TMP/brain/records/sessions" -type f | wc -l | tr -d ' ')"
test "$AFTER_SESSIONS" -eq "$((BEFORE_SESSIONS + 2))"
test -n "$(find "$TMP/brain/records/sessions" -type f -name '*.md' -print -quit)"
test "$(cat "$TMP/brain/raw/source.md")" = 'immutable source'

echo 'context curation fixture: PASS'
