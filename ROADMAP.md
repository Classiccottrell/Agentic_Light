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

## Progress

- Checked-in roadmap added.
- Preset contract audit added to `healthcheck.sh`.
- Bounded context packet added as a standalone, provider-neutral command.
- White-label validator added as a non-destructive audit command.

## Next

1. **Preset execution hardening** — add explicit capabilities and handoff scope for `design-harness` and `wcag-harness`; contract validation now exists.
2. **White-label hardening** — validator exists; add preset-specific fixtures and generated-output checks.
3. **Context integration** — the bounded packet exists; wire it into the appropriate launcher path without injecting it into unrelated target repositories.
4. **Context evaluation** — add one fixture proving the packet stays under its line/byte budget and preserves provenance.

## Deliberately out of scope

- New agent roles for the two presets.
- Background schedulers or retry queues.
- Multi-provider MCP bridges.
- A hosted memory service or a second durable database.

## Working rule

Update this file when a roadmap item ships, is rejected, or changes scope. Keep
the durable source in Markdown; generated dashboards remain derived output.
