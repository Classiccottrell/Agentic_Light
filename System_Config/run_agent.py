#!/usr/bin/env python3
"""run_agent.py — provider-agnostic headless agent invocation (library
module, not a CLI). Python port of run_agent.sh, retargeted at BRAIN (not
VAULT). Callers: `import run_agent as ra; ra.run_agent("<prompt>")`.

Runs with each provider's edit-capable sandbox; cwd defaults to config.BRAIN
and a wall-clock watchdog bounds the run. Ollama is inference-only and
rejected (exit 64).
"""
import os
import subprocess
import sys
import threading
from pathlib import Path

import config

# MAX_SECONDS/MAX_BUDGET are captured ONCE, at import time — mirrors
# run_agent.sh's top-level `${MAX_SECONDS:-300}` assignment, executed once
# per bash `source`. A fresh `python3 ...` process (as every test fixture
# and every pipeline/run.py invocation is) gives the same "once per process"
# semantics. LOG/BRAIN below are the opposite: read fresh on every
# run_agent() call, matching run_agent.sh's live re-read of the ambient
# shell environment (callers like pipeline/run.sh set them via `LOG=...
# BRAIN=... run_agent "$PROMPT"` immediately before each call).
MAX_SECONDS = int(os.environ.get("MAX_SECONDS", "300"))
MAX_BUDGET = os.environ.get("MAX_BUDGET", "2.00")


def _build_argv(provider, command, model, prompt, brain):
    if provider == "gemini":
        argv = [command, "-p", prompt]
        if model:
            argv += ["--model", model]
        # --add-dir must stay on its own line/list-append (not folded into
        # one multi-arg literal) — test_run_agent.py's negative-control
        # fixture line-deletes this exact statement to prove the write-
        # confinement regression is still catchable. Do not refactor.
        argv += ["--add-dir", str(brain)]
        argv += ["--sandbox", "--approval-mode", "auto_edit"]
        return argv
    if provider == "codex":
        argv = [command, "exec", "--sandbox", "workspace-write"]
        if model:
            argv += ["--model", model]
        argv += [prompt]
        return argv
    # claude (default) — allowedTools/disallowedTools/permission-mode fixed;
    # the pipeline, not the coder, owns git and shell.
    argv = [command, "-p", prompt]
    if model:
        argv += ["--model", model]
    argv += [
        "--allowedTools", "Read,Write,Edit,Glob,Grep",
        "--disallowedTools", "Bash,KillShell,Task,WebFetch,WebSearch,NotebookEdit",
        "--permission-mode", "acceptEdits",
        "--max-budget-usd", MAX_BUDGET,
    ]
    return argv


def run_agent(prompt, log=None, brain=None):
    """Returns the coder process's shell-style exit status: 127 if no
    provider resolves, 64 if the resolved provider is ollama, 137/143 on
    watchdog kill/term, 128+N on any other signal, else the process's own
    exit code — same vocabulary run.sh's reason_for_status() expects.

    log: path to append combined stdout+stderr to (None = discard).
    brain: cwd for the child process (None = os.environ["BRAIN"], falling
    back to config.BRAIN) — see the module docstring on why this is a
    per-call parameter rather than a cached default.
    """
    if brain is None:
        brain = os.environ.get("BRAIN") or str(config.BRAIN)
    if log is None:
        log = os.environ.get("LOG")

    if not config.resolve_agent_provider():
        return 127
    provider = config.AGENT_PROVIDER
    if provider == "ollama":
        print("[run_agent] Ollama is inference-only and cannot run write workflows.", file=sys.stderr)
        return 64

    argv = _build_argv(provider, config.AGENT_COMMAND, config.AGENT_MODEL, prompt, brain)

    log_f = None
    stdout_target = subprocess.DEVNULL
    stderr_target = subprocess.DEVNULL
    try:
        if log:
            log_f = open(log, "ab")
            stdout_target = log_f
            stderr_target = subprocess.STDOUT
        proc = subprocess.Popen(argv, cwd=str(brain), stdout=stdout_target, stderr=stderr_target)

        finished = threading.Event()
        watchdog_state = {"signal": None}

        def _watchdog():
            if not finished.wait(MAX_SECONDS):
                watchdog_state["signal"] = "term"
                proc.terminate()
                if not finished.wait(20):
                    watchdog_state["signal"] = "kill"
                    proc.kill()

        wd = threading.Thread(target=_watchdog, daemon=True)
        wd.start()
        rc = proc.wait()
        finished.set()
        wd.join(timeout=1)
    finally:
        if log_f is not None:
            log_f.close()

    if watchdog_state["signal"] == "kill":
        return 137
    if watchdog_state["signal"] == "term":
        return 143
    if rc < 0:
        return 128 - rc
    return rc


if __name__ == "__main__":
    # Library module — smoke-test only.
    sys.exit(run_agent(sys.argv[1] if len(sys.argv) > 1 else "smoke test"))
