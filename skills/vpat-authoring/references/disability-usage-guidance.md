Reference documentation only. Not wired into any gate. Not a required
capability of this preset. Introduces no new API-key dependency.

# Disability-usage guidance — pattern reference

## What this is

A pattern for translating VPAT/audit findings into plain-language guidance
for five disability populations: visual, hearing, speech, motor, and
cognitive. Useful when a stakeholder asks "how does this actually affect a
real user," beyond a criterion ID and an ITI label.

## Hard constraints

- No fabrication — every claim traces to a recorded finding, never invented.
- No endorsements — describe what was found, not a marketing claim.
- No guarantees — assistive-technology behavior varies by device, version,
  and configuration; never promise a specific outcome for a specific user.
- Mandatory caveat, every time (see below).

## Required caveat (fresh, original — always include verbatim)

"This guidance is generated from recorded audit findings only and is not an
accessibility guarantee, certification, or endorsement.
Assistive-technology behavior may vary. Human accessibility review is
required before this is shared outside the team."

## Reusable safety-gate pattern

Before any disability-usage guidance leaves the team, run:

**Automated checks:**
- Banned-word scan — no "guarantee," "certified," "compliant" (outside its
  ITI-label context), or absolute claims like "will always work."
- Mandatory-caveat-substring presence — the caveat text above must appear
  verbatim.
- Evidence-grounding check — every cited criterion ID must exist in the
  actual findings/VPAT it was generated from; any criterion mentioned that
  isn't in the source data is flagged `FABRICATED`.

**Human sign-off checklist (5 boxes, all required before external issuance):**
- [ ] No fabrication — every claim traces to a real finding
- [ ] No endorsements
- [ ] No guarantees
- [ ] Caveat verified present, verbatim
- [ ] Workflow boundaries respected (this guidance doesn't get relabeled as
      a compliance certification downstream)
