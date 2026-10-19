# Agentic Light Roadmap

Last reviewed: 2026-10-19

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
- **Private session continuity** — explicit Claude, Codex, Antigravity JSONL, and Web Clipper sources can be indexed locally by MemPalace; generated hash-only records stay under ignored `brain/context/`, while weekly notes link separately to AI-session and gathered-context archives. Friday adds a count-based overview, and bootstrap can install the daily, Monday, and Friday cadence.
- **Template project lifecycle artifacts** (PR #26) — `Projects/_TEMPLATE/`
  includes `spec.md`, `tasks.md`, and resumable `Plan.md`; its README documents
  the provider-neutral flow from brief through verified tasks and
  execution/resume.
- **Agent risk metadata** — every `agents/*.md` declares
  `risk: {read_only, destructive, idempotent, external_side_effects}`;
  `preset_audit.py` enforces it, `GOVERNANCE.md` renders it, and
  `new_agent.py` scaffolds it.

## Next

### White-label hardening

1. **Context/session promotion — shipped.** Launcher records are typed,
   searchable records with task, target repository, run ID, branch, and
   pipeline-log provenance; the append-only weekly line links to the record.
   The pipeline then runs conservative curation so high-confidence project,
   decision, and learning links are applied and weaker links remain reviewable.
2. **Delegation doctrine and audit trail** — document when work stays inline
   versus delegated, and add provider-neutral launcher audit events. Provider
   hooks may adapt to this trail but cannot be its source of truth.
3. **White-label acceptance fixture** — make `white_label_check.py` verify a
   fork can specialize, run its selected agents and gates, build a context
   packet, regenerate provider mirrors, and contain no Agentic Light identity.

### Roster decision

- **White-label core:** `architect`, `coder`, `eng-manager`, `qa`, `curator`.
- **Design and WCAG overlays:** add `creative-director` plus the relevant
  skills and gates.
- **Handoffs:** `architect → coder → qa → eng-manager → orchestrator`.
  `curator` runs alongside the lifecycle; `creative-director → qa` applies
  only to visual/accessibility presets.
- Keep `archivist` and `rally` excluded. Add no new roles until a concrete
  workflow cannot fit the six-role contract.

### Context and agent audit (2026-10-01)

Each item below was checked by running the code: a fixture or a direct run
reproduces the gap, and it was not inferred from docs alone. Each is a place
where shipped docs promise more than the code delivers.

**Context packet: silently wrong output (small fixes; do first)**

1. **Latest weekly session facts — shipped.** `context_packet.py` now selects
   only dated `YYYY/YYYY-Www.md` notes and chooses the latest ISO week;
   templates and master notes are excluded.
2. **Packet budget and task retrieval — shipped.** The default packet reserves
   space for context by limiting the roadmap excerpt to 30 lines, and
   `pipeline/run.py` passes the task description as the retrieval query.
   The no-query fallback remains alphabetical and should be reconsidered only
   if direct CLI packet use becomes a primary workflow.
3. **Packet retrieval contract — clarified.** The packet uses deterministic
   keyword matches; the separate `memory_search.py` command provides local
   FTS5 and optional Ollama scoring. Documentation no longer promises packet
   semantics that are not implemented. Wiring indexed retrieval into packets
   remains a future enhancement, not a shipped claim.

**Agent roles never reach a model**

4. **Coder prompt assembly — shipped; other roles remain manual.** The
   launcher strips `agents/coder.md` metadata and injects its role body,
   selected skills, optional packet, and task in a fixed delimiter contract.
   The pipeline does not launch architect, QA, or manager roles, so their
   contracts and handoffs remain orchestrator-managed. Provider mirrors are
   intentionally absent; explicit prompt context is canonical.
5. **Coder roster enforcement — shipped; multi-role enforcement remains.**
   The launcher reads `agent-roster.json` before branching and rejects an
   inactive coder or capabilities unavailable to its read/write runtime.
   Architect, QA, and manager roles remain manually launched, so their
   pre-launch enforcement belongs with a future multi-role launcher.
6. **Role text cleanup — partly shipped.** `coder.md` now matches the
   sandboxed runtime and refers only to the target repository. The remaining
   manually-dispatched role files still contain `Agentic_Light/…` paths and
   need relocation-neutral wording before a provider-neutral multi-role
   launcher exists.

**Skill routing**

7. **Skill routing — shipped.** `route_skill.py` now ranks name and
   description matches by rarity and task relevance before the three-skill
   cap. Its fixture proves DBT and accessibility domain skills beat
   alphabetically earlier generic skills. A generic CLI task still produces
   no match because this harness deliberately has no CLI-specific skill;
   selection remains constrained by `skills-selected.json` in specialized
   forks.

**Curation**

8. **Conservative curation — shipped.** Automatic curation now requires at
   least two title-token overlaps and four total overlaps, and it treats
   `author: human` records as suggestion-only. Fixtures cover both a human
   record and a weak agent-authored match.
9. **Curation write discipline — shipped.** `apply_links` extends its
   existing `## Related Context` section, curation session records use
   microsecond timestamps, and both source and audit writes are atomic.

**Provenance and immutability**

10. **Provenance validation — shipped.** `context_validate` now rejects
    missing and out-of-workspace `source:` paths and unresolved frontmatter
    `related:` targets.
11. **Raw immutability during ingest — shipped.** `daily_ingest.py` now
    records the pre-call hash, compares it after the agent returns, and
    marks any changed clip as a failed attempt instead of certifying it.

**Session records (feeds White-label item 2)**

12. **Session records — shipped.**
    `pipeline/run.py` now gives `log_session.py` the task, target repo, run
    ID, branch, and log path. It writes a schema-valid typed record and the
    weekly line links to it, so packets can retrieve meaningful launch facts.
    `daily_ingest.py` uses that same logger for every clip and forbids the
    model from editing weekly logs.

**Suggested order:** let curation link typed records to durable context. Fold 4–6 into
White-label item 2; the prompt-assembly contract is the precondition for the
white-label acceptance fixture.

### Acceptance bar

- A fresh fork can complete the lifecycle without Claude-specific behavior.
- Every active role has declared capability and risk metadata.
- A completed launcher run produces a retrievable, provenance-linked session
  record without mutating raw inputs.
- White-label audit passes after identity replacement and regeneration.
- A launcher run injects the selected role's contract, and the packet it
  injects reflects the latest session and the task at hand.

## Deliberately out of scope

- New agent roles for the two presets.
- Retry queues or any background scheduler beyond the explicit private context cadence.
- Multi-provider MCP bridges.
- A hosted memory service or a second durable database.

## Working rule

Update this file when a roadmap item ships, is rejected, or changes scope. Keep
the durable source in Markdown; generated dashboards remain derived output.
