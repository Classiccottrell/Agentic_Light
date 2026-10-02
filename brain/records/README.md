# Durable Context Records

Records are Markdown files that humans and agents can read, edit, review, and
commit. They are indexed by `System_Config/context_catalog.py` and searched by
the context layer.

## Frontmatter

Every record requires:

```yaml
---
id: stable-kebab-case-id
type: project | decision | learning | reference | session
title: Human-readable title
status: active | stale | superseded | archived
scope: workspace | project | session
created: YYYY-MM-DD
updated: YYYY-MM-DD
author: human | ai | mixed
source: [path/to/source.md]
---
```

List values use the inline `[a, b]` form — `context_validate.py`'s parser
does not accept YAML block lists (`- item` lines).

Optional fields include `projects`, `tags`, and `related`. Use body wikilinks
for readable connections and frontmatter relations for machine retrieval.

## Session records

`sessions/` holds `type: session` records, written by tools, never by hand:

- `sessions/<run-id>.md` — one per `pipeline/run.py` launcher run (id
  `session-<run-id>`, tag `launcher-run`), written when the run ends on every
  exit path. Provenance is the run's `pipeline/logs/<run-id>.events.jsonl`
  (the audit trail of record) and `.log`. See `pipeline/README.md`'s
  "Session records".
- `sessions/curation-*.md` — one per `context_curate.py --apply`.

Both are indexed by `context_catalog.py` like any record and can be linked to
projects, decisions, and learnings with `context.py curate`.

## Write rules

- Human prose is never silently replaced.
- Raw captures remain immutable.
- Claims and learnings carry at least one source path.
- AI curation defaults to a reviewable proposal.
- Stale or conflicting knowledge is marked, not deleted.
- Run `python3 System_Config/context_validate.py validate brain/records` before committing.
