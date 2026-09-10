# P2 (workOrders.js characterization) — session handoff

Plan: `docs/superpowers/plans/2026-09-10-frontend-test-harness-p2.md`.
Working tree: uncommitted, on `main` (local main is 23 ahead of origin).

## Done — Tasks 1–11

| Task | File | Tests |
| --- | --- | --- |
| 1 fixtures | `tests/frontend/helpers/{workOrders,browserStubs}.js`, `factories.js` (extended) | — |
| 2–3 render | `views/workOrders/render.test.js` | 88 |
| 4 roles | `roles.test.js` (frozen 4×7×2 matrix, read off the running code) | 83 |
| 5 lifecycle | `actions.test.js` | 26 |
| 6 editor/labor/materials/pickers | `editorActions.test.js` | 46 |
| 7 filters/sort/search/list | `filters.test.js` | 45 |
| 8 solo + routing | `solo.test.js` | 33 |
| 9 realtime | `realtime.test.js` | 22 |
| 10 integrations | `integrations.test.js` | 40 |
| 11 meta-test | `actionCoverage.test.js` | 6 |

`npx vitest run` = **818 passed / 27 files** on a clean run. Meta-test verified
to fail by name when an action's tests are removed (checked, then restored).

Two deliberate deviations from the plan, both noted in the files:
- Task 6 lives in `editorActions.test.js`, not `actions.test.js` — the repo caps a file at 500 lines.
- One config change (allowed: harness, not app): `vitest.config.js` gained
  `testTimeout/hookTimeout: 20000` and `maxWorkers: 4`. Eight parallel jsdom
  shells timed out at the 5 s default and occasionally killed a worker.

## Remaining

1. **One flaky test**: `integrations.test.js` → "polls the session while a
   sign-in is pending, and stops when it settles" (last line of the file).
   `polls` reached 6, not 2 — under `--coverage` the awaiting-sign-in 3 s
   `setInterval` fires more than once. Either pin it properly (fake
   `setInterval` for the whole file) or assert "polling stopped" rather than
   an exact count. Everything else is green.
2. **Task 12**: record coverage in the commit message
   (`npm run test:ci`; last full number was 29.12% statements overall —
   still need the per-file `backend/static/views/workOrders.js` figure, e.g.
   `npx vitest run --coverage --coverage.reporter=text`), then file the
   findings below in `docs/open-work.md`, then commit.

## Findings to file in `docs/open-work.md` (nothing fixed in P2)

- `dom.js:setMessage` assigns `element.className = type`, stripping `wo-message`.
  The click delegation then re-queries `.wo-message`, gets null, and **silently
  swallows the second error on a card** (no clear, no error text). Characterized
  in `actions.test.js` → "swallows the SECOND error on a card".
- `workOrders.js:840 detailsViewHtml` — the Priority row is
  `detail.priority || "Not imported"`, always truthy, so the `.wo-details-empty`
  empty state is dead markup.
- `showSoloCard` adds `.wo-solo`, then `paintDetail` overwrites `className`
  with `workOrderCardClass(detail)` — the card-page modifier never survives
  the first paint.
- `save-details` on an `assigned` row with no technicians: the editor's status
  options are `[created, in_progress, on_hold]`, so the select falls back to
  `created` and an otherwise-untouched save rolls the status back.
- `hoursInputValue` writes the literal string `"NaN"` for a non-numeric
  duration (a number input then renders it blank).

## Harness gotchas worth keeping

- One `mountView` per test — `vi.resetModules()` runs in `beforeEach`, so a
  second mount inside one test returns the cached module bound to the dead DOM.
- `openCard`/`expandCard` clear the request recorder; "the action refreshed the
  card" is otherwise satisfied by the open's own fetch.
- `window` survives `mountShell`, so every previously imported module instance
  still handles `popstate`. Assert DOM outcomes, not request counts, there.
- The card's message element must be found positionally (see helper comment).
