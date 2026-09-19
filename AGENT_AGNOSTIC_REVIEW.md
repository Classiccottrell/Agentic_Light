# Agentic_Light Roadmap — Agent-Agnostic Review

## Provider-coupling findings

### Phase 1

| Roadmap item | Claude-only assumption | Provider-neutral equivalent |
|---|---|---|
| SessionEnd context hook | A `.claude/hooks/` `SessionEnd` hook is a Claude Code lifecycle primitive. Gemini and Codex do not consume it, and Ollama cannot execute the write workflow. A hook also cannot reliably observe sessions launched outside Claude. | Make `System_Config/log_session.sh` the canonical deterministic logger. Call it from the provider-neutral launcher (`pipeline/run.sh` / `System_Config/run_agent.sh`) after the provider process returns, recording provider, role, exit status, and timestamp. Treat native Claude/Gemini/Codex lifecycle hooks as optional adapters, never the source of truth. Preserve the existing `brain/weekly_logs` location, but rename or support the legacy `## Claude Sessions` heading because the current schema already says entries may come from any provider. |
| Thin skill router: `skills/router/SKILL.md` | A `SKILL.md` is currently a Claude Code skill artifact, and “hands them to the coder role” implies Claude’s `Skill` tool and subagent orchestration. Gemini, Codex, and Ollama do not discover or invoke it natively. | Store the router’s rules as provider-neutral Markdown, e.g. `skills/router/SKILL.md`, but invoke it through `System_Config/route_skill.sh` or directly from the launcher. The launcher should scan descriptions, select skill paths, and prepend their contents to the coder prompt. For Ollama, allow routing/read-only planning only; fail explicitly before any write workflow as the existing contract requires. |
| Router scans skill frontmatter | The roadmap assumes Claude’s skill frontmatter/invocation conventions are meaningful to every provider. Existing frontmatter is usable metadata, but fields such as `disable-model-invocation` are Claude-specific behavior. | Define a small documented metadata subset (`name`, `description`, optional `provider_support`) in `skills/README.md` or `System_Config/skill-schema.md`; ignore Claude-only fields in the shell router. Pass selected skill files as ordinary prompt context. |
| `gate-config.yml` | The file itself is not Claude-specific, but it is read only by the shell pipeline after a provider-specific coder launch. A gate setting cannot be assumed to change the agent’s behavior or tool permissions. | Keep gate selection in `pipeline/gate-config.yml` (or per-target config), parsed by `pipeline/run.sh`; make gate execution wholly external to the provider. Define `custom` as an explicit script path plus working directory/arguments, not an underspecified slot. |

### Phase 2

| Roadmap item | Claude-only assumption | Provider-neutral equivalent |
|---|---|---|
| `specialize.sh` writes `CLAUDE.md`’s roster table | `CLAUDE.md` is auto-loaded by Claude Code only. Gemini looks for `GEMINI.md`, Codex may use `AGENTS.md` or explicit prompt context, and Ollama has no native project-instruction loader. Updating one Claude file leaves the active provider unaware of the selected roster. | Write a canonical machine-readable roster, e.g. `System_Config/agent-roster.yml`, and have the launcher load the selected role file explicitly. Generate optional provider instruction mirrors (`CLAUDE.md`, `GEMINI.md`, `AGENTS.md`) only when desired; never make those mirrors authoritative. Update `agents/README.md` from the canonical roster or document it as generated. |
| “Which agents from the 6-agent roster to keep” | Existing `agents/*.md` files are Claude Code subagent definitions: YAML `tools`, `model: inherit`, and role handoff text are not consumed natively by other providers. | Treat each `agents/<role>.md` as provider-neutral role content after removing or isolating execution metadata. Put provider-specific adapters/tool grants in `System_Config/providers/` or launcher code. The launcher should select a role by name and inject the role file as prompt context. |
| “same UX pattern as provider selection” | Terminal checkbox UX is provider-neutral as a shell interface, but it does not make the generated instructions portable. | Reuse the shell prompt, persist answers in canonical config, validate selected roles against actual files, and render provider-specific instruction files only as derived output. |
| Task-shape presets | Preset names are provider-neutral, but “full roster” and the handoff chain are only prose today; providers cannot infer or delegate roles from them. | Persist preset expansion in `System_Config/agent-roster.yml` and pass an explicit role/task sequence to the selected provider. Do not rely on native subagent tools; if a provider cannot delegate, run roles as separate launcher invocations or treat the preset as a single prompt. |

### Phase 3

The exclusions are not Claude-specific. They are safe only if “out of scope” also means no provider-specific background/session mechanism is introduced later. “Multi-provider SaaS/MCP integration bridges” should not be required for the core path; provider-native MCP/tool configuration remains an optional adapter concern.

## Missing considerations

- **Canonical instruction source.** The roadmap needs one source of truth for role definitions, selected roles, task presets, and constraints. `CLAUDE.md` cannot serve that role for Gemini/Codex/Ollama.
- **Prompt assembly contract.** Define ordering and delimiters for task, role instructions, selected skills, repository context, and output requirements. Providers differ in system-prompt support, context loading, stdin handling, and command-line prompt length.
- **Tool capability negotiation.** Claude’s named tools, Gemini’s sandbox/approval mode, Codex’s workspace sandbox, and Ollama’s inference-only behavior are not interchangeable. The launcher needs a capability check such as `read`, `write`, `shell`, `web`, and `delegate`, with fail-fast behavior when a role requires an unavailable capability.
- **Role handoffs.** `agents/*.md` describes Claude-style delegation/handoffs, but there is no provider-neutral protocol for passing artifacts, status, or failures from architect to coder to QA. Use files or structured launcher outputs, not an assumed subagent tool.
- **Skill content portability.** Several existing Figma skills explicitly require Figma MCP tools and Claude-oriented invocation metadata. The router must distinguish “skill can be read as instructions” from “provider can execute the required MCP/tool calls.” A selected skill should carry prerequisites and a clear unsupported-provider result.
- **Config format and validation.** `gate-config.yml` adds a YAML dependency or parser requirement to a Bash-3.2-safe project. Decide whether to use a deliberately narrow line format, JSON with an existing parser, or a small Python stdlib parser. Validate unknown gates, missing scripts, duplicate roles, and unsafe paths.
- **Provider-specific model and context limits.** Skill/role injection can exceed context limits or prompt-size limits, especially when several Figma directories are selected. Bound the number of skills and pass paths/content predictably.
- **Exit/status semantics.** Preserve the current contract: pre-launch executable fallback only; once a provider starts, its status is final. Session logging and multi-role presets must not introduce implicit retries or mid-run provider handoff.
- **Ollama behavior.** The write workflow must continue to reject Ollama before invocation. Read-only routing, review, or planning needs a separately named path if it is intended; otherwise the preset selector must exclude Ollama for write tasks.
- **Session boundary definition.** A launcher can reliably log its own invocation, but “session ended” is ambiguous for interactive provider sessions, crashes, terminal disconnects, and multiple roles. Record launcher completion and distinguish `exit`, `timeout`, and `signal`; do not promise universal native session capture.
- **Generated-file ownership.** If provider mirrors are generated, define whether humans may edit them and how drift is detected. `healthcheck.sh` and `gen_site.py` currently inspect Claude-shaped files, so their validation must be updated to validate the canonical files instead.
- **External target repository context.** `pipeline/run.sh` runs the coder in the target repository, while the Agentic_Light role/skill files live in this repository. The launcher must pass absolute or explicitly mounted paths and avoid assuming the provider auto-loads Agentic_Light instructions from the target repo.

## Revised phase plan

### Phase 1 — provider-neutral runtime primitives

1. Add `System_Config/log_session.sh` as a plain executable. Accept provider, role, exit status, termination reason, and optional run ID; append one deterministic line to the current week’s `brain/weekly_logs/YYYY/YYYY-Www.md`. Keep the legacy heading for compatibility, but use provider-neutral wording for new entries.
2. Update `System_Config/run_agent.sh` and `pipeline/run.sh` to call the logger exactly once after the provider process completes, including timeout and refusal statuses. Do not implement native lifecycle hooks as a requirement. A future `.claude/hooks/`, `GEMINI.md`, or `AGENTS.md` adapter may call the same logger but must not duplicate entries.
3. Add `System_Config/agent-roster.yml` (or the selected narrow format) as the canonical role/preset registry. Add `System_Config/assemble_prompt.sh` or equivalent minimal launcher logic to load a role file and selected skill contents explicitly.
4. Add `skills/router/SKILL.md` as human-readable routing policy and `System_Config/route_skill.sh` as the provider-neutral executable that reads task text, parses only the supported `name`/`description` metadata, and returns selected skill paths. It must report unsupported tool/MCP prerequisites rather than pretending all providers can run a skill.
5. Add `pipeline/gate-config.yml` and update `pipeline/run.sh` to apply `{eslint, playwright, custom}` outside the provider. Define the custom gate schema and preserve hard-stop, skip, human-gate, and PR semantics. Add a minimal self-check for parsing and unknown gate failures.

### Phase 2 — specialization and portability

1. Add `System_Config/specialize.sh`. Reuse the provider-selection prompt style, but write canonical selections to `System_Config/agent-roster.yml` and `pipeline/gate-config.yml`; do not write only to `CLAUDE.md`.
2. Keep `agents/<role>.md` as role content, and move execution metadata to the canonical roster/provider adapter layer. If compatibility files are generated, generate `CLAUDE.md`, `GEMINI.md`, and `AGENTS.md` from the same source only when selected/configured; never require any of them for execution.
3. Implement `web-app`, `cli-tool`, and `data-pipeline` presets in the canonical roster config. Expand each to explicit role names, skill paths, gate settings, and required capabilities. A preset that includes writes must reject Ollama before launch.
4. Update `System_Config/healthcheck.sh`, `System_Config/gen_site.py`, `agents/README.md`, `System_Config/README.md`, and `pipeline/README.md` to validate and document the canonical config, provider capability checks, and generated-file ownership.

### Phase 3 — remain out of scope

Keep daily/Friday background automation, `archivist`/`rally`, and SaaS/MCP integration bridges out of scope. Do not add provider-native session hooks, subagent APIs, or auto-load filenames as required architecture. If later added, each must be an optional adapter around the canonical launcher/logger/prompt contracts.

## Open questions for the human

1. Should Phase 1’s session record mean “every Agentic_Light launcher invocation completed” or should the project also attempt best-effort capture of manually started provider sessions?
2. Which canonical config format is acceptable for `agent-roster` and gates: narrow Bash-readable text, JSON parsed with Python stdlib, or YAML with a new dependency?
3. Should provider instruction mirrors (`CLAUDE.md`, `GEMINI.md`, `AGENTS.md`) be generated at all, or should every provider receive explicit prompt context only?
4. For a task requiring multiple roles, should the launcher run separate sequential provider invocations, or should the selected provider receive one prompt with a role plan? This affects artifact handoffs and failure semantics.
5. Should Ollama be allowed for read-only routing/review presets, or should it be excluded from all presets and launcher paths except provider discovery/testing?
6. When a selected skill requires Figma MCP or another unavailable tool, should specialization reject the selection, should routing skip it, or should the provider receive it as advisory text?
7. Is `custom` one script path per fork, or can a preset define multiple custom gates with arguments and working directories?
