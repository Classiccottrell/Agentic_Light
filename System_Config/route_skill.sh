#!/usr/bin/env bash
# route_skill.sh — deterministic, provider-neutral skill router.
# Scans skills/*/SKILL.md frontmatter and keyword/substring-matches a task
# description against each skill's `description` field. No LLM call, no
# ranking model — intentionally basic (per Phase 1 build order); smarter
# matching (embeddings, scoring) is a later concern, not this step's job.
#
# If System_Config/skills-selected.json (written by specialize.sh) exists,
# the scan is restricted to only its "selected" skill dirs. Missing file =
# scan all of skills/ (unrestricted), same as before specialize.sh existed.
#
# Bash 3.2-safe, relocatable, matches System_Config/log_session.sh's
# conventions.
#
# Usage: route_skill.sh "<task description>"      (single-arg form)
#        echo "<task description>" | route_skill.sh   (stdin form)
#        route_skill.sh [--verbose] [--skills-dir <path>] "<task>"
#        route_skill.sh --self-test
#
# Prints matching skill directory paths, one per line, to stdout.
# --verbose additionally writes a stderr note when a matched skill's
# SKILL.md description mentions a tool/MCP dependency this script cannot
# verify is available (e.g. "Figma") — the match is still printed to
# stdout; --verbose only explains its provenance.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SKILLS_DIR="$ROOT/skills"
SKILLS_SELECTED_FILE="$ROOT/System_Config/skills-selected.json"
VERBOSE=0

usage() {
  echo "Usage: $(basename "$0") [--verbose] [--skills-dir <path>] \"<task description>\"" >&2
  echo "       echo \"<task>\" | $(basename "$0") [--verbose]" >&2
  echo "       $(basename "$0") --self-test" >&2
}

# frontmatter_field <file> <key> — print the value of a "key: value" line
# inside the leading --- ... --- YAML block. Only name/description are ever
# read here — deliberate, per AGENT_AGNOSTIC_REVIEW.md: Claude-specific
# fields like `disable-model-invocation` are not this router's concern.
# Same awk pattern as skills/skills.sh's frontmatter_field, reused for
# consistency across the repo's two SKILL.md readers.
frontmatter_field() {
  local file="$1" key="$2"
  awk -v key="$key" '
    /^---[[:space:]]*$/ { d++; next }
    d==1 && $0 ~ "^"key":[[:space:]]*" {
      sub("^"key":[[:space:]]*", "");
      print;
      exit
    }
    d>=2 { exit }
  ' "$file"
}

# lc <string> — lowercase, bash-3.2-safe (no ${var,,}).
lc() { tr '[:upper:]' '[:lower:]'; }

# unverifiable_deps <description> — prints a comma-separated list of
# tool/MCP names the description mentions that this script cannot confirm
# are available (deliberately small, hardcoded list; not a general
# capability-detection system).
unverifiable_deps() {
  local desc_lc="$1" found="" term
  for term in figma mcp; do
    if [[ "$desc_lc" == *"$term"* ]]; then
      found="${found:+$found,}${term}"
    fi
  done
  echo "$found"
}

# selected_skill_names — if SKILLS_SELECTED_FILE exists, prints the space-
# separated basenames under its "selected" array (specialize.sh writes this
# via `{"selected": [...]}`, indent=2 — one string per line, parsed without
# a python3 dependency to match this script's other frontmatter parsing).
# Missing file = no restriction (all skills), per the documented fallback.
selected_skill_names() {
  [[ -f "$SKILLS_SELECTED_FILE" ]] || return 1
  sed -n '/"selected"/,/\]/p' "$SKILLS_SELECTED_FILE" | grep -o '"[^"]*"' | sed '1d' | tr -d '"'
  return 0
}

route() {
  local task="$1" dir smd name desc desc_lc task_lc matched=0 deps
  local selection_active=0 selected=""
  task_lc="$(printf '%s' "$task" | lc)"

  if selected="$(selected_skill_names)"; then
    selection_active=1
  fi

  for smd in "$SKILLS_DIR"/*/SKILL.md; do
    [[ -f "$smd" ]] || continue
    dir="$(dirname "$smd")"
    if [[ "$selection_active" -eq 1 ]]; then
      case " $selected " in
        *" $(basename "$dir") "*) ;;
        *) continue ;;
      esac
    fi
    name="$(frontmatter_field "$smd" name)"
    desc="$(frontmatter_field "$smd" description)"
    [[ -z "$name" ]] && name="$(basename "$dir")"
    desc_lc="$(printf '%s' "$desc" | lc)"

    # Simple substring match: does the task mention the skill's name, or
    # does the skill's description share a keyword with the task? Kept
    # deliberately basic — see header comment.
    if [[ -n "$desc_lc" && "$task_lc" == *"$(printf '%s' "$name" | lc)"* ]] \
       || matches_keyword "$task_lc" "$desc_lc"; then
      matched=1
      echo "$dir"
      if [[ "$VERBOSE" -eq 1 ]]; then
        deps="$(unverifiable_deps "$desc_lc")"
        [[ -n "$deps" ]] && echo "[route_skill] $dir: description mentions unverifiable dependency (${deps}) — cannot confirm tool/MCP availability" >&2
      fi
    fi
  done

  return 0
}

# matches_keyword <task_lc> <desc_lc> — true if any whitespace-delimited
# word (len > 3, to skip noise like "the"/"and") in the task appears as a
# substring of the description. Bash 3.2-safe (no associative arrays).
matches_keyword() {
  local task_lc="$1" desc_lc="$2" word
  [[ -z "$desc_lc" ]] && return 1
  for word in $task_lc; do
    [[ ${#word} -gt 3 ]] || continue
    if [[ "$desc_lc" == *"$word"* ]]; then
      return 0
    fi
  done
  return 1
}

self_test() {
  local tmp
  tmp="$(mktemp -d -t route_skill_selftest.XXXXXX)"
  mkdir -p "$tmp/alpha-skill" "$tmp/beta-skill"
  cat > "$tmp/alpha-skill/SKILL.md" <<'EOF'
---
name: alpha-skill
description: "Handles Figma design export and MCP-based screenshot capture."
disable-model-invocation: false
---
# Alpha
EOF
  cat > "$tmp/beta-skill/SKILL.md" <<'EOF'
---
name: beta-skill
description: "Writes unit tests for a codebase."
---
# Beta
EOF

  local out real_dir=$SKILLS_DIR
  SKILLS_DIR="$tmp"
  out="$(route "figma export design")"
  [[ "$out" == *"alpha-skill"* ]] || { SKILLS_DIR=$real_dir; echo "FAIL: alpha-skill not matched by name substring" >&2; exit 1; }

  out="$(route "please write unit tests for this module")"
  [[ "$out" == *"beta-skill"* ]] || { SKILLS_DIR=$real_dir; echo "FAIL: beta-skill not matched by keyword" >&2; exit 1; }
  [[ "$out" != *"alpha-skill"* ]] || { SKILLS_DIR=$real_dir; echo "FAIL: alpha-skill unexpectedly matched unrelated task" >&2; exit 1; }

  local err
  VERBOSE=1
  err="$(route "figma export design" 2>&1 >/dev/null)"
  VERBOSE=0
  [[ "$err" == *"figma"* ]] || { SKILLS_DIR=$real_dir; echo "FAIL: --verbose did not note unverifiable figma dependency" >&2; exit 1; }

  # Selection-file-present case: skills-selected.json restricts the scan to
  # only beta-skill, even though "figma export design" would otherwise also
  # match alpha-skill by name substring.
  local real_selfile=$SKILLS_SELECTED_FILE selfile="$tmp/skills-selected.json"
  SKILLS_DIR="$tmp"
  printf '{\n  "selected": [\n    "beta-skill"\n  ]\n}\n' > "$selfile"
  SKILLS_SELECTED_FILE="$selfile"
  out="$(route "figma export design")"
  SKILLS_SELECTED_FILE=$real_selfile
  SKILLS_DIR=$real_dir
  [[ "$out" != *"alpha-skill"* ]] || { echo "FAIL: skills-selected.json did not exclude deselected alpha-skill" >&2; exit 1; }

  rm -rf "$tmp"
  echo "self-test OK"
}

TASK=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --self-test) self_test; exit 0 ;;
    --verbose) VERBOSE=1; shift ;;
    --skills-dir) SKILLS_DIR="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) TASK="$1"; shift ;;
  esac
done

if [[ -z "$TASK" ]]; then
  if [[ ! -t 0 ]]; then
    TASK="$(cat)"
  fi
fi

[[ -n "$TASK" ]] || { usage; exit 1; }
[[ -d "$SKILLS_DIR" ]] || { echo "route_skill.sh: no such skills dir: $SKILLS_DIR" >&2; exit 1; }

route "$TASK"
