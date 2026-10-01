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
grep -q '\[\[deployment-pipeline\]\]' "$TMP/brain/records/learnings/human.md"
SUGGEST_AFTER="$(python3 "$ROOT/System_Config/context.py" --root "$TMP" curate "$TMP/brain/records/learnings/human.md" --suggest)"
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

# A second high-confidence target added later lands under the SAME
# `## Related Context` heading (a second --apply used to add another).
cat > "$TMP/brain/records/projects/verification.md" <<'EOF'
---
id: verification-pass
type: project
title: Smaller Verification Pass
status: active
scope: project
created: 2026-09-24
updated: 2026-09-24
author: human
source: [brain/raw/source.md]
---
## Summary
Trim the verification pass.
## Goals
- Faster checks.
## Status
Active.
## Links
EOF
SESSIONS_BEFORE="$(find "$TMP/brain/records/sessions" -name 'curation-*.md' | wc -l)"
python3 "$ROOT/System_Config/context.py" --root "$TMP" curate "$TMP/brain/records/learnings/human.md" --apply >/dev/null
python3 "$ROOT/System_Config/context.py" --root "$TMP" curate "$TMP/brain/records/learnings/human.md" --apply >/dev/null
grep -q '\[\[verification-pass\]\]' "$TMP/brain/records/learnings/human.md"
test "$(grep -c '^## Related Context$' "$TMP/brain/records/learnings/human.md")" = 1
test "$(grep -c '\[\[deployment-pipeline\]\]' "$TMP/brain/records/learnings/human.md")" = 1
# Two applies in the same second each leave their own session record.
SESSIONS_AFTER="$(find "$TMP/brain/records/sessions" -name 'curation-*.md' | wc -l)"
test "$SESSIONS_AFTER" -eq $((SESSIONS_BEFORE + 2))
python3 "$ROOT/System_Config/context_validate.py" validate "$TMP/brain/records" --root "$TMP"

# Precision: one shared title word is not enough to auto-link
# ("agent" alone used to link these two).
cat > "$TMP/brain/records/learnings/sqlite.md" <<'EOF'
---
id: sqlite-cache
type: learning
title: Use SQLite for the agent cache
status: active
scope: workspace
created: 2026-09-25
updated: 2026-09-25
author: human
source: [brain/raw/source.md]
---
## Situation
The agent cache needs a store.
## Insight
Use SQLite for the agent cache; it ships with Python.
## Evidence
Stdlib only.
## Reuse When
Picking storage.
EOF
cat > "$TMP/brain/records/learnings/timeouts.md" <<'EOF'
---
id: agent-timeouts
type: learning
title: Agent timeouts need a watchdog
status: active
scope: workspace
created: 2026-09-25
updated: 2026-09-25
author: human
source: [brain/raw/source.md]
---
## Situation
The agent hung for an hour.
## Insight
Kill a hung agent process with a watchdog.
## Evidence
Logs.
## Reuse When
Running any agent.
EOF
python3 "$ROOT/System_Config/context.py" --root "$TMP" curate "$TMP/brain/records/learnings/sqlite.md" --apply >/dev/null
if grep -q '\[\[agent-timeouts\]\]' "$TMP/brain/records/learnings/sqlite.md"; then
  echo 'one shared title word auto-linked an unrelated record' >&2
  exit 1
fi
python3 "$ROOT/System_Config/context.py" --root "$TMP" curate "$TMP/brain/records/learnings/sqlite.md" --suggest | grep -q '^medium	agent-timeouts'

echo 'context curation fixture: PASS'
