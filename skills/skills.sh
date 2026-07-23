#!/usr/bin/env bash
# skills.sh — lightweight, provider-neutral skill CLI.
# Scans skills/*/SKILL.md (generic frontmatter: name/description), no
# Claude-specific assumptions, so any SKILL.md-based loader can reuse it.
#
#   skills.sh list                    — list all skills (name — description)
#   skills.sh run <name> "<args>"     — exec skills/<name>/run_<name>.sh (or
#                                        the sole run_*.sh entrypoint found)
#
# Bash 3.2-safe: no associative arrays, no mapfile.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  echo "usage: skills.sh list" >&2
  echo "       skills.sh run <name> \"<args>\"" >&2
}

# frontmatter_field <file> <key> — print the value of a "key: value" line
# inside the leading --- ... --- YAML block. Bash 3.2-safe (no regex arrays).
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

cmd_list() {
  local dir smd name desc
  for smd in "$ROOT"/*/SKILL.md; do
    [[ -f "$smd" ]] || continue
    dir="$(dirname "$smd")"
    name="$(frontmatter_field "$smd" name)"
    desc="$(frontmatter_field "$smd" description)"
    [[ -z "$name" ]] && name="$(basename "$dir")"
    [[ -z "$desc" ]] && desc="(no description)"
    echo "${name} — ${desc}"
  done
}

cmd_run() {
  local name="$1" args="${2:-}" dir entry found=""
  dir="$ROOT/$name"
  if [[ ! -d "$dir" ]]; then
    echo "skills.sh: no such skill: $name (looked in $dir)" >&2
    return 1
  fi

  entry="$dir/run_${name}.sh"
  if [[ -x "$entry" ]]; then
    found="$entry"
  else
    # Fall back to the sole run_*.sh entrypoint in the skill dir, if exactly one exists.
    local f count=0
    for f in "$dir"/run_*.sh; do
      [[ -f "$f" ]] || continue
      found="$f"
      count=$((count+1))
    done
    [[ "$count" -eq 1 ]] || found=""
  fi

  if [[ -z "$found" ]]; then
    echo "skills.sh: skill '$name' has no executable entrypoint (expected $dir/run_${name}.sh)" >&2
    return 1
  fi
  if [[ ! -x "$found" ]]; then
    echo "skills.sh: found entrypoint but it is not executable: $found (chmod +x it)" >&2
    return 1
  fi

  # shellcheck disable=SC2086
  "$found" $args
}

case "${1:-}" in
  list)
    cmd_list
    ;;
  run)
    shift || true
    [[ $# -ge 1 ]] || { usage; exit 1; }
    cmd_run "$1" "${2:-}"
    ;;
  *)
    usage
    exit 1
    ;;
esac
