# Tutorials 0a — Player, Button, Sample Data, Guard, Work-Order Pilot Implementation Plan

> **Rule added by the user 2026-11-23 (overrides anything below):** every box shows ONE simple sentence. A step that needs more is written as a list of sentences (`text: ["...", "..."]`, at most 3, each at most 120 characters) and the player gives each sentence its own tap on the same lit section. Wording tables that hold two sentences in one step are split at the sentence boundary, never merged into a longer sentence. Use plain words a new hire would use; one idea per sentence. See 0a spec 5.2 and 5.4.

**Goal:** Ship the shared tutorial player, the page button, the sample-data switch in `api.js`, one guard test, and four work-order-card scripts.

**Spec:** `docs/superpowers/specs/2026-11-23-tutorials-0a-player-design.md`. Section numbers below are the spec's. Inline execution; no subagents.

## Spec corrections

| # | Spec says | Code says | Plan does |
|---|---|---|---|
| C1 | Sample ids are negative (3, 6) | Every id is a UUID string (`factories.js` header, `api.shapes` drift test); `/work-orders/-1` would 422 and break the shape contract | Sample ids are UUIDs in the reserved namespace `ffffffff-ffff-4fff-8fff-0000000000NN`. A stray write 404s. The guard asserts the prefix in place of "negative". Viewer's own id (crew) is exempt |
| C2 | Pilot `open` clicks `[data-wo-id="-1"] .wo-card-head` (5.2) | A list card is `details.wo-card[data-id][data-number]` with a peek body; the card with tabs is the card page, reached by `[data-peek-open]` → `openWorkOrderPage` (pushes `/workorder_card/<number>`). Tab row `#wo-sec-tabs`, tabs `.wo-tab[data-wo-tab]` | Scripts use `details.wo-card[data-number="SAMPLE-1"] [data-peek-open]`, then the tab button (T5) |
| C3 | Sample map has the page's records (5.3) | The page also fetches `/work-orders/filter-options`, `/items/`, `/users/`, `/work-orders/<id>/requests` and `/work-orders/<id>` | The pilot sample lists all of them. Under MSW (`onUnhandledRequest: "error"`) an incomplete sample fails the guard, which is the intent |
| C5 | Draft test: note "still there after" (2, 6) | Starting runs `showPage(activePage)`, which re-renders the list and discards the open card and its textarea. `workOrderDrafts.js` only saves on a save attempt, and a stored draft is replayed (saved for real) on reconnect, so it cannot hold a note | **Question for the user.** Plan's call: the button refuses to start while the page holds typed text and says why in `messageDialog`. The Draft test asserts refusal and an intact textarea |
| C6 | "Leaving: `showPage` to another page" (5.4) | The player itself calls `showPage(activePage)` | `nav.showPage` ends a tutorial only when `pageName !== activePage` |

## Plan's calls (spec 8)

- Both tutorial files load with the app: static imports in `tutorials/index.js`, which `main.js` hands to the player.
- `installTutorials({ getActivePage, showPage, tutorials = TUTORIALS })`: injected, so `tutorial.js` never imports `nav.js` (nav imports it) and unit tests pass their own scripts.
- Responder shape: `setSampleResponder(fn | null)`; `api.js` calls `fn(path)` with the query string stripped (spec 5.3), `fn` returns body or `undefined`; `undefined` falls through to the network. Only GETs.
- "Next" is offered when a later script's **last `open` selector** exists now (the tab button is absent for a role that cannot see that tab); the guard proves every present tab has a visible step.
- Visible (spec 5.2) means: exists, not inside `[hidden]`, not inside a closed `<details>` unless it is that details' own `<summary>`. jsdom has no layout, so this is the test-time definition and the browser adds nothing.
- `open` rule (5.2): before clicking selector i, skip the click if what it reveals (selector i+1, or for the last one the first step's target) is already visible, so an open section is never toggled shut. After a click, wait up to 3 s for that next thing to be visible, not merely present.
- A step is skipped when its target is missing or not visible.
- No new element ids, so the id censuses are untouched. z-index chosen above `.tip-bubble` (30) and below the confirm modal (builder checks `styles.css` near line 4044).

## Conventions

Vitest from PowerShell: `Set-Location C:\Users\mcclu\Desktop\inventory_app_git; npx vitest run <files>`. Views load in tests through `mountView`/`importView`/`bootApp`, never a top-level relative import. Positions via CSSOM only (CSP). Commits: one per task, `git add <explicit paths>`, no trailer, no push. If `tutorial.js` nears 450 lines, move placement and DOM building to `tutorialView.js` before T3.

---

### Task 1: Sample responder in `api.js`

**Goal:** `rawFetch` answers listed GETs from an injected function (5.3, 7).
**Files:** Modify `backend/static/api.js`, `tests/frontend/unit/api.test.js`.
**Steps:**
1. Append to `api.test.js` a `describe("setSampleResponder")` with three tests: a responder returning `[{id: "x"}]` for `/work-orders/` makes `api.apiListWorkOrders()` resolve to it with no request reaching MSW (register an MSW handler that throws if hit); a responder returning `undefined` lets the MSW handler answer; after `setSampleResponder(null)` the MSW handler answers again. Add a test that `/work-orders/?status=x&mine=true` is answered by a responder keyed on `/work-orders/` (the responder is called with `"/work-orders/"`). Add a fifth: a POST is never offered to the responder (`vi.fn` not called).
2. Run the test file; the five fail (export missing).
3. In `api.js` beside `setConnectivityHandler`: `let sampleResponder = null; export function setSampleResponder(fn) { sampleResponder = fn; }`.
4. At the top of `rawFetch`, before the `long` line: if `sampleResponder` and method is GET (`(init.method || "GET").toUpperCase()`), call `sampleResponder(url.split("?")[0])`; if not `undefined`, return `new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } })`. Do not call `connectivityHandler`.
5. Add a header comment line: no DOM, no state; the player injects the function.
**Test:** `npx vitest run tests/frontend/unit/api.test.js tests/frontend/unit/staticImports.test.js` — all pass.
**Commit:** `feat(tutorials): api.js sample responder (0a T1)`.

### Task 2: Overlay and step engine

**Goal:** The visible player: spotlight, box, two-tap, Back, End, Esc, missing-target skip, `textFor` (5.4).
**Files:** Create `backend/static/tutorial.js`, `tests/frontend/unit/tutorial.test.js`. Modify `backend/static/styles.css` (append a `/* tutorial */` block).
**Steps:**
1. Read `docs/design-system.md` ("Two surface types") and `styles.css` near `.tip-bubble` (line 5296) for tokens; read `tests/frontend/helpers/browserStubs.js` for `stubScrollIntoView`.
2. In `tutorial.test.js` build a fixture: `mountView("tutorial.js")`, append a host with three divs (`#a`, `#b`, `#c`), one `<details>` closed holding `#d`, one `[hidden]` holding `#e`; stub `scrollIntoView` and `getBoundingClientRect`. Tests call exported `runSteps(script, role)`:
   - first tap on the overlay hides the box and shows the pill text "Tap anywhere for the next step"; second tap shows step 2 (title, "2 of 3");
   - Back absent on step 1, present after; End removes overlay and spotlight;
   - Esc ends; Enter and ArrowRight act as a tap;
   - a step whose target is missing, in `[hidden]`, or in a closed details (not its own summary) is skipped without a tap; `#d` inside an *open* details is shown;
   - `textFor: { supervisor: "X" }` shows "X" for role `supervisor`, the default for `technician`;
   - text is escaped (`<b>` appears literally);
   - `placeBox(rect, box, viewport)` returns below when it fits, above when not, bottom-pinned when neither, and never `left + width > viewport.width` (pure function, exported).
   - a click on the overlay never reaches a button beneath it (spy on a host button).
3. Run; all fail.
4. Implement in `tutorial.js`: constants; `visibleSteps(script, role)` → `[{step, el}]` using the skip rule; one lazily created overlay (`div.tut-overlay` full-viewport, `role="dialog"`, `aria-modal`), `div.tut-spot` (pointer-events none; darkening by a large box-shadow in CSS), `div.tut-box` (title, text, footer "n of N", Back, End, a `.tut-pill`). Positions via `style.left/top/width/height` on these nodes only.
5. Placement: `scrollIntoView({ block: "center" })`, then place on `requestAnimationFrame`; re-resolve the target by selector on every placement (spec 5.3 last bullet); reposition on `resize` and on `scroll` (capture, passive); if the target vanished keep the last position.
6. Input: overlay `click` = tap (state `box` shown → hide box + pill; hidden → next); capture-phase `keydown` on `document` while running: Enter/ArrowRight tap, Esc end, everything else `stopPropagation` except Tab, which cycles inside the box; focus the box's first button on each step.
7. CSS: `.tut-overlay`, `.tut-spot`, `.tut-box`, `.tut-pill`, `.tut-btn` (the page button), per design-system tokens, `max-width: calc(100vw - 16px)`; no `overflow-x`.
8. Export `runSteps(script, role)` (resolves when the box closes or the last step's Done/Next is chosen), `placeBox`, `visibleSteps`.
**Test:** `npx vitest run tests/frontend/unit/tutorial.test.js tests/frontend/unit/staticImports.test.js` — pass; `(Get-Content backend\static\tutorial.js).Count` under 450.
**Commit:** `feat(tutorials): overlay and step engine (0a T2)`.

### Task 3: Session — start, end, open, here, Next, guards

**Goal:** Start/end with sample mode and page restore; script choice; Next; the unsaved-text refusal (5.3, 5.4, C5, C6).
**Files:** Modify `backend/static/tutorial.js`, `tests/frontend/unit/tutorial.test.js`.
**Steps:**
1. Add tests (injected `showPage = vi.fn()`, `getActivePage = () => "demo"`, a two-script `tutorials.demo` with a `sample` returning `{"GET /demo/": [1]}`; `setTestUser` first):
   - `startTutorial("demo")` sets the responder (a fetch of `/demo/?x=1` is answered; `/other/` is not), calls `showPage("demo")` once, then shows step 1;
   - `endTutorial()` clears the responder and calls `showPage("demo")` once more; `endTutorial({ restore: false })` clears it and does not;
   - `endTutorial` when not running does nothing (no `showPage`);
   - `here`: with two scripts whose `here` selectors both match, the later in file order plays; with none matching, the first;
   - `open`: with `[A, B]` where B is already visible, A is not clicked; with B hidden, A is clicked and the run waits (fake timers) up to 3 s for B to be visible (present but hidden does not satisfy it); a click that never reveals the next ends quietly and restores the page; an already-visible first-step target means no click at all, so an open section is not toggled shut;
   - no visible step in the chosen script → ends quietly and restores;
   - last step shows "Next: <title>" and Done only when a later script's last `open` selector exists; Next runs that script without calling `showPage`; Done ends;
   - guard: with a non-empty `<textarea>` inside `#demo-page`, `startTutorial` shows `messageDialog` text, leaves the responder null, never calls `showPage`, textarea value unchanged (dismiss with `dismissMessageDialog` from `helpers/workOrders.js`);
   - starting closes an open tip (`closeTip` spy via the real tooltip: open one first, assert `#tip-bubble` hidden).
2. Run; fail.
3. Implement: module state `running`, `deps`; `installTutorials(deps)` stores deps; `startTutorial(page)`: return if running; refuse on unsaved text (any `textarea` or non-empty text/number `input` inside `#<page>-page` except elements matching `.tut-*`, and not `input[type=search|checkbox|radio]` filters); import `messageDialog` from `dom.js` ("Finish or save what you typed, then start the tutorial. It reloads the page."); `closeTip()`; `setSampleResponder(makeResponder(entry.sample(getCurrentUser())))`; `deps.showPage(page)`; pick script; `runOpen`; `runSteps`.
4. `makeResponder(map)` (exported): `path => map["GET " + path]` (api.js has already stripped the query).
5. `endTutorial({ restore = true } = {})`: set `running = false` first, remove overlay/listeners, `setSampleResponder(null)`, then `deps.showPage(deps.getActivePage())` if `restore` and a start had happened.
6. `runOpen(script)` per the open start rule; poll visibility with `setTimeout` 50 ms up to 3 s; exported for the guard.
7. Keep `import` order free of `nav.js`/`auth.js`.
**Test:** `npx vitest run tests/frontend/unit/tutorial.test.js tests/frontend/unit/staticImports.test.js` — pass.
**Commit:** `feat(tutorials): session, open, here, Next, unsaved-text refusal (0a T3)`.

### Task 4: Button and wiring

**Goal:** The "How this page works" pill on each indexed page; leaving, 401 and sign-out end a tutorial (5.5, 5.4).
**Files:** Create `backend/static/tutorials/index.js` (empty `TUTORIALS = {}` for now). Modify `backend/static/tutorial.js`, `backend/static/main.js`, `backend/static/views/nav.js`, `backend/static/views/auth.js`, `tests/frontend/views/tutorialWiring.test.js` (create).
**Steps:**
1. Write `tutorialWiring.test.js` with `bootApp` from `helpers/app.js`:
   - Register a fake entry through the real `installTutorials`? No: `main.js` installs the real index. Test via a temporary seam-free route: after `bootApp({ role: "supervisor", page: "work-orders" })`, import `tutorial.js` and call `installTutorials({ getActivePage: nav.getActivePage, showPage: nav.showPage, tutorials: { "work-orders": { scripts: [...], sample: () => ({}) } } })`; assert exactly one `.tut-btn` in `#work-orders-page h2`, placed after the existing tip button if any, text "How this page works", and calling `installTutorials` twice adds no second button.
   - Click it → overlay present. `nav.showPage("history")` → overlay gone, responder cleared, no extra `showPage` restore for `work-orders`.
   - Start again; trigger a 401 (`http.get` returns 401 for a non-sampled GET via `api.apiMe()` call) → overlay gone. Start again; click `#logout-btn` (read the real id in `shell` fragments first) → overlay gone.
   - A page not in the index has no button.
2. Run; fail.
3. `tutorial.js`: in `installTutorials`, for each page in `tutorials` find `#<page>-page h2`; insert `<button type="button" class="tut-btn" data-tut-page="…">How this page works</button>` after the h2's last child (after the `.tip-btn`); skip if one exists; one delegated `document` click listener on `.tut-btn` guarded by an `installed` flag.
4. `main.js`: `import { installTutorials } from "./tutorial.js"; import { TUTORIALS } from "./tutorials/index.js";` and call `installTutorials({ getActivePage, showPage, tutorials: TUTORIALS })` beside `installTooltips()` (add `showPage` to the existing nav import).
5. `nav.js`: `import { endTutorial } from "../tutorial.js"`; in `showPage`, before `closeTip()`: `if (activePage !== pageName) endTutorial({ restore: false });`.
6. `auth.js`: same import; first line of `showLoginScreen`: `endTutorial({ restore: false });` (covers the 401 handler and logout, which both route there).
7. Check `main.test.js`, `auth.test.js` still pass.
**Test:** `npx vitest run tests/frontend/views/tutorialWiring.test.js tests/frontend/views/main.test.js tests/frontend/views/auth.test.js tests/frontend/unit/staticImports.test.js` — pass.
**Commit:** `feat(tutorials): page button and leave/401/sign-out hooks (0a T4)`.

### Task 5: Guard test, then the pilot data

**Goal:** The single guard test (6), red first, then the four work-order scripts and sample that make it green (5.6).
**Files:** Create `tests/frontend/views/tutorialGuard.test.js`, `backend/static/tutorials/work-orders.js`, `backend/static/tutorials/work-orders.sample.js`. Modify `backend/static/tutorials/index.js`.
**Steps:**
1. Read `workOrderStatusActions.js` (`statusActionsHtml`), `workOrderPresenters.js` (`isCrewLocked`, `assignedIds`), `workOrderCardHtml.js` lines 513–612, `tests/frontend/helpers/factories.js` (`workOrderCard`, `workOrderDetail`, `workOrderItem`, `workOrderLabor`, `filterOptions`).
2. Write the guard. `describe.each(Object.keys(TUTORIALS))`, one `it` per page:
   - For each role in `PAGE_ACCESS[page]` (import `PAGE_ACCESS` via `bootApp`'s returned `nav`): `bootApp({ role })` (re-boot per role), `setSampleResponder(makeResponder(entry.sample(user)))`, `nav.showPage(page)`; then for each script: `await runOpen(script)`, `visibleSteps(script, role)`, assert at least one is visible for this role, record each visible target selector in a per-page set, re-run `nav.showPage(page)` to reset, finally `setSampleResponder(null)`.
   - After all roles: every step target of every script is in the set (visible for at least one role).
   - Data rules per script: `key` matches `^<page>\.[a-z0-9.-]+$` and is unique; `steps.length <= 8`; each `text` and `textFor` value `<= 240` chars and `<= 2` sentences (split on `/[.!?]+(\s|$)/`); `textFor` keys are in `["technician","supervisor","techfm_oa","admin","owner"]`; `here`/`open` are strings.
   - Sample rule (C1): walk every body; each value under a key `id`, `*_id` or in `*_ids` matches `^ffffffff-ffff-4fff-8fff-` unless it equals the viewer's id.
   - Separate `it` for work-orders: the sample detail has every key of `workOrderDetail()`, and each sample list card has every key of `workOrderCard()`.
3. Run; fails (index empty so `describe.each` has no cases; add an `it("index is not empty")` that fails).
4. `work-orders.sample.js`: `export function sample(user)` returning a map with keys `GET /work-orders/` (two cards), `GET /work-orders/<ID1>` and `<ID2>` (details), `GET /work-orders/<ID>/requests` (`[]`, both), `GET /work-orders/filter-options` (`filterOptions()` shape, written out), `GET /items/` (the three material items), `GET /users/` (viewer plus "Sample Technician"). Order 1: number `SAMPLE-1`, status `in_progress`, `assigned_to_ids: [user.id]`, `active_labor_session: null` (so Begin Charging renders), a two-line note in `notes`, three items, one labor entry of 150 min for the viewer (`labor_minutes: 150`), `item_count: 3`. Order 2: `SAMPLE-2`, status `created`. No imports, no functions beyond `sample`; ids written as literals.
5. `work-orders.js`: `export const SCRIPTS` in this order and these keys: `work-orders.card.details` (no `here`), `.notes`, `.materials`, `.labor`. Every `open` = `['details.wo-card[data-number="SAMPLE-1"] [data-peek-open]']` plus, for the last three, `'.wo-tab[data-wo-tab="<tab>"]'`. Every `here` = `'.wo-solo .wo-tab[data-wo-tab="<tab>"][aria-selected="true"]'` (not on Details). Steps use the wording and order of spec 5.6, with targets:

   | Step | Selector |
   |---|---|
   | Card header | `details.wo-solo > summary.wo-summary` |
   | Tab row | `#wo-sec-tabs` |
   | Details block | `#wo-sec-details .wo-details` |
   | Begin Charging | `#wo-act-start-tracking-wo` |
   | ⋯ button | `.wo-more-btn` |
   | Note log / box | `#wo-sec-notes .wo-notes-log` / `#wo-notes-input` |
   | Materials list / add row | `#wo-sec-materials .wo-items` / `#wo-add-item` |
   | New entries | `#wo-mode-select` (Team Lead+; skipped for others) |
   | Labor list / add hours | `#wo-sec-labor .wo-labor-list` / `#wo-add-labor` (Team Lead+) |
6. `index.js`: `export const TUTORIALS = { "work-orders": { scripts: SCRIPTS, sample } }` with the two static imports.
7. If the guard reports a selector with no match for any role, fix the selector against `renderBody`, not the guard. Do not add ids; if one is truly needed, add it and extend `tests/frontend/views/workOrders/bodyLiveCensus.test.js` in this task.
**Test:** `npx vitest run tests/frontend/views/tutorialGuard.test.js tests/frontend/views/tutorialWiring.test.js tests/frontend/views/workOrders/bodyLiveCensus.test.js tests/frontend/unit/staticImports.test.js` — pass. The Owner run shows no Begin Charging step, by the skip rule. Step targets inside a closed section (for example `#wo-notes-input` before the Notes tab is opened) count as not visible, which `open` must have fixed first.
**Commit:** `feat(tutorials): work-order card pilot scripts, sample, guard (0a T5)`.

### Task 6: Leak and Draft tests on the real page

**Goal:** Prove no sample survives End, and typed text is never lost (2, 6, C5).
**Files:** Create `tests/frontend/views/tutorialLeak.test.js`.
**Steps:**
1. Leak test, `bootApp({ role: "supervisor", handlers })` with MSW handlers answering the five work-order GETs with one real card `REAL-1` (use `workOrderCard`/`workOrderDetail` from `factories.js`; real ids). `nav.showPage("work-orders")`; `clearRequests()`. Click the `.tut-btn`; wait until `.tut-box` shows; assert the document contains `SAMPLE-1` and not `REAL-1`; click End; wait for the list; assert `SAMPLE-1` appears nowhere in `document.body.textContent`, `REAL-1` is back, `requestsFor("/work-orders/")` has at least one entry after End (reached MSW), and `location.pathname` is `/`.
2. Run it. Fails only if T1–T5 left a leak; if it fails, fix the cause in `tutorial.js`, not the test.
3. Draft test, same boot: open `REAL-1`'s card page (click `summary.wo-summary`, then `[data-peek-open]`), type "unsaved words" into `#wo-notes-input` with `userEvent`, click the `.tut-btn`; wait for the dialog (`#scan-confirm-overlay` visible); assert no `.tut-overlay`, textarea value unchanged, and after dismissing, a `GET /work-orders/` made via `api.apiListWorkOrders()` reaches MSW (responder not set).
4. Reference-data check (spec 8, last bullet): grep `backend/static/views` for module-level caches read by the work-order page (`allItems`, `allTechs` in `workOrderReferenceData.js`). The sample's `/items/` and `/users/` fill these during a tutorial, and `loadWorkOrders({ refreshReferenceData: true })` on End refills them from the server. Add one assertion to the Leak test: after End, `GET /items/` and `GET /users/` appear among `requestsFor` (users only for Team Lead+).
**Test:** `npx vitest run tests/frontend/views/tutorialLeak.test.js` — passes.
**Commit:** `test(tutorials): leak and unsaved-text tests on the real page (0a T6)`.

### Task 7: Docs, full frontend run, hand-check list

**Goal:** Current-truth entry; one full frontend run; user's checks.
**Files:** Modify `docs/current-state.md`.
**Steps:**
1. Add a short "Tutorials" entry in the frontend section, clipped bullets: files (`tutorial.js`, `tutorials/index.js`, `tutorials/<page>.js` + `.sample.js`); sample mode via `setSampleResponder`, pathname match, GET only; reserved id namespace `ffffffff-ffff-4fff-8fff-`; start refuses while typed text is on the page; `nav.showPage` (different page) and `showLoginScreen` end a tutorial; guard test `tests/frontend/views/tutorialGuard.test.js` is the rule for new scripts. Stay inside the doc's word budget; delete anything stale in the same edit.
2. Full run: `Set-Location C:\Users\mcclu\Desktop\inventory_app_git; npx vitest run`. Passing = zero failures except the pre-existing hub timer-leak failures noted in memory; name any other failure, do not edit around it.
3. Confirm `(Get-Content backend\static\tutorial.js).Count` (and `tutorialView.js` if split) under 500.
4. Do not start servers, push, or merge.
**Test:** the full run above.
**Commit:** `docs: tutorials 0a in current-state (0a T7)`.

## What the user checks by hand (running app, nothing pushed)

1. Work Orders page: the red "How this page works" pill sits after the title, wraps under it on a phone width, and no sideways scroll appears anywhere in the tutorial.
2. As Technician, Team Lead and Owner: the Details script runs on sample orders `SAMPLE-1` / `SAMPLE-2`; the Owner skips Begin Charging; Team Lead+ sees the Materials mode and Add hours steps, Technician does not.
3. Two-tap feel: first tap hides the box and keeps the section lit; second tap advances; Back, End, Esc and Enter behave; page behind does not react to taps or scrolling by touch.
4. The last box offers "Next: Notes" (then Materials, Labor) and Done; Next jumps without reloading the list.
5. After End or Done: real work orders are back, no `SAMPLE-` text anywhere, address bar is `/`. Press the browser Back button once and note what happens (the card-page entry the tutorial pushed stays in history; plan's call, not undone).
6. Type a note on a real card, press the pill: it refuses with the message and the note stays. Starting from the open real card page returns you to the list afterwards (not the card) — confirm that is acceptable.
7. Leave mid-tutorial (nav button, sign out): overlay disappears and the page is normal.
8. Each box fits a phone screen at the lit section, and every sentence is true against `tips.js` / `current-state.md` (not machine-checked).
