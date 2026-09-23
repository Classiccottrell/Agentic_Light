# axe-core → WCAG 2.2 criterion mapping

Primary lookup: the axe finding's `tags` array (axe-core's `wcagXYZ` tag
convention, e.g. `wcag143` → 1.4.3). Secondary cross-check only: the axe
`rule_id`. Tags-based mapping is primary because one rule can carry
multiple WCAG tags (e.g. `input-image-alt` carries both `wcag111` and
`wcag412`) — the tag tells you which criterion that specific violation maps
to; the rule ID alone does not.

WCAG 4.1.1 Parsing was removed in WCAG 2.2 — dropped from this table,
consistent with `wcag-audit`'s "never cite 4.1.1" rule.

This table was generated directly against an installed `axe-core` package's
real rule metadata (`rule.tags`), not reconstructed from memory — treat it
as a live reference to re-derive (via `axe.getRules()` in Node, filtering
`tags` for the `wcagNNN` pattern) if axe-core's tag set changes.

## Primary: tag → criterion

| Tag | Criterion | Name | Level |
|---|---|---|---|
| `wcag111` | 1.1.1 | Non-text Content | A |
| `wcag121` | 1.2.1 | Audio-only and Video-only (Prerecorded) | A |
| `wcag122` | 1.2.2 | Captions (Prerecorded) | A |
| `wcag131` | 1.3.1 | Info and Relationships | A |
| `wcag135` | 1.3.5 | Identify Input Purpose | AA |
| `wcag141` | 1.4.1 | Use of Color | A |
| `wcag142` | 1.4.2 | Audio Control | A |
| `wcag143` | 1.4.3 | Contrast (Minimum) | AA |
| `wcag144` | 1.4.4 | Resize Text | AA |
| `wcag146` | 1.4.6 | Contrast (Enhanced) | AAA |
| `wcag1412` | 1.4.12 | Text Spacing | AA |
| `wcag211` | 2.1.1 | Keyboard | A |
| `wcag213` | 2.1.3 | Keyboard (No Exception) | AAA |
| `wcag221` | 2.2.1 | Timing Adjustable | A |
| `wcag222` | 2.2.2 | Pause, Stop, Hide | A |
| `wcag224` | 2.2.4 | Interruptions | AAA |
| `wcag241` | 2.4.1 | Bypass Blocks | A |
| `wcag242` | 2.4.2 | Page Titled | A |
| `wcag244` | 2.4.4 | Link Purpose (In Context) | A |
| `wcag249` | 2.4.9 | Link Purpose (Link Only) | AAA |
| `wcag253` | 2.5.3 | Label in Name | A |
| `wcag258` | 2.5.8 | Target Size (Minimum) | AA |
| `wcag311` | 3.1.1 | Language of Page | A |
| `wcag312` | 3.1.2 | Language of Parts | AA |
| `wcag325` | 3.2.5 | Change on Request | AAA |
| `wcag332` | 3.3.2 | Labels or Instructions | A |
| `wcag411` | 4.1.1 | (removed in WCAG 2.2 — do not cite) | — |
| `wcag412` | 4.1.2 | Name, Role, Value | A |

## Secondary cross-check: rule ID → criterion (verified against axe-core)

| Rule ID | Criterion |
|---|---|
| `image-alt` | 1.1.1 |
| `color-contrast` | 1.4.3 |
| `button-name` | 4.1.2 |
| `aria-roles` | 4.1.2 |
| `label` | 4.1.2 |
| `document-title` | 2.4.2 |
| `html-has-lang` | 3.1.1 |

**No axe rule exists named `keyboard` or `focus-visible`** — checked
directly against an installed axe-core package's rule list, not assumed.
2.1.1 Keyboard and 2.4.7 Focus Visible are exactly the kind of criteria
axe-core cannot test at all (they require operating the interface), which
is why SKILL.md's SCAN section requires listing them in the mandatory
scan-limits caveat rather than looking for an axe rule that covers them.
The closest axe-core rules that touch focus-adjacent structure —
`aria-hidden-focus`, `focus-order-semantics`, `frame-focusable-content`,
`scrollable-region-focusable` — check structural focus-trap conditions, not
visible focus indication, and don't substitute for the manual pass.
