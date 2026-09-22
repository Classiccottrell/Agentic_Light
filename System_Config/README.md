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
  `--add-dir "$BRAIN" --sandbox --approval-mode auto_edit` (`--add-dir` is
  required — `agy` silently ignores process cwd for writes without it,
  landing them in `~/.gemini/antigravity-cli/scratch/` instead); Codex uses
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
  argv and model mapping (both the `--model`-set and default sub-branches),
  strict list validation, pre-launch fallback, single-invocation/no retry
  behavior, no-executable exit 127, and Ollama write-workflow refusal. Chains
  `test_run_agent.sh` at the end, so `bash System_Config/test_providers.sh`
  remains the single entrypoint.
- **`test_run_agent.sh`** — regression test for the gemini/agy `--add-dir`
  write-confinement fix: stubs `agy` to emulate the real binary's
  cwd-ignoring write behavior, asserts a write lands in `$BRAIN` with the fix
  present, then strips `--add-dir` from a copy via `sed` and asserts the
  write escapes into a scratch stand-in instead (negative control proving the
  test would have caught the original bug). Not run standalone; invoked by
  `test_providers.sh`.
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
  the week's `## Agent Sessions` section (or the legacy `## Claude Sessions`
  heading, matched for compatibility with pre-rename notes), fills the
  Master Note row's Summary cell (backup → awk rewrite → validate →
  rollback). `acquire_lock` (10 min stale-reclaim); `DRY_RUN=1` preview. No
  microsite regen and no GitHub Pages publish here.
- **`log_session.sh`** — launcher-level session logger (deterministic, no
  AI call). `log_session.sh --provider <name> --role <role> --status
  <exit-code> --reason <exit|timeout|signal|refused> [--note <path>]`
  appends one line under the current week's `## Agent Sessions` heading
  (also matches the legacy `## Claude Sessions` heading). `--self-test`
  runs its own checks against temp fixtures. Called once by
  `pipeline/run.sh` after the coder step completes.
- **`route_skill.sh`** — deterministic keyword/substring skill router (no
  LLM call). `route_skill.sh "<task description>"` (or pipe the task on
  stdin) scans `skills/*/SKILL.md` frontmatter (`name`/`description` only —
  ignores Claude-specific fields like `disable-model-invocation`, per
  `AGENT_AGNOSTIC_REVIEW.md`) and prints matching skill directory paths, one
  per line. A skill may declare an optional `requires:` frontmatter field
  (single-line, comma-separated, e.g. `requires: figma-mcp, some-tool`;
  bracketed `[a, b]` also accepted — multi-line YAML list items are not
  parsed, same limitation as `name`/`description`). `--verbose` reports a
  matched skill's declared `requires:` verbatim on stderr; for a skill that
  doesn't declare one, it falls back to noting when the description
  mentions a tool/MCP dependency (e.g. Figma) this script can't verify is
  available. If `System_Config/skills-selected.json` exists (see
  `specialize.sh` below), the scan is restricted to only its `"selected"`
  dirs; a missing file scans all of `skills/`. `--self-test` / `--skills-dir
  <path>` for testing against a fixture dir instead of the real `skills/`.
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

- **`memory_index.py`** — `memory_index.py [--force]`. Embeds
  `brain/wiki/*.md` pages via a local Ollama call
  (`POST /api/embeddings`, model `nomic-embed-text`, stdlib `urllib`) into
  `brain/wiki/.memoryfield.sqlite3` (gitignored cache, not source of
  truth — `brain/wiki/*.md` stays canonical). Incremental: re-embeds only
  pages whose sha256 content hash changed since last index; prunes rows for
  pages deleted on disk; `--force` re-embeds everything. Each cached row also
  records the embedding model name (`model` column, alongside `dim`); a
  content-unchanged page is still re-embedded if its cached row's model
  doesn't match the configured `MODEL` (including legacy rows from before
  this column existed, which read as `NULL` and are always treated as
  stale). This is per-row, incremental invalidation rather than a full wipe
  on model change — simplest correct option given the incremental design
  already in place. Distinct, specific stderr messages for "can't reach
  Ollama at all" vs. "model not pulled" vs. a malformed/unexpected response
  body, each non-zero exit — never hangs, never an uncaught traceback. A file
  deleted between `glob()` and read (concurrent edit) is skipped with a note,
  not a crash; the DB connection sets a 30s busy_timeout for transient
  SQLite locks. `--self-test` exercises the SQLite read/write/incremental/
  prune/model-invalidation logic with a deterministic hash-based fake
  embedder, no live Ollama needed.

- **`memory_search.py`** — `memory_search.py "<query>" [--top N]` (or pipe
  the query via stdin; `N` must be >= 1, rejected otherwise). Embeds the
  query with the same Ollama call, cosine-searches `memory_index.py`'s
  SQLite cache (pure-Python linear scan, no vector-index library) — a
  row's stored `dim` is checked against the query vector's length before
  scoring, and a mismatched row (e.g. left over from a different embedding
  model) is skipped with a stderr note rather than silently truncate-compared
  — prints up to N (default 5) ranked `brain/wiki/` page paths to stdout —
  pipeable into `xargs cat`. Exits non-zero with no output if the index
  doesn't exist yet or Ollama is unreachable; never silently falls back —
  `curator`'s documented Query method (`brain/CLAUDE.md`) is the one that
  decides to fall back to `rg -l`. `--self-test` mirrors `memory_index.py`'s
  fake-embedder pattern and covers the dimension-mismatch case.

- **`gen_site.py`** — regenerates `microsite/index.html`'s
  `<!-- gen:agents-start/end -->` / `<!-- gen:skills-start/end -->` blocks and
  `<!-- gen:agent-count -->` / `<!-- gen:skills-count -->` counters from
  `agents/*.md` and `skills/*/SKILL.md` frontmatter.
  `--check` exits 1 if stale (used by `healthcheck.sh`); `--dry-run` prints
  the diff without writing. Stdlib-only Python 3.
- **`gen_preset_pages.py`** — regenerates one page per fork-specialization
  preset at `microsite/presets/<name>.html` (purpose, roster table, gate
  table, skills note, task-flow diagram), plus the
  `<!-- gen:presets-start/end -->` index table in `microsite/index.html`,
  from `System_Config/presets.json` and `agent-roster.schema.json`'s fixed
  6-role set. Copies `microsite/template.html` as the scaffold (rewriting its
  sibling-relative `index.html`/`health.html` links to `../` since preset
  pages live one level down). Same CLI shape as `gen_site.py`: bare (write),
  `--check` (exit 1 if stale), `--dry-run`. Kept as a separate script from
  `gen_site.py` because it generates whole files from a template rather than
  rewriting marker blocks inside one fixed file. Stdlib-only Python 3.
- **`gen_governance.py`** — regenerates root `GOVERNANCE.md`: per-role scope
  (`<!-- gen:roles-start/end -->`, from `agents/*.md` frontmatter) and this
  fork's live gate policy (`<!-- gen:gate-policy-start/end -->`, from
  `System_Config/agent-roster.json` + `pipeline/gate-config.json`, or
  "unspecialized fork" text if neither exists yet). Everything outside those
  two marker pairs — the human sign-off gate, the audit-trail/logging
  section, the config-security section — is fixed policy prose maintained in
  the script itself, describing mechanism that doesn't vary per fork. Same
  CLI shape as `gen_site.py`: bare (write), `--check` (exit 1 if stale),
  `--dry-run`. Stdlib-only Python 3.
- **`healthcheck.sh`** — layered PASS/WARN/FAIL check: directory layout,
  agent/skill roster frontmatter completeness, brain scaffolding
  (`wiki/index.md`, current weekly note, Master Note sentinel), read-only
  provider configuration/executable resolution, pipeline log recency, and
  doc currency (including a WARN if `CLAUDE.md`'s Directory Map's
  `System_Config/*` listing drifts from actual `.sh`/`.py`/`.json` files on
  disk).
  Self-heals a stale `microsite/index.html`, stale `microsite/presets/*.html`,
  or stale `GOVERNANCE.md` by invoking `gen_site.py` / `gen_preset_pages.py` /
  `gen_governance.py` for
  real. Writes `microsite/status.json` + `microsite/status.js` (the payload
  `microsite/health.html` renders). Never `set -e`, always exits 0. No
  launchd/cron trigger and no GitHub Pages publish step — run it by hand.
  On a non-`PASS` result, calls `notify.sh` with the overall status and
  pass/warn/fail counts (best-effort — never affects healthcheck's own exit).
  Also runs a heads-up config security scan (AgentShield-lite): greps
  `System_Config/*.sh`, `System_Config/*.json` (excluding `*.example` /
  `*.defaults.json` templates), `.mcp.json`, and any `.env`-shaped file for
  likely-exposed secrets (provider key prefixes, bare `Bearer <token>`,
  non-placeholder `*_KEY`/`*_TOKEN`/`*_SECRET` values) — always `WARN`, never
  `FAIL`, and skips any file already covered by `.gitignore` (expected local
  config, not a leak risk). Separately `WARN`s if `.mcp.json`,
  `.agentic-light.conf`, or `System_Config/.notify.env` — each documented
  elsewhere as local-only — isn't actually gitignored.
- **`notify.sh`** — `notify.sh "<title>" "<body>"`. Sends to
  `SLACK_WEBHOOK_URL` and/or `GCHAT_WEBHOOK_URL` (both may be set; each tried
  independently), plus an opt-in local macOS banner
  (`GCHAT_FALLBACK_LOCAL=1`, via `osascript`, no-op elsewhere). Config comes
  from ignored, mode-`600` `.notify.env` (seed from `.notify.env.example`);
  the webhook URL is piped to `curl --config -` on stdin, never passed as a
  bare argument, to keep it out of `ps` output. Every attempt is logged to
  `logs/notify.log`. Never fails its caller for delivery reasons: exit 0 on
  any successful delivery or a deliberate no-config no-op, exit 1 only if
  every configured channel failed. No flags, no severity levels, no dedup —
  deliberately smaller than a scheduled-job notifier, since Agentic Light has
  no recurring background jobs to suppress repeat alerts for. Currently
  called only by `healthcheck.sh`; `bootstrap.sh` offers an opt-in prompt to
  populate `.notify.env`'s webhook URLs.
- **`specialize.sh`** — one-time fork specialization, run after
  `bootstrap.sh`. Prompts (same checkbox UX as `bootstrap.sh`) for which of
  the 6 roles (read from `agent-roster.schema.json`, never hardcoded), which
  gates (`eslint`/`playwright`/one `custom`, read from
  `gate-config.schema.json`), and which `skills/*` dirs (scanned live) to
  keep. Writes canonical `System_Config/agent-roster.json` and
  `pipeline/gate-config.json` — validated by real structural checks against
  their schemas (fields read from the schema files themselves, not a second
  hand-maintained copy), reusing `pipeline/run.sh`'s own gate-config
  validation logic plus a repo-relocatability check (rejects absolute
  `script`/`cwd` paths) — and `System_Config/skills-selected.json`, which
  `route_skill.sh` reads to restrict its scan to the selected dirs (files
  under `skills/` are never deleted, per the project's leave-files-alone
  philosophy; missing selection file = scan everything). `--preset
  web-app|cli-tool|data-pipeline|design-harness|server-harness|wcag-harness`
  expands a named entry from `System_Config/presets.json` non-interactively
  (`web-app`: full team + eslint/playwright + all skills; `cli-tool`:
  coder+qa, no gates, all skills; `data-pipeline`: architect+coder+qa,
  placeholder custom gate, all skills; `design-harness`:
  architect+coder+creative-director+qa, playwright gate only, all skills;
  `server-harness`: architect+coder+qa, no default gates, no shipped skills
  yet; `wcag-harness`: architect+coder+creative-director+qa, playwright gate
  only, no shipped skills yet); so do the
  `AGENTIC_LIGHT_ROLES`/`AGENTIC_LIGHT_GATES`/`AGENTIC_LIGHT_SKILLS`
  comma-separated env overrides (mirrors `bootstrap.sh`'s
  `AGENTIC_LIGHT_*` convention). `data-pipeline`'s custom gate ships with an
  intentionally empty `"script"` placeholder — `specialize.sh` refuses to
  write a config with a known-empty required custom-gate `"script"` (preset
  or interactive path alike) and exits non-zero with a clear fix message,
  rather than writing a config that `pipeline/run.sh` would only fail at
  execution time. `server-harness` sidesteps this entirely by shipping an
  empty gate list (`[]`, same shape as `cli-tool`) rather than a placeholder
  custom gate — a server project's test command varies too much to guess,
  and an always-failing placeholder preset would be less honest than an
  explicit "no default gates" preset a human fills in later. `server-harness`
  and `wcag-harness` both ship `"skills": []` with a `skills_gap_note` field
  (the only two presets to set one — `wcag-harness` because no shipped
  `skills/*` dir covers accessibility review); when present, `specialize.sh`
  prints an informational "no skill content yet" note after resolving the
  preset, distinguishing a known content gap from a role-appropriate empty
  selection. `wcag-harness` shares `design-harness`'s exact roster and its
  single `playwright` gate — the differentiator is scope, not shape: the
  architect reviews semantic HTML structure, creative-director reviews
  contrast/visual hierarchy, and the actual axe-core assertions live in the
  target repo's own Playwright spec files, not in the gate mechanism itself
  (this project's gate schema has no dedicated accessibility gate type).
  Interactive
  custom-gate field values (script/cwd) are
  passed to the python3 subprocess via argv, never string-interpolated into
  source, so a value containing quotes/triple-quotes can't break the
  generated Python. Idempotent: re-running overwrites all three output
  files cleanly, never appends.
- **`dashboard.sh`** — read-only terminal status readout: preset/provider
  summary, roster (`System_Config/agent-roster.json`), gates
  (`pipeline/gate-config.json`), current week's most recent
  `## Agent Sessions` line, and the 3 most recent `pipeline/logs/*.log`
  runs (filename + `Task:` header line). Plain `printf`/box-drawing, no
  ncurses; a snapshot, not an interactive app — no input handling.
  Every section degrades to a "not yet configured" / "none yet" message
  on a fresh, unspecialized clone rather than erroring. Provider read
  goes through `config.sh`'s `config_value` (sed-based; `.agentic-light.conf`
  is never sourced). JSON parsed with `python3` stdlib, matching
  `specialize.sh`'s convention — file paths are passed via `sys.argv`, never
  string-interpolated into the generated Python source, same reasoning as
  `specialize.sh`'s custom-gate fields. Box is 67 display columns, fits an
  80-column terminal; long values truncate with `…` rather than widening
  the box. `--self-test` exercises both the fresh-clone and
  specialized-fixture cases against scratch JSON/log fixtures.
  Known gaps, not fixed: (1) truncation width (`${#text}`) counts
  characters, not terminal display cells — full-width Unicode in a roster
  name or gate label could misalign the box; not a real risk today since
  generated values are ASCII/Latin. (2) malformed-but-valid JSON in
  `agent-roster.json`/`gate-config.json` (e.g. `"roles"` as a string
  instead of an object) could crash a helper on `.get()`; not a fresh-clone
  failure since these files are always machine-generated by `specialize.sh`,
  but there's no defensive validation against hand-edited breakage.
