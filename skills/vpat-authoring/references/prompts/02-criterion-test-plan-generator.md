# Prompt 2: Criterion Test Plan Generator (Stage: SCAN)

Plan the audit for a given criterion and capture evidence

## Use when

you're planning the audit itself and need to know exactly what to test and what evidence to capture for a given criterion.

## Prompt

```
You are planning a WCAG 2.1 audit following WCAG-EM methodology.

For success criterion {{CRITERION_NUMBER_AND_NAME}}, produce a test plan for {{PRODUCT_TYPE}}:

1. WHAT TO TEST: the specific UI patterns and interactions this criterion applies to in this product type
2. HOW TO TEST: exact steps using (a) manual inspection, (b) automated tooling (name the tool and rule ID where applicable, e.g., axe rules), (c) assistive technology (specify AT + browser pairing)
3. EVIDENCE TO CAPTURE: what screenshots, code snippets, or AT output to save so the VPAT remark is defensible
4. PASS/FAIL DECISION RULE: what observed result maps to Supports vs. Partially Supports vs. Does Not Support
5. COMMON FALSE POSITIVES: what looks like a failure but isn't

Test page inventory: {{LIST_OF_PAGES_OR_FLOWS}}
```

## Output contract

Use ITI rating labels only: Supports, Partially Supports, Does Not Support, Not Applicable. Select exactly one conformance rating per row. Supports only when no known defects exist; defects are permitted with Partially Supports or Does Not Support. Every Remarks and Explanations entry states WHAT fails, WHO is affected, and WHERE it occurs. Return plain text without Markdown.

## Illustrative example (genericized)

**2.4.7 Focus Visible (Level AA) — Test Plan for a web document editor**
**What to test:** every interactive element reachable by Tab/Shift+Tab — toolbar buttons, dialog controls, comment threads, menu items, inline suggestion chips.
**How:** (a) Tab through each flow in a current browser with default styles; watch for elements where focus visually disappears. (b) Automated tooling has limited reach here — this criterion is primarily manual. (c) A screen reader + browser pairing to confirm focus location when the indicator is absent (assistive tech announces focus the eye can't see — that's the failure signature).
**Evidence:** screenshot pairs — element focused vs. unfocused — plus the DOM node's computed `outline`/`box-shadow`.
**Decision rule:** any interactive element with no or invisible indicator → Partially Supports; if most of the tab order is invisible → Does Not Support.
