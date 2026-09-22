# Agentic Light

A lightweight, provider-agnostic template for building a small dev-agent
harness. It supports Claude, Gemini (`agy` or `gemini`), Codex, and Ollama,
with no background service, scheduler, or retry queue — everything here runs
by hand. It ships as a generic fork with all 6 agent roles and no gates; you
run `specialize.sh` once to turn it into a specific harness (a CLI-tool
harness, a design harness, a WCAG-review harness, etc.) for the project you
actually need it for. It also bundles a second-brain (Obsidian vault +
semantic search) and a doc-site microsite that reflect the harness's current
configuration.

## Install

```sh
bash bootstrap.sh          # interactive, idempotent scaffold + provider setup
bash bootstrap.sh --check  # read-only doctor: tool/provider/automation status
bash System_Config/test_providers.sh  # fake-provider regression check
```

`bootstrap.sh --check` reports which of `claude`/`agy`/`gemini`/`codex`/
`ollama`/`gh`/`node`/`npx`/`python3` are installed, whether provider config
exists yet, and confirms there's no background automation. `bootstrap.sh`
itself (no flags) runs the interactive checkbox-style setup: enable/disable
each provider, set priority order, optionally set a model per provider. It
writes the result to `.agentic-light.conf` at the repo root (gitignored,
mode `600`, parsed as text — never sourced as shell). Environment variables
(`AGENTIC_LIGHT_PROVIDERS`, `AGENTIC_LIGHT_PRIORITY`,
`AGENTIC_LIGHT_MODEL_<PROVIDER>`) override it non-interactively.

`System_Config/test_providers.sh` is a fake-binary regression suite covering
argv construction, model mapping, pre-launch fallback, single-invocation (no
retry), and Ollama's write-workflow refusal — it exits 0/`PASS` without
touching any real provider.

## Specialize — turn the template into your harness

This is the core idea: Agentic Light is not one fixed harness, it's a
template you fork and specialize once per project.

```sh
bash System_Config/specialize.sh --preset <name>
```

or run it with no flags for interactive selection (same checkbox UX as
`bootstrap.sh`: pick roles, gates, and skill dirs by hand).

Presets (from `System_Config/presets.json`):

| Preset | Description |
|---|---|
| `web-app` | full team + eslint/playwright gates + all skills |
| `cli-tool` | coder+qa, no gates, all skills |
| `data-pipeline` | architect+coder+qa, placeholder custom gate (needs a script), all skills |
| `design-harness` | architect+coder+creative-director+qa, playwright gate, all skills |
| `server-harness` | architect+coder+qa, no default gates, server-review skill |
| `wcag-harness` | architect+coder+creative-director+qa, playwright gate, wcag-audit skill |

Specializing writes three files: `System_Config/agent-roster.json` (active
roles), `pipeline/gate-config.json` (gate list), and
`System_Config/skills-selected.json` (which `skills/*` dirs `route_skill.sh`
scans). Re-running overwrites cleanly — it's idempotent, not additive. A
fresh, unspecialized clone has none of these files and runs with the full
default roster and the legacy eslint+playwright gate pair. See
`System_Config/README.md` for the full mechanics (env-var overrides,
validation rules, the `data-pipeline` custom-gate guard, etc.).

## Run

```sh
bash pipeline/run.sh "<task description>" /path/to/target/repo
```

`run.sh` targets an **external repo**, not Agentic_Light itself. Flow:
skill routing (`route_skill.sh` prepends matching `SKILL.md` guidance to the
coder prompt) → coder step (one provider, foreground, no retry) → gates
(the ordered list in `pipeline/gate-config.json` if present — `eslint`,
`playwright`, or a `custom` script; falls back to the hardcoded
eslint+playwright pair on an unspecialized fork) → human approval gate
(`[y/N]` on the committed diff) → `gh pr create --draft`. Every gate must
pass (or WARN-skip when the target repo has no lint/e2e setup) before the
diff is ever shown to a human. See `pipeline/README.md` for the full
contract (concurrency lock, exit codes, WARN-vs-hard-stop rules).

## Check on it

Two read-only dashboards, no server required:

```sh
bash System_Config/dashboard.sh         # terminal: preset, provider, roster, gates, last session, recent runs
open microsite/index.html               # browser: doc-site home, links to presets and the dashboard
open microsite/dashboard.html           # browser: condensed health + preset cards + roster-by-preset table
```

Both microsite pages open directly via `file://` — no build step, no
`python -m http.server`. `bash System_Config/healthcheck.sh` runs the full
layered PASS/WARN/FAIL check (directory layout, roster/skill frontmatter,
brain scaffolding, provider config, doc currency, a secrets scan) and
writes `microsite/status.json`/`status.js`, which `health.html` and
`dashboard.html` both render.

## Everything else, briefly

**Brain** (`brain/`) — an Obsidian-vault second brain. `brain/raw/` holds
clipped notes, `daily_ingest.sh` wikifies them into `brain/wiki/`,
`memory_index.py`/`memory_search.py` add local-Ollama semantic search over
the wiki. See `brain/README.md`.

**Skill routing** (`System_Config/route_skill.sh`) — a deterministic
keyword/substring router (no LLM call) that scans `skills/*/SKILL.md`
frontmatter and prints matching skill paths; `pipeline/run.sh` uses it to
inject skill guidance into the coder prompt. Restricted to
`System_Config/skills-selected.json`'s selection once you've specialized.

**Microsite** (`microsite/`) — the static doc site referenced above:
`index.html` (roster/skills/presets, self-healing marker blocks),
`presets/<name>.html` (one page per preset), `health.html`/`dashboard.html`
(status views). See `microsite/README.md`.

## Full docs

- `System_Config/README.md` — every script's exact behavior
- `pipeline/README.md` — gate config schema, session logging, concurrency
- `microsite/README.md` — page structure, regeneration commands
- `brain/README.md` — vault layout, ingestion, semantic search
- `CLAUDE.md` — full command list and directory map (provider-neutral orchestrator context)
