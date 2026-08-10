# pipeline

Task runner: **Task Input → Code Patch (coder) → ESLint → Playwright E2E →
[Human Gate] → GitHub PR Creation (`gh pr create`)**.

This pipeline operates against an **external target repo** you point it at —
not against Agentic_Light itself.

## Run it

```
bash pipeline/run.sh "<task description>" /path/to/target/repo
```

`target-repo-path` defaults to `$PWD` if omitted.

1. **Code Patch** — `run.sh` itself creates the feature branch
   (`git checkout -b agentic-light/<run-id>`) in the target repo, then
   invokes the `coder` step via `System_Config/run_agent.sh`, scoped to the
   target repo (cwd), with the task description as the prompt. The prompt
   tells the coder to implement the change only — it does not ask it to
   branch or commit, because the `claude` invocation in `run_agent.sh` runs
   with `--disallowedTools "Bash,..."` and can't do either. `run.sh` captures
   the coder's diff (`git diff HEAD` + any new untracked files) and commits
   it itself once the coder step returns; a coder run that produces no
   changes fails this step (no commit, no PR). Swappable for testing: set
   `PIPELINE_CODER_CMD` to any command; if set, `run.sh` execs
   `$PIPELINE_CODER_CMD "<task>" "<target-repo>"` instead of the live agent
   call — no agent CLI round-trip needed to test the rest of the pipeline.
2. **ESLint gate** (`lib/eslint_gate.sh <target-repo>`).
3. **Playwright gate** (`lib/playwright_gate.sh <target-repo>`).
4. **Human Gate** (`lib/human_gate.sh "<summary>"`) — renders the already-
   committed diff + gate summary, blocks on interactive `[y/N]`. Swappable
   for testing the same way as the coder step: set `PIPELINE_HUMAN_GATE_CMD`
   to any command taking a summary string as its only argument; `run.sh`
   calls that instead of `lib/human_gate.sh`.
5. **PR creation** (`lib/pr_create.sh <target-repo> --confirmed`) — only
   called by `run.sh`, only after explicit approval.

`agents/qa.md` and `agents/eng-manager.md` are not part of this chain —
they're orchestrator-dispatched (Agent-tool) roles for optional gap-review,
not steps `run.sh` invokes. See `agents/README.md`.

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
| `run.sh` | Main orchestrator, 5-step flow above |
| `lib/eslint_gate.sh` | ESLint gate — WARN+skip or hard-stop |
| `lib/playwright_gate.sh` | Playwright E2E gate — WARN+skip or hard-stop |
| `lib/human_gate.sh` | Renders summary/diff, blocks on `[y/N]` |
| `lib/pr_create.sh` | Guarded `gh pr create --draft` wrapper |
| `test_pipeline.sh` | Fixture tests — see Tests above |
| `logs/` | One timestamped log per run (`<run-id>.log`) |
