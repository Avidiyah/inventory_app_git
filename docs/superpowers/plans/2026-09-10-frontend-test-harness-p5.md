# Frontend Test Harness — P5 (High-churn views) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Component coverage for the nine most-edited view modules outside `workOrders.js` — `nav.js`, `main.js`, `auth.js`, `items.js`, `transactions.js`, `history.js`, `userHub.js`, `scan.js`, `massStage.js` (4,519 lines, 160 commits between them).

**Architecture:** Tests only, on the P0 harness. P2 proved the pattern on one module that owns its own page; P5's problem is different — **these modules are the app's spine and import each other**. `nav.js` imports twelve views, `auth.js` imports nine, `main.js` imports everything. Mounting any of them boots most of the frontend, so P5's first deliverable is a `bootApp()` fixture with a default handler bundle that answers every page loader, and every later chunk mounts through it.

**Tech Stack:** Vitest, jsdom, @testing-library/dom, @testing-library/user-event, msw.

**Spec:** `docs/superpowers/specs/2026-09-10-frontend-test-harness-design.md`
**Roadmap:** `docs/superpowers/plans/2026-09-10-frontend-test-harness-roadmap.md` (P5)
**Depends on:** P0–P4, all landed. P5 does not read the offspring modules directly, but `nav`, `auth`, `transactions`, `massStage` and `userHub` are five of the nine views that import `views/workOrders.js`, so every P5 test boots the barrel.

## Entry gate — verify before Task 1

P4 landed 2026-09-11 (`bdc66c6`..`bdd40eb`): `views/workOrders.js` is a 24-line
barrel over eight modules, largest 752 lines. Suite at that point: **819 tests
/ 27 files, ~50 s, green** — that is the budget this phase spends against.

- [x] `npm test` green, run to completion, count and wall-clock recorded.
- [x] `pytest -m e2e` green.
- [x] No other session is mid-commit in this checkout. P5 is long and its chunks are independent; two writers in `tests/frontend/helpers/` will collide.

## Global constraints

- **Tests only.** No change to any file under `backend/static/` or `backend/app/`. If a test cannot be written without a production change, stop and raise it — do not retrofit an `init()`.
- **Characterization, not correction.** Same rule as P2: assert what the code does, comment the assertion where that looks wrong, file it in `docs/open-work.md` at the end of the chunk. No fixes.
- **No `vi.mock` of any app module.** Seams stay `fetch` (MSW), `WebSocket` (fake class), timers, and browser globals. `scan.js`'s camera is the one new seam and it is stubbed at the *browser* boundary (`navigator.mediaDevices`), not the module boundary.
- **`onUnhandledRequest: "error"` stays on.** Booting the spine fires many requests; the default bundle in Task 1 declares them once, by name.
- **`mountView()` / `bootApp()` before any import.** Every one of these modules captures element ids at import time.
- **One chunk, one session, one green suite.** A chunk is done when `npm test` is green, its own success check passes, and its findings are filed.
- Commit messages end with `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.

## Eight deviations from the roadmap text, decided here

1. **P5 is eight sessions, not one.** The roadmap's standing rule says "each phase is one bounded session" while P5 itself says "one module per session-sized chunk". The second wins: 4,519 lines across nine modules cannot land in one window. The chunks below are the phase's real unit of work; each is independently committable and independently green.
2. **`auth.js` and `main.js` move out of churn order, up next to `nav.js`.** They are not three modules, they are one boot path: `main.js` wires the callbacks, `initAuth()` decides signed-in or not, `nav.js` routes and gates by role. Covering them apart means building the same fixture three times and testing each one's half of a handshake in isolation.
3. **No new coverage for the P4 offspring.** The roadmap lists "plus the P4 offspring" under P5. P2's suite already exercises every one of them through the barrel, and `actionCoverage.test.js` already guards the module boundary. Duplicating that at the new file granularity would freeze the internal seams P4 just chose, which is exactly the coupling the split existed to avoid. Recorded, not silently skipped.
4. **P5b mounts `views/auth.js` directly rather than through `bootApp()`.** `main.js` calls `initAuth()` at import, before a test can choose the `/auth/me` branch, so every boot-check assertion would be unreachable through the P5a fixture. The P5b fixture is `helpers/auth.js`; it still consumes P5a's `pageHandlers()` and media stubs.
5. **P5c's "ranked search through `filterRanked`" bullet was wrong.** `items.js` does not import `filterRanked`; Find Item search is server-side (`GET /items/?q=`) and the page renders whatever comes back. The tests cover the request and the render, not a ranking.
6. **P5c cannot mount `views/items.js` as its own entry point.** `items.js` reaches `nav.js` via `scan.js` -> `transactions.js`, and `nav.js` re-enters `scan.js` through `tools.js` while `scan.js`'s imports are still initializing (TDZ on `BarcodeDecoder`). Production's `main.js` enters at `nav.js` first, so `helpers/items.js` primes the graph the same way (`mountView("views/nav.js")` then `importView("views/items.js")` against the one shell). Consequence for the tests: `nav.js` is live, so the Create-Item scan shortcut really routes pages rather than only firing a click.
7. **P5d lifted the request recorder and the confirm helper into shared fixtures.** `helpers/auth.js` and `helpers/items.js` each carried a private copy; they are now `helpers/requests.js` and `helpers/dialogs.js`, and both earlier fixtures re-export them (same import surface, identical pass counts). P5e+ import the shared ones directly. `helpers/workOrders.js` (P2) keeps its own copy — re-pointing it is P5h's business alongside the action audit.
8. **P5e — pricing is a button, not a tab; `billingEditor.js` is driven for real.** The parent bullets said "pricing tab"; it is a button below the results, and the `scrollTop` reset is on the pricing textarea. `billingEditor.js` has no other covered consumer, so its Save / Don't charge / Cancel are exercised here and P6 must not re-cover them. `historyRow()` factory added with a drift-guard row.

## Chunk sequencing

Churn order, adjusted where a fixture dependency forces it. The adjustments are the only departures from the roadmap's churn table.

| Chunk | Module(s) | Lines | Commits | Why here |
| --- | --- | --- | --- | --- |
| P5a | `helpers/app.js` + `views/nav.js` + `main.js` | 317 | 43 | The fixture every later chunk imports. Highest churn in the phase. |
| P5b | `views/auth.js` | 232 | 14 | The other half of boot; needs P5a's fixture, gives it the signed-in state. |
| P5c | `views/items.js` | 539 | 23 | Needs the media stubs (imports `mountScanner`), so it follows P5a but precedes full scan coverage. |
| P5d | `views/transactions.js` | 900 | 19 | Largest in the phase; owns the scan-and-go seam `main.js` injects. |
| P5e | `views/history.js` | 754 | 17 | Self-contained apart from `subnav.js` / `billingEditor.js`. |
| P5f | `views/userHub.js` + `helpers/hub.js` | 569 | 16 | Builds the shared hub mount helper the roadmap promises P6. |
| P5g | `views/scan.js` + `scan/barcode-decoder.js` + `scan/frame-debouncer.js` | 863 | 23 | The two pure scan units are pulled forward from P7 — they are the thing the camera stub has to be honest about. |
| P5h | `views/massStage.js` + `helpers/actionAudit.js` | 573 | 12 | Thirteen delegated actions; generalises P2's meta-test for the whole suite. |

---

### P5a — the boot spine

**Files.** Create `tests/frontend/helpers/app.js`, `tests/frontend/helpers/media.js`, `tests/frontend/views/nav.test.js`, `tests/frontend/views/main.test.js`. Modify `tests/frontend/helpers/handlers.js`.

#### Task 1: `bootApp()` and the default handler bundle

**Interfaces:** produces `bootApp({ role, page, handlers })` → `{ nav, requests() }`; produces `pageHandlers()`, a named MSW bundle answering every endpoint a `PAGE_LOADERS` entry fires with an empty-but-valid payload.

- [x] Enumerate the loaders: read `PAGE_LOADERS` out of `views/nav.js` and, for each, the endpoint its `load*` function hits. `showPage()` *calls the loader*, so a nav test that does not answer them fails on an unhandled request rather than on its assertion.
- [x] Write `pageHandlers()` in `helpers/handlers.js` as an exported bundle, **not** a default. `defaultHandlers` stays empty per the spec — a test opts in by passing the bundle. Each response is the empty-collection form (`[]`, `{items: []}`) built from `factories.js`, never a hand-typed literal.
- [x] `helpers/app.js`: `vi.resetModules()` → `mountShell()` → `setTestUser({role})` → `import("../../backend/static/main.js")`, with `apiMe` answered so `initAuth()` resolves to the signed-in branch. Export `bootApp` plus `bootLoggedOut()` for the 401 path P5b needs.
- [x] `helpers/media.js`: `stubUserMedia()` (a fake `MediaStream` with a spied `getTracks().stop()`), `stubAudioContext()`, `stubVibrate()`, `stubPermissions(state)`, and `restoreMediaStubs()`. Nothing here is needed at import time — verified: `mountScanner` only touches `navigator.mediaDevices` inside `start()` — but `nav.js` drives `stopLive()` / `refreshPermissionState()` on every page swap, so the stubs install for any test that navigates.

**Test.** `bootApp({role: "owner"})` boots with no unhandled request and no console error; a smoke assertion that `document.getElementById("app-root").hidden === false`.

#### Task 2: `nav.js`

- [x] `PAGE_ACCESS` / `canAccessPage` / `landingPageForRole` as a table test across all five roles and all sixteen pages. Assert the roadmap-relevant invariant explicitly: **every landing page is reachable by its own role** — the fallback to `transaction` exists precisely because that can drift.
- [x] `applyRoleVisibility(role)`: per role, the exact set of visible buttons, and that a group emptied by the role is itself hidden (the trailing-hairline rule the comment records).
- [x] `showPage(page)`: `.active` moves on both the section and the button, `getActivePage()` follows, group menus close, `closeTip()` fires, the page's loader runs exactly once.
- [x] Scanner lifecycle: leaving a scanner page calls `reset()` on the leaving scanner and `refreshPermissionState()` on the entering one; same page twice does not reset. `visibilitychange` with `document.hidden` true calls `stopLive()` on every registered scanner and does **not** reset.
- [x] Nav button clicks go through `user-event`, not `el.click()`.

**Test.** Rename one `data-page` value in `shell-head.html` locally; the visibility table goes red. Revert.

#### Task 3: `main.js`

- [x] The four wirings are observable, so assert each at its effect, not by spying on the import: `setScanResetter` — trigger a batch reset through `transactions.js` and see the scan UI clear; `setScanAutostarter` — begin a batch with permission granted and see the camera start, and with permission denied see it not; `setActivePageGetter` — `showPage("history")` then assert `realtime.js` reports that page (drive it through the fake socket, as P2 does); `installTooltips` — a `data-tip` element added *after* boot still opens a bubble, which is the delegation claim the comment makes.
- [x] `initAuth()` runs at import: with `apiMe` 200 the app reveals and the role's landing page is active; with 401 the login screen shows and no page loader fires.

**Test.** `npm test` green. Commit per task.

---

### P5b — `auth.js`

**Files.** Create `tests/frontend/views/auth.test.js`.

- [x] **Login:** submit through `user-event`; `apiLogin` receives username, password and the remember flag; success reveals `app-root`, hides `login-screen`, sets `state.js`'s current user, calls `applyRoleVisibility` and opens `landingPageForRole`.
- [x] **Failure:** a 401 from `apiLogin` surfaces `friendlyError` copy in `login-message` and leaves the app hidden. The password field clears; the visibility toggle resets to masked.
- [x] **The expiry path, both directions.** `setUnauthorizedHandler` is the real hook: fire a 401 from any wrapper while signed in and assert the timeout copy, `disconnectRealtime()`, and `resetBatch({keepSaved: true})` — the batch snapshot survives. Then the boot-time 401 (`apiMe` before the app ever showed) and assert it is *silent*: no timeout copy. That asymmetry is the comment's whole point and is one edit away from being lost.
- [x] **Logout:** `apiLogout` called, batch cleared (`keepSaved: false`), push unsubscribed for this device, tools view reset, realtime disconnected.
- [x] **Deep link:** boot at `/workorder_card/<n>` with a signed-in session and assert `focusWorkOrderNumber` is reached via `soloNumberFromPath` — through the P4 barrel, unchanged.
- [x] **Batch resume:** signing in as the user who owns a saved `sessionStorage` batch resumes it; a different user does not.
- [x] **Push at login:** `requestPermissionAtLogin` fires only when the notifications checkbox is on. Stub `Notification` and `ServiceWorkerRegistration` in `helpers/media.js`.

**Test.** Every branch of `showLoginScreen` and `enterApp` covered; the expiry asymmetry has a test in both directions.

---

### P5c — `items.js`

**Files.** Create `tests/frontend/views/items.test.js`.

**Done 2026-09-11** — `2026-09-11-frontend-test-harness-p5c-items.md`, 47 tests.

- [x] `loadItems()` / `renderItems()`: populated table, the empty-message path with its custom argument, the skeleton→loaded transition, money and `safeHttpUrl` rendering. Search is server-side, not `filterRanked` — see deviation 5.
- [x] The four delegated actions — `edit`, `correct`, `notes`, `delete` — each: request issued, DOM result, error surfaced. `delete` goes through `confirmDialog`; both answers asserted.
- [x] Role gating: which controls render for technician / supervisor / techfm_oa / admin / owner.
- [x] `confirmArchivedReuse` on a barcode collision — the archived-reuse retry, already covered at the `dom.js` level in P1, asserted here at its call site.
- [x] The two mounted scanners (`itemScanWidget`, `itemsScanner`): a decoded barcode reaches `onItemFound`; a 404 renders the `notFoundLabel` copy; the create shortcut and `openAddBarcode` fire. Camera driving is P5g's job — here, the lookup path only.
- [x] Cross-module callbacks: `setOnSaved` from `notes.js` and `addBarcode.js` refresh the row.

**Test.** `npm test` green; the four actions covered by name.

---

### P5d — `transactions.js`

**Files.** Create `tests/frontend/views/transactions.test.js`.

- [x] `enterTransactionPage()`: form state, role gating (a technician sees dispense only — the Stock toggle is hidden), work-order picker population.
- [x] The batch lifecycle: arm (`scanGoArmed` false until a quantity is set), `commitScannedItem` posts the transaction and appends the line, `resetBatch({keepSaved})` in both forms, `tryResumeBatch(userId)` for the matching and non-matching user.
- [x] `sessionStorage` is the batch's store: assert the written snapshot shape, and that a throwing `setItem` (private-browsing case) degrades silently rather than breaking the commit — the comment claims that and nothing checks it.
- [x] The debounced work-order search on fake timers; `filterRanked` ordering.
- [x] `apiVoidTransaction` with `confirmDialog` both ways; `apiStartWorkOrder` from the picker; the error copy for each failure.
- [x] The injected seams: with `setScanResetter` / `setScanAutostarter` never called (the module's own default), changing the work order must not throw. That is the state every test file other than `main.test.js` runs in.

**Test.** `npm test` green; every export exercised.

---

### P5e — `history.js`

**Files.** Create `tests/frontend/views/history.test.js`.

**Done 2026-09-11** — `2026-09-11-frontend-test-harness-p5e-history.md`, 66 tests.

- [x] `setHistoryTab` / `loadHistory` / `renderHistory` across each tab, including the pricing button and the textarea `scrollTop` reset (deviation 8).
- [x] The 250 ms work-order filter debounce on fake timers.
- [x] `initSubNav` wiring; `openBillingEditor` driven for real (deviation 8).
- [x] Role gating: the Charge column and pricing button appear at TechFM OA and above.
- [x] Skeleton rows, empty state, error copy, `confirmDialog` on void and on the archived-restore offer.

**Test.** `npm test` green.

---

### P5f — `userHub.js` and the hub fixture

**Files.** Create `tests/frontend/helpers/hub.js`, `tests/frontend/views/userHub.test.js`.

- [ ] `helpers/hub.js`: mount the hub with a seeded payload per tab, and a `stopClock()` teardown. The roadmap promises P6 a shared hub helper; building it here, against the module that owns the shell, is what makes P6 nine small files instead of nine setups.
- [ ] `loadUserHub()` / `refreshUserHub()`: each tab's mount function called with its payload; a failing tab renders its error without taking the others down.
- [ ] Role gating over the six hub endpoints — a technician must not fire `apiGetHubAdmin`.
- [ ] The `crewSafetyTimer` interval on fake timers, **including that it is cleared** on leave. An un-cleared interval is a leak that will show up as cross-test bleed later.
- [ ] `subscribe()` from `realtime.js`: a hub-relevant event refreshes; an unrelated one does not. Fake socket, as P2.
- [ ] `openWorkOrdersFilteredByDistribution` and `showPage` hand-offs asserted at the boundary.
- [ ] `destroyHubGraphs` on tab change.

**Test.** `npm test` green; no test leaves a timer running (assert `vi.getTimerCount()` is 0 in the file's `afterEach`).

---

### P5g — `scan.js` and the two pure units

**Files.** Create `tests/frontend/unit/barcodeDecoder.test.js`, `tests/frontend/unit/frameDebouncer.test.js`, `tests/frontend/views/scan.test.js`.

- [ ] **Pure first.** `scan/frame-debouncer.js` (49 lines) and `scan/barcode-decoder.js` (179) get table-driven unit tests, including the field-tested tuning they encode (crop, TRY_HARDER, the three-consecutive rule). These are cheap, they are real, and they are what lets the `scan.js` tests stub the camera without stubbing the decode logic.
- [ ] `mountScanner` as a factory: mount twice with different options and assert the two instances do not share state — the bug class a module-level singleton would hide.
- [ ] Upload path: a file through the chooser reaches `apiDecodeBarcode`, then `lookupFn`; 404 renders `notFoundLabel` copy; `onNotFound` / `onCreateShortcut` / `onAddBarcode` fire per option.
- [ ] Live path on stubbed `getUserMedia`: `start` → `stopLive` releases every track; torch button hidden when the capability is absent; the aimbox toggles in lockstep.
- [ ] Continuous mode: `DWELL_MS` and `COOLDOWN_MS` on fake timers — the same label re-decoded inside the dwell does not commit twice, a different label does commit immediately, `canScan` false suppresses the commit.
- [ ] `buzz` and `primeAudio` degrade silently with the APIs absent (iOS Safari case) — assert no throw, not a call count.
- [ ] `resetScan` / `autoStartTxnScan`: autostart starts only when permission is already granted and **never** prompts.

**Test.** `npm test` green; no real camera, no real timers, no unhandled rejection.

---

### P5h — `massStage.js` and the generalised action audit

**Files.** Create `tests/frontend/helpers/actionAudit.js`, `tests/frontend/views/massStage.test.js`. Modify `tests/frontend/views/workOrders/actionCoverage.test.js`, `tests/frontend/views/items.test.js`.

- [ ] `helpers/actionAudit.js`: lift P2's meta-test into `auditActions({sources, fragment, frozen, behaviourFiles})` — rendered-vs-handled orphans, the frozen list, and the per-action coverage check. Re-point `actionCoverage.test.js` at it with no behaviour change; its result must be identical before and after.
- [ ] Apply the audit to `massStage.js` (thirteen actions: `add-work-order`, `pick-item`, `open-wo`, `remove-slot`, `reuse-stage`, `add-item`, `edit-item`, `remove-item`, `load-item`, `return-item`, `complete-stage`, `save-stage`, `delete-stage`) and to `items.js` (four).
- [ ] Cover the thirteen branches: each issues the right request, produces the right DOM, and surfaces the right error. `complete-stage` and `delete-stage` go through `confirmDialog` — both answers.
- [ ] `loadStages()` with its arguments, the skeleton, the empty state, `canBeWorkOrderTechnician` gating on the technician picker, `tipHtml` presence.
- [ ] `focusWorkOrder` and `showPage` hand-offs at the boundary.

**Test.** Delete one action's tests locally; the audit names it. Restore.

---

## Suite budget

Adding eight modules to a suite that already costs ~180 s locally is the phase's real risk; a suite people skip is worse than no suite.

- [ ] Record wall-clock at each chunk's close, in the commit body.
- [ ] **Memoise the shell.** `helpers/shell.js` re-reads `main.py` and every fragment on every mount. Cache the assembled string at module scope (the parse stays per-test; only the file I/O and concatenation are shared). Test-helper change, allowed, and it pays back on every file.
- [ ] If a chunk pushes the total past ~6 minutes locally, stop and raise it before starting the next. The lever is `maxWorkers` and the shell cache, not deleting assertions.

## Done when

- [ ] All eight chunks are committed, each green at commit time.
- [ ] Every module's exported surface is exercised; every delegated action in `items.js` and `massStage.js` is named by the audit.
- [ ] Findings are filed in `docs/open-work.md` under a new `N-P5-CHARACTERIZED` heading, in the P2 table form (defect, pinned by).
- [ ] `docs/current-state.md`'s verification column no longer says "no Vitest suite for these views yet" for anything P5 covered.
- [ ] Coverage recorded, still advisory. P7 gates.

## Deliberately not in P5

- Any production change. P4 owned the only ones.
- Fixing anything characterization reveals.
- The P4 offspring (see deviation 3), the hub sub-modules (P6, using this phase's `helpers/hub.js`), `tools.js` (P6 — 756 lines, the largest thing left after this phase), `push.js` (P6), `service-worker.js` (P7).
- New E2E journeys. P3's layer stands as-is until P7.

## Drift register — found while planning P5 (2026-09-11)

All rows except D2 were filed the same day: D1/D3/D4/D5 into the roadmap, D6
into `docs/open-work.md` by the P4 session. Kept here as the record of what was
wrong and why it was changed.

| # | Drift | Where | Action |
| --- | --- | --- | --- |
| D1 | The roadmap's standing rule "each phase is one bounded session" contradicts P5/P6/P7, which are explicitly multi-module. | roadmap, preamble vs P5 | **Filed** — roadmap preamble now says exactly that. |
| D2 | P0–P3 (33 commits) have never been seen by CI — the branch is unpushed. Every phase's "CI green" success criterion is unverified. Pushing `main` deploys production. | local `main` vs `origin/main` | **Open.** 45 commits ahead as of 2026-09-11; recorded in the roadmap status block. Owner decision. |
| D3 | The roadmap still describes P2's realtime seam as "via the mocked `__emit`". No such export exists; P2 drove the real dispatch path instead, and that decision lives only in the P2 plan. | roadmap P2, spec §3.3 | **Filed** — roadmap P2 step 6 now records the real dispatch path. |
| D4 | The roadmap names three E2E files; P3 shipped six (`_availability.py`, `_seed.py`, `test_availability.py` added). | roadmap P3 | **Filed** — roadmap P3 file list corrected to six files plus `pytest.ini`. |
| D5 | "Plus the P4 offspring" under P5 would duplicate P2's coverage at a finer granularity and freeze the new internal seams. | roadmap P5 | **Filed** — clause struck from roadmap P5, with the reason kept. |
| D6 | `docs/open-work.md` N6 calls `workOrders.js` "1,705 lines"; it was 2,842 before P4 and is now a barrel plus eight siblings. | `open-work.md` N6 | **Filed** — N6 now reads ~3,100 lines across a barrel and eight modules. |
| D7 | The roadmap's churn table is a snapshot; re-derived 2026-09-11 it is still exact (nav 23, items 23, main 20, transactions 19, history 17, userHub 16, scan 16, auth 14, massStage 12). No file added since the roadmap is unassigned to a phase. | — | No action. Recorded so the next phase does not re-derive it. |
| D8 | `views/tools.js` is 756 lines — the largest module left after P5 — but sits in P6 on 9 commits. Correct by churn, surprising by size. | roadmap P6 | No action; expect `tools.js` to be a full session of its own. |
