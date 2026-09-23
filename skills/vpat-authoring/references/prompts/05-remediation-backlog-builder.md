# Prompt 5: Remediation Backlog Builder (Stage: SYSTEMIZE)

Convert VPAT gaps into engineering tickets

## Use when

you need to hand engineering an actionable ticket list instead of a compliance document.

## Prompt

```
You are translating a VPAT into an engineering remediation backlog.

For every Partially Supports and Does Not Support row, generate tickets:

- TITLE: [WCAG {{criterion}}] concise defect statement
- AFFECTED: pages/components from the remarks
- USER IMPACT: who is blocked and how (lift directly from remarks)
- FIX GUIDANCE: the standard technique (reference WCAG technique IDs where they exist, e.g., G18, ARIA labels, focus-visible CSS)
- ACCEPTANCE CRITERIA: testable pass condition phrased so QA can verify without accessibility expertise
- EFFORT SIGNAL: S/M/L based on defect type (content fix = S, component CSS = M, architectural = L)

Group tickets by component/page when the same page appears under multiple criteria, so one engineer can fix a page once.

VPAT data:
{{PASTE_OR_ATTACH}}
```

## Output contract

Use ITI rating labels only: Supports, Partially Supports, Does Not Support, Not Applicable. Select exactly one conformance rating per row. Supports only when no known defects exist; defects are permitted with Partially Supports or Does Not Support. Every Remarks and Explanations entry states WHAT fails, WHO is affected, and WHERE it occurs. Return plain text without Markdown.

## Illustrative example (genericized)

**[WCAG 1.4.3] Placeholder text contrast below 4.5:1 in AI-assist input fields** — *Affected:* the cover-image-generation page; the document-generation page; the AI-assisted writing page; the AI-assisted rewrite page; the AI-assisted image page. *Impact:* people who are colorblind or have low vision may be unable to read placeholder text. *Fix:* adjust placeholder color to meet 4.5:1 against input background (WCAG technique G18); likely one shared component token. *Acceptance:* Color Contrast Analyzer reads ≥ 4.5:1 for placeholder-on-input across all five pages. *Effort:* S (single design token).

**[WCAG 2.4.7] Missing visual focus indicator on interactive elements** — *Affected:* the header; the template-creation page; the comment-add page; the comment-review page; the chart-insertion page; +9 more pages. *Impact:* sighted keyboard users cannot tell which element has focus. *Fix:* apply a global `:focus-visible` style meeting 3:1 non-text contrast; audit for `outline: none` overrides. *Acceptance:* tabbing through each listed page shows a visible indicator on every stop. *Effort:* M (global CSS + per-component overrides).
