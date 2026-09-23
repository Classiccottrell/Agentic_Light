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
source:
  - path/to/source.md
---
```

Optional fields include `projects`, `tags`, and `related`. Use body wikilinks
for readable connections and frontmatter relations for machine retrieval.

## Write rules

- Human prose is never silently replaced.
- Raw captures remain immutable.
- Claims and learnings carry at least one source path.
- AI curation defaults to a reviewable proposal.
- Stale or conflicting knowledge is marked, not deleted.
- Run `python3 System_Config/context_validate.py validate brain/records` before committing.
