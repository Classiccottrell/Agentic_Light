# brain/ — LLM Wiki Schema

> Karpathy LLM Wiki pattern, adapted for Agentic Light. Three layers:
> Raw → Wiki → Schema (this file). Weekly logs sit alongside as first-class,
> dated records.

---

## brain/ Structure

```
brain/
├── CLAUDE.md                        ← schema (this file) — LLM operating instructions
├── README.md                        ← human-facing: Obsidian + Web Clipper setup
│
├── raw/                             ← LAYER 1: raw, immutable inputs (Web-Clipper format)
│   └── README.md
│   └── [YYYY]/[Wnn label]/          ← e.g. raw/2026/W30 Jul 20-24/
│
├── wiki/                            ← LAYER 2: LLM-maintained entity pages
│   ├── index.md                     ← wiki root with all entity links
│   └── <entity-slug>.md             ← one file per concept/person/project/technology
│
└── weekly_logs/                     ← weekly review notes, nested by year
    ├── Weekly_Note_Template.md
    ├── [YYYY] Master Note.md        ← e.g. "2026 Master Note.md"
    └── [YYYY]/YYYY-Www.md           ← e.g. weekly_logs/2026/2026-W30.md
```

`records/` is the durable, app-agnostic contract for projects, decisions,
learnings, references, and sessions. `index/` is disposable generated output.

---

## Layer 1 — Raw (Immutable)

- Files under `raw/[YYYY]/[Wnn label]/` are **never edited** after creation.
- Format: Obsidian Web Clipper output (`.md` with `clipped`/`source`/`author`
  frontmatter) — see `brain/raw/README.md`.
- Folder naming: `raw/YYYY/Wnn <human label>/`, e.g. `raw/2026/W30 Jul 20-24/`.
  `monday_init.py` creates the current week's folder automatically.
- On ingest (`daily_ingest.py`): create or update the corresponding wiki page
  for each clip's primary entity.

---

## Layer 2 — Wiki (LLM-Maintained)

Each wiki page covers exactly one entity (concept, person, project,
technology, or organization).

### Page frontmatter
```markdown
---
title: <Entity Name>
type: concept | person | project | technology | org
tags: []
updated: YYYY-MM-DD
---
```

### Page format
```markdown
---
title: <Entity Name>
type: concept | person | project | technology | org
tags: []
updated: YYYY-MM-DD
---

## Summary
<2-4 sentence synthesis. No bullet lists here.>

## Key Facts
- <atomic fact>
- <atomic fact>

## Connections
- [[related-entity]]
- [[related-entity]]

## Sources
- [[raw/YYYY/Wnn label/clip-slug]]
```

### Wikilink conventions
- `[[slug]]` — links resolve by filename (no extension), lowercase, hyphens
  only: `[[knowledge-management]]`, not `[[Knowledge Management]]`.
- Weekly notes link as `[[YYYY-Www]]`, e.g. `[[2026-W30]]`.
- Cross-link aggressively: scan existing wiki pages for matching terms and
  add `[[wikilinks]]`.

### Wiki maintenance rules
- One page per entity — merge duplicates, never split.
- Every claim must trace back to a `raw/` source.
- Never delete content — mark stale claims with `~~strikethrough~~` + updated date.
- Contradictions: preserve both claims, note the conflict inline.
- `wiki/index.md` must be updated whenever a page is added or removed
  (backup → edit → validate → rollback, same discipline as the weekly scripts).

---

## Layer 3 — Schema (This File)

Defines structure and conventions. The LLM reads this file first on every
session that touches `brain/`.

---

## Operations

### Ingest (new raw clip arrives)
1. Web Clipper saves to `raw/YYYY/Wnn label/`.
2. `daily_ingest.py` extracts entities → finds or creates wiki pages.
3. `wiki/index.md` is updated.
4. A line is appended to the current week's `## Agent Sessions` section
   (matching the legacy `## Claude Sessions` heading, retained for older
   notes, during the transition). Entries may come from any configured
   provider.

### Weekly cycle
- **Monday** — `monday_init.py` creates `weekly_logs/YYYY/YYYY-Www.md` from
  the template and a row in `[YYYY] Master Note.md`'s Weekly Index.
- **Friday** — `friday_process.py` closes out the week: appends to the
  `## Agent Sessions` section (or the legacy `## Claude Sessions` heading if
  that's what the note still has), then fills the Master Note row's Summary
  cell.

### Query
1. Try semantic search first: `System_Config/memory_search.py "<query>"`.
   Prints up to 5 (`--top N`) ranked `brain/wiki/` page paths, one per line.
2. If it exits non-zero (no index yet, or Ollama unreachable/model not
   pulled), fall back to keyword search: `rg -l "<keyword>" brain/wiki/`.
3. Read matching pages (max 5 at once).
4. Synthesize an answer with `[[citations]]`.
5. If the answer is novel → file it back into the wiki as a new page or update.

### Human-record curation
`System_Config/context.py curate <record> --suggest` proposes related records
without changing the source. Use `--review` to inspect medium and low
confidence candidates. Use `--apply` only when an explicit workflow permits
validated high-confidence links; it appends a Related Context section and
creates an AI session record. Human prose is never rewritten.

`System_Config/context.py validate` checks record frontmatter, required
sections, provenance, IDs, and wikilinks. `context.py catalog` rebuilds
`brain/index/catalog.json` and `links.json`; links in record bodies and
`related`/`source` frontmatter are projected together.

### Semantic search index (cache, not source of truth)
`System_Config/memory_index.py --root <workspace>` indexes records, wiki
pages, and weekly logs into SQLite FTS5 at `brain/index/memory.sqlite3`.
`--semantic` additionally stores local Ollama embeddings. Re-run it after
editing Markdown; the cache is disposable and rebuildable. `memory_search.py`
returns paths by default and structured excerpts with `--json`; `--semantic`
merges embedding scores when Ollama is available, while FTS remains usable
offline. Markdown remains the durable source of truth.

---

## Conventions

- ISO dates everywhere: `YYYY-MM-DD`.
- Weekly note naming: `YYYY-Www.md` (e.g. `2026-W30.md`) — never human-readable dates.
- Slugs: lowercase, hyphens only (`knowledge-management`, not `Knowledge Management`).
- Tags: lowercase, singular (`design`, `ai`, `tooling`, `concept`).
- Weekly logs: append-only — never overwrite existing content.
- `raw/` is immutable — never edited after a clip lands.
