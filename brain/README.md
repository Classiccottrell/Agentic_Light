# brain/ — Second Brain (plain markdown + SQLite)

The context layer is plain markdown (`brain/wiki/*.md`, `brain/raw/`,
`brain/weekly_logs/`) plus a gitignored SQLite semantic-search cache
(`memory_index.py`/`memory_search.py`) — readable and writable by any editor,
script, or agent, with zero Obsidian dependency. Opening it in Obsidian is
one optional way to browse it (graph view, backlinks, switcher); it is not
required for ingest, search, or curation to work. `.obsidian/` config is
shipped at the `Agentic_Light/` root purely for that optional zero-setup
Obsidian experience — see "`.obsidian/` Is Shipped" in the root `CLAUDE.md`.

## Open in Obsidian (optional)
1. Obsidian → **Open folder as vault** → select `Agentic_Light/`.
2. Graph view, backlinks, and the switcher populate from `brain/wiki/` and
   `brain/weekly_logs/` immediately (`.obsidian/graph.json` groups them by
   color).

## Obsidian Web Clipper
Clips land in `brain/raw/YYYY/Wnn <label>/` — `System_Config/monday_init.sh`
creates the current week's folder when you run it. `daily_ingest.sh` also
self-heals the same folder if missing, so a note has somewhere to land
whichever script you run first. Point the Web Clipper's save location at
that week's folder (or configure a template that writes there). See
`brain/raw/README.md` for the exact naming convention and frontmatter format.

## Ingestion
`System_Config/daily_ingest.sh` scans `brain/raw/**/*.md` (two levels deep)
and turns new clips into wiki pages under `brain/wiki/`. See
`brain/CLAUDE.md` for the full schema.

## Semantic search
`System_Config/memory_index.py --root <workspace>` builds a gitignored,
rebuildable SQLite cache over records, wiki pages, and weekly logs. FTS5 works
offline; add `--semantic` to request local Ollama embeddings. Use
`System_Config/memory_search.py "<query>" --root <workspace> --json` for
typed results with excerpts. Markdown remains the source of truth and the
cache can be deleted and rebuilt at any time.

## Weekly cycle
- `System_Config/monday_init.sh` — starts the week's note + raw folder. Also runs automatically the first time `log_session.sh` logs a session in a week with no note yet; sessions are appended after initialization succeeds, while initialization failure emits a warning and skips the append.
- `System_Config/friday_process.sh` — closes out the week.

Both are manual-trigger only — Agentic Light has no background scheduler.
