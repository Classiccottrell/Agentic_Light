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
  (also matches the legacy `## Claude Sessions` heading). If the default
  current-week note doesn't exist yet, it runs `monday_init.sh` first
  (stdout redirected to stderr) to create the full templated note — plus
  the same raw folder and Master Note index row a manual run adds — then
  appends. It used to skip instead, to avoid writing a bare stub note
  missing the template's sections, but that silently dropped runs from the
  audit trail. An explicit `--note` path (or its env equivalent
  `LOG_SESSION_NOTE`, which `pipeline/test_pipeline.sh` sets so fixtures
  never write into `brain/`) is never auto-created. If
  `monday_init.sh` fails or the note is still missing, it prints a warning
  to stderr and exits 0 (logging never fails the pipeline). No lock
  conflict: `monday_init.sh` locks `System_Config/logs/monday_init.lock`,
  `pipeline/run.sh` locks `pipeline/logs/.run.*.lock`. `--self-test` runs
  its own checks against temp fixtures (including a temp copy of the
  workspace scripts for the auto-init path; the real vault is never
  touched). Called once by `pipeline/run.sh` after the coder step completes.
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
- **`context_packet.sh`** — bounded, provider-neutral resume packet. It reads
  `ROADMAP.md`, the active preset, the newest weekly log tail, and optional
  semantic matches. `AGENTIC_LIGHT_CONTEXT_MAX_LINES` and
  `AGENTIC_LIGHT_CONTEXT_MAX_BYTES` cap output; Markdown remains the source of
  truth and the packet is derived output. Truncation is byte-exact
  (`printf '%s' "$packet" | LC_ALL=C head -c "$MAX_BYTES"`), not a bash
  character slice — under UTF-8, `${s:0:N}` counts characters, so a tiny
  `MAX_BYTES` override against multi-byte content (this repo's own em dashes)
  could silently exceed its budget. `pipeline/run.sh` prepends this script's
  output to the coder prompt, labeled `Resume context packet:`, opt-in only
  (`AGENTIC_LIGHT_CONTEXT_PACKET=1`, or automatically when the pipeline's
  target repo resolves to this workspace's own root) — never injected into an
  unrelated external target repo by default.
- **`test_context_packet.sh`** — fixture tests for `context_packet.sh`: a
  tiny `AGENTIC_LIGHT_CONTEXT_MAX_LINES`/`AGENTIC_LIGHT_CONTEXT_MAX_BYTES`
  budget against a synthetic `ROADMAP.md` with a dense multi-byte (em dash)
  first line stays under budget byte-for-byte (not just character-for-byte —
  the scenario that would have passed on the old buggy line), and the default
  budget preserves every provenance header. Uses POSIX `[ ]`, not `[[ ]]`, for
  its numeric assertions — this system's bash 3.2.57 does not abort under
  `set -e` on a failing bare `[[ ]]` command, verified empirically.
- **`preset_audit.py`** — stdlib-only validation of preset roles, gates, skills,
  and focused role-note overlays. For `design-harness`/`wcag-harness`
  specifically, also validates the optional `role_capabilities`/
  `role_handoff` maps: keys must exactly match `role_notes`'s keys, each
  role's capabilities must be a non-empty, duplicate-free subset of
  `agent-roster.schema.json`'s capability enum (read live, falling back to
  the hardcoded 4 if unreadable), and each handoff target must be one of the
  preset's active roles or `"orchestrator"`. Any preset's `role_notes`/
  `role_capabilities`/`role_handoff` map is also checked for an inactive-role
  key. `healthcheck.sh` runs it as a hard contract check.
- **`white_label_check.py`** — non-destructive audit for a specialized fork.
  It checks active roles against the selected preset, pruned agent files,
  selected skills, and old/new identity text — plus, via
  `_check_generated_output()`, that `gen_governance.py`/`gen_site.py`/
  `gen_preset_pages.py --check` all pass inside the fork (each resolves its
  own root via `__file__`, so no cwd gymnastics; a missing generator script is
  itself a finding). It never deletes or rewrites — `_check_generated_output`
  only shells out to each generator's own read-only `--check` mode.
  `--self-test` builds 5 real forks under `_build_clean_fork()` (copies this
  repo's own generator scripts + `microsite/template.html`, renaming the
  literal `"Agentic Light"` baked into their *source* — a naive white-label
  pass that only swept generated output would always fail the old-name check
  — then actually runs all 3 generators): two clean presets (`wcag-harness`
  with `["coder"]` only, `design-harness` with its full live roster — both
  read from the live `presets.json` entry, not a hand-copied paraphrase, so
  the new `role_capabilities`/`role_handoff` overlay is exercised too), a
  deliberately-stale-old-name-text failure, a roster/preset-mismatch failure,
  and a generated-output-staleness failure (an agent's `description:` edited
  post-generation so `gen_site.py --check` disagrees with the already-
  rendered `index.html`).
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

- **`gen_site.py`** — regenerates `microsite/dashboard.html`'s preset cards and
  roster-by-preset table from `System_Config/presets.json` and
  `agent-roster.schema.json`. `microsite/index.html` is a static compatibility
  redirect to the dashboard.
  `--check` exits 1 if stale (used by `healthcheck.sh`); `--dry-run` prints
  the diff without writing. Stdlib-only Python 3.
- **`gen_preset_pages.py`** — regenerates one page per fork-specialization
  preset at `microsite/presets/<name>.html` (purpose, roster table, gate
  table, skills note, task-flow diagram) from `System_Config/presets.json` and
  `agent-roster.schema.json`'s fixed
  6-role set. Copies `microsite/template.html` as the scaffold (rewriting its
  sibling-relative `index.html`/`health.html` links to `../` since preset
  pages live one level down). Same CLI shape as `gen_site.py`: bare (write),
  `--check` (exit 1 if stale), `--dry-run`. Kept as a separate script from
  `gen_site.py` because it generates whole files from a template rather than
  rewriting marker blocks inside one fixed file. Stdlib-only Python 3.
  If a preset carries an optional `role_notes` object (currently
  `design-harness` and `wcag-harness` only — one or two sentences per active
  role, harness-specific, additive to that role's generic scope in
  `agents/*.md`), renders an extra "Harness-Specific Role Notes" section;
  presets without `role_notes` render byte-identical to before this field
  existed. When a preset also carries the optional `role_capabilities`/
  `role_handoff` maps (currently `design-harness`/`wcag-harness` only), each
  role's note line grows an inline `(capabilities: ...)` / `(hands off to:
  ...)` suffix; a preset lacking either field renders that role's line
  unchanged. Same rule for the optional `requires` list (currently
  `design-harness` only): rendered html-escaped as a "Requires:" line under
  Skills only when present.
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
  The roles section also renders a harness-specific overlay, additive below
  the generic scope table, when `System_Config/.active-preset` (written by
  `specialize.sh --preset <name>`) names a preset with `role_notes` in
  `presets.json`. Absent `.active-preset` (unspecialized fork, or a fork
  specialized interactively/via env-override rather than by preset name) or
  a preset with no `role_notes` → no overlay, table unchanged. Notes render
  only for roles `active: true` in `agent-roster.json` (roster absent → no
  notes); newlines in a note are collapsed to spaces. When the active
  preset also carries `role_capabilities`/`role_handoff`, each overlay row
  grows an inline `_(capabilities: ...)_` / `_(hands off to: ...)_` suffix;
  a preset without either field renders that row unchanged (no-op guard, so
  output stays byte-identical for any preset lacking the new fields).
- **`healthcheck.sh`** — layered PASS/WARN/FAIL check: directory layout,
  agent/skill roster frontmatter completeness, brain scaffolding
  (`wiki/index.md`, current weekly note, Master Note sentinel), read-only
  provider configuration/executable resolution, pipeline log recency, and
  doc currency (including a WARN if `CLAUDE.md`'s Directory Map's
  `System_Config/*` listing drifts from actual `.sh`/`.py`/`.json` files on
  disk).
  Self-heals a stale `microsite/dashboard.html`, stale `microsite/presets/*.html`,
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
  elsewhere as local-only — isn't actually gitignored. The pattern set lives
  once, in `config.sh`'s `looks_like_secret`, shared with
  `pipeline/run.sh`'s pre-commit secret scan (see `pipeline/README.md`) —
  not duplicated between the two.
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
  gates (`eslint`/`playwright`/`axe`/`vpat-lint`/one `custom`, read from
  `gate-config.schema.json`), and which `skills/*` dirs (scanned live) to
  keep. Gate prompts default to yes, except `axe` and `vpat-lint`, which
  default to no: they're accessibility-specific, and `wcag-harness` turns
  them on explicitly. Also writes (`--preset` path only) `System_Config/.active-preset`,
  a plain-text file naming the preset — `gen_governance.py` reads it to look
  up that preset's optional `role_notes` overlay in `presets.json`. It is
  removed at the start of every run and written (mktemp + `mv`) only after
  all other outputs succeed, so a failed or interactive/env-override run
  leaves it absent rather than stale.
  Writes canonical `System_Config/agent-roster.json` and
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
  (`web-app`: full team + eslint/playwright + `react-doctor`/`shadcn` skills;
  `cli-tool`: coder+qa, no gates, `systematic-debugging`/
  `managing-python-dependencies` skills; `data-pipeline`: architect+coder+qa,
  no default gate, `gcp-data-pipelines`/`dbt-bigquery`/
  `discovering-gcp-data-assets` skills; `design-harness`:
  architect+coder+creative-director+qa, playwright gate only, all skills,
  plus `"requires": ["figma-mcp"]`;
  `server-harness`: architect+coder+qa, no default gates, `server-review`
  skill; `wcag-harness`: architect+coder+creative-director+qa, playwright
  + axe + vpat-lint gates, `wcag-audit`/`vpat-authoring` skills —
  `design-harness` and `wcag-harness` also
  carry a `role_notes` field in `presets.json`, giving `architect`/
  `creative-director`/`qa` harness-specific scope text additive to their
  generic `agents/*.md` description, rendered by `gen_governance.py` and
  `gen_preset_pages.py`); so do the
  `AGENTIC_LIGHT_ROLES`/`AGENTIC_LIGHT_GATES`/`AGENTIC_LIGHT_SKILLS`
  comma-separated env overrides (mirrors `bootstrap.sh`'s
  `AGENTIC_LIGHT_*` convention). `data-pipeline` and `server-harness` ship
  empty gate lists because a project's test command varies too much to guess;
  add a repo-root-relative custom gate only when the target project defines
  one. `server-harness`
  ships `"skills": ["server-review"]` (see `skills/server-review/SKILL.md`) and
  `wcag-harness` ships `["wcag-audit", "vpat-authoring"]`; a preset only carries a
  `skills_gap_note` field when its listed skill selection is a genuinely
  known content gap, not by default — neither preset sets one now that both
  have a shipped skill dir. A preset may also carry an optional `requires`
  list (`design-harness`: `["figma-mcp"]` — all 12 `figma-*` skills need the
  Figma MCP server); `--preset` prints it as an informational `Note:` line
  (not a warning, never a failure, no detection of whether it's installed)
  and `gen_preset_pages.py` renders it on the preset page. `wcag-harness`
  shares `design-harness`'s exact roster; its gates are `["playwright",
  "axe", "vpat-lint"]` — the `axe` gate (`pipeline/lib/axe_gate.sh`) runs
  the target repo's `test:a11y`/`a11y` script and WARN-skips when there is
  none, and the `vpat-lint` gate (`pipeline/lib/vpat_lint_gate.sh`) checks
  any `accessibility/vpat-draft.json` against 6 deterministic ITI-discipline
  rules and WARN-skips when there is no draft (see `pipeline/README.md`'s
  "Accessibility (axe) gate" and "VPAT draft lint (vpat-lint) gate").
  Beyond that the differentiator is scope: the architect reviews semantic
  HTML structure, creative-director reviews contrast/visual hierarchy,
  `wcag-audit` drives the 4-pass audit/checklist method, and
  `vpat-authoring` turns those findings into an ITI VPAT 2.5Rev conformance
  report. Both harnesses also carry a
  `role_capabilities`/`role_handoff` overlay in `presets.json`, alongside
  `role_notes`: per-role tool capabilities and which role (or
  `"orchestrator"`) receives that role's output. Written `agent-roster.json`
  entries prefer a `--preset`'s own `role_capabilities` value over
  `agent-roster.example.json`'s flat defaults —
  `role_caps_overlay.get(role, default_caps.get(role))` per role, so a role
  the overlay doesn't mention (e.g. `coder` on either harness preset) still
  falls through to the same default it always got. Every other path
  (interactive, `AGENTIC_LIGHT_*` env overrides) passes an empty `{}`
  overlay, so behavior there is unchanged; `preset_audit.py` validates the
  overlay's shape (see that script's entry above).
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
