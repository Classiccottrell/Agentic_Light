# Prompt 8: Axe Scan → VPAT Row Converter (Stage: SHIP)

Convert axe-core JSON scan results to draft ITI-compliant VPAT rows

## Use when

you (or a buyer) ran a free automated scan — axe DevTools, `npx @axe-core/cli <url>`, or Lighthouse — and want the JSON output converted into draft ITI-compliant VPAT rows. This replaces a custom scanning CLI with zero code to maintain: free scanner does the scan, this prompt does the judgment and documentation.

## Prompt

```
You are converting raw axe-core JSON scan results into draft VPAT® 2.5 rows.

Process:
1. MAP each violation to its WCAG 2.1 success criterion using the axe "tags" field (e.g., wcag143 → 1.4.3 Contrast (Minimum); wcag111 → 1.1.1 Non-text Content; wcag412 → 4.1.2 Name, Role, Value).
2. CONSOLIDATE: multiple violations under one criterion become one row with one exception bullet per distinct defect pattern.
3. WRITE each row in the professional pattern:
   - Conformance Level: Partially Supports (automated scans cannot establish "the majority fails" — never output Does Not Support from scan data alone)
   - Remarks open with what works, then "The following exceptions exist:" with per-defect bullets stating the defect, who it affects and how, and where it occurs (use the scanned URL/page name)
   - Include the specific measured values from failureSummary (e.g., actual contrast ratio) — this is what makes the row defensible
4. FLAG THE LIMITS — end with a mandatory caveat block:
   - Criteria this scan CANNOT clear: list criteria with no violations but which require manual testing (keyboard traps, focus order, focus visibility, meaningful sequence, error identification). A clean automated scan NEVER justifies "Supports."
   - Mark every generated row "DRAFT — pending manual verification."

Axe JSON:
{{PASTE_AXE_JSON}}

Page name(s) for the scanned URL(s): {{PAGE_NAMES}}
```

## Output contract

Use ITI rating labels only: Supports, Partially Supports, Does Not Support, Not Applicable. Select exactly one conformance rating per row. Supports only when no known defects exist; defects are permitted with Partially Supports or Does Not Support. Every Remarks and Explanations entry states WHAT fails, WHO is affected, and WHERE it occurs. Return plain text without Markdown.

## Illustrative example (genericized)

**1.4.3 Contrast (Minimum) (Level AA)** — Partially Supports *(DRAFT — pending manual verification)*
Most text and images of text have the required color contrast ratio with their backgrounds. The following exceptions exist:
- The color contrast ratio between placeholder text in an input and the input's background is 3.1:1, below the required 4.5:1, so people who are colorblind or have low vision may have difficulty reading the placeholder text. This occurs on the following page: the document-generation page.

**⚠ Scan limits:** this automated scan cannot clear 2.1.1 Keyboard, 2.1.2 No Keyboard Trap, 2.4.3 Focus Order, 2.4.7 Focus Visible, 1.3.2 Meaningful Sequence, or 3.3.1 Error Identification. Absence of violations for these criteria is not evidence of support — manual testing required before any "Supports" rating.
