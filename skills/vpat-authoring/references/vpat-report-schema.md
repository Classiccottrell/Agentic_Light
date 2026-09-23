# VPAT draft report — schema walkthrough

Full JSON Schema: `vpat-report.schema.json`. This is the prose companion —
read it if you want the "why", read the JSON if you need the exact
validation rule.

## Top-level shape

```
schema_version        string, e.g. "1.0"
product.name           string, required
product.version        string, optional
report.title           string, required
report.version         string, required (e.g. the VPAT template revision, "2.5Rev")
report.date            string, required
report.contact         string, optional
evaluation_methods     array of strings, at least one (e.g. "axe-core automated scan")
criteria               array of criterion rows, at least one
limitations            array of strings, at least one — always includes the
                        mandatory disclaimer from SKILL.md
```

## Criterion row shape

```
id        string — WCAG success criterion number, e.g. "1.4.3"
name      string — WCAG success criterion name, e.g. "Contrast (Minimum)"
level     "A" | "AA" | "AAA"
rating    one of the 4 ITI labels — see SKILL.md
remarks   string — rating-aware, plain text, no Markdown
evidence  optional: "automated" | "manual" | "both"
```

`additionalProperties: false` at both the report and criterion level — the
schema is deliberately closed. Don't add ad hoc fields; if a new field is
genuinely needed, update the schema and `vpat_lint_gate.sh` together.

## Why `evidence` matters

A criterion whose only evidence is an automated scan cannot be rated
`Supports` or `Does Not Support` — see `vpat_lint_gate.sh`'s
`automated_evidence_cap` rule and SKILL.md's SCAN section. Mark
`"evidence": "automated"` on any row sourced purely from
`accessibility/axe-scan.json` so the gate can enforce the cap
automatically, rather than relying on the drafter to remember it.

## Relationship to the gate

`pipeline/lib/vpat_lint_gate.sh` checks a draft at
`accessibility/vpat-draft.json` (override via `VPAT_DRAFT_PATH`) against 6
deterministic rules — see `lint-rules.md`. The gate proves structural and
ITI-terminology correctness; it does not and cannot verify that a rating is
factually accurate. That's still a human accessibility reviewer's job.
