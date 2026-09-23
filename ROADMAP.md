# Agentic Light Roadmap

Last reviewed: 2026-09-23

## Shipped

- Provider-neutral launcher, ordered fallback, sandbox limits, and session logging.
- Skill routing with an overridable injection cap.
- Preset specialization and config-driven gates.
- Semantic wiki search with a rebuildable local cache.
- Governance, config-security checks, microsite generation, and dashboards.
- `design-harness` and `wcag-harness` presets with focused skills and gates.
- White-labeling guide and PR #20.
- Checked-in roadmap added.
- Preset contract audit added to `healthcheck.sh`.
- **Preset execution hardening** — `design-harness`/`wcag-harness` now carry explicit `role_capabilities` (per-role capability subset) and `role_handoff` (which role, or `orchestrator`, receives each role's output) alongside `role_notes` in `presets.json`; validated by `preset_audit.py` (keys must match `role_notes`, capabilities a non-empty duplicate-free subset of the schema enum, handoff targets an active role or `orchestrator`), wired through `specialize.sh` into `agent-roster.json`'s per-role capabilities, and rendered inline by `gen_governance.py`/`gen_preset_pages.py`.
- **White-label hardening** — `white_label_check.py` now also shells out to `gen_governance.py`/`gen_site.py`/`gen_preset_pages.py --check` inside the audited fork (a missing generator is itself a finding), and `--self-test` builds 5 real forks (two clean presets, a stale-old-name-text failure, a roster/preset-mismatch failure, and a generated-output-staleness failure) that actually run the (renamed) generator scripts rather than asserting against hand-written fixture files.
- **Context integration** — `pipeline/run.sh` prepends `System_Config/context_packet.sh`'s output to the coder prompt, opt-in only (`AGENTIC_LIGHT_CONTEXT_PACKET=1`, or automatically when the target repo is this workspace's own root) — this pipeline runs against external target repos by default, so the packet never leaks in uninvited.
- **Context evaluation** — fixed a real UTF-8 byte-vs-character truncation bug in `context_packet.sh` (`${packet:0:MAX_BYTES}` sliced characters, not bytes) and added `test_context_packet.sh`, which proves the byte budget holds against a synthetic `ROADMAP.md` with dense multi-byte content and that the default budget preserves every provenance header.
- **`vpat-authoring` skill + `vpat-lint` gate** — `wcag-harness` gained a second skill covering the VPAT/ACR authoring side of accessibility work (wcag-audit finds defects, vpat-authoring documents them in ITI VPAT 2.5Rev language). All 9 original Scan/Systemize/Ship prompts live in `skills/vpat-authoring/references/prompts/`; the 4 that produce/validate `accessibility/vpat-draft.json` (Findings-to-Row, VPAT Linter, Axe-Scan-to-Row, Final Assembler) are condensed into `SKILL.md` since only `SKILL.md` is ever injected into the coder's prompt; the other 5 (test-plan generation, gap analysis, remediation backlog, procurement summary, cross-standard mapping) are on-request references. The new `vpat-lint` gate (`pipeline/lib/vpat_lint_gate.sh`) checks any `accessibility/vpat-draft.json` against 6 deterministic rules (ITI terms only, one rating per criterion, no Supports/defect contradiction, rating-aware What/Who/Where/Evidence/Why markers, no Markdown leak, automated-evidence-only capped below Supports/Does Not Support) — WARN+skip with no draft, hard stop on a violation.
- **Microsite integrity and polish** — dashboard preset cards and roster tables now regenerate from source, invalid placeholder gate copy was removed, favicon loading is local, preset task flow is semantic, and shared typography, contrast, borders, and status motion were tightened.
- **Microsite field redesign** — dashboard is now the canonical home reached from `index.html`, all generated pages share the dark field system, and a local reduced-motion-aware contour canvas replaces the old grain backdrop and striped preset-card texture.
- **App-agnostic context layer** — typed Markdown records, disposable catalog/link projections, offline FTS5 search with optional Ollama embeddings, profile-scoped packets, and conservative agent curation of human records are now available through `context.sh`; raw inputs remain immutable.

## Next

_None currently open — see Shipped above._

## Deliberately out of scope

- New agent roles for the two presets.
- Background schedulers or retry queues.
- Multi-provider MCP bridges.
- A hosted memory service or a second durable database.

## Working rule

Update this file when a roadmap item ships, is rejected, or changes scope. Keep
the durable source in Markdown; generated dashboards remain derived output.
