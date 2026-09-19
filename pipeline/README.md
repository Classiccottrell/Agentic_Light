# pipeline

Task runner: **Task Input → Code Patch (coder) → Gates (ESLint + Playwright,
or `gate-config.json` if present) → [Human Gate] → GitHub PR Creation
(`gh pr create`)**.

This pipeline operates against an **external target repo** you point it at —
not against Agentic_Light itself.

## Run it

```
bash pipeline/run.sh "<task description>" /path/to/target/repo
```

`target-repo-path` defaults to `$PWD` if omitted.

## Flow

0. **Gate-config validation** — before anything else runs (before the coder
   step), if `pipeline/gate-config.json` exists it's validated up front:
   valid JSON, and every entry either a known gate name (`eslint`,
   `playwright`) or a well-formed `custom` object (`script` required,
   `cwd`/`args` optional, no unknown fields). A malformed config prints a
   `FAILED: ...` message and exits 1 immediately — no coder run, no gates,
   no opaque mid-run failure under `set -u`. See "Gate configuration" below.
0. **Skill routing** — `System_Config/route_skill.sh "<task description>"`
   runs before the coder step. Each matched skill's `SKILL.md` is prepended
   to the coder prompt (capped at the first 3 matches — the router's basic
   substring/keyword match can hit many skills on an ordinary task
   sentence; the cap keeps the prompt from ballooning). No match, or the
   router being unavailable, is a silent no-op.
1. **Code Patch** — `run.sh` itself creates the feature branch
   (`git checkout -b agentic-light/<run-id>`) in the target repo, then
   invokes the `coder` step via `System_Config/run_agent.sh`, scoped to the
   target repo (cwd), with the task description (plus any routed skill
   guidance from step 0) as the prompt. The prompt tells the coder to
   implement the change only — it does not ask it to branch or commit,
   because the `claude` invocation in `run_agent.sh` runs with
   `--disallowedTools "Bash,..."` and can't do either. Exactly one call to
   `System_Config/log_session.sh` follows the coder process, logging
   provider/role/exit-status/reason (success, timeout, or refusal alike) —
   see "Session logging" below. A `64` exit only maps to `refused` when the
   resolved provider for that run was `ollama`; any other provider exiting
   64 is logged as a generic `exit`. `run.sh` then captures the coder's
   diff (`git diff HEAD` + any new untracked files) and commits it itself;
   a coder run that produces no changes fails this step (no commit, no PR).
   Swappable for testing: set `PIPELINE_CODER_CMD` to any command; if set,
   `run.sh` execs `$PIPELINE_CODER_CMD "<task>" "<target-repo>"` instead of
   the live agent call — no agent CLI round-trip needed to test the rest of
   the pipeline.
2. **Gates** — `lib/eslint_gate.sh <target-repo>` and
   `lib/playwright_gate.sh <target-repo>`, run in order, unless
   `pipeline/gate-config.json` exists (see "Gate configuration" below).
3. **Human Gate** (`lib/human_gate.sh "<summary>"`) — renders the already-
   committed diff + gate summary, blocks on interactive `[y/N]`. Swappable
   for testing the same way as the coder step: set `PIPELINE_HUMAN_GATE_CMD`
   to any command taking a summary string as its only argument; `run.sh`
   calls that instead of `lib/human_gate.sh`.
4. **PR creation** (`lib/pr_create.sh <target-repo> --confirmed`) — only
   called by `run.sh`, only after explicit approval.

`agents/qa.md` and `agents/eng-manager.md` are not part of this chain —
they're orchestrator-dispatched (Agent-tool) roles for optional gap-review,
not steps `run.sh` invokes. See `agents/README.md`.

## Gate configuration

If `pipeline/gate-config.json` exists (see `System_Config/gate-config.schema.json`
/ `.example.json`), its ordered `gates` array replaces the default
eslint+playwright pair — entries are `"eslint"`, `"playwright"`, or a
`custom` object (`{"name": "custom", "script": "...", "cwd": "...",
"args": [...]}`). `script`/`cwd` are resolved relative to the **target
repo**, matching how `eslint_gate.sh`/`playwright_gate.sh` already `cd`
into it. Parsed with `python3` (stdlib `json`); if the config file exists
but `python3` is not found, `run.sh` hard-fails rather than silently
falling back — running the wrong gate set would defeat the "100% pass
before a human sees the diff" contract. No config file (an un-specialized
fork) keeps the original hardcoded eslint+playwright behavior.

Before any of this runs, the file is validated in full (see "Flow" step 0
above) — an unknown gate name or a malformed `custom` object fails the run
immediately with a clear `FAILED: ...` message, rather than surfacing
partway through gate execution. An empty `"gates": []` array is valid (no
gates configured, not malformed) and simply runs zero gates.

## Session logging

After the coder step completes (success, watchdog timeout, or an Ollama
write-workflow refusal), `run.sh` calls `System_Config/log_session.sh`
exactly once with the resolved provider, `--role coder`, the exit status,
and a reason (`exit`/`timeout`/`signal`/`refused`). This is the sole
launcher-level call site — `run_agent()` itself is not instrumented, since
it's also called once per clip by `daily_ingest.sh`, which already logs its
own line per clip.

## Contract: 100% pass before the patch is even shown to a human

Every gate runs and must pass (or be skipped, see below) **before** the diff
is rendered at the Human Gate. The patch is never presented for human review
if a gate actually failed.

## Concurrency lock

`run.sh` takes an `acquire_lock` (see `System_Config/config.sh`) keyed by a
checksum of `target-repo-path` before doing anything else. A second run
against the *same* target repo while one is already in flight is refused
outright (exit 1) — without this, two concurrent runs could interleave the
coder agent's git operations (branch creation, commits) in the same working
tree and corrupt it. Runs against different target repos are unaffected. A
lock older than 2h is treated as abandoned (crashed run) and reclaimed.

## Halt-on-failure guarantee

A failing gate (ESLint or Playwright) makes `run.sh` print `FAILED: ...`,
write it to the run log, and `exit 1` immediately. No later step runs — in
particular `pr_create.sh` is never invoked on any failure path. Every step's
outcome is visible in `pipeline/logs/<run-id>.log` (the whole run is teed to
it).

## WARN-vs-hard-stop: missing config vs. failing run

- **No ESLint/Playwright setup found at all** in the target repo (no
  `scripts.lint`/`.eslintrc*`/`eslint.config.*`, no
  `scripts["test:e2e"|"e2e"]`/`playwright.config.*`) → the gate prints
  `WARN`, exits 0, and the pipeline continues. Keeps the pipeline usable
  against repos that don't use ESLint/Playwright.
- **A config/script exists and the actual run fails** (non-zero exit) → the
  gate prints `FAIL`, propagates the non-zero exit, and `run.sh` hard-stops.

## Human Gate exit codes

`lib/human_gate.sh` returns a 3-way result so `run.sh` can distinguish
"declined" from "no one was there to ask":

- `0` — approved (`y`/`Y` typed at an interactive TTY)
- `1` — declined (anything else typed at an interactive TTY)
- `2` — pending (non-interactive session, e.g. no TTY on stdin) — the report
  is printed but the gate **never auto-approves**; `run.sh` exits 2 without
  creating a PR

## pr_create.sh guard

`lib/pr_create.sh` requires a literal `--confirmed` flag as its second
argument so a plain `pr_create.sh <target-repo>` call — a stray invocation
from a script, a shell-history recall, someone poking at `lib/` directly —
doesn't skip the human gate by accident. This is an accident guard for a
single-user interactive tool, not a security boundary: anyone who can run
the script at all can also type `--confirmed`. It also checks `gh` is
installed and `gh auth status` before calling `gh pr create --draft`.

## Tests

`bash pipeline/test_pipeline.sh` — fixture coverage: a normal pass through
`run.sh` to `gh pr create` (via `PIPELINE_CODER_CMD` +
`PIPELINE_HUMAN_GATE_CMD` overrides and a stubbed `gh`, asserting the gate
summary shows both the tracked and untracked changes that actually get
committed), a coder run that produces no changes, an ESLint gate failure, a
Playwright gate failure, no-TTY pending behavior, a declined human-gate
response (exercised directly against `lib/human_gate.sh` via a pty, since a
declined *interactive* response needs a real TTY), and a direct
`lib/pr_create.sh` call without `--confirmed`. Every failure/pending/decline
case asserts the stubbed `gh` never received a `pr create` call.

## Files

| File | Purpose |
|---|---|
| `run.sh` | Main orchestrator, flow above |
| `gate-config.json` | Optional; see "Gate configuration" above |
| `lib/eslint_gate.sh` | ESLint gate — WARN+skip or hard-stop |
| `lib/playwright_gate.sh` | Playwright E2E gate — WARN+skip or hard-stop |
| `lib/human_gate.sh` | Renders summary/diff, blocks on `[y/N]` |
| `lib/pr_create.sh` | Guarded `gh pr create --draft` wrapper |
| `test_pipeline.sh` | Fixture tests — see Tests above |
| `logs/` | One timestamped log per run (`<run-id>.log`) |
