# brain/raw/ — Immutable Raw Inputs

One folder per ISO week: `YYYY/Wnn <label>/`, e.g. `2026/W30 Jul 20-24/`.
`System_Config/monday_init.sh` creates the current week's folder
automatically every run; you don't create these by hand.

## Convention
- Path: `raw/[YYYY]/[Wnn label]/`, where `label` is a short human-readable
  date range (e.g. `Jul 20-24`), matching the week's note title in
  `brain/weekly_logs/`.
- Files inside a week's folder are Obsidian Web Clipper output: `.md` with
  `clipped` / `source` / `author` frontmatter.
- Files here are **never edited** after they land — immutable inputs.
  `System_Config/daily_ingest.sh` reads them and writes derived content to
  `brain/wiki/`, never back into `raw/`.

## Obsidian Web Clipper setup
Point the clipper's save-folder at the current week's `raw/YYYY/Wnn label/`
path. Since the folder is created fresh each Monday, update the clipper's
target weekly (or template the path with today's date if your clipper
supports variables).
