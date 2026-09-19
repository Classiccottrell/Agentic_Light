# agents/ — Agentic Light Roster

Each agent is a single self-contained file: `agents/<name>.md`
(frontmatter `name`/`description`/`tools`/`model: inherit` + body). No split
`.md` + `SKILL.md` pair like the parent workspace — Agentic Light keeps one
file per role. Scaffold new ones with
`bash System_Config/new_agent.sh <name> "<scope>" [--write]`.

## Base roster

| Agent | Scope | Hands off to |
|---|---|---|
| `architect` | Blueprints, schema, directory structure decisions | `coder` |
| `coder` | Implementation, builds, tests | `qa` (production PRs), `eng-manager` |
| `eng-manager` | `Agentic_Light/Projects/` lifecycle | `architect`, `coder`, `qa` |
| `qa` | Test coverage, regression checks against cloned repos | `eng-manager` |
| `curator` | `Agentic_Light/brain/` knowledge base curation | — (terminal) |
| `creative-director` | Brand/visual/copy review (e.g. `microsite/`) | — (terminal, opt-out of Caveman Protocol) |

`archivist` and `rally` are **excluded from this roster by design**. Agentic
Light has no archival pipeline and no rally/broadcast agent — do not add
them back in; if a future task seems to need one, treat that as a signal to
route the work through the existing roster or reconsider the task, not to
silently reintroduce a role the spec deliberately dropped.

## `qa` / `eng-manager` are not part of `pipeline/run.sh`

`qa` and `eng-manager` are orchestrator-dispatched roles: something (a human
or the root orchestrator session) invokes them explicitly via the Agent tool.
`pipeline/run.sh`'s automated shell chain — coder → ESLint → Playwright →
Human Gate → `gh pr create` (see `pipeline/README.md`) — never calls either
`.md` file; it has no Agent-tool dispatch at all. Treat them as optional
gap-review you route to by hand after a pipeline run, not steps the pipeline
itself executes.
