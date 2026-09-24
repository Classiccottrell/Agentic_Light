# Starting a New Project

`_TEMPLATE/` is the canonical skeleton for a new project. Do not edit it in place —
copy it.

## Quick start

```sh
# from Agentic_Light/
cp -R Projects/_TEMPLATE "Projects/my-new-project"
```

Then:

1. Open `Projects/my-new-project/BRIEF.md` and fill in every section
   (goal, non-goals, constraints, stack, acceptance criteria, status).
2. Fill [spec.md](spec.md) with expected behavior, affected components,
   acceptance checks, and unresolved questions from the brief.
3. Break the spec into ordered, verifiable tasks in [tasks.md](tasks.md).
   Link each task to its spec checks and record dependencies.
4. Execute the next unblocked task; record its verification result in
   `tasks.md` before marking it done. Keep [Plan.md](Plan.md) current with
   partial work, decisions, blockers, checks, and the exact next action.
5. Update `README.md` with how to run/build/check the project. Put
   work-in-progress under `active/`; move superseded work to `archive/`.

## Execute and resume

`BRIEF.md` → `spec.md` → `tasks.md` → execution / `Plan.md` checkpoint.

These files are shared Markdown context for any provider or human. Supply
their paths with the task; no provider-specific session or automatic loading
is required. On resume, read them in that order, inspect current files and
any Git diff, then continue from `Plan.md`'s next action. Reconcile stale
checkpoints with actual work and preserve other contributors' changes.

Keep intent/status in the brief, behavior/checks in the spec, task progress
and evidence in the task list, and only the current handoff in `Plan.md`.
If scope changes, update the brief and spec before revising dependent tasks.
Resolve blocking questions before executing affected tasks. When all tasks
and acceptance checks pass, update the brief's status and final checkpoint;
shipping still follows the existing review and approval process.

## Layout

```
my-new-project/
├── BRIEF.md     ← requirements + status (start here)
├── spec.md      ← behavior + acceptance checks
├── tasks.md     ← ordered tasks + verification evidence
├── Plan.md      ← current checkpoint + next action
├── README.md    ← how to run / build
├── active/      ← work in progress
└── archive/     ← superseded or paused work
```

When the project ships, `agents/eng-manager.md` picks up BRIEF.md's
`Status` field (`shipped`) to drive its PR-drafting flow.
