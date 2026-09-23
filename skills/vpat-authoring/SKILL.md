---
name: vpat-authoring
description: Use when drafting, reviewing, or lint-checking a VPAT / Accessibility Conformance Report (ACR) against the ITI VPAT 2.5Rev template - converting axe-core or manual WCAG findings into ITI-labeled conformance rows, writing WHAT/WHO/WHERE remarks, assembling accessibility/vpat-draft.json for the vpat-lint gate, or preparing gap analysis, remediation backlogs, procurement summaries, or Section 508/EN 301 549 mappings from a finished VPAT. Companion to wcag-audit: wcag-audit finds defects, vpat-authoring documents them in ITI-compliant language.
---

# VPAT / ACR Authoring (ITI 2.5Rev discipline)

## Overview

`wcag-audit` finds accessibility defects. This skill turns those findings
into a VPAT / Accessibility Conformance Report a customer or procurement
reviewer can actually read — ITI VPAT 2.5Rev conformance language, not raw
scan output. Organized Scan → Systemize → Ship: SCAN turns findings into
rows, SYSTEMIZE checks and analyzes a finished VPAT, SHIP turns it into
audience-specific deliverables. This file covers the SCAN/SHIP stages that
produce and validate `accessibility/vpat-draft.json` (the file the
`vpat-lint` gate checks) in full; the SYSTEMIZE analysis stages and the
non-draft SHIP deliverables are one paragraph each below with a pointer to
`references/prompts/` — read the named file directly when that specific
deliverable is requested.

## The 4 ITI conformance labels (the only values `rating` may ever take)

- `Supports`
- `Partially Supports`
- `Does Not Support`
- `Not Applicable`

Never write a synonym ("Compliant", "Fully Supports", "N/A" as a label
string, "Non-compliant") in place of one of these four. Rate exactly one
label per criterion row — never zero, never more than one for the same
criterion ID.

## Output contract — apply to every row

- Only the four labels above appear as a `rating` value.
- `Supports` only if no known defects exist for that criterion; defects are
  permitted with `Partially Supports` or `Does Not Support`. Never
  editorialize severity in remarks — state facts and user impact.
- Remarks are rating-aware, plain text (no Markdown — no `**`, no `##`, no
  bullet dashes):
  - `Partially Supports` / `Does Not Support`: open with what DOES work
    ("Most X have/do Y..."), then a `What:` / `Who:` / `Where:` marker set
    per distinct defect — what fails, who is affected and how, where it
    occurs.
  - `Supports`: an `Evidence:` marker stating the evidence and evaluated
    scope supporting the rating (there's no defect to report, but the
    rating still needs to say what was checked).
  - `Not Applicable`: a `Why:` marker stating the reason and scope.
- One row per criterion, consolidating multiple findings under it.

## SCAN — turning findings into rows

**From raw findings (manual notes, screen-reader session logs):** for each
finding, identify the WCAG success criterion (number, name, level), assign
one ITI rating, and write remarks in the pattern above — open with what
works, then a `What:`/`Who:`/`Where:` bullet-equivalent sentence per
defect. Full original prompt: `references/prompts/01-findings-to-vpat-row-writer.md`.

**From an axe-core JSON scan** (`accessibility/axe-scan.json`, produced by
`qa` — see `references/scan-evidence-schema.md` for its shape, `findings`
vs `manual_review` kept as separate arrays, never merged):
1. Map each finding's `tags` entries to a WCAG criterion via
   `references/axe-wcag-mapping.md` (e.g. `wcag143` → 1.4.3 Contrast
   (Minimum); `wcag111` → 1.1.1 Non-text Content; `wcag412` → 4.1.2 Name,
   Role, Value).
2. Consolidate multiple findings under one criterion into one row, one
   defect-pattern sentence per distinct issue.
3. Rating is capped at `Partially Supports` — **automated scans cannot
   establish "the majority fails," so never output `Does Not Support` from
   scan data alone.**
4. Quote the actual measured value from `failure_summary` (e.g. the real
   contrast ratio) in the `What:` clause — a defensible row cites the
   number, not just the rule name.
5. Prefix every generated row's remarks with `DRAFT — pending manual
   verification.`
6. End with the mandatory scan-limits caveat: list the criteria this scan
   cannot clear — keyboard traps, focus order (2.4.3), focus visibility
   (2.4.7), meaningful sequence (1.3.2), error identification (3.3.1), and
   any other criterion `wcag-audit`'s manual passes require. **A clean
   automated scan (zero violations) never justifies `Supports`** — if axe
   finds nothing for a criterion, leave it out of `criteria` and note it as
   manually-unverified in `limitations` instead of fabricating a pass.
Full original prompt: `references/prompts/08-axe-scan-to-vpat-row-converter.md`.

## Drafting workflow (produces `accessibility/vpat-draft.json`)

1. Read `accessibility/axe-scan.json` if present.
2. Apply the SCAN method above to produce reviewed rows.
3. Self-check every row against the SYSTEMIZE linter checklist below before
   assembling.
4. Assemble the final JSON (this is the Final Report Assembler stage —
   full original prompt: `references/prompts/09-final-vpat-report-assembler.md`):
   preserve every reviewed criterion's id/name/level/rating/remarks
   exactly — do not invent, infer, revise, summarize, or omit. Write to
   `accessibility/vpat-draft.json` (repo-root-relative; override via
   `VPAT_DRAFT_PATH` only if this repo's docs layout requires a different
   path) matching the JSON shape below.
5. Append the disclaimer text below as an item in the report's
   `limitations` array, every time.

## Required disclaimer (append verbatim as a `limitations` array entry)

"This document is not an automated accessibility audit, certification,
legal opinion, or guarantee of conformance to WCAG, Section 508, EN 301
549, or any other standard. It does not replace manual testing, qualified
accessibility review, current ITI VPAT instructions, or legal advice."

## JSON shape (full schema: `references/vpat-report-schema.md`)

```json
{
  "schema_version": "1.0",
  "product": { "name": "string", "version": "string" },
  "report": { "title": "string", "version": "string", "date": "YYYY-MM-DD" },
  "evaluation_methods": ["axe-core automated scan", "manual keyboard pass"],
  "criteria": [
    {
      "id": "1.4.3",
      "name": "Contrast (Minimum)",
      "level": "AA",
      "rating": "Partially Supports",
      "remarks": "Most text meets the 4.5:1 minimum. The following exceptions exist: What: placeholder text renders at 3.1:1 contrast. Who: low-vision and colorblind users. Where: the Generate Document input field.",
      "evidence": "automated"
    },
    {
      "id": "4.1.2",
      "name": "Name, Role, Value",
      "level": "A",
      "rating": "Supports",
      "remarks": "Evidence: manual screen-reader pass (NVDA + Chrome) confirmed every interactive control exposes an accessible name, role, and state. Evaluated scope: all interactive components across the app."
    },
    {
      "id": "2.1.1",
      "name": "Keyboard",
      "level": "A",
      "rating": "Not Applicable",
      "remarks": "Why: this build ships no interactive controls beyond native form elements already covered by 4.1.2."
    }
  ],
  "limitations": ["the disclaimer text above"]
}
```

`evidence` is optional per-criterion (`"automated"` | `"manual"` |
`"both"`) — a criterion whose only support is an automated finding is
capped by the `vpat-lint` gate at `Partially Supports`/`Not Applicable`,
never `Supports`/`Does Not Support` (see the SCAN section above).

## Self-check before handoff (SYSTEMIZE — VPAT Linter / ITI Compliance QA)

Before calling a draft done, check it the way a VPAT QA reviewer would.
BLOCKING (draft is not usable): a required top-level field missing; a
non-ITI conformance term anywhere; a row missing `rating` or `remarks`.
QUALITY (undermines defensibility): `Supports` paired with remarks
describing a known defect; `Partially Supports`/`Does Not Support` remarks
that don't say what/who/where; `Not Applicable` with no stated reason;
vague remarks ("mostly accessible", "some issues") with no specifics. Full
original prompt (BLOCKING/QUALITY structure, for a full finished-VPAT
review, not just the draft-in-progress check above):
`references/prompts/03-vpat-linter-iti-compliance-qa.md`.

## Other VPAT deliverables — available on request, not part of the default draft/lint flow

These produce free-text or differently-shaped output, outside
`accessibility/vpat-draft.json` and outside anything `vpat-lint` checks.
Read the named file directly when one of these is specifically requested:

| Stage | Deliverable | Reference |
|---|---|---|
| SCAN | Test plan for a specific criterion before auditing | `references/prompts/02-criterion-test-plan-generator.md` |
| SYSTEMIZE | Executive gap analysis (conformance snapshot, POUR-principle gaps, hotspots, severity tiers) | `references/prompts/04-gap-analysis-executive-summary.md` |
| SYSTEMIZE | Engineering remediation backlog (one ticket per gap, grouped by page/component) | `references/prompts/05-remediation-backlog-builder.md` |
| SHIP | Plain-language procurement summary (one page, no WCAG jargon) | `references/prompts/06-procurement-plain-language-summary.md` |
| SHIP | Cross-standard mapping (WCAG → Section 508 / EN 301 549) | `references/prompts/07-cross-standard-mapper.md` |

## Common mistakes

| Mistake | Reality |
|---|---|
| "axe found nothing, so this criterion Supports." | Automated-only evidence caps at `Partially Supports`. Never `Supports` from a scan alone. |
| "axe found a critical violation, so Does Not Support." | Still capped — get a manual check before ruling `Does Not Support`. |
| Rating `Supports` with remarks describing a bug | Contradiction — the row is unreviewed, not compliant. Fix the rating. |
| `Supports` row with no `Evidence:` marker | Not defensible — state what was actually checked and how. |
| Remarks without What/Who/Where (for a defect row) | Not a usable ACR row — a reviewer can't act on it. |
| Markdown bullets/bold in remarks | ITI documents are plain text. Strip all Markdown. |
| Citing WCAG 4.1.1 Parsing | Removed in WCAG 2.2 (see `wcag-audit`). Never cite it here either. |

## Do not claim conformance without evidence

Every draft this skill produces is exactly that — a draft. `vpat-lint`
only checks structure and the rules above; it proves nothing about
semantic accuracy. State plainly in the PR/handoff that
`accessibility/vpat-draft.json` requires human accessibility review before
it becomes a customer-facing VPAT.
