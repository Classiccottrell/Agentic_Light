# Normalized accessibility scan evidence — schema walkthrough

Full JSON Schema: `scan-evidence.schema.json`. This is the shape `qa`
writes to `accessibility/axe-scan.json` after running an automated scan
against the target repo, so the coder has real evidence to cite when
drafting `accessibility/vpat-draft.json`.

## Top-level shape

```
source        const "axe-core" — this schema is axe-specific by design
page.url      string, required — the scanned URL
page.title    string, optional
scanned_at    string — timestamp, any parseable format
engine.name   string, required
engine.version string, required
findings      array — automated violations (see below)
manual_review array — items axe cannot check, flagged for a human pass
```

## `findings[]` shape

```
rule_id           string — the axe rule ID, e.g. "color-contrast"
impact            string — axe's own impact label (minor/moderate/serious/critical)
tags              array of strings — includes WCAG tags like "wcag143"; see
                   axe-wcag-mapping.md to convert these to a criterion
description       string
failure_summary   string, optional — the actual measured value (e.g. the
                   real contrast ratio); quote this verbatim in a drafted
                   row's `What:` clause
target            array of strings, optional — CSS selector(s) of the
                   affected element(s)
```

## `manual_review[]` shape

```
rule_id      string
description  string
```

## Why `findings` and `manual_review` stay separate arrays

They're never merged. `findings` is what axe actually detected and can
cite a measured value for. `manual_review` is a list of things axe cannot
check at all (keyboard traps, focus order, meaningful sequence, etc.) that
`qa` flags for the manual pass. Merging them would blur "automated
evidence" into "things nobody checked yet" — exactly the mistake the
`vpat-lint` gate's `automated_evidence_cap` rule exists to prevent upstream
of the gate, at drafting time.
