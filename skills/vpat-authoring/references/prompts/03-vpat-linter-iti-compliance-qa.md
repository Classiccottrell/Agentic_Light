# Prompt 3: VPAT Linter (ITI Compliance QA) (Stage: SYSTEMIZE)

Check VPAT draft for errors before shipping

## Use when

a VPAT draft is done and you need to catch errors before it ships — the wrong conformance term, remarks that contradict the level, missing required sections.

## Prompt

```
You are a VPAT® QA reviewer enforcing ITI Essential Requirements for Authors (VPAT 2.5Rev).

Review the attached VPAT and flag every violation, organized by severity:

BLOCKING (report is non-compliant):
- Missing required sections: report title format, VPAT version, product/version, report date, product description, contact info, evaluation methods, applicable standards, terms definitions
- Non-ITI conformance terms used without a documented deviation note
- A criterion row missing either Conformance Level or Remarks

QUALITY (undermines defensibility):
- "Supports" paired with remarks describing known defects (contradiction)
- "Partially Supports" or "Does Not Support" with remarks that don't say WHAT fails, WHO is affected, or WHERE
- "Not Applicable" without a stated reason
- "Not Evaluated" used outside WCAG Level AAA (prohibited by ITI)
- Vague remarks ("mostly accessible", "some issues") with no specifics

For each flag: cite the row/section, quote the problem, state the fix.

VPAT to review:
{{PASTE_VPAT_OR_ATTACH}}
```

## Output contract

Use ITI rating labels only: Supports, Partially Supports, Does Not Support, Not Applicable. Select exactly one conformance rating per row. Supports only when no known defects exist; defects are permitted with Partially Supports or Does Not Support. Every Remarks and Explanations entry states WHAT fails, WHO is affected, and WHERE it occurs. Return plain text without Markdown.

## Illustrative example (genericized)

**BLOCKING: 0 findings.** All required header sections present (title, version 2.5Rev, product, date, contact, WCAG-EM methods, standards table, ITI terms definitions). All applicable A/AA rows have both a conformance level and remarks.
**QUALITY: 2 findings.**
1. *Terms section* — definition reads "Does not support: The majority of product functionality does not meet the criteria" — "criteria" should be singular "criterion" per ITI wording. Cosmetic, but exact-match deviations technically require a notes-section mention.
2. *Consistency note* — every "Not Applicable" row states its reason (e.g., 1.2.1: "Prerecorded audio-only files are not present") ✓ — no fix needed; flagged as verified-pass.
