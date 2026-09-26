#!/usr/bin/env python3
"""vpat_lint_gate.py — VPAT draft lint gate. Checks the target repo's VPAT
draft (accessibility/vpat-draft.json by default; VPAT_DRAFT_PATH overrides,
repo-root-relative) against 6 deterministic, regex/structural rules — see
skills/vpat-authoring/references/lint-rules.md. No draft file found -> WARN
+ skip. Draft present and violates a rule -> hard stop.

No python3-availability check needed (this gate script IS Python now —
bash's `command -v python3` guard is structurally impossible to trigger).
Usage: vpat_lint_gate.py <target-repo-path>
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

ITI_LABELS = {"Supports", "Partially Supports", "Does Not Support", "Not Applicable"}
DEFECT_WORDS = ["fail", "missing", "violat", "defect", "bug", "lacks", "lack of",
                "broken", "inaccessible", "not accessible", "unsupported"]
NEAR_MISS_LABELS = ["compliant", "non-compliant", "noncompliant", "fully supports",
                     "does not comply", "complies"]
MD_PATTERN = re.compile(r"\*\*|##|```|(^|\n)[\-\*]\s")


class LintFailure(Exception):
    pass


def fail(msg):
    raise LintFailure(msg)


def lint(draft_path):
    try:
        data = json.loads(draft_path.read_text(encoding="utf-8"))
    except Exception as e:
        fail(f"{draft_path} is not valid JSON: {e}")

    # --- schema-shape precondition ---
    required_top = {"schema_version", "product", "report", "evaluation_methods", "criteria", "limitations"}
    if not isinstance(data, dict) or not required_top.issubset(data.keys()):
        present = set(data.keys()) if isinstance(data, dict) else set()
        fail(f"{draft_path} missing required top-level keys: {sorted(required_top - present)}")
    report = data.get("report")
    if not isinstance(report, dict) or not all(isinstance(report.get(k), str) and report.get(k).strip() for k in ("title", "version", "date")):
        fail(f'{draft_path} "report" must have non-empty string title/version/date')
    limitations = data.get("limitations")
    if not isinstance(limitations, list) or not limitations or not all(isinstance(x, str) and x.strip() for x in limitations):
        fail(f'{draft_path} "limitations" must be a non-empty array of non-empty strings')
    criteria = data.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        fail(f'{draft_path} "criteria" must be a non-empty array')
    for i, c in enumerate(criteria):
        if not isinstance(c, dict):
            fail(f"criteria[{i}] must be an object")
        for key in ("id", "name", "level", "rating", "remarks"):
            if key not in c or not isinstance(c[key], str) or not c[key].strip():
                fail(f"criteria[{i}] missing or empty required field {key!r}")

    # --- rule 1: iti_terms_only ---
    for i, c in enumerate(criteria):
        if c["rating"] not in ITI_LABELS:
            fail(f"rule iti_terms_only: criteria[{i}] ({c['id']}) rating {c['rating']!r} is not one of {sorted(ITI_LABELS)}")
        remarks_lc = c["remarks"].lower()
        for term in NEAR_MISS_LABELS:
            if term in remarks_lc:
                fail(f"rule iti_terms_only: criteria[{i}] ({c['id']}) remarks contains non-standard term {term!r}")

    # --- rule 2: single_conformance_rating (one rating per row, no duplicate IDs) ---
    seen_ids = {}
    for i, c in enumerate(criteria):
        if c["id"] in seen_ids:
            fail(f"rule single_conformance_rating: criterion id {c['id']!r} appears more than once (rows {seen_ids[c['id']]} and {i})")
        seen_ids[c["id"]] = i

    # --- rule 3: no_supports_contradiction ---
    for i, c in enumerate(criteria):
        if c["rating"] == "Supports":
            remarks_lc = c["remarks"].lower()
            for word in DEFECT_WORDS:
                if word in remarks_lc:
                    fail(f"rule no_supports_contradiction: criteria[{i}] ({c['id']}) rated Supports but remarks contains defect word {word!r}")

    # --- rule 4: structured_remarks (rating-aware, per the assembler's own contract) ---
    for i, c in enumerate(criteria):
        rating, remarks = c["rating"], c["remarks"]
        if rating == "Not Applicable":
            if "Why:" not in remarks:
                fail(f'rule structured_remarks: criteria[{i}] ({c["id"]}) is Not Applicable but remarks has no "Why:" marker')
        elif rating == "Supports":
            if "Evidence:" not in remarks:
                fail(f'rule structured_remarks: criteria[{i}] ({c["id"]}) is Supports but remarks has no "Evidence:" marker (state the evidence and evaluated scope)')
        else:
            for marker in ("What:", "Who:", "Where:"):
                if marker not in remarks:
                    fail(f"rule structured_remarks: criteria[{i}] ({c['id']}) remarks missing {marker!r} marker")

    # --- rule 5: no_markdown_leak ---
    for i, c in enumerate(criteria):
        if MD_PATTERN.search(c["remarks"]):
            fail(f"rule no_markdown_leak: criteria[{i}] ({c['id']}) remarks contains Markdown syntax")
    for i, item in enumerate(limitations):
        if MD_PATTERN.search(item):
            fail(f"rule no_markdown_leak: limitations[{i}] contains Markdown syntax")

    # --- rule 6: automated_evidence_cap (Agentic Light addition — operationalizes
    # "automated scan alone never proves Supports/Does Not Support") ---
    for i, c in enumerate(criteria):
        if c.get("evidence") == "automated" and c["rating"] in ("Supports", "Does Not Support"):
            fail(f"rule automated_evidence_cap: criteria[{i}] ({c['id']}) rated {c['rating']!r} from automated-only evidence — cap is Partially Supports or Not Applicable")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("target_repo")
    args = parser.parse_args()
    target = Path(args.target_repo)
    draft_rel = os.environ.get("VPAT_DRAFT_PATH", "accessibility/vpat-draft.json")
    draft_path = target / draft_rel
    manual_ref = "skills/vpat-authoring/SKILL.md (in the Agentic Light workspace)"

    if not draft_path.is_file():
        print(f"[vpat_lint_gate] WARN — no VPAT draft found at {draft_rel} (override with VPAT_DRAFT_PATH); see {manual_ref}. Skipping.")
        return 0

    try:
        lint(draft_path)
    except LintFailure as e:
        print(f"[vpat_lint_gate] FAIL — {e}")
        print(f"[vpat_lint_gate] FAIL — {draft_rel} failed lint (see rule output above)")
        return 1

    print("[vpat_lint_gate] all rules passed: iti_terms_only, single_conformance_rating, "
          "no_supports_contradiction, structured_remarks, no_markdown_leak, automated_evidence_cap")
    print(f"[vpat_lint_gate] PASS — {draft_rel} passes structural + ITI-discipline lint "
          "(proves syntax, not semantic accuracy — human review still required)")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
