# Tutorials 5 — Starter Tutorials Implementation Plan

> **User rule (2026-11-23):** every box shows ONE simple sentence; a step may carry a list of up to 3, each at most 120 characters, one tap each (0a 5.2, 5.4).

**Goal:** A wait-for-tap player step, scripts that survive a page change, a third Hub sub-tab "Starter", and five menu-tour scripts, with tests proving input is blocked except the lit menu control.

**Spec:** `docs/superpowers/specs/2026-11-23-tutorials-5-starter-design.md` ("spec"; section numbers are its). Built on 0a, 0b and T1 plans (`2026-11-23-tutorials-0a-player.md`, `-0b-progress.md`, `-1-technician.md`). Names below come from those plans: `tutorial.js` (`runSteps`, `visibleSteps`, `startTutorial(page, key)`, `endTutorial`, `installTutorials`), `tutorials/index.js` (`TUTORIALS`), `tutorials/relevance.js` (`relevant`, `audienceLabel`), `tutorials/catalogue.js`, `tutorialProgress.js` (`mark`, `isDone`, `onChange`), `views/hubTutorials.js` (`mountHubTutorials`), `tutorialGuard.test.js`, `helpers/app.js::bootApp`. Inline execution, one builder, no subagents.

## Spec corrections

| # | Spec says | Code says | Plan does |
| --- | --- | --- | --- |
| C1 | 5.1: a step is skipped when no `waitTap` or `via` is visible (rects) | In a compact bar every popover button has no rects until its toggle is opened (`styles.css` 422-440), and a role-hidden button is `[hidden]`. "Rects" cannot tell "closed popover" from "this role has no such page" (`applyRoleVisibility` sets `btn.hidden`) | Role test: `waitTap` exists and has no `[hidden]` ancestor-or-self. Layout test: rects, only to choose `via` first. Role test fails: skip. After `via`, `waitTap` still has no rects after 3 s: end quietly |
| C2 | 2: "only click ever forwarded is a menu button" | Tap 1 for Team Lead and above is `.nav-group-toggle`, not `.nav-btn` | Forwarding is allowed only to the step's `via` or `waitTap` element, and the guard asserts each is `.nav-group-toggle` or `.nav-btn[data-page]` |
| C3 | 9: a tour's first wait reads "Tap X to begin." | Which page is first depends on role (Inventory: Add Item for OA+, Find Item below; Review: Low Stock for OA+, History for Team Lead) | Author "Now tap X." and add `textFor` on the role-first page: Inventory `Find Item` for technician and supervisor, Review `History` for supervisor |
| C4 | 5.2 "Technician (flat)" via comment "4 pages" | `PAGE_ACCESS` gives a Technician 5 non-hub pages (SMR added); still under the `> 5` threshold, flat | T6 fixes the stale comment in `nav.js` |
| C5 | 6 Playwright: Team Lead | `backend/tests/e2e/_seed.py` seeds owner, admin and technician only | T7 uses `admin_page` (same compact bar) and the technician login (flat bar) |
| C6 | 5.1 `endTutorial` returns at once while `expectNav` is set | A 401 or sign-out inside the 3 s window must still end it | The `expectNav` guard applies only to the `showPage` caller (`endTutorial({ restore: false, fromNav: true })`) |
| C7 | 7 current-state says four groups | `shell-head.html` has five: Inventory, Field, People, Review, Integration | T8 fixes it |

## Plan's calls

- Wait logic lives in new `backend/static/tutorialWait.js` (state, forward rule, `via`/`waitTap` resolution), imported by `tutorial.js`. `tutorialView.js` may not exist; the spec leaves the home to the builder (7).
- `textFor` values may be a list, like `text`; T1 adds a test and fixes the player if it only takes strings.
- Starter scripts carry `sample: false`; `startTutorial` also skips the responder, `showPage`, reload and unsaved-text refusal when the entry has no `sample` function (spec 5.3).
- 0b edits listed in spec 10.3 may or may not be in the plan as built: each such task writes the test first and keeps the code change only if the test is red.
- jsdom has no layout and loads no stylesheet. `tests/frontend/helpers/starterWalk.js` stubs `getClientRects` with the rules of `styles.css`: hidden by any `[hidden]` ancestor, by `.page:not(.active)`, by `.nav-group-toggle` outside `#main-nav.nav-compact`, and by a `.nav-group-menu` without `.open` inside a compact bar.

## Conventions

Vitest from PowerShell: `Set-Location C:\Users\mcclu\Desktop\inventory_app_git; npx vitest run <files>`. Views load through `bootApp`, `mountView`, `importView`. No inline styles (CSSOM only), no nested buttons, no sideways scroll, files under 500 lines. Commits: one per task, `git add <explicit paths>`, no trailer, nothing pushed (pushing main deploys).

---

### Task 1: Wait step in the player (unit)

**Goal:** `waitTap`, `via`, `viaText` behave as spec 5.1's table, minus page changes.
**Files:** Create `backend/static/tutorialWait.js`, `tests/frontend/helpers/starterWalk.js` (the `stubClientRects` half only). Modify `backend/static/tutorial.js`, `backend/static/styles.css` (no new rules unless the box needs a "waiting" look; classes only), `tests/frontend/unit/tutorial.test.js`.
**Steps:**
1. Write the stub helper, then tests (fixture: two buttons `#t1`, `#t2` plus `#other`, host spies on each click, fake timers, `stubScrollIntoView`):
   - Box stays up on a wait step; no pill; first tap does not hide it.
   - Overlay click with `clientX/Y` inside the lit rectangle (plus the builder's padding) calls `#t2.click()` once and the event does not reach a `document` click listener; a click outside calls nothing, advances nothing.
   - Enter and ArrowRight click the lit target; every other key, and `keyup` of Enter and Space, are `preventDefault`ed and stopped, so a focused host button never activates.
   - `via` visible and `waitTap` without rects: the player lights `via`; a click forwards to `via`; `waitTap` is lit once it has rects (poll 50 ms, re-resolved at each placement).
   - C1: `waitTap` under `[hidden]` skips the step and every step up to the next wait step; a role-visible `waitTap` with no `via` rects and no rects of its own ends quietly after 3 s.
   - Esc and End end it, not completed. Back is absent on the first step after a wait. `text` list and `textFor` list each give one sentence per tap.
2. Run; all red.
3. Implement in `tutorialWait.js`: `isWaitStep`, `resolveWait(step)` returning `{ el, kind }` (`"via"`, `"tap"`, `"skip"`), `forwardTap(event, litEl, pad)`, `blockKeys()` (capture `keydown` and `keyup`, installed by the player for the whole run). `tutorial.js` calls them from `runSteps`; keep it under 450 lines.
**Test:** `npx vitest run tests/frontend/unit/tutorial.test.js tests/frontend/unit/staticImports.test.js` passes; `(Get-Content backend\static\tutorial.js).Count` under 450.
**Commit:** `feat(tutorials): wait-for-tap player step (5 T1)`.

### Task 2: Run a script across pages

**Goal:** One script survives the page change its forwarded tap causes, and any other page change still ends it (5.1, C6).
**Files:** Modify `backend/static/tutorialWait.js`, `backend/static/tutorial.js`, `backend/static/views/nav.js`, `tests/frontend/unit/tutorial.test.js`, `tests/frontend/views/tutorialWiring.test.js`.
**Steps:**
1. Unit tests: after a `waitTap` forward, `isExpectingNav()` is true; it clears when the next step shows and after 3 s without a target (the run ends quietly, no progress `completed`). A start with an entry that has no `sample` and a script `sample: false` sets no responder, calls `showPage` zero times, never opens `messageDialog` with a non-empty textarea on the page, and `endTutorial` calls `showPage` zero times. Progress: entry marks `seen`, the last visible step marks `completed`, End early never does (reuse the 0b T7 expectations).
2. Wiring tests with `bootApp({ role: "supervisor" })` (real nav): start a fixture script `[wait Inventory via, wait Find Item, overview #saved-items-page]`. Forward both taps by overlay clicks inside the lit rect: `nav.getActivePage()` becomes `saved-items`, the overlay is still up, step 3 shows. A second script: while waiting, call `nav.showPage("history")` directly: overlay gone. Third: forward the page tap, then within the 3 s call `document` sign-out path (`#logout-btn` click): overlay gone (C6).
3. Run; red.
4. Implement: `expectNav` flag with a 3 s timer in `tutorialWait.js`; `nav.js::showPage` calls `endTutorial({ restore: false, fromNav: true })`, which returns at once only when `fromNav && expectNav`; `auth.js` keeps its plain call. In `startTutorial`, branch on `entry.sample` as in the Plan's calls, and `startTutorial("starter", key)` never calls `showPage`.
5. Fix the stale "Technician (4 pages)" comment above `COMPACT_NAV_THRESHOLD` (C4): 5 pages.
**Test:** `npx vitest run tests/frontend/unit/tutorial.test.js tests/frontend/views/tutorialWiring.test.js tests/frontend/views/nav.test.js` passes (find the nav test with Glob `tests/frontend/views/nav*.test.js`).
**Commit:** `feat(tutorials): scripts survive the page change a tap causes (5 T2)`.

### Task 3: Input lockdown proof

**Goal:** Prove that during a starter nothing but the lit menu control accepts input and that no request leaves except the opened page's own GETs (user's standing rule: tutorials never change real data).
**Files:** Create `tests/frontend/views/tutorialLockdown.test.js`.
**Steps:**
1. `bootApp({ role: "supervisor" })` and, in a second `describe`, `role: "technician"`; `clearRequests()`; start a fixture script (`#main-nav` overview, then wait Inventory via, wait Find Item, overview `#saved-items-page`, `#logout-btn` overview). At every step, including the overview steps:
   - Dispatch clicks at the overlay outside the lit rect, and `pointerdown`/`touchstart`; then `requests()` is empty, `nav.getActivePage()` unchanged, `#logout-btn` not called (spy on `fetch` for `/auth/logout`), toggle `aria-expanded` unchanged.
   - Dispatch `keydown`/`keyup` for Tab, Space, Enter-on-a-focused-`#logout-btn` (focus it first); nothing activates and focus moves into the box.
   - Overlay is the last child of `body`, and `styles.css` text holds `.tut-overlay` with `position: fixed` and a z-index above `.nav-group-menu` (20), read from the file, so the cover cannot silently shrink.
2. Forward the real taps and assert every request in `requests()` has method `GET`; no request is recorded between two taps; Find Item makes none (`PAGE_LOADERS["saved-items"]` loads nothing).
3. Add a case that a starter run on the Work Orders page-change (Field via, Work Orders) records only GETs, matching `GET /work-orders/*` paths.
4. Run. If a case is red, fix `tutorialWait.js`, not the test.
**Test:** `npx vitest run tests/frontend/views/tutorialLockdown.test.js` passes.
**Commit:** `test(tutorials): starter blocks all input except the lit menu control (5 T3)`.

### Task 4: Relevance and the Starter sub-tab

**Goal:** `relevant`/`catalogue` accept `starter` entries; Hub Tutorials gains Starter (spec 5.4, 5.5, 10.3).
**Files:** Modify `backend/static/tutorials/relevance.js`, `backend/static/tutorials/catalogue.js`, `backend/static/views/hubTutorials.js` (split the entry renderer into `backend/static/views/hubTutorialEntries.js` if it passes 450 lines), `backend/static/styles.css`, `tests/frontend/unit/tutorialRelevance.test.js`, `tests/frontend/unit/tutorialCatalogue.test.js`, `tests/frontend/views/hubTutorials.test.js`, `tests/frontend/views/usersTutorials.test.js`.
**Steps:**
1. Tests first:
   - `relevant({ page: "starter", minRole: "supervisor" }, "technician")` false, `"supervisor"` true; `minRole: "technician"` true for every role; `audienceLabel` says "Everyone" and "Team Lead and above" from `roleLabel`.
   - `catalogue(fakeTutorials)` returns a `starter` entry's scripts with `page: "starter"`.
   - Hub (`openHub({ tab: "tutorials", role })`, progress seeded by MSW `me`): three sub-tab buttons in order To do, Completed, Starter; opens on To do; Starter lists only relevant starters in order labelled New, Started, or Done with Replay; its count is the unfinished number and the count span is absent at 0; the same starters also appear in To do (grouped "Menu") and Completed; "You have finished every tutorial" holds only when starters are finished too; the Tutorials tab dot counts an unfinished starter; each entry is one `button`, none nested; a tap calls `startTutorial("starter", key)` and never `showPage`; `setTutorialsSub("starter")` before `loadUserHub` opens on Starter (batch 6 uses it).
   - Users page (`usersTutorials.js`): a supervisor's total includes all five starters, a technician's three, counted in "N of M".
   - No `#starter-page` exists, so no page dot or button (assert `document.querySelector("[data-tut-page=starter]")` null).
2. Run; red where the 0b plan has not already been amended.
3. Implement; keep a test green that already was. Sub-tab buttons reuse the To do/Completed classes and wrap on a phone (no sideways scroll). Export `setTutorialsSub(name)` from `hubTutorials.js`.
**Test:** `npx vitest run tests/frontend/unit/tutorialRelevance.test.js tests/frontend/unit/tutorialCatalogue.test.js tests/frontend/views/hubTutorials.test.js tests/frontend/views/usersTutorials.test.js tests/frontend/views/hubIdsCensus.test.js tests/frontend/unit/staticImports.test.js` passes.
**Commit:** `feat(tutorials): Starter sub-tab and starter relevance (5 T4)`.

### Task 5: Guard additions (red)

**Goal:** The cross-page guard of spec 6 for all five roles, failing until the scripts exist.
**Files:** Modify `tests/frontend/helpers/starterWalk.js` (add `walkWaits(script, role)`), `tests/frontend/views/tutorialGuard.test.js`.
**Steps:**
1. `walkWaits` on a booted app: for each step with `waitTap`, if the role test (C1) fails skip it and the steps up to the next wait; else if `waitTap` lacks rects, assert `via` is a visible `.nav-group-toggle` and click it; assert `waitTap` now has rects and matches `.nav-btn[data-page]`; click it; assert `#<page>-page` has `.active` and the next step's target has rects; return the visited pages.
2. In the guard: change the 0a per-page loop to skip entries without `sample`; add `describe("starter scripts")`:
   - Index has `starter` with exactly the keys `starter.menu|inventory|field|people|review`, no `sample` on the entry, `sample: false` on each script, no `open`, no `here`.
   - Per script, per role in `ALL_ROLES` from `minRole` up: `bootApp({ role })`, `stubClientRects()`, `walkWaits`; visited pages equal the group's pages for that role minus `smr` and `smr-admin-review`, read from the markup (`[data-nav-group=<g>] .nav-btn:not([hidden])`). The menu script visits only `saved-items`. Roles below `minRole` have zero visible buttons in that group (no step offered).
   - Data rules: each `waitTap`/`via` is `.nav-btn[data-page]`/`.nav-group-toggle` by selector shape; wait `text` is one sentence of at most 120 characters; every other box at most 3 sentences of at most 120 characters (split on `/[.!?]+(\s|$)/`), also for `textFor` lists; at most 8 steps; keys unique across all pages; overview targets other than `#main-nav`, `#auth-user-indicator`, `#logout-btn` are `#<page>-page`; no step targets anything inside a pop-up.
   - Every step of every script is visible or role-skipped for each eligible role (a wait step the role can never see is allowed only when its page is absent from that role's `PAGE_ACCESS`).
3. Run; red (index has no `starter`).
**Test:** `npx vitest run tests/frontend/views/tutorialGuard.test.js` fails only on the starter describe.
**Commit:** `test(tutorials): cross-page starter guard, red (5 T5)`.

### Task 6: Starter scripts and registration

**Goal:** The five scripts, wording verbatim from spec 9, green against T5.
**Files:** Create `backend/static/tutorials/starter.js`. Modify `backend/static/tutorials/index.js`.
**Steps:**
1. `export const SCRIPTS = [...]` data only, no imports, in tour order menu, inventory, field, people, review. Keys, `minRole` and wording from spec 5.4 and 9; titles: "Using the menu", "Inventory", "Field", "People", "Review". Every script `sample: false`.
2. Step shape per page (spec 9 tables): `{ waitTap: '.nav-btn[data-page="<page>"]', via: '[data-nav-group="<g>"] .nav-group-toggle', viaText: "Tap <Group> to open it.", text: "Now tap <Page>." }`, then `{ target: "#<page>-page", text: [...] }`. Technician is flat, so `via` is skipped by the layout test and the tour reads without it. Add C3's `textFor` on the role-first waits. Menu script: `#main-nav` step with `textFor` for supervisor, techfm_oa, admin, owner (spec 9 second sentence), the Find Item wait (via Inventory), `#main-nav`, `#auth-user-indicator`, `#logout-btn`.
3. `index.js`: `starter: { scripts: STARTER }` beside the other entries, no `sample`; `installTutorials` finds no `#starter-page`, so no button.
4. Run the guard. If a selector misses, fix it against `shell-head.html` lines 112-152, never invent an id. Wording problems are reported, not reworded.
**Test:** `npx vitest run tests/frontend/views/tutorialGuard.test.js tests/frontend/views/tutorialLockdown.test.js tests/frontend/views/hubTutorials.test.js` passes.
**Commit:** `feat(tutorials): five starter menu tours (5 T6)`.

### Task 7: Real-player flow and phone layout

**Goal:** Each starter completes on the real player in the real shell; the Field starter fits a 375 px phone.
**Files:** Create `tests/frontend/views/tutorialStarterFlow.test.js`, `backend/tests/e2e/test_starter_tutorial.py`.
**Steps:**
1. Flow test, `bootApp` for technician, supervisor and owner, `stubClientRects()`, fake timers: `startTutorial("starter", "starter.field")`; forward taps with overlay clicks at the lit rect (stubbed `getBoundingClientRect`); step through overview taps; assert the visited pages equal T5's expectation, `completed` marked once on the last visible step, no PUT before it, `seen` marked at start, and the person ends on the last opened page. A run that Esc-ends after the first forwarded tap marks no `completed`. The Menu starter ends with the person on Find Item for every role.
2. Playwright (`pytest.mark.e2e`, fixtures `admin_page`, and `login_as(seeded.technician_username)`; no local Chromium: write it, run only if installed): at 375 px click `#hub-tab-tutorials`, open Starter, play Field. Using real mouse clicks (`page.mouse`), click `#logout-btn` while a wait step is lit and assert `#login-screen` stays hidden; record `page.on("request")` and assert every request during the starter is a GET; tap the lit toggle then Scan / Stock; assert no horizontal overflow with the `_OFFENDERS_JS` helper from `test_mobile_overflow.py`. Repeat as technician for the flat bar.
**Test:** `npx vitest run tests/frontend/views/tutorialStarterFlow.test.js` passes. Optional: `backend\venv\Scripts\python.exe -m pytest backend\tests\e2e\test_starter_tutorial.py -m e2e` from `backend\` (commits `E2E-` rows and sweeps them; skip locally if unsure).
**Commit:** `test(tutorials): starter flow on the real player, phone e2e (5 T7)`.

### Task 8: Docs, full frontend run, hand-check list

**Goal:** `docs/current-state.md` is current truth; one full frontend run is green.
**Files:** Modify `docs/current-state.md`.
**Steps:**
1. Frontend Feature Context, Navigation line (about line 916): replace "four task-domain groups — Inventory, Field, People, Review" with five, adding Integration (C7). In the Tutorials entry add clipped bullets: `starter` is a page-less entry (`tutorials/starter.js`, no sample, `sample: false`); the player's wait step forwards only the lit tap; `expectNav`; Hub Starter sub-tab; guard `describe("starter scripts")`. Delete anything stale in the same edit; mind the doc's word budget.
2. From PowerShell: `Set-Location C:\Users\mcclu\Desktop\inventory_app_git; npx vitest run`. Passing = zero failures except the known hub timer-leak failures; name any other failure, do not edit around it.
3. Confirm `(Get-Content backend\static\tutorial.js).Count` and the new files are under 500.
4. Do not start servers, push, or merge.
**Test:** the full run above, coverage gate green.
**Commit:** `docs: tutorials starter in current-state (5 T8)`.

---

## What the user checks by hand (running app, nothing pushed)

For every role: Hub, Tutorials, Starter lists the right starters in order with New/Started/Done; a tap plays at once on the Hub; Esc and End leave you where you are; no sideways scroll at 320 and 375 px; every sentence is true against the app.

| Role | Check |
| --- | --- |
| Technician (flat bar) | Menu starter: no group step, lights Find Item; Inventory shows Find Item and Tools only; Field shows Scan / Stock and Work Orders; no People or Review starter listed |
| Team Lead | Group name lit first, then the page inside the open popover; Field includes Mass Stage; People shows Users; Review shows History only, and the History wait reads "Tap History to begin." |
| TechFM OA | Inventory starts with Add Item; Review starts with Low Stock and covers User Requests and Admin Review; SMR entries never lit |
| Admin and Owner | Same as TechFM OA; Menu box 1 second sentence names the groups |
| All | While a box waits, tapping Log Out, other buttons, the page or typing does nothing and no data changes; Back is not offered after a page change; finishing Menu leaves you on Find Item; the Tutorials tab dot clears when the last starter is done |
