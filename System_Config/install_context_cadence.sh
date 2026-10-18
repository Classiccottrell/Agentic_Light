#!/usr/bin/env bash
# Install the Agentic Light daily, Monday, and Friday cadence on macOS.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="${1:---install}"
if [[ "$MODE" != "--install" && "$MODE" != "--dry-run" && "$MODE" != "--uninstall" ]]; then
  echo "usage: install_context_cadence.sh [--install|--dry-run|--uninstall]" >&2
  exit 2
fi

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "context cadence: launchd is only available on macOS; run the scripts with your scheduler."
  exit 0
fi

AGENTS="$HOME/Library/LaunchAgents"
LOG_DIR="$ROOT/System_Config/logs"
USER_ID="$(id -u)"
if [[ "$MODE" == "--uninstall" ]]; then
  for name in daily-ingest monday-init friday-process; do
    destination="$AGENTS/com.${USER}.agentic-light.${name}.plist"
    launchctl bootout "gui/$USER_ID" "$destination" 2>/dev/null || true
    rm -f "$destination"
  done
  echo "removed Agentic Light context cadence"
  exit 0
fi
write_job() {
  local name="$1" hour="$2" minute="$3" weekday="${4:-}" script="$5"
  local destination="$AGENTS/com.${USER}.agentic-light.${name}.plist"
  if [[ "$MODE" == "--dry-run" ]]; then
    echo "would install ${name}: ${script} at ${hour}:${minute}${weekday:+ on weekday $weekday}"
    return
  fi
  mkdir -p "$AGENTS" "$LOG_DIR"
  python3 - "$destination" "com.${USER}.agentic-light.${name}" "$script" "$LOG_DIR" "$hour" "$minute" "$weekday" <<'PY'
import plistlib
import sys

destination, label, script, log_dir, hour, minute, weekday = sys.argv[1:]
calendar = {"Hour": int(hour), "Minute": int(minute)}
if weekday:
    calendar["Weekday"] = int(weekday)
payload = {
    "Label": label,
    "ProgramArguments": ["/bin/bash", script],
    "StartCalendarInterval": calendar,
    "StandardOutPath": f"{log_dir}/{label}.out",
    "StandardErrorPath": f"{log_dir}/{label}.err",
}
with open(destination, "wb") as output:
    plistlib.dump(payload, output)
PY
  launchctl bootout "gui/$USER_ID" "$destination" 2>/dev/null || true
  launchctl bootstrap "gui/$USER_ID" "$destination"
  echo "installed ${name}"
}

write_job daily-ingest 7 0 "" "$ROOT/System_Config/daily_ingest.sh"
write_job monday-init 8 0 2 "$ROOT/System_Config/monday_init.sh"
write_job friday-process 19 0 6 "$ROOT/System_Config/friday_process.sh"
