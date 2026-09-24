# pipeline

Task runner: **Task Input → Code Patch (coder) → Gates (ESLint + Playwright,
or `gate-config.json` if present) → [Human Gate] → GitHub PR Creation
(`gh pr create`)**.

This pipeline operates against an **external target repo** you point it at —
not against Agentic_Light itself.

## Run it

```
python3 pipeline/run.py "<task description>" /path/to/target/repo
python3 pipeline/run.py --help   # print usage and exit
```

`target-repo-path` defaults to `$PWD` if omitted.

## Flow

0. **Pre-flight sensitive-file scan** — before the coder step, `run.py` scans
   the target repo for filenames matching `.env*`, `*.key`, `*.pem`,
   `id_rsa*` (including gitignored files — that's normally where a real
   `.env` lives). A match hard-stops the run (`FAILED: ...`) unless
   `AGENTIC_LIGHT_ALLOW_SENSITIVE_REPO=1` is set. **This is advisory
   filename screening, not a security boundary** — a check on filenames,
   not access control. It catches common accidental-secret-file patterns
   sitting in the target repo; it is not a guarantee the coder can't reach
   a secret some other way. The
   coder's `--allowedTools "Read,...Grep"` (`System_Config/run_agent.py`)
   still has no path restriction within its cwd once it launches — this
   check doesn't stop it reading a sensitive file that doesn't match these
   globs, a file created mid-run, or anything the coder can reach some other
   way. It only closes the "obviously-named credential file sitting in the
   target repo" gap.
0. **Gate-config validation** — before anything else runs (before the coder
   step), if `pipeline/gate-config.json` exists it's validated up front:
   valid JSON, and every entry either a known gate name (`eslint`,
   `playwright`, `axe` — read from `System_Config/gate-config.schema.json`'s
   enum, which must be readable) or a well-formed `custom` object (`script` required,
   `cwd`/`args` optional, no unknown fields). A malformed config prints a
   `FAILED: ...` message and exits 1 immediately — no coder run, no gates,
   no opaque mid-run failure under `set -u`. See "Gate configuration" below.
0. **Skill routing** — `System_Config/route_skill.py "<task description>"`
   runs before the coder step. Each matched skill's `SKILL.md` is prepended
   to the coder prompt (capped at the first `AGENTIC_LIGHT_SKILL_MATCH_LIMIT`
   matches, default 3 — the router's basic substring/keyword match can hit
   many skills on an ordinary task sentence; the cap keeps the prompt from
   ballooning). Override with `AGENTIC_LIGHT_SKILL_MATCH_LIMIT=<N>` (a
   non-negative integer; `0` injects no skill context); a malformed or unset
   value falls back to 3 with a stderr note. No match, or the router being
   unavailable, is a silent no-op.
0. **Context packet (opt-in)** — `System_Config/context_packet.py` (run from
   `$ROOT`, never from inside `$TARGET_REPO`) is prepended to the coder
   prompt, labeled `Resume context packet:`, only when
   `AGENTIC_LIGHT_CONTEXT_PACKET=1` is set, or automatically when
   `$TARGET_REPO` resolves (symlink-safe, `pwd -P` on both sides) to this
   workspace's own root — i.e. a run dogfooding the pipeline against
   Agentic Light itself. Default-off otherwise: this pipeline runs against
   an **external target repo** (see top of this file), and unconditionally
   injecting Agentic Light's own roadmap/session context into every coder
   prompt would leak unrelated-workspace context into someone else's repo.
   Fails silently, same as skill routing above — never blocks the coder
   step. Set `AGENTIC_LIGHT_CONTEXT_PROFILE=<name>` to use the profile-driven
   packet interface; without it, the legacy Agentic Light packet remains the
   compatibility path.
1. **Code Patch** — `run.py` itself creates the feature branch
   (`git checkout -b agentic-light/<run-id>`) in the target repo, then
   invokes the `coder` step via `System_Config/run_agent.py`, scoped to the
   target repo (cwd), with the task description (plus any routed skill
   guidance from step 0) as the prompt. The prompt tells the coder to
   implement the change only — it does not ask it to branch or commit,
   because the `claude` invocation in `run_agent.py` runs with
   `--disallowedTools "Bash,..."` and can't do either. Exactly one call to
   `System_Config/log_session.py` follows the coder process, logging
   provider/role/exit-status/reason (success, timeout, or refusal alike) —
   see "Session logging" below. A `64` exit only maps to `refused` when the
   resolved provider for that run was `ollama`; any other provider exiting
   64 is logged as a generic `exit`. `run.py` then stages the coder's
   changes (`git add -A`) and diffs `--cached` — staging first, not just
   `git diff HEAD`, so a brand-new file's full content is visible, not just
   its filename. Before committing, it scans the added lines of that staged
   diff for likely secrets with `config.py`'s `looks_like_secret` (the same
   pattern set `System_Config/healthcheck.py`'s Config Security Scan uses —
   one regex definition, not two); a hit hard-stops the run (`git reset` +
   `FAILED: ...`, no commit, no PR). This reset is safe because step 1 also
   asserts, before creating the feature branch, that `$TARGET_REPO`'s index
   is empty at the start of the run — the pipeline's contract is "coder
   starts on a clean index, pipeline commits only what it added," and a
   dirty index at launch is a hard `FAILED: ...`, not silently overridden.
   A coder run that produces no changes also fails this step (no commit,
   no PR).
   Swappable for testing: set `PIPELINE_CODER_CMD` to any command; if set,
   `run.py` execs `$PIPELINE_CODER_CMD "<task>" "<target-repo>"` instead of
   the live agent call — no agent CLI round-trip needed to test the rest of
   the pipeline.
2. **Gates** — `lib/eslint_gate.py <target-repo>` and
   `lib/playwright_gate.py <target-repo>`, run in order, unless
   `pipeline/gate-config.json` exists (see "Gate configuration" below).
   `lib/axe_gate.py <target-repo>` (the accessibility gate) runs only when
   listed in `gate-config.json` — it is not part of the default pair. See
   "Accessibility (axe) gate" below.
3. **Human Gate** (`lib/human_gate.py "<summary>"`) — renders the already-
   committed diff + gate summary, blocks on interactive `[y/N]`. Swappable
   for testing the same way as the coder step: set `PIPELINE_HUMAN_GATE_CMD`
   to any command taking a summary string as its only argument; `run.py`
   calls that instead of `lib/human_gate.py` — but **only** when
   `AGENTIC_LIGHT_TEST_MODE=1` is also set. `PIPELINE_HUMAN_GATE_CMD` is
   test-only: it exists so `test_pipeline.py` can drive the approved path
   without faking a TTY, not as a way to skip human approval on a real run.
   Setting it alone, without the guard flag, is ignored (with a stderr
   warning) and the real interactive gate still runs.
4. **PR creation** (`lib/pr_create.py <target-repo> --confirmed`) — only
   called by `run.py`, only after explicit approval.

`agents/qa.md` and `agents/eng-manager.md` are not part of this chain —
they're orchestrator-dispatched (Agent-tool) roles for optional gap-review,
not steps `run.py` invokes. See `agents/README.md`.

## Gate configuration

If `pipeline/gate-config.json` exists (see `System_Config/gate-config.schema.json`
/ `.example.json`), its ordered `gates` array replaces the default
eslint+playwright pair — entries are `"eslint"`, `"playwright"`, `"axe"`, or a
`custom` object (`{"name": "custom", "script": "...", "cwd": "...",
"args": [...]}`). `script`/`cwd` are resolved relative to the **target
repo**, matching how `eslint_gate.py`/`playwright_gate.py` already `cd`
into it. Parsed with `python3` (stdlib `json`); if the config file exists
but `python3` is not found, `run.py` hard-fails rather than silently
falling back — running the wrong gate set would defeat the "100% pass
before a human sees the diff" contract. No config file (an un-specialized
fork) keeps the original hardcoded eslint+playwright behavior.

A custom gate's resolved `script` and `cwd` are contained to the target
repo: both are resolved with `cd ... && pwd -P` (this project's existing
path-resolution idiom, no `realpath` dependency) and rejected with a clear
`FAILED: ...` if the resolved path doesn't fall under the target repo.
`pipeline/gate-config.json` is read from the **Agentic Light workspace**
(`$PIPELINE_DIR/gate-config.json`), not from the target repo's own tree —
so this containment check is what stops a traversal path like `"script":
"../../evil.sh"`, or a legitimate-looking relative path resolving through a
symlink, from reaching outside `$TARGET_REPO`; without it, a
malicious/compromised fork's `gate-config.json` could point a gate
anywhere on disk. The script path is additionally rejected outright if its
final component is a symlink (not just if its parent directory resolves
outside the target repo) — resolving only the parent directory would let a
symlinked script pass containment while still executing whatever it
points at.

Before any of this runs, the file is validated in full (see "Flow" step 0
above) — an unknown gate name or a malformed `custom` object fails the run
immediately with a clear `FAILED: ...` message, rather than surfacing
partway through gate execution. An empty `"gates": []` array is valid (no
gates configured, not malformed) and simply runs zero gates.

## Accessibility (axe) gate

`lib/axe_gate.py` (gate name `axe`; the `wcag-harness` preset sets
`["playwright", "axe"]`) checks the target repo, in this order:

1. `package.json` `scripts["test:a11y"]`, then `scripts.a11y` → runs
   `npm run <key>`. Exit 0 → `PASS`; non-zero → `FAIL`, propagated, and
   `run.py` hard-stops before the human gate.
2. Otherwise `@axe-core/cli`, `@axe-core/playwright`, or `pa11y` in
   `dependencies`/`devDependencies` → `WARN`, exit 0, **nothing runs**. The
   CLI tools need a URL to scan, and `@axe-core/playwright` is a library
   called from the repo's own specs (which the `playwright` gate already
   runs). The gate never guesses a URL or starts a server; the WARN tells you
   to add a `test:a11y` script that does.
3. Neither → `WARN`, exit 0, stating plainly that no automated accessibility
   check ran and pointing to `skills/wcag-audit/references/running-axe.md`
   for the manual path.

No browser driver, no dependency added to this repo. A passing axe gate is
one machine-detectable pass (roughly a third of WCAG AA failures), not a
conformance claim.

## VPAT draft lint (vpat-lint) gate

`lib/vpat_lint_gate.py` (gate name `vpat-lint`; the `wcag-harness` preset
sets `["playwright", "axe", "vpat-lint"]`) checks the target repo's VPAT
draft — `accessibility/vpat-draft.json` by default, `VPAT_DRAFT_PATH`
overrides (repo-root-relative) — against 6 deterministic, structural rules:
ITI terms only, one rating per criterion, no `Supports`/defect
contradiction, rating-aware `What:`/`Who:`/`Where:`/`Evidence:`/`Why:`
markers, no Markdown leak in remarks/limitations, and automated-only
evidence capped below `Supports`/`Does Not Support`. Full rule list:
`skills/vpat-authoring/references/lint-rules.md`.

- No draft file at the resolved path → `WARN`, exit 0, points to
  `skills/vpat-authoring/SKILL.md`. Skipping.
- Draft present and passes all 6 rules → `PASS`, exit 0. Proves structure
  and ITI-discipline compliance only — not semantic accuracy; human
  accessibility review is still required before the draft becomes a
  customer-facing VPAT.
- Draft present and violates any rule → `FAIL`, propagated, `run.py`
  hard-stops before the human gate.
- Draft present but `python3` unavailable → `FAIL` (hard stop, not a WARN —
  a missing interpreter when a draft actually exists to check is a real
  gap, not an absent-tool no-op).

## Session logging

After the coder step completes (success, watchdog timeout, or an Ollama
write-workflow refusal), `run.py` calls `System_Config/log_session.py`
exactly once with the resolved provider, `--role coder`, the exit status,
and a reason (`exit`/`timeout`/`signal`/`refused`). This is the sole
launcher-level call site — `run_agent()` itself is not instrumented, since
it's also called once per clip by `daily_ingest.py`, which already logs its
own line per clip.

## Contract: 100% pass before the patch is even shown to a human

Every gate runs and must pass (or be skipped, see below) **before** the diff
is rendered at the Human Gate. The patch is never presented for human review
if a gate actually failed.

## Concurrency lock

`run.py` takes an `acquire_lock` (see `System_Config/config.py`) keyed by a
checksum of `target-repo-path` before doing anything else. A second run
against the *same* target repo while one is already in flight is refused
outright (exit 1) — without this, two concurrent runs could interleave the
coder agent's git operations (branch creation, commits) in the same working
tree and corrupt it. Runs against different target repos are unaffected. A
lock older than 2h is treated as abandoned (crashed run) and reclaimed.

## Halt-on-failure guarantee

A failing gate (ESLint, Playwright, axe, or custom) makes `run.py` print `FAILED: ...`,
write it to the run log, and `exit 1` immediately. No later step runs — in
particular `pr_create.py` is never invoked on any failure path. Every step's
outcome is visible in `pipeline/logs/<run-id>.log` (the whole run is teed to
it).

## WARN-vs-hard-stop: missing config vs. failing run

- **No ESLint/Playwright/a11y setup found at all** in the target repo (no
  `scripts.lint`/`.eslintrc*`/`eslint.config.*`, no
  `scripts["test:e2e"|"e2e"]`/`playwright.config.*`, no
  `scripts["test:a11y"|"a11y"]`) → the gate prints
  `WARN`, exits 0, and the pipeline continues. Keeps the pipeline usable
  against repos that don't use ESLint/Playwright.
- **A config/script exists and the actual run fails** (non-zero exit) → the
  gate prints `FAIL`, propagates the non-zero exit, and `run.py` hard-stops.

## Human Gate exit codes

`lib/human_gate.py` returns a 3-way result so `run.py` can distinguish
"declined" from "no one was there to ask":

- `0` — approved (`y`/`Y` typed at an interactive TTY)
- `1` — declined (anything else typed at an interactive TTY)
- `2` — pending (non-interactive session, e.g. no TTY on stdin) — the report
  is printed but the gate **never auto-approves**; `run.py` exits 2 without
  creating a PR

## pr_create.py guard

`lib/pr_create.py` requires a literal `--confirmed` flag as its second
argument so a plain `pr_create.py <target-repo>` call — a stray invocation
from a script, a shell-history recall, someone poking at `lib/` directly —
doesn't skip the human gate by accident. This is an accident guard for a
single-user interactive tool, not a security boundary: anyone who can run
the script at all can also type `--confirmed`. It also checks `gh` is
installed and `gh auth status` before calling `gh pr create --draft`.

## Tests

`python3 pipeline/test_pipeline.py` — fixture coverage: a normal pass through
`run.py` to `gh pr create` (via `PIPELINE_CODER_CMD` +
`PIPELINE_HUMAN_GATE_CMD` overrides and a stubbed `gh`, asserting the gate
summary shows both the tracked and untracked changes that actually get
committed), a coder run that produces no changes, an ESLint gate failure, a
Playwright gate failure, no-TTY pending behavior, a declined human-gate
response (exercised directly against `lib/human_gate.py` via a pty, since a
declined *interactive* response needs a real TTY), a direct
`lib/pr_create.py` call without `--confirmed`, and three axe-gate runs
(no a11y tooling → WARN+skip and continue; failing `test:a11y` → hard stop
before the human gate; passing `test:a11y` → pass). The axe fixtures write a
temporary `pipeline/gate-config.json` (`["axe"]`), backing up and restoring
any existing one on exit. Every failure/pending/decline
case asserts the stubbed `gh` never received a `pr create` call. A pair of
fixtures drives the real `System_Config/run_agent.py` path (a fake
`claude` binary on `$FAKE_HOME/.local/bin`, `AGENTIC_LIGHT_PROVIDERS`/
`_PRIORITY` pinned to `claude`) — `PIPELINE_CODER_CMD` bypasses `$PROMPT`
entirely, so the context-packet opt-in wiring above can only be exercised
this way — asserting the packet is absent from the coder prompt by default
and present only with `AGENTIC_LIGHT_CONTEXT_PACKET=1`. A final seven
fixtures (10a-10g) cover the `vpat-lint` gate via a temporary
`pipeline/gate-config.json` (`["vpat-lint"]`, reusing the axe fixtures'
backup/restore): no draft → WARN+skip and continue; a compliant draft →
PASS and continue; four distinct rule violations (`iti_terms_only`,
`no_supports_contradiction`, `automated_evidence_cap`, `structured_remarks`)
each → hard stop before the human gate, with the stubbed `gh` never
receiving a `pr create` call; and a `Supports` row using legitimate
compliant language containing "does not" → PASS (regression test proving
the narrowed `no_supports_contradiction` word list doesn't false-positive
on genuine compliant remarks).

`python3 System_Config/test_context_packet.py` — fixture coverage for
`System_Config/context_packet.py` directly: a tiny
`AGENTIC_LIGHT_CONTEXT_MAX_LINES`/`AGENTIC_LIGHT_CONTEXT_MAX_BYTES` budget
against a synthetic `ROADMAP.md` with a dense multi-byte (em dash) first
line is respected byte-for-byte (not character-for-byte — see
`context_packet.py`'s header comment), and the default budget still
contains every provenance header (`# Agentic Light Context Packet`,
`Generated:`, `## Roadmap`, `## Active Preset`, `## Recent Session Facts`).

## Files

| File | Purpose |
|---|---|
| `run.py` | Main orchestrator, flow above |
| `gate-config.json` | Optional; see "Gate configuration" above |
| `lib/eslint_gate.py` | ESLint gate — WARN+skip or hard-stop |
| `lib/playwright_gate.py` | Playwright E2E gate — WARN+skip or hard-stop |
| `lib/axe_gate.py` | Accessibility gate — runs `test:a11y`/`a11y`, else WARN+skip |
| `lib/vpat_lint_gate.py` | VPAT draft lint gate — 6 rules, else WARN+skip if no draft |
| `lib/human_gate.py` | Renders summary/diff, blocks on `[y/N]` |
| `lib/pr_create.py` | Guarded `gh pr create --draft` wrapper |
| `test_pipeline.py` | Fixture tests — see Tests above |
| `logs/` | One timestamped log per run (`<run-id>.log`) |
