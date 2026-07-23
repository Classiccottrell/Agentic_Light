# shellcheck shell=bash
# run_agent.sh — provider-agnostic headless agent invocation (sourced library, not standalone)
# Adapted from the parent workspace's run_agent.sh, retargeted at BRAIN (not VAULT).
#
# Usage: source config.sh, then source this file, then call:
#   run_agent "<prompt>"
#
# Expects from the caller's environment (all provided by config.sh, or
# overridable before sourcing): $CLAUDE $AGENT_TYPE $BRAIN $LOG (caller-defined
# log file path). $MAX_SECONDS / $MAX_BUDGET default below if unset.
#
# File tools only; Bash and other escape hatches denied; cwd = brain so the
# sandbox confines writes to the brain/ tree; budget + wall-clock watchdog
# bound the run.
MAX_SECONDS="${MAX_SECONDS:-300}"   # wall-clock watchdog — both providers
MAX_BUDGET="${MAX_BUDGET:-2.00}"    # USD ceiling — claude only (gemini/agy have
                                    # no cost flag; MAX_SECONDS is their ceiling)

run_agent() {
  local prompt="$1" pid wd rc
  cd "$BRAIN" || return 1
  if [[ "${AGENT_TYPE:-}" == "gemini" ]]; then
    "$CLAUDE" -p "$prompt" \
          --sandbox \
          --dangerously-skip-permissions >> "${LOG:-/dev/null}" 2>&1 &
  else
    "$CLAUDE" -p "$prompt" \
          --allowedTools "Read,Write,Edit,Glob,Grep" \
          --disallowedTools "Bash,KillShell,Task,WebFetch,WebSearch,NotebookEdit" \
          --permission-mode acceptEdits \
          --max-budget-usd "$MAX_BUDGET" >> "${LOG:-/dev/null}" 2>&1 &
  fi
  pid=$!
  # TERM first; a CLI wedged in a network read can ignore TERM, so escalate to
  # KILL 20s later — otherwise `wait` blocks forever and the job never exits.
  ( sleep "$MAX_SECONDS"; kill -TERM "$pid" 2>/dev/null
    sleep 20;             kill -KILL "$pid" 2>/dev/null ) &
  wd=$!
  disown "$wd" 2>/dev/null || true   # silence the "Terminated" job-control notice when we cancel the watchdog
  if wait "$pid"; then rc=0; else rc=$?; fi
  kill "$wd" 2>/dev/null || true
  return "$rc"
}
