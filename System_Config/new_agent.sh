#!/usr/bin/env bash
# new_agent.sh - scaffold a new agents/<name>.md from the roster pattern.
# Usage: new_agent.sh <name> "<scope one-liner>" [--write]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./config.sh
source "$SCRIPT_DIR/config.sh"

NAME="${1:-}"
SCOPE="${2:-}"
WRITE=0
for arg in "${@:3}"; do
  [[ "$arg" == "--write" ]] && WRITE=1
done

if [[ -z "$NAME" || -z "$SCOPE" ]]; then
  echo "usage: new_agent.sh <name> \"<scope one-liner>\" [--write]" >&2
  exit 1
fi

# bash 3.2 safe lowercase-hyphen slug validation (no extglob dependency).
if ! echo "$NAME" | grep -Eq '^[a-z][a-z0-9]*(-[a-z0-9]+)*$'; then
  echo "new_agent.sh: name must be a lowercase-hyphen slug (e.g. 'data-migrator'): $NAME" >&2
  exit 1
fi

AGENT_MD="$WORKSPACE/agents/${NAME}.md"

if [[ -e "$AGENT_MD" ]]; then
  echo "new_agent.sh: refusing to overwrite existing file: $AGENT_MD" >&2
  exit 1
fi

DESCRIPTION="${SCOPE}. Authority limited to its scope."

read -r -d '' AGENT_BODY <<EOF || true
---
name: ${NAME}
description: ${DESCRIPTION}
tools: Read, Glob, Grep, Edit, Write
model: inherit
---

You are the ${NAME} agent for this multi-agent workspace.

Role: ${SCOPE}. Authority limited to its scope.

Rules:
- Read existing files to deduce stack and conventions before acting. Do not ask.
- Stay strictly within your scope; hand off anything outside it back to the orchestrator.
- Never overwrite or delete files outside your assigned scope.

Response style (Caveman Protocol): no filler, no preamble/postamble, no narration of tool use. Omit markdown explanation of code unless asked.

Your final message is your deliverable to the orchestrator — return the diff/result, not a chat reply.
EOF

if [[ "$WRITE" -eq 0 ]]; then
  echo "DRY RUN — would create:"
  echo "  $AGENT_MD"
  echo
  echo "--- $AGENT_MD ---"
  echo "$AGENT_BODY"
  echo
  echo "Run again with --write to create."
  exit 0
fi

mkdir -p "$WORKSPACE/agents"
printf '%s' "$AGENT_BODY" > "$AGENT_MD"

echo "Created:"
echo "  $AGENT_MD"
echo "Register ${NAME} in agents/README.md's roster table — not automated."
