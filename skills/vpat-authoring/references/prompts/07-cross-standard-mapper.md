# Prompt 7: Cross-Standard Mapper (WCAG → Section 508 / EN 301 549) (Stage: SHIP)

Map WCAG findings to Section 508 and EN 301 549 for government/EU procurements

## Use when

a client needs Section 508 or EN 301 549 language for a government/EU procurement, but your audit findings are organized by WCAG.

## Prompt

```
You are mapping WCAG 2.1 audit findings to their corresponding Revised Section 508 and EN 301 549 clauses for a {{US_FEDERAL / EU}} procurement response.

For each WCAG criterion result provided:
1. List the corresponding EN 301 549 clause(s) — Chapter 9 (Web) at minimum; include Chapters 10/11 clauses only if non-web documents or software are in scope
2. List the corresponding Revised Section 508 provision(s)
3. State whether the WCAG conformance level carries over directly to those clauses (for web content it does — EN 301 549 Ch. 9 and 508 §E205/501 incorporate WCAG 2.x A/AA by reference)
4. Flag criteria that are WCAG 2.1-only (2.1.4, 1.3.4, 1.3.5, 1.4.10–1.4.13, 2.5.1–2.5.4, 4.1.3) and note their treatment: included in EN 301 549 v3.x; NOT required under Section 508's WCAG 2.0 baseline — mark these "exceeds 508 baseline"

Scope of product: {{WEB / SOFTWARE / DOCS}}
Findings: {{PASTE_ROWS}}
```

## Output contract

Use ITI rating labels only: Supports, Partially Supports, Does Not Support, Not Applicable. Select exactly one conformance rating per row. Supports only when no known defects exist; defects are permitted with Partially Supports or Does Not Support. Every Remarks and Explanations entry states WHAT fails, WHO is affected, and WHERE it occurs. Return plain text without Markdown.

## Illustrative example (genericized)

**Test approach:** cross-checked against a published ACR's own printed "Also applies to" mappings for the same two criteria.

**1.1.1 Non-text Content (Partially Supports)** → EN 301 549: 9.1.1.1 (Web) [also 10.1.1.1, 11.1.1.1.1/.2, 11.8.2, 12.1.2, 12.2.4 if docs/software in scope] · Section 508: 501 (Web)(Software), 504.2 (Authoring Tool), 602.3 (Support Docs). Conformance carries over directly.
**1.4.10 Reflow (Does Not Support)** → EN 301 549: 9.1.4.10 (Web). **Exceeds 508 baseline** — WCAG 2.1-only criterion; not required under Section 508's WCAG 2.0 incorporation, but required for EN 301 549 v3.x / EU procurements. A US federal buyer cannot cite this row as a 508 failure; an EU buyer can.
