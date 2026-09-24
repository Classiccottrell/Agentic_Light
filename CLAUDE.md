# Agentic Light — Orchestrator Context

Lighter sibling of the parent workspace: Obsidian second brain + dev pipeline
+ self-bootstrapping. No background automation.

## Build / Run

Windows note: `python3` may not exist (or may be a Microsoft Store stub)
on Windows — use `python` or `py -3` in place of `python3` in every
command below.

- `python3 bootstrap.py` — interactive, idempotent scaffold and provider configuration.
- `python3 bootstrap.py --check` — read-only doctor (tools + provider + no-automation note).
- `python3 System_Config/test_providers.py` — fake-provider check for ordered pre-launch fallback, one invocation, and no retry after failure.
- `python3 System_Config/test_run_agent.py` — regression test for the gemini/agy `--add-dir` write-confinement contract (stubs `agy` to emulate its silent-cwd-ignoring bug so a future edit that drops the flag fails loudly instead of regressing writes).
- `python3 pipeline/run.py` — Task Input → coder → ESLint gate → Playwright gate → Human Gate → `gh pr create`.
- `python3 pipeline/test_pipeline.py` — integration test for the whole pipeline gate/lock/secret-scan contract.
- `bash skills/skills.sh list` — list available skills (not yet ported — Tier 4).
- `python3 System_Config/healthcheck.py` — layered PASS/WARN/FAIL report, self-heals docs via `gen_site.py` / `gen_preset_pages.py` / `gen_governance.py`.
- `python3 System_Config/gen_governance.py [--check|--dry-run]` — generates `GOVERNANCE.md` (per-role scope, human sign-off gate, audit trail, this fork's live gate policy, config security) from `agents/*.md`, `agent-roster.json`, `gate-config.json`.
- `python3 System_Config/new_agent.py <name> "<scope>" [--write]` — scaffold a new `agents/<name>.md`.
- `python3 System_Config/specialize.py [--preset web-app|cli-tool|data-pipeline|design-harness|server-harness|wcag-harness]` — one-time fork specialization; writes `System_Config/agent-roster.json` + `pipeline/gate-config.json`.
- `python3 System_Config/log_session.py --provider <name> --role <role> --status <exit-code> --reason <exit|timeout|signal|refused>` — deterministic (no LLM call) session logger; appends one line to the current ISO week's weekly note under `## Agent Sessions`.
- `python3 System_Config/route_skill.py "<task description>"` — deterministic, provider-neutral skill router; scans `skills/*/SKILL.md` frontmatter and prints matching skill directory paths.
- `python3 System_Config/memory_index.py [--force]` — build/refresh the SQLite semantic-search cache over `brain/wiki/*.md` (stdlib + local Ollama embeddings; rebuildable, not source of truth).
- `python3 System_Config/memory_search.py "<query>" [--top N]` — cosine semantic search over the `memory_index.py` cache; prints top-N matching `brain/wiki/` page paths to stdout.
- `python3 System_Config/context_packet.py [query]` — print a bounded resume packet from the roadmap, active preset, recent session facts, and optional semantic matches. Byte-exact truncation, not a character slice. `pipeline/run.py` prepends its output to the coder prompt opt-in only (`AGENTIC_LIGHT_CONTEXT_PACKET=1`, or automatically when the target repo is this workspace's own root) — never injected into an unrelated external target repo by default.
- `python3 System_Config/context.py [--root ROOT] packet|validate|catalog|curate ...` — thin dispatcher to `context_packet.py`/`context_validate.py`/`context_catalog.py`/`context_curate.py` (the latter three already pure Python, untouched by this port).
- `bash System_Config/test_context_packet.sh` — fixture tests proving the packet respects a tiny `AGENTIC_LIGHT_CONTEXT_MAX_LINES`/`_MAX_BYTES` budget against dense multi-byte (em dash) content, and that the default budget preserves every provenance header (not yet ported — Tier 4).
- `python3 System_Config/preset_audit.py` — validate preset role, gate, skill, and focused role-note contracts, including `design-harness`/`wcag-harness`'s `role_capabilities`/`role_handoff` overlays.
- `python3 System_Config/white_label_check.py <fork> --name <name> --preset <preset>` — audit a pruned fork's identity, active role files, selected skills, and (via each generator's own `--check` mode) that generated output isn't stale, without modifying it.
- `python3 System_Config/dashboard.py` — read-only terminal status readout: preset, provider, roster, gates, last agent session, recent pipeline runs.
- `python3 System_Config/notify.py "<title>" "<body>"` — Slack/Google Chat webhook + opt-in local macOS banner dispatch.

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
├── ROADMAP.md
├── GOVERNANCE.md (generated — see gen_governance.py)
├── bootstrap.sh · bootstrap.py (bash original kept alongside its Python port — not yet deleted)
├── .obsidian/{app,appearance,core-plugins,community-plugins,graph}.json
├── Projects/_TEMPLATE/{BRIEF.md,README.md,spec.md,tasks.md,Plan.md,active/.gitkeep,archive/.gitkeep}
├── System_Config/ (ported .sh originals kept alongside their .py ports for now — not yet deleted)
│   ├── config.sh · config.py · test_providers.sh · test_providers.py · mcp.defaults.json · new_agent.sh · new_agent.py · README.md · logs/.gitkeep
│   ├── monday_init.sh · friday_process.sh · daily_ingest.sh (not yet ported — Tier 4) · run_agent.sh · run_agent.py · test_run_agent.sh · test_run_agent.py
│   ├── log_session.sh · log_session.py · route_skill.sh · route_skill.py · context.sh · context.py · context_packet.sh · context_packet.py
│   ├── specialize.sh · specialize.py · presets.json
│   ├── agent-roster.schema.json · agent-roster.example.json
│   ├── gate-config.schema.json · gate-config.example.json
│   ├── memory_index.py · memory_search.py · test_context_packet.sh (not yet ported — Tier 4) · preset_audit.py · white_label_check.py
│   ├── gen_site.py · gen_preset_pages.py · gen_governance.py · healthcheck.sh · healthcheck.py · dashboard.sh · dashboard.py
│   ├── notify.sh · notify.py · .notify.env.example
├── agents/
│   └── architect.md · coder.md · creative-director.md · curator.md · eng-manager.md · qa.md · README.md
├── skills/
│   ├── skills.sh
│   ├── figma-* (12 dirs, from figma/mcp-server-guide) — code-connect, create-new-file,
│   │   design-to-code, generate-design, generate-diagram, generate-library,
│   │   implement-motion, swiftui, use, use-figjam, use-motion, use-slides
│   ├── wcag-audit/ (vendored from 84emllc/claude-wcag-skill, MIT + W3C
│   │   Document License — see skills/wcag-audit/NOTICE) — wcag-harness skill
│   ├── vpat-authoring/ (authored in-repo) — wcag-harness skill, VPAT/ACR
│   │   drafting + the vpat-lint gate's discipline
│   ├── server-review/ (authored in-repo) — server-harness skill
│   ├── react-doctor/, shadcn/ (vendored, no license metadata) — web-app skill
│   ├── systematic-debugging/, managing-python-dependencies/ (vendored;
│   │   managing-python-dependencies is Apache-2.0/Google — see its NOTICE)
│   │   — cli-tool skills
│   └── gcp-data-pipelines/, dbt-bigquery/, discovering-gcp-data-assets/
│       (vendored, Apache-2.0/Google — see each dir's NOTICE) — data-pipeline
│       skills
├── microsite/{template.html, index.html, health.html, status.json, status.js, README.md,
│   presets/{web-app,cli-tool,data-pipeline,design-harness,server-harness,wcag-harness}.html}
├── brain/
│   ├── CLAUDE.md · README.md
│   ├── raw/README.md
│   ├── wiki/index.md
│   └── weekly_logs/{Weekly_Note_Template.md, "2026 Master Note.md", 2026/2026-W30.md}
└── pipeline/ (ported .sh originals kept alongside their .py ports for now — not yet deleted)
    ├── run.sh · run.py · test_pipeline.sh · test_pipeline.py · README.md · logs/.gitkeep · gate-config.json (generated by specialize.py, optional)
    └── lib/{eslint_gate.sh, eslint_gate.py, playwright_gate.sh, playwright_gate.py, axe_gate.sh, axe_gate.py, vpat_lint_gate.sh, vpat_lint_gate.py, human_gate.sh, human_gate.py, pr_create.sh, pr_create.py}
```

## Cross-Platform Constraints

- Python 3.9+ stdlib only — no third-party dependencies, no pip install
  required. Do not use `match` statements or `X | Y` union type hints
  (3.10+ only); `Path.is_relative_to` (3.9+) is fine.
- Every script: `ROOT = Path(__file__).resolve().parent.parent` at the
  top — relocatable, no hardcoded absolute paths.
- `pathlib.Path` throughout; never manual `/`-string path joining.
- UTF-8 everywhere: `encoding="utf-8"` on every `open()`/`subprocess`
  call; `newline="\n"` on every write; reconfigure stdout/stderr to
  UTF-8 at each entry point (Windows defaults to cp1252 when piped).
- Atomic writes: `tempfile.mkstemp()` + `os.replace()` (not `os.rename`,
  which fails on Windows if the destination exists).
- Resolve external tools via `shutil.which()`, never a bare name in
  `subprocess.run([...], shell=False)` — Windows npm/gh/claude/gemini/
  codex are typically `.cmd` shims that need `PATHEXT` resolution first.
- "Fail fast, fail loud" (bash's `set -euo pipefail`): every script's
  `main()` returns a nonzero int on any hard failure, caught by
  `sys.exit(main())`; unexpected exceptions propagate (a visible
  traceback) rather than being caught-and-swallowed.
- Windows has no execute bit / shebang dispatch — every script is
  invoked as `python script.py`, never directly executed; `bootstrap.py`
  no longer chmod's anything.
- `python3` may not exist on Windows (or may be the Microsoft Store
  stub) — Windows users should use `python` or `py -3`.

Tier 4 scripts (`monday_init.sh`, `friday_process.sh`, `daily_ingest.sh`,
`skills/skills.sh`, `test_context_packet.sh`) are not yet ported and
remain bash-3.2-safe (no associative arrays, no `mapfile`, no
`${var,,}`) until their own pass.

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
