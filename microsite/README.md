# microsite/

Static, file://-safe doc site for Agentic Light. No build step, no server,
no external JS dependencies. Reuses the parent workspace's ClassicCottrell
design system verbatim (same tokens, same header/footer/`.wordmark`/`.subnav`
structure) rather than a new palette.

## View

```
open Agentic_Light/microsite/index.html
```

Every page here (`index.html`, `health.html`, `template.html`) opens
directly from disk — no `python -m http.server` needed.

## Files

- **`template.html`** — canonical scaffold. Copy this when adding a new
  microsite page; never hand-write the CSS block.
- **`index.html`** — doc-site home page. Roster and skills tables live
  inside self-healing marker comments (`<!-- gen:agents-start/end -->`,
  `<!-- gen:skills-start/end -->`, `<!-- gen:agent-count -->`,
  `<!-- gen:skills-count -->`), plus a preset index table
  (`<!-- gen:presets-start/end -->`) linking to `presets/*.html`.
- **`presets/<name>.html`** — one page per fork-specialization preset
  (purpose, roster, gates, skills, task-flow diagram), generated from
  `System_Config/presets.json` by `System_Config/gen_preset_pages.py`.
- **`health.html`** — status dashboard. Loads `status.js` via a `<script
  src>` tag (not `fetch`/XHR), so it renders correctly over `file://` with
  no server. Auto-refreshes every 5 minutes (`<meta http-equiv="refresh">`).
- **`status.json`** / **`status.js`** — the health snapshot.
  `status.json` is the plain-data form; `status.js` wraps the same payload
  as `window.__STATUS__ = {...};`, which is what `health.html` actually
  loads. Both start as an `UNKNOWN`/empty placeholder and are overwritten
  by `System_Config/healthcheck.sh` on every run — `healthcheck.sh` is the
  sole writer of both files.

## Regeneration

`index.html`'s roster/skills blocks are generated from `agents/*.md` and
`skills/*/SKILL.md` frontmatter:

```
python3 System_Config/gen_site.py          # rewrite index.html in place
python3 System_Config/gen_site.py --check  # exit 1 if stale (used by healthcheck.sh)
python3 System_Config/gen_site.py --dry-run # preview the diff, no write
```

`presets/*.html` and index.html's preset table are generated from
`System_Config/presets.json` by a separate script (different operation —
whole-file generation from a template vs. marker-block rewrite):

```
python3 System_Config/gen_preset_pages.py          # rewrite preset pages + index.html table
python3 System_Config/gen_preset_pages.py --check  # exit 1 if stale (used by healthcheck.sh)
python3 System_Config/gen_preset_pages.py --dry-run # preview, no write
```

`System_Config/healthcheck.sh`'s Layer F (doc currency) self-heals by
invoking `gen_site.py` and `gen_preset_pages.py` for real whenever it
detects `index.html` or `presets/*.html` has drifted — the site should
never go stale for long.
