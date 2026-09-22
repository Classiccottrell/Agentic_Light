# Governance — Agentic Light

<!-- GENERATED FILE — produced by `System_Config/gen_governance.py`. Do not
hand-edit sections inside a `<!-- gen:*-start/end -->` marker pair; they are
rebuilt from `agents/*.md`, `System_Config/agent-roster.json`, and
`pipeline/gate-config.json` every run and any manual edit is overwritten.
Text outside marker pairs is fixed policy prose maintained directly in
`gen_governance.py`, not per-fork data — edit it there. -->

This is the single place to answer: **what can an agent in this fork
actually do, and what requires a human's own explicit sign-off before it
ships?** It documents the mechanism `pipeline/run.sh` already enforces; it
does not add new mechanism.

## 1. Per-Role Scope

Pulled from each role file's own frontmatter (`description` + `tools`) in
`agents/`. This is the actual grant, not a paraphrase — see the linked file
for the full rules each role also follows (context discipline, response
style, hand-off targets).

<!-- gen:roles-start -->
| Role | Stated scope (from frontmatter `description`) | Granted tools | Source |
|---|---|---|---|
| `architect` | System designer for Agentic Light. Use for high-level architecture, schemas, folder structures, API contracts, and data-model design — before any implementation. Produces specs and Mermaid diagrams; hands blueprints to the coder agent. Not for writing feature code. | `Read, Glob, Grep, Write, Edit` | `agents/architect.md` |
| `coder` | Implementation engineer for Agentic Light. Use to write or modify code against an existing stack or an architect's blueprint, fix bugs, and run builds/tests. Returns diffs of changed lines. Not for high-level design (use architect) or knowledge notes (use curator). | `Read, Glob, Grep, Edit, Write, Bash` | `agents/coder.md` |
| `creative-director` | Elite Creative Director and Brand Strategist for Agentic Light. Use for brand critique, campaign concepts, tagline generation, visual direction, copy refinement, and design feedback (e.g. `microsite/`). Applies Impact/Clarity/Disruption framework. Tone: inspiring, candid, sophisticated — NOT Caveman Protocol. | `Read, Write, Edit, Bash` | `agents/creative-director.md` |
| `curator` | Knowledge curator for the Agentic Light Obsidian LLM-wiki. Use to ingest sources into wiki entity pages, extract concept notes, maintain wiki/index.md and cross-links, and answer knowledge queries from the brain. Follows the Karpathy LLM Wiki schema. Authority limited to Agentic_Light/brain/. | `Read, Glob, Grep, Write, Edit` | `agents/curator.md` |
| `eng-manager` | Project lifecycle controller for Agentic_Light/Projects/. Use to scope a project from its BRIEF.md and stack, plan and route work to architect/coder, validate completion, and prepare artifacts for handoff. Authority limited to Agentic_Light/Projects/. | `Read, Glob, Grep, Edit, Write, Bash` | `agents/eng-manager.md` |
| `qa` | Quality-assurance verifier for pull requests against existing, cloned repositories under Agentic_Light/Projects/. Use to run a target repo's own lint/typecheck/unit-test commands, extend or author browser/e2e coverage, and compile a pass/fail QA report before a PR is drafted. Not for implementation (use coder) or for creating branches, commits, or PRs (that stays with the orchestrator's approved flow). | `Read, Glob, Grep, Bash, Write, Edit` | `agents/qa.md` |
<!-- gen:roles-end -->

`archivist` and `rally` are excluded from the roster by design (see
`agents/README.md`) — Agentic Light has no archival pipeline and no
rally/broadcast agent.

`qa` and `eng-manager` are orchestrator-dispatched roles, not steps
`pipeline/run.sh` itself invokes — see `agents/README.md`'s "`qa` /
`eng-manager` are not part of `pipeline/run.sh`" section.

## 2. The Human Sign-Off Gate

**No code produced by this system reaches a pull request without an
explicit human approval.** This is the governance checkpoint of the whole
pipeline, enforced structurally, not by convention:

- `pipeline/run.sh` step 3, the **Human Gate** (`pipeline/lib/human_gate.sh`
  by default; `PIPELINE_HUMAN_GATE_CMD` overrides it only when
  `AGENTIC_LIGHT_TEST_MODE=1` is also set — otherwise the override is
  ignored with a warning and the real gate runs),
  renders the full diff already committed to the run's feature branch plus
  the gate-run summary, and blocks on an interactive `[y/N]` prompt.
- The gate **never auto-approves**. A non-interactive session (no TTY on
  stdin) exits `2` (pending) — the pipeline stops and creates no PR, rather
  than defaulting to yes.
- `pipeline/lib/pr_create.sh` (step 4, `gh pr create --draft`) is only ever
  called after the Human Gate returns approval (`0`). Every other exit path
  — a failed gate, a declined human gate, a pending non-interactive gate —
  hard-stops before this step; see `pipeline/README.md`'s "Halt-on-failure
  guarantee" and "Human Gate exit codes".
- Every configured gate (ESLint/Playwright/axe, or the fork's own
  `gate-config.json` list — see §4 below) must pass, or be skipped via its
  own documented no-op condition, **before** the human ever sees the diff.
  A failing gate is a hard stop, not a warning shown alongside the PR.

## 3. Audit Trail — What Gets Logged, and Where

- **`System_Config/log_session.sh`** — called exactly once per coder
  invocation, after the coder step, regardless of outcome (success, watchdog
  timeout, or an Ollama write-workflow refusal). Appends one line —
  provider, role, exit status, reason — under `## Agent Sessions` in the
  current ISO week's weekly note (`brain/weekly_logs/YYYY/YYYY-Www.md`).
  This is the append-only session record: every coder invocation, whether
  it made it to a PR or not, leaves a trace.
- **`pipeline/logs/<run-id>.log`** — the full run, gate output included, is
  teed to a per-run log file (`RUN_ID="$(date +%Y%m%d-%H%M%S)-$$"`). This is
  the gate-run history: what ran, in what order, and whether it passed.
- **`System_Config/healthcheck.sh`**'s "Pipeline Logs" layer reports log
  recency (WARN on a fresh scaffold with zero runs yet, PASS once any exist)
  so a stalled/idle pipeline is visible in the health dashboard, not just in
  a directory listing.

## 4. Gate Policy — This Fork's Current State

Reflects the actual specialization state of **this** clone/fork, not a
generic description — regenerated from `System_Config/agent-roster.json`
and `pipeline/gate-config.json` (or their absence) every run.

<!-- gen:gate-policy-start -->
**This fork is unspecialized** — `System_Config/agent-roster.json` and `pipeline/gate-config.json` are both absent. `System_Config/specialize.sh` has not been run against a preset yet.

Default behavior in this state (per `pipeline/run.sh`):
- All 6 roles in `agents/` are available for orchestrator dispatch.
- The pipeline gate step runs the hardcoded default pair, in order: `eslint` (`pipeline/lib/eslint_gate.sh`), then `playwright` (`pipeline/lib/playwright_gate.sh`).
<!-- gen:gate-policy-end -->

Run `bash System_Config/specialize.sh --preset <name>` (see
`System_Config/presets.json` for the list) to change this fork's active
roles/gates, then re-run `python3 System_Config/gen_governance.py` to
refresh this section.

## 5. Config Security

`System_Config/healthcheck.sh`'s **Layer G — Config Security Scan** is part
of this governance layer, not a separate concern: it greps the project's own
config surface (`System_Config/*.sh`, `System_Config/*.json`, `.mcp.json`,
any `.env*`, `.agentic-light.conf`) for credential-shaped strings (known
provider key prefixes, bearer tokens, `*_KEY`/`*_TOKEN`/`*_SECRET`
assignments that aren't placeholders), and WARNs on any hit that isn't
already covered by `.gitignore`. It also asserts that files documented as
local-only (`.mcp.json`, `.agentic-light.conf`,
`System_Config/.notify.env`) are in fact gitignored. Run it directly with
`bash System_Config/healthcheck.sh`, or read the "Config Security Scan"
section of the generated `microsite/health.html`.

## See also

- `pipeline/README.md` — the full gate -> human-gate -> PR flow, gate
  configuration schema, concurrency lock, and test coverage.
- `agents/README.md` — full roster table and hand-off graph.
- `System_Config/README.md` — script-by-script reference, including
  `healthcheck.sh` and `log_session.sh`.
- `System_Config/agent-roster.schema.json` / `gate-config.schema.json` —
  the schemas §1/§4 validate against.
