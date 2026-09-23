# Prompt 9: Final VPAT Report Assembler (Stage: SHIP)

Assemble reviewed VPAT rows and metadata into renderer-ready report JSON

## Use when

reviewed VPAT rows and report metadata markers are ready for a renderer-ready report file.

## Prompt

```
You are assembling a final VPAT report from reviewed VPAT rows and report metadata markers.

Precondition: every reviewed criterion must already provide a rating and rating-aware remarks:
- Partially Supports and Does Not Support: state WHAT fails, WHO is affected, and WHERE it occurs.
- Supports: state the evidence and evaluated scope supporting the rating.
- Not Applicable: state the reason and scope.
If a reviewed row or required metadata is absent or invalid, reject or flag the input for human correction; do not rewrite approved evidence or fabricate a value.

Return JSON only: no Markdown, code fences, commentary, or additional top-level keys. The JSON object must contain exactly these keys:
- "schema_version": a non-empty string
- "product": an object with non-empty product.name
- "report": an object with non-empty report.title, report.version, and report.date
- "evaluation_methods"
- "criteria"
- "limitations"

evaluation_methods and limitations must be arrays. criteria must be an array, and each criterion object must contain id, name, level, rating, and remarks. Each rating must be exactly one ITI label: Supports, Partially Supports, Does Not Support, or Not Applicable.

Preserve every reviewed criterion ID, name, level, rating, and remarks exactly. Do not invent, infer, revise, summarize, or omit findings, ratings, remarks, evaluation methods, or limitations.

The output must match vpat-report.schema.json and is input for `python3 vpat-optimizer/scripts/render_vpat.py input.json output.html`. A human must review the JSON against the source evidence and current ITI instructions before rendering or distribution.

Reviewed VPAT rows:
{{REVIEWED_VPAT_ROWS_JSON}}

Report metadata markers:
{{REPORT_METADATA_MARKERS_JSON}}
```

## Output contract

Use ITI rating labels only: Supports, Partially Supports, Does Not Support, Not Applicable. Select exactly one conformance rating per row. Supports only when no known defects exist. For Partially Supports and Does Not Support, remarks must state WHAT fails, WHO is affected, and WHERE it occurs. For Supports, remarks must state the evidence and evaluated scope supporting the rating. For Not Applicable, remarks must state the reason and scope. Return JSON only without Markdown.

Note: the prompt text above references `vpat-optimizer/scripts/render_vpat.py`, a renderer that does not exist in this workspace. This repo's own renderer-adjacent asset is `references/vpat-report-template.html` (a `{{PLACEHOLDER}}`-substitution HTML template) — use that to render the assembled JSON instead.

## Illustrative example (genericized)

```json
{
  "schema_version": "1.0",
  "product": { "name": "the reviewed product", "version": "1.0.0" },
  "report": { "title": "the reviewed product Accessibility Conformance Report", "version": "2.5Rev", "date": "2026-09-22" },
  "evaluation_methods": ["axe-core automated scan", "manual keyboard pass"],
  "criteria": [
    {
      "id": "1.4.3",
      "name": "Contrast (Minimum)",
      "level": "AA",
      "rating": "Partially Supports",
      "remarks": "Most text meets the required ratio. What: placeholder text renders at 3.2:1 contrast, below the 4.5:1 minimum. Who: low-vision users reading affected fields. Where: the settings page.",
      "evidence": "automated"
    }
  ],
  "limitations": ["This document is not an automated accessibility audit, certification, legal opinion, or guarantee of conformance to WCAG, Section 508, EN 301 549, or any other standard. It does not replace manual testing, qualified accessibility review, current ITI VPAT instructions, or legal advice."]
}
```
