# Agentic Light Roadmap

Last reviewed: 2026-09-22

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
