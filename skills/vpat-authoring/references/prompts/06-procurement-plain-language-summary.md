# Prompt 6: Procurement Plain-Language Summary (Stage: SHIP)

Write plain-language accessibility summary for procurement officers

## Use when

a buyer, procurement officer, or non-technical stakeholder asks "so is it accessible or not?"

## Prompt

```
You are writing a plain-language accessibility summary of a VPAT for a procurement audience with no WCAG knowledge. One page maximum.

Structure:
1. WHAT THIS PRODUCT IS and what was evaluated (from the VPAT header)
2. THE SHORT ANSWER: can it be used by people with disabilities today? Frame honestly — no legal conclusions, no "compliant/non-compliant" language.
3. WHO IS WELL-SERVED: which disability groups can use the product effectively, based on Supports rows.
4. WHO WILL HIT BARRIERS: which groups face obstacles and in which tasks — translate remarks into plain scenarios ("a keyboard-only user adding a comment may lose track of their place on screen").
5. QUESTIONS TO ASK THE VENDOR: 3-5 pointed follow-ups a buyer should raise, derived from the worst gaps.

Never invent findings not in the VPAT. Never soften "Does Not Support."

VPAT: {{PASTE_OR_ATTACH}}
```

## Output contract

Use ITI rating labels only: Supports, Partially Supports, Does Not Support, Not Applicable. Select exactly one conformance rating per row. Supports only when no known defects exist; defects are permitted with Partially Supports or Does Not Support. Every Remarks and Explanations entry states WHAT fails, WHO is affected, and WHERE it occurs. Return plain text without Markdown.

## Illustrative example (genericized)

**The short answer:** the reviewed product is broadly usable with assistive technology for core tasks, but users with low vision and keyboard-only users will encounter real obstacles, especially in newer AI-assisted features.
**Who will hit barriers:** People who magnify their screen to 400% will find content does not reflow — it requires scrolling in two directions, which the report itself classifies at its lowest rating (Reflow: Does Not Support). A keyboard-only user reviewing comments may lose track of where they are on screen, because the focus indicator disappears on pages like *the comment-add page* and *the comment-review page*.
**Questions to ask the vendor:** (1) What is the remediation timeline for Reflow (1.4.10), your only Does-Not-Support rating? (2) The AI-assisted features carry a disproportionate share of defects — are accessibility reviews gating new AI feature launches? (3) …
