#!/usr/bin/env bash
# healthcheck.sh — Agentic Light health check → microsite/status.{json,js}
#
# Probes directory layout, agent/skill roster completeness, brain
# scaffolding, pipeline log recency, and doc currency.
# On a stale microsite (Layer F), self-heals by invoking gen_site.py for
# real so microsite/index.html never drifts from the roster.
#
# Deliberately NOT `set -e`: a failing probe is a result to REPORT, not a
# reason to abort. bash 3.2 compatible (no associative arrays). Always
# exits 0. No GitHub Pages publish step — local files only.
#
#   Manual run:  bash System_Config/healthcheck.sh
#   View:        open microsite/health.html

set -uo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/config.sh"

SYSCFG="$WORKSPACE/System_Config"
AGENTS="$WORKSPACE/agents"
SKILLS="$WORKSPACE/skills"
MICROSITE="$WORKSPACE/microsite"
PIPELINE="$WORKSPACE/pipeline"
OUT_JSON="$MICROSITE/status.json"
OUT_JS="$MICROSITE/status.js"

NOW_HUMAN="$(date '+%Y-%m-%d %H:%M:%S %Z' 2>/dev/null || date)"

TOTAL=0; PASS_N=0; WARN_N=0; FAIL_N=0
OVERALL="PASS"
CUR_SECTION=""; SEC_PASS=0; SEC_WARN=0; SEC_FAIL=0
JSON_ITEMS=""

json_esc() { printf '%s' "$1" | tr '\n\r\t' '   ' | sed 's/\\/\\\\/g; s/"/\\"/g'; }

# mtime <path> — epoch mtime, portable across GNU (stat -c) and BSD (stat -f).
mtime() {
  stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null || echo 0
}

# newest_mtime <path...> — newest mtime among existing paths; 0 if none exist.
newest_mtime() {
  local m=0 t p
  for p in "$@"; do
    [ -e "$p" ] || continue
    t=$(mtime "$p")
    [ "$t" -gt "$m" ] 2>/dev/null && m="$t"
  done
  echo "$m"
}

# check <PASS|WARN|FAIL> <name> <detail>
check() {
  local st="$1" name="$2" detail="$3"
  TOTAL=$((TOTAL + 1))
  case "$st" in
    PASS) PASS_N=$((PASS_N + 1)); SEC_PASS=$((SEC_PASS + 1)) ;;
    WARN) WARN_N=$((WARN_N + 1)); SEC_WARN=$((SEC_WARN + 1)); [ "$OVERALL" = "PASS" ] && OVERALL="WARN" ;;
    FAIL) FAIL_N=$((FAIL_N + 1)); SEC_FAIL=$((SEC_FAIL + 1)); OVERALL="FAIL" ;;
    *)    st="WARN"; WARN_N=$((WARN_N + 1)); SEC_WARN=$((SEC_WARN + 1)); [ "$OVERALL" = "PASS" ] && OVERALL="WARN" ;;
  esac
  local comma=""
  [ -n "$JSON_ITEMS" ] && comma=","
  JSON_ITEMS="${JSON_ITEMS}${comma}{\"layer\":\"$(json_esc "$CUR_SECTION")\",\"status\":\"${st}\",\"name\":\"$(json_esc "$name")\",\"detail\":\"$(json_esc "$detail")\"}"
  echo "  [${st}] ${name} — ${detail}"
}

begin_section() {
  CUR_SECTION="$1"; SEC_PASS=0; SEC_WARN=0; SEC_FAIL=0
  echo "== ${CUR_SECTION} =="
}
end_section() {
  echo "-- ${CUR_SECTION}: ${SEC_PASS} pass / ${SEC_WARN} warn / ${SEC_FAIL} fail --"
  echo
}

# frontmatter_ok <path> — 0 if the first frontmatter block has both name: and description:.
frontmatter_ok() {
  awk '
    /^---$/{n++; next}
    n==1 && /^name:[[:space:]]*[^[:space:]]/{has_name=1}
    n==1 && /^description:[[:space:]]*[^[:space:]]/{has_desc=1}
    n>=2{exit}
    END{exit !(has_name && has_desc)}
  ' "$1"
}

# doc_check <name> <readme_path> <documented files...> — WARN if any
# documented file changed AFTER the README was last touched.
doc_check() {
  local name="$1" readme="$2"; shift 2
  if [ ! -s "$readme" ]; then check WARN "Doc: $name" "README missing or empty"; return; fi
  local rmt srct age
  rmt=$(mtime "$readme")
  srct=$(newest_mtime "$@")
  if [ "$srct" -gt "$rmt" ] 2>/dev/null; then
    age=$(( (srct - rmt) / 3600 ))
    check WARN "Doc: $name" "stale — documented file changed ${age}h after the README; review & update"
  else
    check PASS "Doc: $name" "up to date"
  fi
}

# ════════════════════════════════════════════════════════════════════════
# LAYER A — Directory layout
# ════════════════════════════════════════════════════════════════════════
begin_section "Directory Layout"
REQUIRED_DIRS="
.obsidian
System_Config
System_Config/logs
agents
skills
microsite
brain
brain/raw
brain/wiki
brain/weekly_logs
pipeline
pipeline/lib
pipeline/logs
Projects/_TEMPLATE
Projects/_TEMPLATE/active
Projects/_TEMPLATE/archive
"
for d in $REQUIRED_DIRS; do
  [ -d "$WORKSPACE/$d" ] && check PASS "Dir: $d/" "present" || check FAIL "Dir: $d/" "MISSING"
done
end_section

# ════════════════════════════════════════════════════════════════════════
# LAYER B — Roster completeness (agents + skills frontmatter)
# ════════════════════════════════════════════════════════════════════════
begin_section "Roster Completeness"
for f in "$AGENTS"/*.md; do
  [ -e "$f" ] || continue
  b="$(basename "$f")"
  [ "$b" = "README.md" ] && continue
  if frontmatter_ok "$f"; then check PASS "Agent: $b" "frontmatter valid (name + description)"
  else check FAIL "Agent: $b" "missing name/description in frontmatter"; fi
done
for f in "$SKILLS"/*/SKILL.md; do
  [ -e "$f" ] || continue
  b="$(basename "$(dirname "$f")")/SKILL.md"
  if frontmatter_ok "$f"; then check PASS "Skill: $b" "frontmatter valid (name + description)"
  else check FAIL "Skill: $b" "missing name/description in frontmatter"; fi
done
end_section

# ════════════════════════════════════════════════════════════════════════
# LAYER C — Brain scaffolding
# ════════════════════════════════════════════════════════════════════════
begin_section "Brain Scaffolding"
[ -s "$BRAIN/wiki/index.md" ] && check PASS "Wiki index" "brain/wiki/index.md present" || check FAIL "Wiki index" "brain/wiki/index.md missing or empty"
YEAR=$(date +%G); WEEK=$(date +%V)
WEEK_NOTE="$BRAIN/weekly_logs/${YEAR}/${YEAR}-W${WEEK}.md"
[ -s "$WEEK_NOTE" ] && check PASS "Current weekly note" "${YEAR}-W${WEEK}.md present" || check WARN "Current weekly note" "${YEAR}-W${WEEK}.md missing (run monday_init.sh)"
MASTER_NOTE="$BRAIN/weekly_logs/${YEAR} Master Note.md"
if [ -s "$MASTER_NOTE" ]; then
  if grep -qF '<!-- WEEKLY-INDEX-INSERT -->' "$MASTER_NOTE"; then
    check PASS "Master Note sentinel" "<!-- WEEKLY-INDEX-INSERT --> present in ${YEAR} Master Note.md"
  else
    check FAIL "Master Note sentinel" "<!-- WEEKLY-INDEX-INSERT --> missing from ${YEAR} Master Note.md"
  fi
else
  check FAIL "Master Note" "${YEAR} Master Note.md missing or empty"
fi
end_section

# ════════════════════════════════════════════════════════════════════════
# LAYER D — Provider configuration (read-only)
# ════════════════════════════════════════════════════════════════════════
begin_section "Provider Configuration"
HC_ENABLED="${AGENTIC_LIGHT_PROVIDERS:-$(config_value PROVIDERS)}"
HC_PRIORITY="${AGENTIC_LIGHT_PRIORITY:-$(config_value PRIORITY)}"
[ -n "$HC_ENABLED" ] || HC_ENABLED="claude,gemini,codex,ollama"
[ -n "$HC_PRIORITY" ] || HC_PRIORITY="$HC_ENABLED"
if validate_provider_lists "$HC_ENABLED" "$HC_PRIORITY"; then
  check PASS "Provider lists" "priority is an exact ordering of enabled providers"
  if resolve_agent_provider >/dev/null 2>&1; then
    check PASS "Provider executable" "$AGENT_PROVIDER: $AGENT_COMMAND"
  else
    check FAIL "Provider executable" "no enabled provider executable found"
  fi
else
  check FAIL "Provider lists" "unknown, duplicate, or mismatched enabled/priority entries"
fi
end_section

# ════════════════════════════════════════════════════════════════════════
# LAYER E — Pipeline log recency (informational — fresh scaffold has none yet)
# ════════════════════════════════════════════════════════════════════════
begin_section "Pipeline Logs"
PLOGS="$PIPELINE/logs"
if [ -d "$PLOGS" ]; then
  lcount=$(find "$PLOGS" -maxdepth 1 -type f -name '*.log' 2>/dev/null | wc -l | tr -d ' ')
  if [ "$lcount" -eq 0 ]; then
    check WARN "Pipeline run logs" "no .log files yet in pipeline/logs/ — expected on a fresh scaffold, run pipeline/run.sh"
  else
    check PASS "Pipeline run logs" "${lcount} log file(s) present"
  fi
else
  check FAIL "Pipeline logs dir" "pipeline/logs/ missing"
fi
end_section

# ════════════════════════════════════════════════════════════════════════
# LAYER F — Doc currency (self-heals the microsite via gen_site.py)
# ════════════════════════════════════════════════════════════════════════
begin_section "Documentation Currency"
PRE_WARN=$WARN_N; PRE_FAIL=$FAIL_N
doc_check "System_Config/README" "$SYSCFG/README.md" "$SYSCFG"/*.sh "$SYSCFG/gen_site.py"
doc_check "brain/README" "$BRAIN/README.md" "$BRAIN/CLAUDE.md" "$SYSCFG/monday_init.sh" "$SYSCFG/friday_process.sh" "$SYSCFG/daily_ingest.sh"

if command -v python3 >/dev/null 2>&1; then
  if python3 "$SYSCFG/gen_site.py" --check >/dev/null 2>&1; then
    check PASS "microsite/index.html" "up to date with agents/skills frontmatter"
  else
    check WARN "microsite/index.html" "stale vs agents/skills frontmatter"
  fi
  if python3 "$SYSCFG/gen_preset_pages.py" --check >/dev/null 2>&1; then
    check PASS "microsite/presets/*.html" "up to date with presets.json"
  else
    check WARN "microsite/presets/*.html" "stale vs presets.json"
  fi
else
  check WARN "microsite/index.html" "python3 not found — cannot verify currency"
  check WARN "microsite/presets/*.html" "python3 not found — cannot verify currency"
fi

if [ "$WARN_N" -gt "$PRE_WARN" ] || [ "$FAIL_N" -gt "$PRE_FAIL" ]; then
  if command -v python3 >/dev/null 2>&1; then
    if GEN_OUT=$(python3 "$SYSCFG/gen_site.py" 2>&1); then
      check PASS "Self-heal: gen_site.py" "$(printf '%s' "$GEN_OUT" | tr '\n' ' ')"
    else
      check FAIL "Self-heal: gen_site.py" "regeneration failed: $(printf '%s' "$GEN_OUT" | tr '\n' ' ')"
    fi
    if GEN_OUT=$(python3 "$SYSCFG/gen_preset_pages.py" 2>&1); then
      check PASS "Self-heal: gen_preset_pages.py" "$(printf '%s' "$GEN_OUT" | tr '\n' ' ')"
    else
      check FAIL "Self-heal: gen_preset_pages.py" "regeneration failed: $(printf '%s' "$GEN_OUT" | tr '\n' ' ')"
    fi
  else
    check WARN "Self-heal: gen_site.py" "skipped — python3 not found"
    check WARN "Self-heal: gen_preset_pages.py" "skipped — python3 not found"
  fi
fi

# CLAUDE.md Directory Map vs actual System_Config/ contents (structural diff,
# not a markdown-tree parser — tokenize the fenced tree, compare filenames).
MAP_SC=$(awk '/^├── System_Config\//{f=1; next} f && /^├── [a-zA-Z]/{exit} f' "$WORKSPACE/CLAUDE.md" \
  | tr -cs 'A-Za-z0-9._-' '\n' | grep -E '\.(sh|py|json)$' | sort -u)
DISK_SC=$(ls "$SYSCFG" 2>/dev/null | grep -E '\.(sh|py|json)$' | grep -vx 'agent-roster.json' | sort -u)
SC_DRIFT=$(comm -3 <(printf '%s\n' "$DISK_SC") <(printf '%s\n' "$MAP_SC") | tr -d '\t' | tr '\n' ' ' | sed 's/ *$//')
if [ -n "$SC_DRIFT" ]; then
  check WARN "CLAUDE.md Directory Map" "System_Config/ drift vs disk: $SC_DRIFT"
else
  check PASS "CLAUDE.md Directory Map" "matches System_Config/ contents"
fi
end_section

# ════════════════════════════════════════════════════════════════════════
# LAYER G — Config security scan (AgentShield-lite, heads-up only)
# ════════════════════════════════════════════════════════════════════════
begin_section "Config Security Scan"

# secret_pattern_files — the project's own config surface: shell/json config
# plus any .env-shaped file. *.example / *.defaults.json are templates by
# convention (placeholder values, meant to be committed) and are excluded.
SECRET_SCAN_FILES=""
for f in "$SYSCFG"/*.sh "$SYSCFG"/*.json "$WORKSPACE"/.mcp.json; do
  [ -f "$f" ] || continue
  case "$f" in *.example|*.defaults.json) continue ;; esac
  SECRET_SCAN_FILES="$SECRET_SCAN_FILES $f"
done
for f in $(find "$WORKSPACE" -maxdepth 2 -type f -name '.env*' 2>/dev/null) "$WORKSPACE/.agentic-light.conf"; do
  [ -f "$f" ] || continue
  case "$f" in *.example|*.defaults.json) continue ;; esac
  SECRET_SCAN_FILES="$SECRET_SCAN_FILES $f"
done

# looks_like_secret <file> — greps for common credential shapes. Tight,
# repo-specific pattern set (not a general secret scanner): known provider
# key prefixes, a bare "Bearer <token>", and *_KEY/*_TOKEN/*_SECRET vars
# assigned a non-placeholder-looking value (skips "", NULL-ish placeholders,
# and anything wrapped in <...> or starting with YOUR_/CHANGEME/xxx).
looks_like_secret() {
  grep -nE '(sk-[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{12,}|Bearer[[:space:]]+[A-Za-z0-9._-]{10,})' "$1" 2>/dev/null
  grep -nEi '[A-Z0-9_]*(KEY|TOKEN|SECRET)[[:space:]]*[:=][[:space:]]*"?[A-Za-z0-9_/+=.-]{8,}"?' "$1" 2>/dev/null \
    | grep -viE '=[[:space:]]*"?(null|none|changeme|your_|xxx|<.*>|\$\{)' \
    | grep -viE '(KEY|TOKEN|SECRET)_(ENUM|SCHEMA|NAME|FIELD)'
}

SECRET_HITS=0
for f in $SECRET_SCAN_FILES; do
  rel="${f#$WORKSPACE/}"
  # A real secret in a file .gitignore already covers is expected (local-only
  # config), not a finding — only WARN on a tracked (or untracked-but-not-
  # ignored) file so this layer stays quiet on the repo's normal template
  # files and only flags what could actually leak via a commit.
  if git -C "$WORKSPACE" check-ignore -q "$f" 2>/dev/null; then
    continue
  fi
  hit="$(looks_like_secret "$f" | head -1)"
  if [ -n "$hit" ]; then
    SECRET_HITS=$((SECRET_HITS + 1))
    check WARN "Possible secret: $rel" "$(printf '%s' "$hit" | cut -c1-120)"
  fi
done
[ "$SECRET_HITS" -eq 0 ] && check PASS "Config secret scan" "no likely-exposed secrets in tracked config surface"

# Documented-as-local-only files must actually be gitignored.
LOCAL_ONLY_FILES=".mcp.json .agentic-light.conf System_Config/.notify.env"
for rel in $LOCAL_ONLY_FILES; do
  f="$WORKSPACE/$rel"
  if git -C "$WORKSPACE" check-ignore -q "$f" 2>/dev/null; then
    check PASS "Gitignore: $rel" "covered by .gitignore"
  else
    check WARN "Gitignore: $rel" "documented as local-only but NOT covered by .gitignore"
  fi
done
end_section

# ════════════════════════════════════════════════════════════════════════
# WRITE status.json / status.js
# ════════════════════════════════════════════════════════════════════════
mkdir -p "$MICROSITE"
TMPJ="$(mktemp 2>/dev/null || echo "${OUT_JSON}.tmp")"
printf '{"generated":"%s","overall":"%s","pass":%d,"warn":%d,"fail":%d,"checks":[%s]}\n' \
  "$NOW_HUMAN" "$OVERALL" "$PASS_N" "$WARN_N" "$FAIL_N" "$JSON_ITEMS" > "$TMPJ"
mv "$TMPJ" "$OUT_JSON"

TMPS="$(mktemp 2>/dev/null || echo "${OUT_JS}.tmp")"
{ printf 'window.__STATUS__ = '; cat "$OUT_JSON"; printf ';\n'; } > "$TMPS"
mv "$TMPS" "$OUT_JS"

echo "================================================"
echo "Status: ${OVERALL} — ${PASS_N} pass / ${WARN_N} warn / ${FAIL_N} fail (of ${TOTAL})"
echo "Wrote ${OUT_JSON}"
echo "Wrote ${OUT_JS}"
echo "View: open ${MICROSITE}/health.html"

# Notify only on a non-clean result — a banner on every all-clear manual run
# would just be noise. notify.sh no-ops quietly if no channel is configured.
if [ "$OVERALL" != "PASS" ] && [ -r "$SYSCFG/notify.sh" ]; then
  bash "$SYSCFG/notify.sh" "Healthcheck: $OVERALL" \
    "${PASS_N} pass / ${WARN_N} warn / ${FAIL_N} fail (of ${TOTAL})" || true
fi
exit 0
