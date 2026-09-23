# Prompt 4: Gap Analysis & Executive Summary (Stage: SYSTEMIZE)

Analyze VPAT conformance posture for stakeholders

## Use when

the VPAT is complete and stakeholders need to understand the conformance posture without reading every row.

## Prompt

```
You are an accessibility strategist. Analyze the attached VPAT and produce an executive gap analysis:

1. CONFORMANCE SNAPSHOT: counts by conformance level, split by WCAG Level A vs. AA. State plainly whether the product can claim WCAG 2.1 AA conformance (it cannot if any A or AA criterion is below Supports).
2. GAPS BY PRINCIPLE: group Partially Supports + Does Not Support by POUR principle (Perceivable, Operable, Understandable, Robust) to show where the product structurally struggles.
3. HOTSPOTS: which pages/components appear most often across defect remarks — these are the highest-leverage fixes.
4. SEVERITY TIERING: tier the gaps by user impact — Tier 1: blocks task completion for a user group; Tier 2: significant friction; Tier 3: inconvenience.
5. THE ONE-PARAGRAPH VERDICT: what a procurement officer should take away.

VPAT data:
{{PASTE_OR_ATTACH}}
```

## Output contract

Use ITI rating labels only: Supports, Partially Supports, Does Not Support, Not Applicable. Select exactly one conformance rating per row. Supports only when no known defects exist; defects are permitted with Partially Supports or Does Not Support. Every Remarks and Explanations entry states WHAT fails, WHO is affected, and WHERE it occurs. Return plain text without Markdown.

## Illustrative example (genericized)

**Snapshot:** 20 Supports, 23 Partially Supports, 1 Does Not Support, 6 Not Applicable. Gaps split 14 Level A / 10 Level AA. **The reviewed product cannot claim WCAG 2.1 AA conformance** — 24 of 50 applicable criteria fall below Supports, including core Level A criteria (Keyboard 2.1.1, Name/Role/Value 4.1.2).
**By principle:** Perceivable 10 gaps · Operable 9 · Understandable 3 · Robust 2. The product's weakness is concentrated in visual presentation (contrast, reflow, text spacing) and keyboard/focus interaction — a classic pattern for feature-dense editor UIs.
**Hotspots (defect citations per page):** the comment-review page (11), the AI-assist panel (9), the chart-insertion page (8), the version-history page (8), the accessibility-scan page (7). The newest AI-assisted surfaces are disproportionately represented — newest features carry the most debt.
**Tier 1:** 1.4.10 Reflow (Does Not Support — content unusable at 400% zoom for low-vision users), 2.1.1 Keyboard, 4.1.2 Name/Role/Value.
