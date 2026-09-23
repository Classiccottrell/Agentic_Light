# `vpat-lint` gate rules

`pipeline/lib/vpat_lint_gate.sh` checks `accessibility/vpat-draft.json`
(override path: `VPAT_DRAFT_PATH`) against 6 deterministic, regex/structural
rules. No draft file → `WARN` + skip (exit 0). Draft present and violating
any rule → hard stop (non-zero exit), before the human gate.

A schema-shape precondition runs first (required top-level keys present;
`report.title`/`version`/`date` non-empty strings; `limitations` a
non-empty array of non-empty strings; `criteria` a non-empty array of
objects each with non-empty `id`/`name`/`level`/`rating`/`remarks`) — a
failure here reports as a plain "missing required field" message before any
of the 6 named rules run.

1. **`iti_terms_only`** — every `rating` must be exactly one of `Supports`,
   `Partially Supports`, `Does Not Support`, `Not Applicable`. Remarks may
   not contain a near-miss synonym ("compliant", "non-compliant",
   "fully supports", "does not comply", "complies").
2. **`single_conformance_rating`** — no criterion `id` may appear more than
   once in `criteria`. One rating per criterion.
3. **`no_supports_contradiction`** — a row rated `Supports` may not contain
   a defect word in its remarks ("fail", "missing", "broken", "unsupported",
   etc.) — that's a contradiction, not a compliant row. The word list is
   deliberately narrow (excludes generic terms like "does not", "cannot",
   or "error" that appear in legitimate compliant WCAG language, e.g.
   "does not rely on color alone") to avoid false-positiving correct rows.
4. **`structured_remarks`** — rating-aware marker check: `Not Applicable`
   requires a `Why:` marker; `Supports` requires an `Evidence:` marker;
   `Partially Supports`/`Does Not Support` require all three of `What:`,
   `Who:`, `Where:` markers.
5. **`no_markdown_leak`** — remarks and limitations entries may not contain
   Markdown syntax (`**`, `##`, code fences, bullet dashes at line start).
   ITI documents are plain text.
6. **`automated_evidence_cap`** (Agentic Light addition) — a criterion with
   `"evidence": "automated"` may not be rated `Supports` or
   `Does Not Support`. Automated-only evidence caps at `Partially Supports`
   or `Not Applicable` — operationalizes the SCAN section's rule that a
   scan alone cannot establish either "no defects" or "the majority fails."

What this gate proves: structure and ITI-discipline compliance. What it
does **not** prove: that any rating is factually correct. A passing
`vpat-lint` run is a necessary, not sufficient, condition for a
customer-facing VPAT — human accessibility review is still required (see
SKILL.md's final section).
