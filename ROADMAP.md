# Agentic Light Roadmap

Last reviewed: 2026-10-01

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
- **Template project lifecycle artifacts** (PR #26) — `Projects/_TEMPLATE/`
  includes `spec.md`, `tasks.md`, and resumable `Plan.md`; its README documents
  the provider-neutral flow from brief through verified tasks and
  execution/resume.

## Next

### White-label hardening

1. **Agent risk metadata** — implemented; PR under review. Every
   `agents/*.md` declares `risk: {read_only, destructive, idempotent,
   external_side_effects}`; `preset_audit.py` enforces all four flags and
   their consistency with `tools:`, `GOVERNANCE.md` renders them, and
   `new_agent.py` scaffolds them. `tools:` stays capability metadata; risk
   metadata describes blast radius. Move to Shipped after PR merge.
2. **Context/session promotion** — connect launcher results to typed session
   records, then let the curator link those records to projects, decisions,
   and learnings. Preserve weekly logs as append-only compatibility output.
3. **Delegation doctrine and audit trail** — document when work stays inline
   versus delegated, and add provider-neutral launcher audit events. Provider
   hooks may adapt to this trail but cannot be its source of truth.
4. **White-label acceptance fixture** — make `white_label_check.py` verify a
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

1. **"Recent Session Facts" shows the weekly template, not the latest
   week.** `context_packet.py` picks the last `brain/weekly_logs/**/*.md` by
   path string, and `Weekly_Note_Template.md` sorts after `2026/…`. Select
   only `YYYY/YYYY-Www.md` notes, by ISO week.
2. **The roadmap uses up the packet budget.** The 120-line default cap gives
   ~80 lines to `ROADMAP.md`, and context matches get cut off after about one
   entry. With no query, "matches" are the last 5 `brain/**/*.md` files by
   alphabetical path, not by recency or relevance. `pipeline/run.py` always
   passes an empty query, even though it has the task description.
3. **The packet has no semantic matches.** `CLAUDE.md` and
   `System_Config/README.md` promise "optional semantic matches", but the
   packet runs a case-insensitive substring scan and never calls
   `memory_search.py`'s FTS5/embedding index. Either wire it in or correct
   the docs.

**Agent roles never reach a model**

4. **No provider loads `agents/*.md`.** The pipeline's coder prompt is
   inline text, and `run_agent.py` never reads `agents/coder.md`. No provider
   discovers `agents/`: there is no `.claude/agents/`, `AGENTS.md` or
   `GEMINI.md` mirror. Role scope, capabilities, handoffs and risk are
   governance documentation only. White-label item 4's "regenerate provider
   mirrors" assumes mirrors exist, and they do not. The fix is the
   prompt-assembly contract from `AGENT_AGNOSTIC_REVIEW.md`, which was never
   built: role file + selected skills + packet + task, with fixed order and
   delimiters, injected by the launcher.
5. **Nothing enforces roster, capabilities or risk at launch.** The launcher
   never reads `agent-roster.json`. Launching an inactive role, or a role
   whose capabilities the provider lacks, is not a pre-launch failure.
6. **Role text contradicts the runtime.** `coder.md` says to run
   builds/tests and to stay "Bash 3.2-safe", which is stale since the Python
   port. The pipeline prompt and `run_agent.py` disallow Bash for the coder.
   The agent files also hardcode `Agentic_Light/…` paths, which leaks
   identity into white-label forks and assumes the parent-workspace cwd.

**Skill routing**

7. **The router does not rank by relevance.** A skill matches if any task
   word over 3 characters appears in its description. Matches are ordered
   alphabetically, and the 3-skill cap applies in that order.
   - "write a dbt model for orders" routes to two Figma skills, not
     `dbt-bigquery`.
   - "fix the login form accessibility" injects `figma-use`,
     `gcp-data-pipelines` and `react-doctor`, and the cap drops `wcag-audit`
     and `vpat-authoring`.
   - "add a CLI flag" routes to nothing.

   Rank before capping, for example by name/keyword weighting or reusing
   FTS5 bm25. Add a routing fixture with expected picks. Specialized forks
   are only partly protected by `skills-selected.json`.

**Curation**

8. **"Conservative" curation is not conservative.** A link counts as
   "high" with one title-token overlap plus two body-token overlaps. Tokens
   can be 3 characters, and the 13-word stoplist misses words like
   `for`/`use`. Verified: `--apply` wrote a link from "Use SQLite for the
   agent cache" to "Agent timeouts need a watchdog" into a human-authored
   record. Raise the threshold, make `author: human` records suggest-only,
   and add a precision fixture.
9. **Curation writes are messy.** `apply_links` appends a new
   `## Related Context` heading every time new links appear, instead of
   extending the existing one. Curation session files are named per second,
   so two runs in the same second overwrite each other, and the writes are
   not atomic.

**Provenance and immutability**

10. **Provenance is checked for presence, not validity.** `context_validate`
    requires a non-empty `source:` but never checks that the paths exist, and
    frontmatter `related:` links are not validated. Verified: records citing
    nonexistent raw files pass.
11. **Raw immutability during ingest is only a prompt instruction.**
    `daily_ingest.py` hashes the clip after the agent call, so an edited
    clip gets recorded instead of caught. Hash before the call, compare
    after, and fail the clip on a mismatch.

**Session records (feeds White-label item 2)**

12. **Session lines can't say what happened.** A line records only
    provider/role/exit/reason: no task, target repo, run id, branch, or
    pipeline log path. The packet's "Recent Session Facts" therefore can't
    describe past work. Only `pipeline/run.py` calls `log_session.py`;
    `daily_ingest.py` asks the LLM to append its own line, which is not
    deterministic and breaks the single-logger rule.

**Suggested order:** 1–3 and 11 (small, contained bugs), then 10, 8–9 and
7. Fold 12 into White-label item 2, and 4–6 into White-label item 3 (the
prompt-assembly contract is the precondition for item 4's acceptance
fixture).

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
- Background schedulers or retry queues.
- Multi-provider MCP bridges.
- A hosted memory service or a second durable database.

## Working rule

Update this file when a roadmap item ships, is rejected, or changes scope. Keep
the durable source in Markdown; generated dashboards remain derived output.
