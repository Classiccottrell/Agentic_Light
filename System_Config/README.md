# System_Config

Scripts and configuration for Agentic Light. **No launchd/cron — every
script here runs by hand; that's the only way it runs in Agentic Light.**

## Scripts (this batch)

- **`config.sh`** — shared, relocatable configuration. Source from every
  script (`source "$SCRIPT_DIR/config.sh"`). Derives `WORKSPACE`, `BRAIN`,
  `RAW`, `LOG_DIR` from its own location. Reads the bootstrap-generated,
  non-secret `.agentic-light.conf` without evaluating it, then selects the
  first enabled, installed provider in explicit priority order: Claude,
  Gemini (`agy` command alias supported), Codex, or Ollama. Environment
  overrides are `AGENTIC_LIGHT_PROVIDERS`, `AGENTIC_LIGHT_PRIORITY`, and
  `AGENTIC_LIGHT_MODEL_<PROVIDER>`. Bootstrap collects the same values with
  terminal checkbox-style yes/no prompts, a comma-separated priority text
  field, and one optional model text field per enabled provider, then writes
  them to ignored `../.agentic-light.conf` with mode `600`. The config is
  parsed as text, not evaluated as shell. Legacy `AGENT_TYPE`, `$CLAUDE`, and
  `$AGENT_TYPE` consumers remain supported; after resolution, `$CLAUDE`
  aliases the selected executable even when the provider is not Claude.
  Enabled and priority lists are validated strictly: priority must contain
  every enabled provider exactly once, in the requested order.
  Provides `validate_config()`
  (never exits — returns 0/1; invoked once at the bottom of `config.sh`
  itself, warning on failure). Provides `acquire_lock <dir> [max_age_s]`, an
  atomic-`mkdir` lock shared by the scripts below — a lock older than
  `max_age_s` (default 3600) is treated as abandoned by a killed/crashed run
  and reclaimed once. Provides `ensure_current_week_raw_folder()`, an
  idempotent `mkdir -p` of the current ISO week's `brain/raw/YYYY/Wnn label/`
  folder; called by both `monday_init.sh` and `daily_ingest.sh` so a note
  always has somewhere to land regardless of which script runs first.
  `date_offset()` keeps its week calculations compatible with BSD `date` on
  macOS and GNU `date` on Linux.
- **`mcp.defaults.json`** — provider-agnostic MCP server template. Copy to
  `../.mcp.json` and populate `mcpServers`; `bootstrap.sh` does this
  automatically on first run if `.mcp.json` is absent.
- **`new_agent.sh`** — `new_agent.sh <name> "<scope>" [--write]`. Scaffolds
  `agents/<name>.md` with frontmatter (`name`/`description`/`tools`/`model`).
  Dry-run by default; refuses to overwrite an existing file.
- **`logs/`** — script output lands here. `.gitkeep` tracks the empty dir.

- **`run_agent.sh`** — sourced library (not standalone). Provides
  `run_agent "<prompt>"`: a thin wrapper around the resolved agent CLI
  (`$AGENT_COMMAND`/`$AGENT_PROVIDER` from `config.sh`) with a wall-clock watchdog
  (`MAX_SECONDS`, default 300s) and a Claude-only budget cap (`MAX_BUDGET`).
  cwd is `$BRAIN`. The Claude adapter allows file tools, denies Bash/web and
  other escape tools, and uses `acceptEdits`; Gemini uses
  `--sandbox --approval-mode auto_edit`; Codex uses
  `exec --sandbox workspace-write`. Ollama is inference-only, so write
  workflows reject it with exit 64 without invoking it. The
  watchdog uses a sentinel-file handshake rather than a bare
  `kill -TERM $pid` after sleeping, so it can't end up signaling an
  unrelated process that reused `$pid` after the agent exited and was
  reaped. Configured models are passed with each executable CLI's native
  model flag.
  Provider fallback happens only before launch when an executable
  is missing; a launched command's non-zero exit is returned without retry.
  Each call runs one foreground task and waits for it. No provider adapter
  schedules work or creates a background retry.
- **`test_providers.sh`** — fake-binary shell check for exact Gemini/Codex
  argv and model mapping, strict list validation, pre-launch fallback,
  single-invocation/no retry behavior, no-executable exit 127, and Ollama
  write-workflow refusal.
- **`monday_init.sh`** — weekly initializer. Creates
  `brain/weekly_logs/${YEAR}/${YEAR}-Www.md` from the template, creates
  `brain/raw/${YEAR}/Wnn label/`, and adds a row to
  `brain/weekly_logs/${YEAR} Master Note.md`'s Weekly Index (backup → edit
  → validate → rollback). Implements **Vacation Recovery**: if the most
  recently logged week is more than 7 days behind the current week, inserts
  exactly one synthetic catch-up row (`catch-up`, weeks-skipped count) before
  resuming normal weekly notes. `acquire_lock` (10 min stale-reclaim);
  `DRY_RUN=1` preview.
- **`friday_process.sh`** — weekly close-out. Appends a close-out line to
  the week's `## Claude Sessions`, fills the Master Note row's Summary cell
  (backup → awk rewrite → validate → rollback). `acquire_lock` (10 min
  stale-reclaim); `DRY_RUN=1` preview. No microsite regen and no GitHub
  Pages publish here.
- **`daily_ingest.sh`** — self-heals the current week's `brain/raw/` folder
  via `ensure_current_week_raw_folder()` before scanning (so a manual run
  works even if `monday_init.sh` hasn't run yet this week), then scans
  `brain/raw/YYYY/Wnn label/*.md` (exactly two
  levels deep; deeper nesting WARNs and is skipped) for new clips and
  ingests each with one `run_agent` call, wikifying it into `brain/wiki/`.
  Content-hash manifest (`brain/raw/.ingested.log`, sha256-keyed) for
  idempotent re-scans; quarantines a clip after 3 failed attempts
  (`brain/raw/.failed.log`). `acquire_lock`, stale-reclaim threshold sized to
  `MAX_CLIPS_PER_RUN × (MAX_SECONDS + 30s)` so a legitimately long ingest is
  never reclaimed from under itself; `DRY_RUN=1` preview.

- **`gen_site.py`** — regenerates `microsite/index.html`'s
  `<!-- gen:agents-start/end -->` / `<!-- gen:skills-start/end -->` blocks and
  `<!-- gen:agent-count -->` / `<!-- gen:skills-count -->` counters from
  `agents/*.md` and `skills/*/SKILL.md` frontmatter.
  `--check` exits 1 if stale (used by `healthcheck.sh`); `--dry-run` prints
  the diff without writing. Stdlib-only Python 3.
- **`healthcheck.sh`** — layered PASS/WARN/FAIL check: directory layout,
  agent/skill roster frontmatter completeness, brain scaffolding
  (`wiki/index.md`, current weekly note, Master Note sentinel), read-only
  provider configuration/executable resolution, pipeline log recency, and
  doc currency.
  Self-heals a stale `microsite/index.html` by invoking `gen_site.py` for
  real. Writes `microsite/status.json` + `microsite/status.js` (the payload
  `microsite/health.html` renders). Never `set -e`, always exits 0. No
  launchd/cron trigger and no GitHub Pages publish step — run it by hand.
