# Prompt 1: Findings-to-VPAT Row Writer (Stage: SCAN)

Convert raw audit findings to ITI-compliant VPAT rows

## Use when

you have raw audit findings (axe DevTools output, tester notes, screen reader session logs) and need ITI-compliant VPAT rows.

## Prompt

```
You are an accessibility documentation specialist writing VPAT® 2.5 conformance rows per ITI Essential Requirements.

For each raw finding below, produce a VPAT row with:
1. WCAG 2.1 success criterion (number, name, level)
2. Conformance Level using ITI terms only: Supports / Partially Supports / Does Not Support / Not Applicable
3. Remarks and Explanations that follow the professional pattern:
   - Open with what DOES work ("Most X have/do Y...")
   - Then "The following exceptions exist:" with a bullet per defect
   - Each bullet states: the defect, WHO it affects and HOW ("so people who [disability context] will [impact]"), and WHERE it occurs ("This occurs on the following page(s): ...")

Rules:
- "Supports" only if no known defects for that criterion
- "Partially Supports" if some functionality fails; "Does Not Support" if the majority fails
- Never editorialize severity in remarks; state facts and user impact
- One row per criterion, consolidating multiple findings under it

Raw findings:
{{PASTE_FINDINGS}}

Product/context: {{PRODUCT_NAME_AND_SCOPE}}
```

## Output contract

Use ITI rating labels only: Supports, Partially Supports, Does Not Support, Not Applicable. Select exactly one conformance rating per row. Supports only when no known defects exist; defects are permitted with Partially Supports or Does Not Support. Every Remarks and Explanations entry states WHAT fails, WHO is affected, and WHERE it occurs. Return plain text without Markdown.

## Illustrative example (genericized)

**1.1.1 Non-text Content (Level A)** — Partially Supports
Most non-text content has text alternatives or a text alternative that serves an equivalent purpose. The following exceptions exist:
- A complex image does not have a text alternative, so people who are blind and/or use a screen reader will not be able to understand the information available in the image. This occurs on the following page: the chart-insertion page.
- A decorative image is not hidden from screen readers, so people who are blind and/or use a screen reader will have to navigate through unnecessary and duplicative text. This occurs on the following page: the document-generation page.
