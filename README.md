# Agentic Light

A lightweight, provider-agnostic template for building a small dev-agent
harness. It supports Claude, Gemini (`agy` or `gemini`), Codex, and Ollama,
with no background service, scheduler, or retry queue — everything here runs
by hand. It ships as a generic fork with all 6 agent roles and no gates; you
run `specialize.py` once to turn it into a specific harness (a CLI-tool
harness, a design harness, a WCAG-review harness, etc.) for the project you
actually need it for. It also bundles a second-brain (plain markdown +
semantic search, optionally viewable in Obsidian) and a doc-site microsite
that reflect the harness's current configuration.

## Install

```sh
python3 bootstrap.py          # interactive, idempotent scaffold + provider setup
python3 bootstrap.py --check  # read-only doctor: tool/provider/automation status
python3 System_Config/test_providers.py  # fake-provider regression check
```

`bootstrap.py --check` reports which of `claude`/`agy`/`gemini`/`codex`/
`ollama`/`gh`/`node`/`npx`/`python3` are installed, whether provider config
exists yet, and confirms there's no background automation. `bootstrap.py`
itself (no flags) runs the interactive checkbox-style setup: enable/disable
each provider, set priority order, optionally set a model per provider. It
writes the result to `.agentic-light.conf` at the repo root (gitignored,
mode `600`, parsed as text — never sourced as shell). Environment variables
(`AGENTIC_LIGHT_PROVIDERS`, `AGENTIC_LIGHT_PRIORITY`,
`AGENTIC_LIGHT_MODEL_<PROVIDER>`) override it non-interactively.

`System_Config/test_providers.py` is a fake-binary regression suite covering
argv construction, model mapping, pre-launch fallback, single-invocation (no
retry), and Ollama's write-workflow refusal — it exits 0/`PASS` without
touching any real provider.

## Specialize — turn the template into your harness

This is the core idea: Agentic Light is not one fixed harness, it's a
template you fork and specialize once per project.

```sh
python3 System_Config/specialize.py --preset <name>
```

or run it with no flags for interactive selection (same checkbox UX as
`bootstrap.py`: pick roles, gates, and skill dirs by hand).

Presets (from `System_Config/presets.json`):

| Preset | Description |
|---|---|
| `web-app` | full team + eslint/playwright gates + react-doctor/shadcn skills |
| `cli-tool` | coder+qa, no gates, systematic-debugging/managing-python-dependencies skills |
| `data-pipeline` | architect+coder+qa, no default gate, gcp-data-pipelines/dbt-bigquery/discovering-gcp-data-assets skills |
| `design-harness` | architect+coder+creative-director+qa, playwright gate, all skills (requires Figma MCP) |
| `server-harness` | architect+coder+qa, no default gates, server-review skill |
| `wcag-harness` | architect+coder+creative-director+qa, playwright+axe+vpat-lint gates, wcag-audit+vpat-authoring skills |

Specializing writes `System_Config/agent-roster.json` (active roles),
`pipeline/gate-config.json` (gate list), and
`System_Config/skills-selected.json` (which `skills/*` dirs `route_skill.py`
scans). With `--preset`, it also writes `System_Config/.active-preset` (the
preset name), which `gen_governance.py` reads to render that preset's
`role_notes` — harness-specific notes on what each active role covers.
Re-running overwrites cleanly — it's idempotent, not additive. None of these
are gitignored: in a fork you commit them (see `microsite/whitelabel.html`). A
fresh, unspecialized clone has none of these files and runs with the full
default roster and the legacy eslint+playwright gate pair. See
`System_Config/README.md` for the full mechanics (env-var overrides and
validation rules).

## Run

For a new project, copy [`Projects/_TEMPLATE/`](Projects/_TEMPLATE/README.md)
and follow its provider-neutral lifecycle: `BRIEF.md` → `spec.md` →
`tasks.md` → execution, keeping `Plan.md` as the resumable checkpoint.

```sh
python3 pipeline/run.py "<task description>" /path/to/target/repo
```

`run.py` targets an **external repo**, not Agentic_Light itself. Flow:
skill routing (`route_skill.py` prepends matching `SKILL.md` guidance to the
coder prompt) → coder step (one provider, foreground, no retry) → gates
(the ordered list in `pipeline/gate-config.json` if present — `eslint`,
`playwright`, `axe`, or a `custom` script; falls back to the hardcoded
eslint+playwright pair on an unspecialized fork) → human approval gate
(`[y/N]` on the committed diff) → `gh pr create --draft`. Every gate must
pass (or WARN-skip when the target repo has no lint/e2e/a11y setup) before the
diff is ever shown to a human. See `pipeline/README.md` for the full
contract (concurrency lock, exit codes, WARN-vs-hard-stop rules).

## Check on it

Two read-only dashboards, no server required:

```sh
python3 System_Config/dashboard.py         # terminal: preset, provider, roster, gates, last session, recent runs
open microsite/index.html               # browser: dashboard entry point
open microsite/dashboard.html           # browser: condensed health + preset cards + roster-by-preset table
```

Both microsite pages open directly via `file://` — no build step, no
`python -m http.server`. `python3 System_Config/healthcheck.py` runs the full
layered PASS/WARN/FAIL check (directory layout, roster/skill frontmatter,
brain scaffolding, provider config, doc currency, a secrets scan) and
writes `microsite/status.json`/`status.js`, which `health.html` and
`dashboard.html` both render.

## Governance

`GOVERNANCE.md` (repo root, generated — `python3 System_Config/gen_governance.py`)
is where "what can an agent here actually do, and what needs my sign-off"
lives: per-role scope pulled from `agents/*.md`, the human approval gate
before any PR, the session-log/pipeline-log audit trail, this fork's live
gate policy (from `agent-roster.json`/`gate-config.json`, or "unspecialized
fork" if neither exists), and the `healthcheck.py` config-security scan.
`healthcheck.py` self-heals it when stale, same as the microsite docs below.

## Everything else, briefly

**Brain** (`brain/`) — a plain-markdown + SQLite second brain, optionally
viewable as an Obsidian vault. `brain/raw/` holds immutable clipped notes;
typed records under `brain/records/` capture projects, decisions, learnings,
references, and sessions. `context.py` validates, catalogs, searches, curates,
and builds profile-scoped packets; FTS5 works offline and Ollama embeddings
are optional. `daily_ingest.py` still wikifies raw clips into `brain/wiki/`.
All source is plain text/stdlib, with zero Obsidian dependency. `.obsidian/` is
shipped for zero-setup Obsidian viewing but is not required by the pipeline.
See `brain/README.md`.

**Skill routing** (`System_Config/route_skill.py`) — a deterministic
keyword/substring router (no LLM call) that scans `skills/*/SKILL.md`
frontmatter and prints matching skill paths; `pipeline/run.py` uses it to
inject skill guidance into the coder prompt. Restricted to
`System_Config/skills-selected.json`'s selection once you've specialized.

**Microsite** (`microsite/`) — the static doc site referenced above:
`index.html` (roster/skills/presets, self-healing marker blocks),
`presets/<name>.html` (one page per preset), `health.html`/`dashboard.html`
(status views). See `microsite/README.md`.

## Full docs

- `GOVERNANCE.md` — generated governance layer: role scope, human sign-off gate, audit trail, this fork's gate policy, config security
- `System_Config/README.md` — every script's exact behavior
- `pipeline/README.md` — gate config schema, session logging, concurrency
- `microsite/README.md` — page structure, regeneration commands
- `brain/README.md` — vault layout, ingestion, semantic search
- `CLAUDE.md` — full command list and directory map (provider-neutral orchestrator context)
