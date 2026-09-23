#!/usr/bin/env bash
# vpat_lint_gate.sh — VPAT draft lint gate. Checks the target repo's VPAT
# draft (accessibility/vpat-draft.json by default; VPAT_DRAFT_PATH overrides,
# repo-root-relative) against 6 deterministic, regex/structural rules — see
# skills/vpat-authoring/references/lint-rules.md. No draft file found -> WARN
# + skip. Draft present and violates a rule -> hard stop.
# Usage: vpat_lint_gate.sh <target-repo-path>
set -euo pipefail

TARGET="${1:?usage: vpat_lint_gate.sh <target-repo-path>}"
cd "$TARGET"

DRAFT_PATH="${VPAT_DRAFT_PATH:-accessibility/vpat-draft.json}"
MANUAL_REF="skills/vpat-authoring/SKILL.md (in the Agentic Light workspace)"

if [ ! -f "$DRAFT_PATH" ]; then
  echo "[vpat_lint_gate] WARN — no VPAT draft found at $DRAFT_PATH (override with VPAT_DRAFT_PATH); see $MANUAL_REF. Skipping."
  exit 0
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "[vpat_lint_gate] FAIL — $DRAFT_PATH exists but python3 is not available to lint it."
  exit 1
fi

if python3 - "$DRAFT_PATH" <<'PYEOF'
import json, re, sys

path = sys.argv[1]
ITI_LABELS = {"Supports", "Partially Supports", "Does Not Support", "Not Applicable"}
DEFECT_WORDS = ["fail", "missing", "violat", "defect", "bug", "lacks",
                "lack of", "broken", "inaccessible", "not accessible",
                "unsupported"]
NEAR_MISS_LABELS = ["compliant", "non-compliant", "noncompliant",
                     "fully supports", "does not comply", "complies"]
MD_PATTERN = re.compile(r"\*\*|##|```|(^|\n)[\-\*]\s")

def fail(msg):
    print("[vpat_lint_gate] FAIL — %s" % msg)
    sys.exit(1)

try:
    with open(path) as f:
        data = json.load(f)
except Exception as e:
    fail("%s is not valid JSON: %s" % (path, e))

# --- schema-shape precondition ---
required_top = {"schema_version", "product", "report", "evaluation_methods", "criteria", "limitations"}
if not isinstance(data, dict) or not required_top.issubset(data.keys()):
    fail("%s missing required top-level keys: %s" % (path, sorted(required_top - set(data if isinstance(data, dict) else {}))))
report = data.get("report")
if not isinstance(report, dict) or not all(isinstance(report.get(k), str) and report.get(k).strip() for k in ("title", "version", "date")):
    fail("%s \"report\" must have non-empty string title/version/date" % path)
limitations = data.get("limitations")
if not isinstance(limitations, list) or not limitations or not all(isinstance(x, str) and x.strip() for x in limitations):
    fail("%s \"limitations\" must be a non-empty array of non-empty strings" % path)
criteria = data.get("criteria")
if not isinstance(criteria, list) or not criteria:
    fail("%s \"criteria\" must be a non-empty array" % path)
for i, c in enumerate(criteria):
    if not isinstance(c, dict):
        fail("criteria[%d] must be an object" % i)
    for key in ("id", "name", "level", "rating", "remarks"):
        if key not in c or not isinstance(c[key], str) or not c[key].strip():
            fail("criteria[%d] missing or empty required field %r" % (i, key))

# --- rule 1: iti_terms_only ---
for i, c in enumerate(criteria):
    if c["rating"] not in ITI_LABELS:
        fail("rule iti_terms_only: criteria[%d] (%s) rating %r is not one of %s" % (i, c["id"], c["rating"], sorted(ITI_LABELS)))
    remarks_lc = c["remarks"].lower()
    for term in NEAR_MISS_LABELS:
        if term in remarks_lc:
            fail("rule iti_terms_only: criteria[%d] (%s) remarks contains non-standard term %r" % (i, c["id"], term))

# --- rule 2: single_conformance_rating (one rating per row, no duplicate IDs) ---
seen_ids = {}
for i, c in enumerate(criteria):
    if c["id"] in seen_ids:
        fail("rule single_conformance_rating: criterion id %r appears more than once (rows %d and %d)" % (c["id"], seen_ids[c["id"]], i))
    seen_ids[c["id"]] = i

# --- rule 3: no_supports_contradiction ---
for i, c in enumerate(criteria):
    if c["rating"] == "Supports":
        remarks_lc = c["remarks"].lower()
        for word in DEFECT_WORDS:
            if word in remarks_lc:
                fail("rule no_supports_contradiction: criteria[%d] (%s) rated Supports but remarks contains defect word %r" % (i, c["id"], word))

# --- rule 4: structured_remarks (rating-aware, per the assembler's own contract) ---
for i, c in enumerate(criteria):
    rating, remarks = c["rating"], c["remarks"]
    if rating == "Not Applicable":
        if "Why:" not in remarks:
            fail("rule structured_remarks: criteria[%d] (%s) is Not Applicable but remarks has no \"Why:\" marker" % (i, c["id"]))
    elif rating == "Supports":
        if "Evidence:" not in remarks:
            fail("rule structured_remarks: criteria[%d] (%s) is Supports but remarks has no \"Evidence:\" marker (state the evidence and evaluated scope)" % (i, c["id"]))
    else:
        for marker in ("What:", "Who:", "Where:"):
            if marker not in remarks:
                fail("rule structured_remarks: criteria[%d] (%s) remarks missing %r marker" % (i, c["id"], marker))

# --- rule 5: no_markdown_leak ---
for i, c in enumerate(criteria):
    if MD_PATTERN.search(c["remarks"]):
        fail("rule no_markdown_leak: criteria[%d] (%s) remarks contains Markdown syntax" % (i, c["id"]))
for i, item in enumerate(limitations):
    if MD_PATTERN.search(item):
        fail("rule no_markdown_leak: limitations[%d] contains Markdown syntax" % i)

# --- rule 6: automated_evidence_cap (Agentic Light addition — operationalizes
# "automated scan alone never proves Supports/Does Not Support") ---
for i, c in enumerate(criteria):
    if c.get("evidence") == "automated" and c["rating"] in ("Supports", "Does Not Support"):
        fail("rule automated_evidence_cap: criteria[%d] (%s) rated %r from automated-only evidence — cap is Partially Supports or Not Applicable" % (i, c["id"], c["rating"]))

print("[vpat_lint_gate] all rules passed: iti_terms_only, single_conformance_rating, no_supports_contradiction, structured_remarks, no_markdown_leak, automated_evidence_cap")
PYEOF
then
  echo "[vpat_lint_gate] PASS — $DRAFT_PATH passes structural + ITI-discipline lint (proves syntax, not semantic accuracy — human review still required)"
  exit 0
else
  rc=$?
  echo "[vpat_lint_gate] FAIL — $DRAFT_PATH failed lint (see rule output above)"
  exit "$rc"
fi
