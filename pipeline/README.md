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

## Flow

1. **Code Patch** — invokes the `coder` step via `System_Config/run_agent.sh`,
   scoped to the target repo (cwd), with the task description as the prompt.
   Swappable for testing: set `PIPELINE_CODER_CMD` to any command; if set,
   `run.sh` execs `$PIPELINE_CODER_CMD "<task>" "<target-repo>"` instead of
   the live agent call — no agent CLI round-trip needed to test the rest of
   the pipeline.
2. **ESLint gate** (`lib/eslint_gate.sh <target-repo>`).
3. **Playwright gate** (`lib/playwright_gate.sh <target-repo>`).
4. **Human Gate** (`lib/human_gate.sh "<summary>"`) — renders the diff + gate
   summary, blocks on interactive `[y/N]`.
5. **PR creation** (`lib/pr_create.sh <target-repo> --confirmed`) — only
   called by `run.sh`, only after explicit approval.

## Contract: 100% pass before the patch is even shown to a human

Every gate runs and must pass (or be skipped, see below) **before** the diff
is rendered at the Human Gate. The patch is never presented for human review
if a gate actually failed.

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
argument (not user-guessable) so it cannot be run standalone and
accidentally skip the human gate. It also checks `gh` is installed and
`gh auth status` before calling `gh pr create --draft`.

## Files

| File | Purpose |
|---|---|
| `run.sh` | Main orchestrator, 5-step flow above |
| `lib/eslint_gate.sh` | ESLint gate — WARN+skip or hard-stop |
| `lib/playwright_gate.sh` | Playwright E2E gate — WARN+skip or hard-stop |
| `lib/human_gate.sh` | Renders summary/diff, blocks on `[y/N]` |
| `lib/pr_create.sh` | Guarded `gh pr create --draft` wrapper |
| `logs/` | One timestamped log per run (`<run-id>.log`) |
