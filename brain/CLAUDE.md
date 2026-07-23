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

---

## Layer 1 — Raw (Immutable)

- Files under `raw/[YYYY]/[Wnn label]/` are **never edited** after creation.
- Format: Obsidian Web Clipper output (`.md` with `clipped`/`source`/`author`
  frontmatter) — see `brain/raw/README.md`.
- Folder naming: `raw/YYYY/Wnn <human label>/`, e.g. `raw/2026/W30 Jul 20-24/`.
  `monday_init.sh` creates the current week's folder automatically.
- On ingest (`daily_ingest.sh`): create or update the corresponding wiki page
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
2. `daily_ingest.sh` extracts entities → finds or creates wiki pages.
3. `wiki/index.md` is updated.
4. A line is appended to the current week's `## Claude Sessions`.

### Weekly cycle
- **Monday** — `monday_init.sh` creates `weekly_logs/YYYY/YYYY-Www.md` from
  the template and a row in `[YYYY] Master Note.md`'s Weekly Index.
- **Friday** — `friday_process.sh` closes out the week: appends to
  `## Claude Sessions`, fills the Master Note row's Summary cell.

### Query
1. Search `wiki/` for entity pages: `rg -l "<keyword>" brain/wiki/`
2. Read matching pages (max 5 at once).
3. Synthesize an answer with `[[citations]]`.
4. If the answer is novel → file it back into the wiki as a new page or update.

---

## Conventions

- ISO dates everywhere: `YYYY-MM-DD`.
- Weekly note naming: `YYYY-Www.md` (e.g. `2026-W30.md`) — never human-readable dates.
- Slugs: lowercase, hyphens only (`knowledge-management`, not `Knowledge Management`).
- Tags: lowercase, singular (`design`, `ai`, `tooling`, `concept`).
- Weekly logs: append-only — never overwrite existing content.
- `raw/` is immutable — never edited after a clip lands.
