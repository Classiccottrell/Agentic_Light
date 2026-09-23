# VPAT decision register — template

A running log of open judgment calls made while drafting a VPAT/ACR, so a
reviewer can see what was decided and why instead of re-litigating it.
Columns: `id | category | question | status | owner | recommended_default | decision | evidence`.

| id | category | question | status | owner | recommended_default | decision | evidence |
|---|---|---|---|---|---|---|---|
| REG-001 | scope | Has product-owner sign-off been recorded for this VPAT's coverage claims (which pages/flows were actually evaluated)? | open | — | do not claim coverage beyond what was evaluated | — | — |
| REG-002 | evidence | Is an automated-only finding (no manual verification) enough to justify `Partially Supports`, or does it require a human pass first? | resolved | — | automated-only findings may be drafted as `Partially Supports`, capped, never `Supports`/`Does Not Support` — see `vpat_lint_gate.sh`'s `automated_evidence_cap` rule | apply the recommended default | `references/lint-rules.md` |
| REG-003 | terminology | Does this report need a documented deviation note for any non-standard term, or should every row use ITI labels with zero exceptions? | resolved | — | zero exceptions — ITI labels only, no deviation notes | apply the recommended default | `SKILL.md` |

Add rows as new judgment calls come up. Do not reuse these example IDs for
real decisions — start a fresh register per VPAT/product.
