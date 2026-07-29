# shellcheck shell=bash
# run_agent.sh — provider-agnostic headless agent invocation (sourced library, not standalone)
# Adapted from the parent workspace's run_agent.sh, retargeted at BRAIN (not VAULT).
#
# Usage: source config.sh, then source this file, then call:
#   run_agent "<prompt>"
#
# Expects from the caller's environment (all provided by config.sh, or
# overridable before sourcing): $AGENT_COMMAND $AGENT_PROVIDER $BRAIN $LOG (caller-defined
# log file path). $MAX_SECONDS / $MAX_BUDGET default below if unset.
#
# File tools only; Bash and other escape hatches denied; cwd = brain so the
# sandbox confines writes to the brain/ tree; budget + wall-clock watchdog
# bound the run.
MAX_SECONDS="${MAX_SECONDS:-300}"   # wall-clock watchdog — both providers
MAX_BUDGET="${MAX_BUDGET:-2.00}"    # USD ceiling — claude only (gemini/agy have
                                    # no cost flag; MAX_SECONDS is their ceiling)

run_agent() {
  local prompt="$1" pid wd rc donefile
  cd "$BRAIN" || return 1
  resolve_agent_provider || return 127
  if [[ "$AGENT_PROVIDER" == "gemini" ]]; then
    # Unlike the claude branch below, this CLI has no --allowedTools/
    # --disallowedTools equivalent here — tool restriction is delegated
    # entirely to its own --sandbox, which this wrapper cannot verify.
    # Treat this path as lower-trust, especially against untrusted prompt
    # content (e.g. brain/raw/ clips ingested by daily_ingest.sh).
    echo "[run_agent] WARNING: AGENT_TYPE=gemini has no tool allow/deny list here; relies solely on the CLI's own --sandbox." >&2
    if [[ -n "$AGENT_MODEL" ]]; then
      "$AGENT_COMMAND" -p "$prompt" --model "$AGENT_MODEL" \
            --sandbox \
            --dangerously-skip-permissions >> "${LOG:-/dev/null}" 2>&1 &
    else
      "$AGENT_COMMAND" -p "$prompt" \
            --sandbox \
            --dangerously-skip-permissions >> "${LOG:-/dev/null}" 2>&1 &
    fi
  elif [[ "$AGENT_PROVIDER" == "codex" ]]; then
    if [[ -n "$AGENT_MODEL" ]]; then
      "$AGENT_COMMAND" exec --model "$AGENT_MODEL" "$prompt" >> "${LOG:-/dev/null}" 2>&1 &
    else
      "$AGENT_COMMAND" exec "$prompt" >> "${LOG:-/dev/null}" 2>&1 &
    fi
  elif [[ "$AGENT_PROVIDER" == "ollama" ]]; then
    "$AGENT_COMMAND" run "${AGENT_MODEL:-llama3.2}" "$prompt" >> "${LOG:-/dev/null}" 2>&1 &
  else
    if [[ -n "$AGENT_MODEL" ]]; then
      "$AGENT_COMMAND" -p "$prompt" --model "$AGENT_MODEL" \
            --allowedTools "Read,Write,Edit,Glob,Grep" \
            --disallowedTools "Bash,KillShell,Task,WebFetch,WebSearch,NotebookEdit" \
            --permission-mode acceptEdits \
            --max-budget-usd "$MAX_BUDGET" >> "${LOG:-/dev/null}" 2>&1 &
    else
      "$AGENT_COMMAND" -p "$prompt" \
            --allowedTools "Read,Write,Edit,Glob,Grep" \
            --disallowedTools "Bash,KillShell,Task,WebFetch,WebSearch,NotebookEdit" \
            --permission-mode acceptEdits \
            --max-budget-usd "$MAX_BUDGET" >> "${LOG:-/dev/null}" 2>&1 &
    fi
  fi
  pid=$!
  # Sentinel-file handshake, not a bare `kill -TERM "$pid"` after sleeping:
  # by the time the watchdog wakes, $pid may already have exited and been
  # reaped, and the OS is free to hand that same PID to an unrelated
  # process — a blind kill-by-PID could then signal the wrong process.
  # The watchdog only signals while $donefile is absent; the main path
  # creates it immediately once `wait` returns, so the unguarded window
  # shrinks from the full watchdog sleep to the instant between wait()
  # returning and the touch below.
  donefile="$(mktemp -u "${TMPDIR:-/tmp}/run_agent.XXXXXX")"   # unique name only; must NOT exist yet
  ( sleep "$MAX_SECONDS"
    [[ -e "$donefile" ]] || kill -TERM "$pid" 2>/dev/null
    sleep 20
    [[ -e "$donefile" ]] || kill -KILL "$pid" 2>/dev/null ) &
  wd=$!
  disown "$wd" 2>/dev/null || true   # silence the "Terminated" job-control notice when we cancel the watchdog
  if wait "$pid"; then rc=0; else rc=$?; fi
  touch "$donefile" 2>/dev/null || true
  kill "$wd" 2>/dev/null || true
  rm -f "$donefile" 2>/dev/null || true
  return "$rc"
}
