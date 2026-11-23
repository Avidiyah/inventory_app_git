# Tutorials 1 — Technician Batch Implementation Plan

> **Rule added by the user 2026-11-23 (overrides anything below):** every box shows ONE simple sentence. A step that needs more is written as a list of sentences (`text: ["...", "..."]`, at most 3, each at most 120 characters) and the player gives each sentence its own tap on the same lit section. Wording tables that hold two sentences in one step are split at the sentence boundary, never merged into a longer sentence. Use plain words a new hire would use; one idea per sentence. See 0a spec 5.2 and 5.4.

> **For the orchestrator (Opus 5.5):** run Tasks 1–3 yourself; spawn Tasks 4–8 as parallel Sonnet 5.5 agents (medium effort, never forks) after the owner authorizes agents; then Task 9. This repo bars subagents unless authorized per task.

**Goal:** Nine Technician-loop tutorial scripts on five pages (work-orders, transaction, user-hub, tools, saved-items), written as data.

**Architecture:** Three small player/page changes first (a button slot, an end hook, a tolerant `open`), then one agent per page writing only that page's two files, then registration, gates and one wording-review table.

**Spec:** `docs/superpowers/specs/2026-11-23-tutorials-1-technician-design.md` (T1). Foundations: `...-0a-player-design.md` (0a), `...-0b-progress-design.md` (0b). Section numbers below are theirs. Assumes 0a and 0b are built; file and function names are from `2026-11-23-tutorials-0a-player.md` (0a plan).

## Spec corrections (verified in code 2026-11-23)

| # | Spec says | Code says | Handled by |
|---|---|---|---|
| 1 | T1 §4: keys match "path and query to the character"; `sample(user)` picks the Tech vs other `GET /work-orders/` | 0a 5.3 matches the path alone, so one key per path; the body cannot vary by query | Briefs: one `GET /work-orders/` key per page |
| 2 | T1 §5: gate card may need `.wo-gate-card` | Cards are `button.wo-card` in `#wo-gate-cards` (`transactions.js:451`); `#wo-gate-cards .wo-card` already works | No anchor added |
| 3 | T1 §5: items row needs an action-cell class | The cell is `td[data-label="Actions"]` (`items.js:322`); present only for `canAdmin \|\| canNotes` | No anchor added |
| 4 | 0a 5.5: button on the first `h2` | Transaction's first `h2` sits in `#wo-gate`, hidden during a batch; Find Item's sits in the Find panel, hidden on Scan. The button vanishes where T1 §3.2 and §3.5 scripts need it | Task 1 slot, for all three pages |
| 5 | T1 §3.4: `open` clicks only for OA+ | 0a 5.2: a missing `open` selector ends the tutorial, so Tech/TL would end at once | Task 3 optional `open` |
| 6 | T1 §3.3: `.hub-tile-grid` | The class appears in Home, priorities, crew and admin panels | Brief scopes it under `#hub-tabpanel-home` |
| 7 | T1 §8: "no leaked batch state" as a hand check | Tapping a gate card sets module state and `sessionStorage["scango-batch"]`, and `searchItemsLoaded` caches sample items (`transactions.js:55,138,298`). End would re-enter the sample batch | Task 2 hook and test |
| 9 | T1 §4, §7 and 0a 5.3: sample ids are negative | Every id is a UUID string; 0a plan C1 reserves the prefix `ffffffff-ffff-4fff-8fff-0000000000NN` (the viewer's own id is exempt) | Every brief uses the prefix, with fixed `NN` ranges per page |
| 8 | T1 §9: phone `open` may need `#hub-picker-toggle` | Tab buttons stay in the DOM when the picker is closed (`display:none`); a programmatic click reaches `showTab`, and `syncSectionPicker` updates the label (`userHub.js:90`) | Task 3 test; no toggle click |

## Global constraints

- CSP: classes only. No nested buttons. No sideways scrolling at phone width.
- Vitest from PowerShell at `C:\Users\mcclu\Desktop\inventory_app_git` (`npx vitest run <file>`). Targeted files only.
- Commits: stage explicit paths, no `Co-Authored-By` trailer, nothing pushed (pushing main deploys).
- Agents write only their own two files. The orchestrator alone edits app code, `tutorials/index.js`, tests, docs.
- No new ids on morph-patched rows or tiles, so the id census (`tests/frontend/views/hubIdsCensus.test.js`) needs no change. Re-run it to prove that.

---

### Task 1: Button slot (Hub exception, plus transaction and Find Item)

**Goal:** 0a 5.5 gains one rule: if `#<page>-page` contains `[data-tutorial-slot]`, the button goes inside it, else after the first `h2`. Hub, Transaction and Find Item get a slot.

**Files:**
- Modify: `backend/static/tutorial.js` (the 0a button-placement code); `backend/static/pages/user-hub.html`, `pages/transaction.html`, `pages/saved-items.html`; `backend/static/styles.css`
- Test: `tests/frontend/unit/tutorial.test.js` (0a plan T2)

**Steps:**
- [ ] `user-hub.html`: add `<div class="tutorial-slot" data-tutorial-slot></div>` as the LAST child of `#hub-picker`, after `<nav id="hub-tabs">`.
  - Desktop: `#hub-picker` becomes a wrapping flex row (`display:flex; flex-wrap:wrap; align-items:flex-start; gap:var(--space-3)`), `.hub-tabs` gets `flex:1 1 auto; min-width:0`, so the pill ends the tab row. Wrapping drops the pill to its own line between 601 and about 900 px instead of scrolling.
  - Phone (inside the existing `max-width:600px` block): the slot is a full-width row inside the picker card with `border-top: var(--border)` and `padding: var(--space-3)`. Closed card: toggle, then button. Open card: toggle, tile grid, then button. The button is always reachable and never inside the toggle button.
- [ ] `transaction.html`: slot as first child of `#transaction-page`. `saved-items.html`: slot right after `<nav class="sub-nav">`. Both are outside every hidden panel.
- [ ] `styles.css`: `.tutorial-slot:empty { display:none }` so a page with no tutorial shows nothing.
- [ ] Player: find `[data-tutorial-slot]` first, fall back to the `h2` rule. The slot rule must also win for `user-hub`, whose rendered Home panel contains `h2`s that the fallback would wrongly match.

**Test:** Player unit test, three cases: slot present gets the button inside it; no slot uses the `h2`; `user-hub` markup with a Home `h2` still uses the slot. Then run `staticImports.test.js` and `hubIdsCensus.test.js`.

---

### Task 2: End hook clears a sample scanning batch

**Goal:** Ending any tutorial leaves no sample batch, saved snapshot or cached sample item list (spec correction 7).

**Files:**
- Modify: `backend/static/tutorial.js` (the single end routine), `backend/static/views/transactions.js` (about 6 lines; the file is already over its cap, and these lines delegate to existing `resetBatch`)
- Test: new `tests/frontend/views/transactionTutorialEnd.test.js`

**Steps:**
- [ ] In the player's end routine, after clearing the responder and before the final `showPage(activePage)`, run `document.dispatchEvent(new CustomEvent("tutorial:end"))`.
- [ ] `transactions.js`: add a `document` listener for `tutorial:end`. If `batchWorkOrder` is set and `String(batchWorkOrder.id).startsWith("ffffffff-ffff-4fff-8fff-")`, call `resetScanUi?.()` then `resetBatch()`. `resetBatch` already clears the snapshot, `searchItemsLoaded`, the log and the gate cards.
- [ ] Do not touch real batches: an id without the reserved prefix is never reset.

**Test:** Mount the transaction view (follow `tests/frontend/views/` transaction tests for the mount helper), tap the gate card whose `data-wo-id` is `ffffffff-ffff-4fff-8fff-000000000011`, dispatch `tutorial:end`, then assert: gate visible, `sessionStorage.getItem("scango-batch")` is null, and a second batch start re-requests `GET /items/`. A second case with a real UUID id (no reserved prefix) asserts nothing is reset.

---

### Task 3: Player `open` tolerates focus-driven and role-only clicks

**Goal:** Two additions to 0a 5.2 `open`: a leading `?` marks a selector optional (skipped at once when absent, no 3 s wait); every click is preceded by `el.focus?.()`, because the Tools user list renders on focus (`tools.js:290`). Plus proof that a hidden Hub tab can be clicked.

**Files:**
- Modify: `backend/static/tutorial.js`
- Test: `tests/frontend/unit/tutorial.test.js`

**Steps:**
- [ ] In the `open` loop: strip a leading `?`; if optional and `querySelector` finds nothing now, continue; else keep the 3 s wait and fail rule. Call `focus()` then `click()`.
- [ ] Confirm the guard test (0a 6) strips the `?` before checking an `open` selector exists for some role. Fix it if not.

**Test:** Player unit tests (0a's rules stay: skip a click when what it reveals is already visible; wait for visible, not present): optional-absent is skipped without waiting; required-absent still ends quietly; focus fires before click; a click on an element inside a `display:none` container (Hub tab case) reaches its handler. Update the 0a doc line for `open` by one sentence in `docs/current-state.md` during Task 9, not here.

---

## Agent briefs (Tasks 4–8)

For each task paste the **Common block** first, then that page's block. The orchestrator does not summarize either.

### Common block

> You are writing tutorial data for one page of an existing app (FastAPI backend, no-build vanilla-JS frontend). Write ONLY the two files named in your page block. Never edit any other file, never run git, tests or a server, never spawn agents. Return paths, missing anchors and questions only, never file contents.
>
> Read first, in full: `docs/superpowers/specs/2026-11-23-tutorials-0a-player-design.md` (sections 5.2, 5.3, 5.6), `...-0b-progress-design.md` section 5.4, `docs/superpowers/specs/2026-11-23-tutorials-1-technician-design.md` (your page's rows in sections 3, 4, 6, 7), `backend/static/tips.js`, `docs/current-state.md` (Roles and Frontend Feature Context), then the worked example `backend/static/tutorials/work-orders.js` and `work-orders.sample.js`, then your page's html and view modules.
>
> Script file: `export const SCRIPTS = [...]`, data only, no imports, no functions. Use the exact `key`, `title`, `here`, `open` named in the spec. Wording is copied VERBATIM from the spec wording tables; never reword. The Role column: "X only" or "skipped" means rely on the missing-target rule and add no `textFor`; a quoted wording becomes `textFor` keyed by stored role (`technician`, `supervisor`, `techfm_oa`, `admin`, `owner`). Each script is for everyone, so add no `minRole`. If a spec selector is not in the real markup, keep the step, do NOT invent a selector, and report it. If wording breaks a house rule (8 steps, 2 sentences, 240 characters), keep it and report.
>
> Sample file: `export function sample(user)` returns `{ "GET /path": body }`. Keys are the path alone with no query string (a request matches on path only). Every sample record id is a UUID with the reserved prefix `ffffffff-ffff-4fff-8fff-0000000000NN`, using only the `NN` values your page block gives (the viewer's own id is exempt); the guard fails on any other UUID in an `id`, `*_id` or `*_ids` value. Names are made up in the style of the existing sample file. Read the viewer from `user` (`id`, `role`, names); never hard-code a role. Response shapes come from the real API: the page's `api*` function in `backend/static/api.js`, the matching router and schema under `backend/app/routers` and `backend/app/schemas`, and the factories in `tests/frontend/helpers/factories.js` (copy their shapes; do not import them). Read `docs/superpowers/plans/2026-11-23-tutorials-0a-player.md` (Spec corrections C1 to C3 and its work-orders sample task) for the real pilot selectors: a list card is `details.wo-card[data-id][data-number]`, and the tabbed card is the card page reached through its `[data-peek-open]`. List every GET the page's loader issues for each role, and answer each one you can; answer nothing else.
>
> Report back: the two file paths; every selector not found (and what the markup gives instead); the GET paths you answered; every GET you saw but did not answer; any question only the owner can settle.

### Task 4: work-orders (extend, never rewrite)

**Goal:** Add `work-orders.list.find` (T1 §3.1) as the FIRST script, with no `here` and no `open`.

**Files:** edit `backend/static/tutorials/work-orders.js` and `work-orders.sample.js`. All four pilot scripts and their keys stay byte-for-byte; add the new script above them.

**Steps (page block):**
- Read `pages/work-orders.html`, `views/workOrders.js`, `workOrderList.js`, `workOrderReferenceData.js`, `workOrderFilters.js`.
- Sample: add order `SAMPLE-3` (Assigned, id `ffffffff-ffff-4fff-8fff-000000000003`) beside pilot orders `SAMPLE-1` (In-Progress, viewer on crew) and `SAMPLE-2` (Created). Keep the pilot orders unchanged. One community and two service types across them. Answer `GET /work-orders/` (card list shape) and `GET /work-orders/filter-options` (`filterOptions` factory). The "first sample card" target is the first `details.wo-card` in the list container; use the real container selector.
- The Technician-filter step uses the real id the filters module renders; report it.
- Report: the exact GET paths the default load issues.

**Test:** the orchestrator's guard run in Task 9.

### Task 5: transaction

**Goal:** `transaction.scan.pick` and `transaction.scan.scanning` (T1 §3.2).

**Files:** create `backend/static/tutorials/transaction.js` and `transaction.sample.js`.

**Steps (page block):**
- Read `pages/transaction.html`, `views/transactions.js` (gate render at line 440, `selectWorkOrderForBatch` at 365, `refreshWoCards` at 485), `views/scan.js`.
- Sample, one key each: `GET /work-orders/` returns `SAMPLE-11` and `SAMPLE-12` (In-Progress, ids `ffffffff-ffff-4fff-8fff-000000000011`, `ffffffff-ffff-4fff-8fff-000000000012`) and `SAMPLE-13` (Assigned, id `ffffffff-ffff-4fff-8fff-000000000013`); each carries `id`, `number`, `status`, `community`, `building_number`, `unit_number`, `assigned_to_name`. Every role gets the same list, with the viewer as assignee on `-11` and `-12`. `GET /items/` returns three items, ids `ffffffff-ffff-4fff-8fff-000000000021` to `ffffffff-ffff-4fff-8fff-000000000023`, with barcodes, locations and quantities.
- Step targets: first gate card is `#wo-gate-cards .wo-card`. `open` for scanning taps `#wo-gate-cards .wo-card[data-wo-id="ffffffff-ffff-4fff-8fff-000000000011"]`. Never tap `SAMPLE-13` (a tap asks to start the order and writes).
- Report: whether the gate selector held; whether a resumed batch skips the gate; the `GET /work-orders/` calls a Tech versus a Team Lead issues.

### Task 6: user-hub

**Goal:** `user-hub.home` and `user-hub.work-orders` (T1 §3.3).

**Files:** create `backend/static/tutorials/user-hub.js` and `user-hub.sample.js`.

**Steps (page block):**
- Read `pages/user-hub.html`, `views/userHub.js`, `hubHome.js`, `hubClock.js`, `hubTechnician.js`, `hubPicker.js`, and `backend/app/routers/hub.py`.
- Sample: `GET /hub` (`hubPayload` factory; `user` built from the `user` argument; `server_now` set; `startable` is one entry with work-order id `ffffffff-ffff-4fff-8fff-000000000051` from `hubStartable`; counts assigned 2, in progress 1, ready 0; nothing running). `GET /attendance/me` (`attendanceMe` factory; not punched in; one earlier punch this week with an id ending `53`). The My Work Orders tab calls `GET /work-orders/` through the shared list module: answer it with the page 4 card shape (numbers `SAMPLE-51` and `SAMPLE-52`, ids `ffffffff-ffff-4fff-8fff-000000000051` and `ffffffff-ffff-4fff-8fff-000000000052`) and `GET /work-orders/filter-options` if the list issues it. `/hub/crew` and `/hub/admin` are NOT answered; list them as unanswered.
- Scope the counts target as `#hub-tabpanel-home .hub-tile-grid`; if more than one match exists there, use the unique tile id's parent instead.
- `open` clicks `#hub-tab-home` and `#hub-tab-work-orders`; a collapsed phone picker does not matter (Task 3 test).
- Report: every GET issued on load per role; whether the Owner renders `#hub-clock-mount`; anything that needs the picker toggle.

### Task 7: tools

**Goal:** `tools.custody.checkin` (T1 §3.4).

**Files:** create `backend/static/tutorials/tools.js` and `tools.sample.js`.

**Steps (page block):**
- Read `pages/tools.html`, `views/tools.js` (loader at 680; user list renders on focus at 290; check-in button at 215), `views/toolReturn.js`.
- Sample: `GET /tools/` returns two tools, ids `ffffffff-ffff-4fff-8fff-000000000031` and `ffffffff-ffff-4fff-8fff-000000000032`, shapes from `tool` and `toolCustodyEntry`. Tool `ffffffff-ffff-4fff-8fff-000000000031` has custody for the viewer (`user.id`), tool `ffffffff-ffff-4fff-8fff-000000000032` for a made-up "Pat Sample", id `ffffffff-ffff-4fff-8fff-000000000041`. `GET /users/` (called only when the viewer is OA+) returns the viewer and Pat Sample, shaped like `user` in the factories, none archived.
- `open` is OA+ only and uses optional steps (Task 3): `'?#tool-user-picker:not([hidden]) #tool-user-search'`, then `'?.tool-user-option[data-user-id="ffffffff-ffff-4fff-8fff-000000000041"]'`. Replace the second selector with the real option attribute. Tech and TL pick no one (the page pins their own card); OA+ lands on Pat Sample's card.
- Report: the real option selector; whether `#tool-user-picker` carries `hidden` for Tech and TL; whether the `/users/` call is per role.

### Task 8: saved-items

**Goal:** `saved-items.find.search` and `saved-items.scan.scan` (T1 §3.5).

**Files:** create `backend/static/tutorials/saved-items.js` and `saved-items.sample.js`.

**Steps (page block):**
- Read `pages/saved-items.html`, `views/items.js` (columns at 240; `loadItemResults` at 150), `views/subnav.js`.
- Sample: `GET /items/` returns four items, ids `ffffffff-ffff-4fff-8fff-000000000021` to `ffffffff-ffff-4fff-8fff-000000000024`, with barcode, location and quantity; `price` and `product_link` filled so OA+ sees them.
- Row action target: `#items-table td[data-label="Actions"]` (first one). It exists only when the viewer can admin or add notes.
- `saved-items.find.search` `open` is `#items-load-all-btn` so the table renders. The wording in step 1 is shown on the Find tab only.
- Report: columns shown for a Tech versus OA+; whether the Actions cell is absent for a Tech.

---

### Task 9: Register, gate, review, commit

**Goal:** All five pages play in the guard test; the owner gets one wording table.

**Files:**
- Modify: `backend/static/tutorials/index.js` (extend the `TUTORIALS` map with `"<page>": { scripts: SCRIPTS, sample }` and two static imports per page; `work-orders` is already there), `docs/current-state.md` (only the Tutorials entry)
- Test: the 0a guard test (`tests/frontend/views/tutorialGuard.test.js`), `tests/frontend/unit/tutorial.test.js`, `staticImports.test.js`, `hubIdsCensus.test.js`, the Task 2 test

**Steps:**
- [ ] Read each agent's report. Resolve missing anchors: add the id or class to the page html yourself, or fix the selector in the agent's file if the markup already has it. Answer the owner-only questions in the final message, never silently.
- [ ] Register the pages, each with the same entry shape `work-orders` uses.
- [ ] Run the guard, player, Task 2, `staticImports` and census files, one `npx vitest run` call each from PowerShell. Fix failures in this order: selector missing, `open` unreachable, a sample GET not answered, house-rule limits. If a wording limit fails, shorten the wording and flag the change in the table.
- [ ] Look for unanswered GETs in agent reports that would otherwise show real rows next to sample ones (for example `/hub/crew`), and decide: leave or sample.
- [ ] Produce one table for the owner: page, script key, step, final wording, role variants, anything changed from the spec's wording. Two checks stay with the owner (they start the server): the Hub scripts and the Technician run of `transaction.scan.scanning` at phone width.
- [ ] `docs/current-state.md`: add one line to the Tutorials entry only if its facts changed (page list; `[data-tutorial-slot]` rule; `tutorial:end` event; `?` optional `open`).
- [ ] Commit with explicit paths only: the `tutorials/*` files, `tutorial.js`, `transactions.js`, three page html files, `styles.css`, the new and edited tests, `docs/current-state.md`. No trailer, no push.

**Test:** every file above green; `git status` shows no staged path outside that list.
