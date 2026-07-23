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
2. Update `README.md` with how to run/build the project.
3. Put work-in-progress under `active/`; move superseded work to `archive/`.

## Layout

```
my-new-project/
├── BRIEF.md     ← requirements + status (start here)
├── README.md    ← how to run / build
├── active/      ← work in progress
└── archive/     ← superseded or paused work
```

When the project ships, `agents/eng-manager.md` picks up BRIEF.md's
`Status` field (`shipped`) to drive its PR-drafting flow.
