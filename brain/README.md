# brain/ — Second Brain (Obsidian Vault)

Open `Agentic_Light/` itself (the folder containing this `brain/` directory
one level up, i.e. `Agentic_Light/`) as an Obsidian vault — `.obsidian/` is
shipped at the `Agentic_Light/` root, so the vault opens with working core
plugins and graph view out of the box. `brain/` is where the actual content
lives.

## Open in Obsidian
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
`System_Config/memory_index.py` embeds `brain/wiki/*.md` pages via a local
Ollama call (`nomic-embed-text`) into `brain/wiki/.memoryfield.sqlite3` — a
gitignored, rebuildable cache (not source of truth). Run it after editing
wiki pages; it's incremental (content-hash based). `System_Config/memory_search.py
"<query>"` then ranks pages by cosine similarity. Neither script falls back
on its own: both just exit non-zero with a clear stderr message if Ollama
isn't running or the index doesn't exist yet. It's `curator`'s documented
Query method that owns the fallback decision, dropping to `rg -l` in that
case. See `brain/CLAUDE.md`'s Query section.

## Weekly cycle
- `System_Config/monday_init.sh` — starts the week's note + raw folder. Also runs automatically the first time `log_session.sh` logs a session in a week with no note yet, so pipeline runs are never dropped from the log.
- `System_Config/friday_process.sh` — closes out the week.

Both are manual-trigger only — Agentic Light has no background scheduler.
