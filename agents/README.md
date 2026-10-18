# agents/ — Agentic Light Roster

Each agent is a single self-contained file: `agents/<name>.md`
(frontmatter `name`/`description`/`tools`/`risk`/`model: inherit` + body). No split
`.md` + `SKILL.md` pair like the parent workspace — Agentic Light keeps one
file per role. Scaffold new ones with
`python3 System_Config/new_agent.py <name> "<scope>" [--write]`.

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

## Risk metadata

`tools:` is capability metadata — what a role *can* call. `risk:` is its
declared blast radius — what running it is allowed to do to the world:

```yaml
risk: {read_only: false, destructive: false, idempotent: false, external_side_effects: false}
```

| Flag | `true` means |
|---|---|
| `read_only` | Never modifies files or state. |
| `destructive` | May delete or overwrite existing work, not just add to it. |
| `idempotent` | Re-running the same task with the same inputs leaves the same end state. |
| `external_side_effects` | May act outside the workspace (network, remote service, PR creation). |

| Agent | Flags set | Why |
|---|---|---|
| `architect` | none | Writes specs/diagrams; no shell. |
| `coder` | `destructive` | Edits and removes existing code and runs builds; never pushes or opens a PR. |
| `creative-director` | none | Review and copy edits; additive. |
| `curator` | none | `brain/` is create-or-append only, never delete; raw sources immutable. |
| `eng-manager` | `external_side_effects` | May create a PR — only after the user's explicit go-ahead. |
| `qa` | none | Runs checks and adds tests; never branches, commits, or opens a PR. |

The flags describe each role's contract, bounded by its `tools:` —
`python3 System_Config/preset_audit.py` (run by `healthcheck.py`) fails if
any role omits a flag or contradicts its tools (e.g. `read_only: true` with
Write/Edit/Bash). `GOVERNANCE.md` §1 renders the flags per role. When a
role's rules change what it may do, update its `risk:` in the same edit.

## `qa` / `eng-manager` are not part of `pipeline/run.py`

`qa` and `eng-manager` are orchestrator-dispatched roles: something (a human
or the root orchestrator session) invokes them explicitly via the Agent tool.
`pipeline/run.py`'s automated shell chain — coder → ESLint → Playwright →
Human Gate → `gh pr create` (see `pipeline/README.md`) — never calls either
`.md` file; it has no Agent-tool dispatch at all. Treat them as optional
gap-review you route to by hand after a pipeline run, not steps the pipeline
itself executes.
