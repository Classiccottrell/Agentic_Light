# App-Agnostic Context Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Make the harness context layer a portable Markdown knowledge system that humans can write, agents can curate and cross-link, and future agents can retrieve with provenance.

**Architecture:** Markdown remains canonical. A stdlib cataloger validates typed records and emits metadata/backlink projections; SQLite provides FTS5 and optional embeddings; a profile-driven packet builder assembles bounded excerpts. Agent curation defaults to a reviewable proposal and only applies validated links when explicitly requested.

**Tech Stack:** Bash, Python 3 standard library, SQLite FTS5, existing local Ollama embedding endpoint, Markdown, JSON profiles.

**Spec:** docs/superpowers/specs/2026-09-23-app-agnostic-context-layer-design.md

## Global Constraints

- Preserve brain/raw/ immutability.
- Preserve existing wiki and weekly-log formats during migration.
- Keep Markdown as the durable source of truth; all indexes must be rebuildable.
- Keep external-repository context injection default-off.
- Do not add hosted services or runtime dependencies.
- Never silently rewrite or delete human-authored prose.
- Keep packet output bounded by explicit byte and line limits.

## Review Focus

- Broken wikilinks and duplicate record IDs must fail validation; covered by Task 1.
- Unicode content must remain within packet byte limits; covered by Task 3.
- Missing Ollama must still leave lexical search usable; covered by Task 2.
- Low-confidence AI links must not apply silently; covered by Task 4.
- An unrelated app profile must not read Agentic Light files; covered by Task 3.

## File map

- brain/records/README.md: human and agent record contract.
- System_Config/context_validate.py: frontmatter, body-section, provenance, and link validation.
- System_Config/context_catalog.py: source scan and generated catalog/backlink projections.
- System_Config/memory_index.py: index all catalog documents, not only wiki pages.
- System_Config/memory_search.py: hybrid lexical/semantic search with excerpts.
- System_Config/context_packet.sh: compatibility wrapper around profile-driven retrieval.
- System_Config/context_profiles/*.json: app-specific context boundaries.
- System_Config/context_curate.py: candidate-link proposal and validated apply flow.
- System_Config/context.sh: context packet, validate, catalog, and curate dispatcher.
- System_Config/test_context_*.sh: fixture tests for each boundary.
- brain/index/: generated cache location, ignored by Git.

### Task 1: Record schema, validator, and catalog

**Files:**
- Create: brain/records/README.md
- Create: System_Config/context_validate.py
- Create: System_Config/context_catalog.py
- Create: System_Config/test_context_catalog.sh
- Modify: .gitignore
- Modify: System_Config/README.md

**Interfaces:**
- context_validate.py validate PATH [--root ROOT] exits 0 for valid records and 1 for invalid records; --json emits machine-readable findings.
- context_catalog.py build --root ROOT --out-dir ROOT/brain/index writes catalog.json and links.json atomically.
- Catalog entries expose id, path, type, title, scope, projects, tags, updated, and a short plain-text excerpt.

- [ ] Step 1: Write fixture tests for valid records, duplicate IDs, broken links, missing provenance, and immutable raw exclusion.
- [ ] Step 2: Run bash System_Config/test_context_catalog.sh and confirm it fails before implementation.
- [ ] Step 3: Implement stdlib-only frontmatter parsing, record validation, link resolution, and atomic catalog writes.
- [ ] Step 4: Add ignored generated-cache paths and document the human/agent record workflow.
- [ ] Step 5: Run bash System_Config/test_context_catalog.sh and commit:
  git add brain/records System_Config/context_validate.py System_Config/context_catalog.py System_Config/test_context_catalog.sh .gitignore System_Config/README.md
  git commit -m 'feat: add typed context records and catalog'

### Task 2: Unified lexical and semantic search

**Files:**
- Modify: System_Config/memory_index.py
- Modify: System_Config/memory_search.py
- Create: System_Config/test_context_search.sh
- Modify: brain/CLAUDE.md
- Modify: brain/README.md

**Interfaces:**
- memory_index.py [--root ROOT] [--force] indexes catalog documents into ROOT/brain/index/memory.sqlite3.
- memory_search.py QUERY [--root ROOT] [--top N] [--json] returns path, title, type, score, and excerpt.
- Search uses SQLite FTS5 first, merges embeddings when available, and falls back to FTS without Ollama.

- [ ] Step 1: Extend the self-test fixture with a project, decision, learning, wiki page, and weekly log. Assert that a query returns the learning excerpt and type, and that missing Ollama does not make lexical search fail.
- [ ] Step 2: Run bash System_Config/test_context_search.sh and confirm failure before implementation.
- [ ] Step 3: Add FTS5 document storage and catalog-driven indexing while retaining existing embedding dimension/model checks.
- [ ] Step 4: Add bounded excerpt generation and JSON output without changing plain-path output unless --json is requested.
- [ ] Step 5: Run python3 System_Config/memory_index.py --self-test, python3 System_Config/memory_search.py --self-test, and bash System_Config/test_context_search.sh. Commit:
  git add System_Config/memory_index.py System_Config/memory_search.py System_Config/test_context_search.sh brain/CLAUDE.md brain/README.md
  git commit -m 'feat: search the unified context catalog'

### Task 3: Profile-driven context packets

**Files:**
- Create: System_Config/context_profiles/agentic-light.json
- Create: System_Config/context_profiles/example-app.json
- Modify: System_Config/context_packet.sh
- Create: System_Config/context.sh
- Create: System_Config/test_context_packet_profiles.sh
- Modify: pipeline/run.sh
- Modify: pipeline/README.md

**Interfaces:**
- context.sh packet --profile PROFILE --query QUERY --top N --max-bytes BYTES emits a labeled packet.
- context.sh validate and context.sh catalog dispatch the corresponding Python commands.
- Existing context_packet.sh [query] remains a compatibility path using the Agentic Light profile.
- pipeline/run.sh retains explicit opt-in and workspace-root matching.

- [ ] Step 1: Write fixtures for Agentic Light and an unrelated app profile. Assert that the unrelated profile cannot read ROADMAP.md or brain/ outside its configured context_root, and that multibyte output never exceeds --max-bytes.
- [ ] Step 2: Run bash System_Config/test_context_packet_profiles.sh and confirm failure before implementation.
- [ ] Step 3: Implement JSON profile loading, scope filtering, query retrieval, provenance labels, and byte-safe truncation.
- [ ] Step 4: Preserve external-repository isolation and the compatibility command.
- [ ] Step 5: Run bash System_Config/test_context_packet_profiles.sh and bash System_Config/test_context_packet.sh. Commit:
  git add System_Config/context_profiles System_Config/context.sh System_Config/context_packet.sh System_Config/test_context_packet_profiles.sh pipeline/run.sh pipeline/README.md
  git commit -m 'feat: make context packets profile driven'

### Task 4: Agent curation and link application

**Files:**
- Create: System_Config/context_curate.py
- Create: System_Config/test_context_curate.sh
- Modify: System_Config/context.sh
- Modify: brain/CLAUDE.md
- Modify: System_Config/daily_ingest.sh

**Interfaces:**
- context.sh curate FILE --suggest writes a proposal without changing the source.
- context.sh curate FILE --apply applies only validated high-confidence relations and links.
- context.sh curate FILE --review lists medium/low-confidence candidates and unresolved targets.
- Curation records accepted/rejected candidates in a session record.

- [ ] Step 1: Write fixtures proving suggest mode is non-mutating, apply mode adds only links, low-confidence candidates remain unapplied, and raw files stay unchanged.
- [ ] Step 2: Run bash System_Config/test_context_curate.sh and confirm failure before implementation.
- [ ] Step 3: Implement candidate collection from FTS/semantic search, exact-ID confidence handling, proposal output, and validated apply patches.
- [ ] Step 4: Add a curation session record with agent identity, source file, accepted links, rejected links, and timestamp.
- [ ] Step 5: Change daily_ingest.sh to use apply mode only for immutable raw inputs and keep its existing idempotency check.
- [ ] Step 6: Run bash System_Config/test_context_curate.sh, bash System_Config/test_context_catalog.sh, and bash System_Config/test_context_search.sh. Commit:
  git add System_Config/context_curate.py System_Config/test_context_curate.sh System_Config/context.sh brain/CLAUDE.md System_Config/daily_ingest.sh
  git commit -m 'feat: curate and cross-link human context records'

### Task 5: Evaluation, migration, and documentation closeout

**Files:**
- Create: System_Config/test_context_layer.sh
- Modify: ROADMAP.md
- Modify: README.md
- Modify: System_Config/README.md
- Modify: brain/README.md
- Modify: brain/CLAUDE.md

- [ ] Step 1: Build one end-to-end fixture containing a human learning, an agent session, a project, a decision, a wiki page, and an immutable raw source.
- [ ] Step 2: Assert record → validate → catalog → curate suggestion → apply approved links → search excerpt → bounded packet.
- [ ] Step 3: Assert broken link, duplicate ID, stale embedding dimension, unavailable Ollama, unrelated profile, oversized Unicode packet, and raw mutation failures.
- [ ] Step 4: Backfill only high-value existing records and leave the rest of the wiki/weekly logs compatible.
- [ ] Step 5: Update roadmap and governing documentation with shipped interfaces.
- [ ] Step 6: Run bash System_Config/test_context_layer.sh, bash System_Config/test_context_packet.sh, python3 System_Config/preset_audit.py, and bash System_Config/healthcheck.sh. Commit:
  git add System_Config brain README.md ROADMAP.md
  git commit -m 'test and document the context layer'

## Plan self-review

- Spec coverage: records, linking, curation, catalog, hybrid search, profiles, bounded packets, safety, rollout, and acceptance criteria map to tasks.
- Placeholder scan: no incomplete implementation step remains.
- Type consistency: catalog fields and CLI names are defined once and reused.
- Review focus: all five high-risk input classes have explicit fixture ownership.
