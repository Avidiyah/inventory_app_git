# Tutorials build — orchestration handoff (updated 2026-11-23, late)

You orchestrate the in-app tutorials build. Batches 0a, 0b, 1–4 and 5 (Starter)
are BUILT and committed on local main (last commit 80259a7). **Nothing is
pushed.** 0b carries migration `c4e6a8b0d2f3` (applied to the local DB only);
pushing main deploys it. Never push without asking.

## Read first

1. Memory `tutorials-workstream.md` (every user decision; settled) and
   `feedback-orchestrate-tutorial-batches.md`.
2. `docs/current-state.md` → Frontend Feature Context → Tutorials (current truth).
3. For batch 6: `docs/superpowers/specs/2026-11-23-tutorials-6-welcome-design.md`
   and `docs/superpowers/plans/2026-11-23-tutorials-6-welcome.md`. Treat the plan
   as a draft: it predates everything built since; check names against the code.

## Where we are

| Item | State |
| --- | --- |
| 0a player, 0b progress/dot/Hub tab/Users count | Built |
| Batches 1–4: 13 pages, 49 scripts | Built; wording approved by the user |
| Batch 5 Starter: wait-for-tap step, cross-page run, Hub Starter sub-tab, 5 menu tours | Built; awaiting the user's in-app check |
| Batch 6 Welcome | **Next.** Greeting is in the welcome spec 5.5 step 1, verbatim. Switches on only after every batch is done. Ends on the Starter sub-tab (`setTutorialsSub("starter")` exists) |
| Full frontend suite | Green (3,045) after the last timeout fix |
| e2e `backend/tests/e2e/test_starter_tutorial.py` | Written, never run (no Chromium) |

Known gaps, deliberately left: a profile opened from the Hub shows an empty
Tutorials block; the Hub tab dot does not repaint on a role change alone.

## Method (the user's standing preference)

- Orchestrate; do not build inline. Every batch, sequential ones included,
  goes to Sonnet 5.5 medium agents (never forks), each prompt opening with
  "Take a deep breath before beginning." Up to 10 at once.
- Maximise concurrency: split by file ownership, one owner per file, tell
  each agent which files it may NOT touch. The orchestrator alone edits
  `tutorial.js` while agents run, and messages any agent whose file it touches.
- Each agent reports commits, test commands with counts, deviations.
- Vitest only from PowerShell at `C:\...`. Targeted runs per task; one full run
  per batch. Explicit `git add` paths, no Co-Authored-By trailer.
- User reviews wording once per batch as a table (generate it from the script
  files with a node script into the scratchpad).

## Lessons that cost time

- Guard flakiness was always a race, never the scripts: boot load landing
  after sample mode, page reload landing after `open` clicks, a second Owner
  boot. The guard and player now wait (boot 300 ms, reload 400 ms, settle,
  one `open` retry). Suspect timing first.
- `open`'s last click is judged by `here` when the script has one; give a
  script a `here` when its first step is always visible.
- Targets inside collapsed `<details>` groups never count as visible; light
  the container instead.
- Heavy guard tests need long timeouts under full-suite load.
