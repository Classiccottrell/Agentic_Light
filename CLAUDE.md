# Agentic Light — Orchestrator Context

Lighter sibling of the parent workspace: Obsidian second brain + dev pipeline
+ self-bootstrapping. No background automation.

## Build / Run

- `bash bootstrap.sh` — interactive, idempotent scaffold and provider configuration.
- `bash bootstrap.sh --check` — read-only doctor (tools + provider + no-automation note).
- `bash System_Config/test_providers.sh` — fake-provider check for ordered pre-launch fallback, one invocation, and no retry after failure.
- `bash pipeline/run.sh` — Task Input → coder → ESLint gate → Playwright gate → Human Gate → `gh pr create`.
- `bash skills/skills.sh list` — list available skills.
- `bash System_Config/healthcheck.sh` — layered PASS/WARN/FAIL report, self-heals docs via `gen_site.py`.
- `bash System_Config/new_agent.sh <name> "<scope>" [--write]` — scaffold a new `agents/<name>.md`.
- `bash System_Config/specialize.sh [--preset web-app|cli-tool|data-pipeline|design-harness|server-harness|wcag-harness]` — one-time fork specialization; writes `System_Config/agent-roster.json` + `pipeline/gate-config.json`.
- `bash System_Config/log_session.sh --provider <name> --role <role> --status <exit-code> --reason <exit|timeout|signal|refused>` — deterministic (no LLM call) session logger; appends one line to the current ISO week's weekly note under `## Agent Sessions`.
- `bash System_Config/route_skill.sh "<task description>"` — deterministic, provider-neutral skill router; scans `skills/*/SKILL.md` frontmatter and prints matching skill directory paths.
- `python3 System_Config/memory_index.py [--force]` — build/refresh the SQLite semantic-search cache over `brain/wiki/*.md` (stdlib + local Ollama embeddings; rebuildable, not source of truth).
- `python3 System_Config/memory_search.py "<query>" [--top N]` — cosine semantic search over the `memory_index.py` cache; prints top-N matching `brain/wiki/` page paths to stdout.
- `bash System_Config/dashboard.sh` — read-only terminal status readout: preset, provider, roster, gates, last agent session, recent pipeline runs.

## Provider Contract

Interactive bootstrap uses terminal checkbox-style prompts for Claude,
Gemini, Codex, and Ollama, followed by comma-separated priority and optional
per-provider model text fields. It stores the result in the ignored,
mode-`600` `.agentic-light.conf`; the file is parsed as data, never sourced.
Priority must be an exact ordering of enabled providers; malformed,
duplicate, unknown, missing, or extra entries fail validation.
`AGENTIC_LIGHT_PROVIDERS`, `AGENTIC_LIGHT_PRIORITY`, and
`AGENTIC_LIGHT_MODEL_<PROVIDER>` override local values.

Resolution selects the first enabled executable in priority order before
launch. A provider that starts owns that task's result: no failure retry,
queue, or scheduler exists. One pipeline task runs in the foreground per
target repository. Legacy `AGENT_TYPE` priority and exported
`AGENT_TYPE`/`CLAUDE` adapter variables remain for older scripts.

Claude has wrapper-enforced file-tool, permission, time, and budget controls.
Gemini runs with `--sandbox --approval-mode auto_edit --add-dir "$BRAIN"` (the
`--add-dir` flag is required — `agy` silently ignores `cwd` for writes without it);
Codex runs through
`codex exec --sandbox workspace-write`. Ollama is inference-only and this
write workflow fails fast with exit 64. Executed adapters have a wall-clock
watchdog; only Claude has the wrapper's dollar budget flag.

## Directory Map

```
Agentic_Light/
├── CLAUDE.md
├── bootstrap.sh
├── .obsidian/{app,appearance,core-plugins,community-plugins,graph}.json
├── Projects/_TEMPLATE/{BRIEF.md,README.md,active/.gitkeep,archive/.gitkeep}
├── System_Config/
│   ├── config.sh · test_providers.sh · mcp.defaults.json · new_agent.sh · README.md · logs/.gitkeep
│   ├── monday_init.sh · friday_process.sh · daily_ingest.sh · run_agent.sh · test_run_agent.sh
│   ├── log_session.sh · route_skill.sh
│   ├── specialize.sh · presets.json
│   ├── agent-roster.schema.json · agent-roster.example.json
│   ├── gate-config.schema.json · gate-config.example.json
│   ├── memory_index.py · memory_search.py
│   ├── gen_site.py · gen_preset_pages.py · healthcheck.sh · dashboard.sh
│   ├── notify.sh · .notify.env.example
├── agents/
│   └── architect.md · coder.md · creative-director.md · curator.md · eng-manager.md · qa.md · README.md
├── skills/
│   ├── skills.sh
│   ├── figma-* (12 dirs, from figma/mcp-server-guide) — code-connect, create-new-file,
│   │   design-to-code, generate-design, generate-diagram, generate-library,
│   │   implement-motion, swiftui, use, use-figjam, use-motion, use-slides
│   ├── wcag-audit/ (vendored from 84emllc/claude-wcag-skill, MIT + W3C
│   │   Document License — see skills/wcag-audit/NOTICE) — wcag-harness skill
│   └── server-review/ (authored in-repo) — server-harness skill
├── microsite/{template.html, index.html, health.html, status.json, status.js, README.md,
│   presets/{web-app,cli-tool,data-pipeline,design-harness,server-harness,wcag-harness}.html}
├── brain/
│   ├── CLAUDE.md · README.md
│   ├── raw/README.md
│   ├── wiki/index.md
│   └── weekly_logs/{Weekly_Note_Template.md, "2026 Master Note.md", 2026/2026-W30.md}
└── pipeline/
    ├── run.sh · test_pipeline.sh · README.md · logs/.gitkeep · gate-config.json (generated by specialize.sh, optional)
    └── lib/{eslint_gate.sh, playwright_gate.sh, human_gate.sh, pr_create.sh}
```

## Terminal Constraints

- Bash-3.2-safe: no associative arrays, no `mapfile`, no `${var,,}` — use `tr` for case work.
- Every script is relocatable: `ROOT="$(cd "$(dirname "$0")" && pwd)"` (or `${BASH_SOURCE[0]}` when sourced) at the top. Never hardcode an absolute path.
- `set -euo pipefail` in every script unless a step must survive a non-zero exit (guard with `|| true`).

## The 4 Karpathy Agentic Coding Principles

1. **Think Before Coding** — state assumptions and surface trade-offs before editing.
2. **Simplicity First** — write the minimum code required, eliminate speculative abstractions.
3. **Surgical Changes** — touch strictly the requested code, no drive-by refactoring.
4. **Goal-Driven Execution** — define explicit success criteria, verify with tests.

## Agent Roster

| Agent | Scope |
|---|---|
| `architect` | Blueprints, schema, directory structure decisions |
| `coder` | Implementation |
| `creative-director` | Brand/visual/copy review |
| `curator` | `brain/` knowledge base curation |
| `eng-manager` | `Projects/` lifecycle, PR drafting |
| `qa` | Test coverage, regression checks |

`archivist` and `rally` are **excluded from this roster by design** — Agentic
Light has no archival pipeline and no rally/broadcast agent; do not add them.

## `.obsidian/` Is Shipped

Unlike the parent workspace (which gitignores `.obsidian/`), Agentic Light
ships `app.json`, `appearance.json`, `core-plugins.json`,
`community-plugins.json`, `graph.json` directly. This is the only supported
KB strategy here (no VS Code/Foam alternative), so committing vault config
guarantees every clone opens with working core plugins and graph view with
zero setup. `workspace.json`/`workspace-mobile.json` (per-machine session
state) are intentionally omitted.
