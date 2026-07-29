# Agentic Light

Small, manual-trigger runner for local development. It supports Claude,
Gemini (`agy` or `gemini`), Codex, and Ollama without a background service,
scheduler, or retry queue.

## Setup

```sh
bash bootstrap.sh
bash bootstrap.sh --check
bash System_Config/test_providers.sh
```

Interactive setup shows each provider as a text checkbox, `[x]` when its
command is installed and `[ ]` when it is not. Answer each `Enable ...?`
prompt, enter a comma-separated priority, then optionally set one model per
enabled provider. This is terminal text selection, not a graphical picker.
Priority must contain every enabled provider exactly once; unknown,
duplicate, missing, and extra entries are rejected.
Non-interactive setup uses all providers unless environment overrides narrow
the list.

Setup writes the selection to `.agentic-light.conf` at the repository root
with mode `600`. The file is local and gitignored. It contains provider and
model names, not API keys, and is read as text rather than sourced as shell
code.

Environment values take precedence:

```sh
AGENTIC_LIGHT_PROVIDERS=codex,ollama
AGENTIC_LIGHT_PRIORITY=codex,ollama
AGENTIC_LIGHT_MODEL_CODEX=<model>
AGENTIC_LIGHT_MODEL_OLLAMA=<model>
```

The model variable suffix can be `CLAUDE`, `GEMINI`, `CODEX`, or `OLLAMA`.
Legacy `AGENT_TYPE=<provider>` still moves one provider to the front.
`AGENT_TYPE` and `CLAUDE` remain exported for older scripts after resolution;
`CLAUDE` may point to any selected provider executable.

## Run

```sh
bash pipeline/run.sh "<task>" /path/to/target/repo
```

Each run launches one provider task in the foreground and waits for it before
lint, Playwright, human approval, and PR steps continue. Provider priority is
ordered fallback before launch only: missing executables are skipped. Once a
provider starts, its exit status is final. Agentic Light does not retry with
another provider and does not schedule a later run.

Provider safety differs by CLI. Claude receives an explicit file-tool allow
list, denied shell/web tools, `acceptEdits`, a time limit, and a budget limit.
Gemini uses `--sandbox --approval-mode auto_edit`. Codex uses
`codex exec --sandbox workspace-write`. Ollama is inference-only, so this
write workflow refuses it with exit 64. Executed providers receive a
wall-clock limit. See `System_Config/README.md` for exact adapter flags.
