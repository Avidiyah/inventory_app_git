# Tutorials build — orchestration handoff (2026-11-23)

You are orchestrating the build of in-app tutorials for this app: a button on
each page darkens the screen, lights one section, and explains it one sentence
per tap. The design is settled and the user has approved the strategy. Your
job is to get it built batch by batch, with the user checking each batch.

## Read first

1. Memory `tutorials-workstream.md`: every decision the user made. Settled; do
   not reopen any of it.
2. `docs/superpowers/specs/2026-11-23-tutorials-0a-player-design.md` and
   `docs/superpowers/plans/2026-11-23-tutorials-0a-player.md`, in full.
3. The other specs and plans (`2026-11-23-tutorials-{0b,1,2,3,4,6}-*`) only
   when you reach that batch.

## What you must know about these documents

- I wrote the 0a spec. Sonnet agents wrote everything else, and nobody has
  read those files end to end. Treat every plan as a draft: check its
  selectors, paths and names against the code before acting on it.
- Each plan opens with a rule note and a "Spec corrections" table. Both
  override the spec beneath them.
- Later plans change the player (a script's lowest role, hidden targets, a
  fixed button slot, optional opening taps, an end-of-tutorial clean-up). Read
  the 0b and batch 1 prep tasks before building 0a, and fold in whatever is
  cheaper to build once.
- The wording tables predate the one-sentence rule. Split at sentence
  boundaries; never merge.
- The 0b plan's Hub tab task carries an added line (sub-tab named "Completed",
  the tab has its own red dot) that its steps below do not yet reflect.
- Open risk: User Requests has four tabs, and sample data matches on path
  only. Check whether the page filters by type itself before batch 3.
- Nothing is committed. Ask the user whether to commit the documents before
  you start.

## Order and method

| Batch | How |
| --- | --- |
| 0a player and work-order pilot | Sequential, by its plan. Stop for the user's in-app check |
| 0b progress, red dot, Hub tab, Users count | Sequential; carries a migration. Stop for the in-app check |
| 1 Technician, 2 Team Lead, 3 Office, 4 Admin | Parallel: one Sonnet 5.5 medium agent per page, using the briefs in that batch's plan |
| 6 Welcome | Last. The user's greeting is in the welcome spec, 5.5 step 1; use it verbatim |

There is no batch 5: SMR is finished and gets no tutorials.

For a parallel batch: do the prep task yourself, launch every page agent in
one message, then register the pages, run the guard test, fix what fails, and
give the user ONE wording table for the whole batch. Wait for their approval
before committing.

## Rules

- Subagents are Sonnet 5.5 at medium effort, never forks. Each owns exactly
  its page's two files. You alone edit existing app code and
  `tutorials/index.js`.
- Follow the repo `CLAUDE.md`: chat replies short and plain, outcome first.
- Commit with explicit paths, no Co-Authored-By trailer. Other sessions share
  this checkout, so never `git add -A`.
- **Never push without asking.** Pushing main deploys to production.
- Run Vitest from PowerShell at `C:\...`; it fails from Git Bash. Targeted
  tests per task.
- The user checks the running app themselves. Do not start a preview server
  for them.
- When something is genuinely the user's call, ask with AskUserQuestion. A
  recommendation of yours is not accepted until they say so.

## Start

Read items 1 and 2, then report in under 200 words: what in the 0a plan
disagrees with the code or the spec, what you would fold in from the later
plans, and whether you are ready to build 0a.
