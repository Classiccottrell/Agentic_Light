#!/usr/bin/env bash
#
# specialize.sh — one-time fork specialization for Agentic Light.
#
# Run once per fork, after bootstrap.sh. Prompts for which roles, gates, and
# skill dirs this fork keeps, writes canonical config to
# System_Config/agent-roster.json, pipeline/gate-config.json, and
# System_Config/skills-selected.json (read by route_skill.sh to restrict its
# scan — see that script's header).
# Idempotent: re-running overwrites those files cleanly.
#
#   ./System_Config/specialize.sh
#   ./System_Config/specialize.sh --preset web-app|cli-tool|data-pipeline|design-harness|server-harness|wcag-harness
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SYSCFG="$ROOT/System_Config"
PRESETS_FILE="$SYSCFG/presets.json"
ROSTER_SCHEMA="$SYSCFG/agent-roster.schema.json"
GATE_SCHEMA="$SYSCFG/gate-config.schema.json"
ROSTER_OUT="$SYSCFG/agent-roster.json"
GATE_OUT="$ROOT/pipeline/gate-config.json"
SKILLS_OUT="$SYSCFG/skills-selected.json"

case "${1:-}" in
  --help)
    echo "Usage: ./System_Config/specialize.sh [--preset web-app|cli-tool|data-pipeline|design-harness|server-harness|wcag-harness]"
    echo "  (no args)        interactive checkbox prompts"
    echo "  --preset <name>  non-interactive, expand a named preset from System_Config/presets.json"
    echo "                   web-app: full team + eslint/playwright gates + all skills"
    echo "                   cli-tool: coder+qa, no gates, all skills"
    echo "                   data-pipeline: architect+coder+qa, placeholder custom gate (needs a script), all skills"
    echo "                   design-harness: architect+coder+creative-director+qa, playwright gate, all skills"
    echo "                   server-harness: architect+coder+qa, no default gates, no shipped skills yet"
    echo "                   wcag-harness: architect+coder+creative-director+qa, playwright gate, no shipped skills yet"
    echo "  --help           this message"
    echo
    echo "Env overrides (non-interactive): AGENTIC_LIGHT_ROLES, AGENTIC_LIGHT_GATES,"
    echo "AGENTIC_LIGHT_SKILLS — comma-separated. AGENTIC_LIGHT_GATES entries are gate"
    echo "names (eslint, playwright); a custom gate cannot be expressed via env override."
    exit 0
    ;;
  --preset)
    PRESET="${2:?usage: specialize.sh --preset <name>}"
    ;;
  --*)
    echo "Unknown flag: $1" >&2
    echo "Usage: ./System_Config/specialize.sh [--preset web-app|cli-tool|data-pipeline|design-harness|server-harness|wcag-harness]" >&2
    exit 1
    ;;
  "") PRESET="" ;;
esac

command -v python3 >/dev/null 2>&1 || { echo "FAILED: python3 not found — required to read/validate JSON config" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Discover the fixed role set from agent-roster.schema.json (never hardcode —
# task requires this list track the schema, not a possibly-stale copy).
# ---------------------------------------------------------------------------
ALL_ROLES="$(python3 -c "
import json
with open('$ROSTER_SCHEMA') as f:
    s = json.load(f)
print(' '.join(s['properties']['roles']['properties'].keys()))
")"

# Known gate names, from gate-config.schema.json's own enum path.
KNOWN_GATES="$(python3 -c "
import json
with open('$GATE_SCHEMA') as f:
    s = json.load(f)
print(' '.join(s['definitions']['gate']['oneOf'][0]['enum']))
")"

# Skill dirs actually present under skills/ (directories only — skills.sh is
# a file, not a skill).
SKILL_DIRS="$(find "$ROOT/skills" -mindepth 1 -maxdepth 1 -type d -exec basename {} \; 2>/dev/null | sort)"

echo "=================================================="
echo " Agentic Light — specialize"
echo " Workspace: $ROOT"
echo "=================================================="
echo

# ---------------------------------------------------------------------------
# Resolve selections: --preset > env overrides > interactive checkboxes.
# ---------------------------------------------------------------------------
SEL_ROLES=""
SEL_GATES_JSON=""   # JSON array of gate entries (strings or custom objects)
SEL_SKILLS=""

if [ -n "$PRESET" ]; then
  [ -f "$PRESETS_FILE" ] || { echo "FAILED: $PRESETS_FILE not found" >&2; exit 1; }
  PRESET_DATA="$(python3 -c "
import json, sys
with open('$PRESETS_FILE') as f:
    presets = json.load(f)
name = '$PRESET'
if name not in presets:
    print('FAILED: unknown preset %r (known: %s)' % (name, ', '.join(sorted(presets))), file=sys.stderr)
    sys.exit(1)
p = presets[name]
skills = p.get('skills', [])
print(','.join(p.get('roles', [])))
print(json.dumps(p.get('gates', [])))
print('*' if skills == '*' else ','.join(skills))
print(p.get('skills_gap_note', ''))
")" || exit 1
  SEL_ROLES="$(printf '%s\n' "$PRESET_DATA" | sed -n '1p' | tr ',' ' ')"
  SEL_GATES_JSON="$(printf '%s\n' "$PRESET_DATA" | sed -n '2p')"
  SEL_SKILLS_RAW="$(printf '%s\n' "$PRESET_DATA" | sed -n '3p')"
  SKILLS_GAP_NOTE="$(printf '%s\n' "$PRESET_DATA" | sed -n '4p')"
  if [ "$SEL_SKILLS_RAW" = "*" ]; then
    SEL_SKILLS="$SKILL_DIRS"
  else
    SEL_SKILLS="$(printf '%s' "$SEL_SKILLS_RAW" | tr ',' ' ')"
  fi
  echo "→ Using preset: $PRESET"
  if [ -n "$SKILLS_GAP_NOTE" ]; then
    echo "Note: this preset ships no skill content yet ($SKILLS_GAP_NOTE) — agents will work from base instructions only."
  fi
elif [ -n "${AGENTIC_LIGHT_ROLES:-}${AGENTIC_LIGHT_GATES:-}${AGENTIC_LIGHT_SKILLS:-}" ]; then
  SEL_ROLES="$(printf '%s' "${AGENTIC_LIGHT_ROLES:-}" | tr ',' ' ')"
  SEL_SKILLS="$(printf '%s' "${AGENTIC_LIGHT_SKILLS:-}" | tr ',' ' ')"
  SEL_GATES_JSON="$(python3 -c "
import json
gates = '${AGENTIC_LIGHT_GATES:-}'.split(',') if '${AGENTIC_LIGHT_GATES:-}' else []
print(json.dumps([g for g in gates if g]))
")"
  echo "→ Using env overrides."
elif [ -t 0 ]; then
  echo "→ Roles — keep which of the 6 roles in this fork?"
  for role in $ALL_ROLES; do
    printf "  [x] Enable %s? [Y/n]: " "$role"
    read -r reply || reply=""
    case "${reply:-Y}" in
      n|N|no|NO) ;;
      *) SEL_ROLES="${SEL_ROLES:+$SEL_ROLES }$role" ;;
    esac
  done
  echo
  echo "→ Gates — which apply after the coder step?"
  GATE_ENTRIES=""
  for gate in $KNOWN_GATES; do
    printf "  [x] Enable %s gate? [Y/n]: " "$gate"
    read -r reply || reply=""
    case "${reply:-Y}" in
      n|N|no|NO) ;;
      *) GATE_ENTRIES="${GATE_ENTRIES:+$GATE_ENTRIES }$gate" ;;
    esac
  done
  printf "  [ ] Add one custom gate? [y/N]: "
  read -r reply || reply=""
  CUSTOM_JSON="null"
  case "$reply" in
    y|Y|yes|YES)
      printf "    Script (repo-root-relative to target repo, blank to fill in later): "
      read -r cscript || cscript=""
      printf "    Working dir (repo-root-relative, default .): "
      read -r ccwd || ccwd=""
      ccwd="${ccwd:-.}"
      # Values passed via argv, never interpolated into python source —
      # avoids breaking out of a string literal on quotes/triple-quotes.
      CUSTOM_JSON="$(python3 -c "
import json, sys
script, cwd = sys.argv[1], sys.argv[2]
print(json.dumps({'name': 'custom', 'script': script, 'cwd': cwd, 'args': []}))
" "$cscript" "$ccwd")"
      ;;
  esac
  SEL_GATES_JSON="$(python3 -c "
import json, sys
entries = sys.argv[1].split()
custom = json.loads(sys.argv[2]) if sys.argv[2] != 'null' else None
out = list(entries)
if custom is not None:
    out.append(custom)
print(json.dumps(out))
" "$GATE_ENTRIES" "$CUSTOM_JSON")"
  echo
  echo "→ Skills — which skill dirs under skills/ to keep? (config-only gate; files are never deleted)"
  for skill in $SKILL_DIRS; do
    printf "  [x] Enable %s? [Y/n]: " "$skill"
    read -r reply || reply=""
    case "${reply:-Y}" in
      n|N|no|NO) ;;
      *) SEL_SKILLS="${SEL_SKILLS:+$SEL_SKILLS }$skill" ;;
    esac
  done
else
  echo "FAILED: non-interactive session with no --preset and no AGENTIC_LIGHT_* overrides." >&2
  exit 1
fi

[ -n "$SEL_GATES_JSON" ] || SEL_GATES_JSON="[]"

# ---------------------------------------------------------------------------
# Refuse to write a custom gate with a known-empty "script" — it passes
# schema validation (script just has to be a string) but fails
# pipeline/run.sh's own runtime preflight the first time it actually runs.
# Same policy for preset and interactive paths (Codex's note).
# ---------------------------------------------------------------------------
python3 -c "
import json, sys
gates = json.loads(sys.argv[1])
for g in gates:
    if isinstance(g, dict) and g.get('name') == 'custom':
        script = g.get('script', '')
        if not isinstance(script, str) or not script.strip():
            sys.stderr.write('FAILED: custom gate has an empty \"script\" field.\n')
            sys.stderr.write('pipeline/run.sh will fail this gate the first time it actually runs.\n')
            sys.stderr.write('Fix: supply a script path now (rerun with a filled-in custom gate),\n')
            sys.stderr.write('or choose a preset/gate list without a custom gate.\n')
            sys.exit(1)
" "$SEL_GATES_JSON" || exit 1

# ---------------------------------------------------------------------------
# Validate role selections against the schema's fixed role set.
# ---------------------------------------------------------------------------
for role in $SEL_ROLES; do
  case " $ALL_ROLES " in
    *" $role "*) ;;
    *) echo "FAILED: unknown role '$role' — must be one of: $ALL_ROLES" >&2; exit 1 ;;
  esac
done

# ---------------------------------------------------------------------------
# Build agent-roster.json (capabilities sourced from the shipped example, not
# duplicated here) and validate before writing.
# ---------------------------------------------------------------------------
ROSTER_TMP="$(mktemp "${TMPDIR:-/tmp}/agent-roster.XXXXXX")"
python3 - "$ROOT" "$SEL_ROLES" "$ROSTER_TMP" "$ROSTER_SCHEMA" <<'PYEOF'
import json, sys

root, sel_roles_str, out_path, schema_path = sys.argv[1:5]
sel_roles = set(sel_roles_str.split())

with open(schema_path) as f:
    schema = json.load(f)
all_roles = list(schema["properties"]["roles"]["properties"].keys())

example_path = root + "/System_Config/agent-roster.example.json"
default_caps = {}
try:
    with open(example_path) as f:
        example = json.load(f)
    for role, val in example.get("roles", {}).items():
        default_caps[role] = val.get("capabilities", [])
except FileNotFoundError:
    pass

roster = {"roles": {}}
for role in all_roles:
    entry = {"active": role in sel_roles}
    if role in default_caps:
        entry["capabilities"] = default_caps[role]
    roster["roles"][role] = entry

with open(out_path, "w") as f:
    json.dump(roster, f, indent=2)
    f.write("\n")
PYEOF

# Real structural validation against agent-roster.schema.json — derived from
# the schema's own fields, not a hand-maintained second copy of its rules.
if ! python3 - "$ROSTER_TMP" "$ROSTER_SCHEMA" <<'PYEOF'
import json, sys

data_path, schema_path = sys.argv[1], sys.argv[2]
with open(data_path) as f:
    data = json.load(f)
with open(schema_path) as f:
    schema = json.load(f)

if not isinstance(data, dict):
    print("FAILED: agent-roster.json must be an object"); sys.exit(1)

top_props = set(schema["properties"].keys())
unknown_top = set(data.keys()) - top_props
if unknown_top:
    print("FAILED: agent-roster.json has unknown top-level keys: %s" % sorted(unknown_top)); sys.exit(1)
for req in schema.get("required", []):
    if req not in data:
        print("FAILED: agent-roster.json missing required key %r" % req); sys.exit(1)

roles_schema = schema["properties"]["roles"]["properties"]
role_def = schema["definitions"]["role"]
cap_enum = set(role_def["properties"]["capabilities"]["items"]["enum"])

roles = data.get("roles", {})
if not isinstance(roles, dict):
    print("FAILED: agent-roster.json \"roles\" must be an object"); sys.exit(1)
unknown = set(roles.keys()) - set(roles_schema.keys())
if unknown:
    print("FAILED: agent-roster.json roles has unknown keys: %s" % sorted(unknown)); sys.exit(1)
for role, entry in roles.items():
    if not isinstance(entry, dict):
        print("FAILED: agent-roster.json roles.%s must be an object" % role); sys.exit(1)
    extra = set(entry.keys()) - {"active", "capabilities"}
    if extra:
        print("FAILED: agent-roster.json roles.%s has unknown fields: %s" % (role, sorted(extra))); sys.exit(1)
    if "active" not in entry or not isinstance(entry["active"], bool):
        print("FAILED: agent-roster.json roles.%s.active must be a boolean" % role); sys.exit(1)
    if "capabilities" in entry:
        caps = entry["capabilities"]
        if not isinstance(caps, list) or not all(c in cap_enum for c in caps):
            print("FAILED: agent-roster.json roles.%s.capabilities must be an array of %s" % (role, sorted(cap_enum))); sys.exit(1)
        if len(caps) != len(set(caps)):
            print("FAILED: agent-roster.json roles.%s.capabilities must have unique entries" % role); sys.exit(1)
print("ok")
PYEOF
then
  rm -f "$ROSTER_TMP"
  exit 1
fi

mv "$ROSTER_TMP" "$ROSTER_OUT"
echo "→ Wrote $ROSTER_OUT"

# ---------------------------------------------------------------------------
# Build pipeline/gate-config.json and validate against gate-config.schema.json
# (same shape-check pattern pipeline/run.sh already applies to this file).
# ---------------------------------------------------------------------------
GATE_TMP="$(mktemp "${TMPDIR:-/tmp}/gate-config.XXXXXX")"
python3 -c "
import json, sys
gates = json.loads(sys.argv[1])
with open(sys.argv[2], 'w') as f:
    json.dump({'gates': gates}, f, indent=2)
    f.write('\n')
" "$SEL_GATES_JSON" "$GATE_TMP"

# Same validation logic pipeline/run.sh applies to gate-config.json at
# run-time (reused here, not a second hand-maintained validator), plus a
# repo-relocatability check (reject absolute script/cwd paths) that neither
# run.sh nor the JSON Schema itself enforces structurally.
if ! python3 - "$GATE_TMP" "$KNOWN_GATES" <<'PYEOF'
import json, sys
path, known_str = sys.argv[1], sys.argv[2]
KNOWN = tuple(known_str.split())
with open(path) as f:
    cfg = json.load(f)
if not isinstance(cfg, dict) or "gates" not in cfg:
    print("FAILED: generated gate-config missing \"gates\" key"); sys.exit(1)
gates = cfg["gates"]
if not isinstance(gates, list):
    print("FAILED: generated gate-config \"gates\" must be an array"); sys.exit(1)
for i, gate in enumerate(gates):
    if isinstance(gate, str):
        if gate not in KNOWN:
            print("FAILED: gates[%d] unknown gate name %r (expected one of %s or a custom object)" % (i, gate, KNOWN)); sys.exit(1)
        continue
    if isinstance(gate, dict):
        if gate.get("name") != "custom":
            print("FAILED: gates[%d] object gate must have \"name\": \"custom\"" % i); sys.exit(1)
        script = gate.get("script")
        if not isinstance(script, str) or not script:
            print("FAILED: gates[%d] custom gate missing required string \"script\"" % i); sys.exit(1)
        if script.startswith("/"):
            print("FAILED: gates[%d] custom gate \"script\" must be repo-root-relative, not absolute: %r" % (i, script)); sys.exit(1)
        cwd = gate.get("cwd", ".")
        if not isinstance(cwd, str):
            print("FAILED: gates[%d] custom gate \"cwd\" must be a string" % i); sys.exit(1)
        if cwd.startswith("/"):
            print("FAILED: gates[%d] custom gate \"cwd\" must be repo-root-relative, not absolute: %r" % (i, cwd)); sys.exit(1)
        args = gate.get("args", [])
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            print("FAILED: gates[%d] custom gate \"args\" must be an array of strings" % i); sys.exit(1)
        extra = set(gate.keys()) - {"name", "script", "cwd", "args"}
        if extra:
            print("FAILED: gates[%d] custom gate has unknown fields: %s" % (i, sorted(extra))); sys.exit(1)
        continue
    print("FAILED: gates[%d] must be a known gate name or a custom gate object" % i); sys.exit(1)
print("ok")
PYEOF
then
  rm -f "$GATE_TMP"
  exit 1
fi

mv "$GATE_TMP" "$GATE_OUT"
echo "→ Wrote $GATE_OUT"

# ---------------------------------------------------------------------------
# Build skills-selected.json — route_skill.sh reads this to restrict its
# scan to only the selected skill dirs; files under skills/ are never
# deleted, matching the repo's create-or-append philosophy.
# ---------------------------------------------------------------------------
SKILLS_TMP="$(mktemp "${TMPDIR:-/tmp}/skills-selected.XXXXXX")"
python3 -c "
import json, sys
skills = sys.argv[1].split()
with open(sys.argv[2], 'w') as f:
    json.dump({'selected': sorted(skills)}, f, indent=2)
    f.write('\n')
" "$SEL_SKILLS" "$SKILLS_TMP"
mv "$SKILLS_TMP" "$SKILLS_OUT"
echo "→ Wrote $SKILLS_OUT (route_skill.sh restricts its scan to these dirs)"

echo
echo "=================================================="
echo " Done."
echo "=================================================="
echo " Roles:  ${SEL_ROLES:-<none>}"
echo " Gates:  $(python3 -c "import json, sys; print(json.dumps(json.loads(sys.argv[1])))" "$SEL_GATES_JSON")"
echo " Skills: ${SEL_SKILLS:-<none>}"
