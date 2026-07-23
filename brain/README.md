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
Clips land in `brain/raw/YYYY/Wnn <label>/` — the current week's folder is
created automatically by `System_Config/monday_init.sh` every Monday. Point
the Web Clipper's save location at that week's folder (or configure a
template that writes there). See `brain/raw/README.md` for the exact
naming convention and frontmatter format.

## Ingestion
`System_Config/daily_ingest.sh` scans `brain/raw/**/*.md` (two levels deep)
and turns new clips into wiki pages under `brain/wiki/`. See
`brain/CLAUDE.md` for the full schema.

## Weekly cycle
- `System_Config/monday_init.sh` — starts the week's note + raw folder.
- `System_Config/friday_process.sh` — closes out the week.

Both are manual-trigger only — Agentic Light has no background scheduler.
