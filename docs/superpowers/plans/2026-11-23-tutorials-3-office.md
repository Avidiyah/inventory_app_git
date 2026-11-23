# Tutorials 3 — Office Work Implementation Plan

> **Rule added by the user 2026-11-23 (overrides anything below):** every box shows ONE simple sentence. A step that needs more is written as a list of sentences (`text: ["...", "..."]`, at most 3, each at most 120 characters) and the player gives each sentence its own tap on the same lit section. Wording tables that hold two sentences in one step are split at the sentence boundary, never merged into a longer sentence. Use plain words a new hire would use; one idea per sentence. See 0a spec 5.2 and 5.4.

> **For the orchestrator (Opus 5.5):** run T0, then T1–T7 as seven parallel Sonnet 5.5 agents (medium effort, never forks; the user authorizes agents for this batch), then T8. This repo bars subagents unless authorized per task.

**Goal:** 16 tutorial scripts on seven office pages, as data only, with sample files.

**Spec:** `docs/superpowers/specs/2026-11-23-tutorials-3-office-design.md` ("spec"). Foundation: 0a (`...-0a-player-design.md`, format 5.2, sample data 5.3, guard test 6) and 0b (`minRole`, treated as built). Batches 1–2, 0a, 0b are assumed built; `backend/static/tutorials/` does not exist in this checkout yet.

## Spec corrections

| # | Spec says | Code says | Handling |
|---|---|---|---|
| 1 | Section 5: "the id census gains both" ids | No census covers static page ids; `tests/frontend/helpers/items.js:34` only maps `items-scan-chooser` into a DOM helper; the `*Census` tests cover hub/cards/body ids | T0 adds no census entry; the 0a guard test is what proves the new ids resolve |
| 2 | A3 hint sits in the Scan section for everyone | `saved-items.html:80-97` is open to all roles; Add Barcode is OA+ only | T0 places the hint, and the script's `minRole` (C1) already limits who is taught it; T0 confirms a Technician seeing the hint is harmless (a plain hint line) |
| 3 | Spec 3.3 targets `#ureq-card--41` (negative id) | Card id is `"ureq-card-" + id` (`userRequestCards.js:378`); `low-stock-card-` (`lowStock.js:80`) and `review-card-` (`adminReview.js:79`) likewise | Prefix plus the UUID, per correction 5 |
| 5 | Spec 4 and every selector use negative ids (-11, -41, -61 ...) | Ids are UUID strings; 0a plan C1 reserves `ffffffff-ffff-4fff-8fff-0000000000NN` (the guard asserts the prefix) | Everywhere below, spec id `-NN` means `ffffffff-ffff-4fff-8fff-0000000000NN`: `#ureq-card--41` becomes `#ureq-card-ffffffff-ffff-4fff-8fff-000000000041`, `[data-id="-11"]` becomes `[data-id="ffffffff-ffff-4fff-8fff-000000000011"]`, and so on. Agents rewrite the spec's selectors this way and nothing else |
| 4 | Integrations "Admin+" comment | `PAGE_ACCESS.integrations` is `owner, admin, techfm_oa` (`views/nav.js:137`) | T0 fixes the comment (`pages/integrations.html:2`) |

Verified present: every id and class the spec names for create-item, saved-items editors, user-requests cards, low-stock, admin-review, integrations and tools (grep of `pages/*.html`, `userRequestCards.js`, `userRequests.js`, `lowStock*.js`, `tools.js`). Row menus come from `menus.js:37` (`[data-menu][data-id]`, `.menu-trigger`, `[data-value]`). Missing today: `user-requests-export-link`, `items-scan-add-barcode-hint` (spec A2, A3).

## Global constraints

- Content only: no player code, no edits to existing app code outside T0 and T8.
- CSP drops `style=` attributes; no nested buttons (no markup in scripts anyway).
- Vitest runs from PowerShell at `C:\Users\mcclu\Desktop\inventory_app_git` (uppercase drive; Git Bash fails "failed to find the runner"). Targeted runs only.
- Stage explicit paths only (shared checkout). No `Co-Authored-By` trailer. Nothing is pushed (pushing main deploys).
- File ownership: each agent owns exactly its two files; T0 and T8 are the orchestrator's alone; `index.js` is edited only in T8.

## Common brief (prepend verbatim to every T1–T7 prompt)

> You write tutorial content for a vanilla-JS inventory app at `C:\Users\mcclu\Desktop\inventory_app_git`. You own only the two files named below. Never edit any other file. Run no git commands, no servers, no tests; spawn no agents.
>
> Read first, fully: `docs/superpowers/specs/2026-11-23-tutorials-3-office-design.md` (your page's part of section 3, section 4 row, section 6 row) and `docs/superpowers/specs/2026-11-23-tutorials-0a-player-design.md` (sections 5.2 script format, 5.3 sample data, 6 guard test). `minRole` is an optional script field from `docs/superpowers/specs/2026-11-23-tutorials-0b-progress-design.md`: set it exactly where your brief says. Worked example to copy structure from: `backend/static/tutorials/work-orders.js` and `work-orders.sample.js`.
>
> Foundation built by the 0a plan (`docs/superpowers/plans/2026-11-23-tutorials-0a-player.md`, read its Spec corrections table): `<page>.js` exports `SCRIPTS`; `<page>.sample.js` exports `sample(user)` returning a map of `"GET <path>"` to a JSON body (a request matches on path alone, query string ignored; unlisted GETs reach the server). Record ids are UUID strings, so wherever the spec writes a negative id `-NN` use `ffffffff-ffff-4fff-8fff-0000000000NN` (twelve digits after the last hyphen; -41 is `...000000000041`), in the sample and in every selector or `open` entry that carries an id. A step target inside a closed `<details>` counts as hidden unless it is that details' own `<summary>`.
>
> Rules: (1) Each step's wording is copied verbatim from the spec's wording table for that script; never reword, never add steps. (2) Keys, `open`, `here`, "For" audience and step targets are exactly as the spec lists them. A target that does not exist in the page html or the view module that draws it is NOT silently changed: keep the spec selector and report it. (3) Sample file: every record id uses the reserved prefix above (the viewer's own id is exempt); made-up names in the style of the 0a pilot sample; answer only the GET paths your brief lists (a sampled GET matches on path alone, the query string is ignored); response shapes must match what the real backend returns, taken from the API code and `tests/frontend/helpers/factories.js` (reuse a factory's field list; do not import it). Include every field the view code reads for the elements your steps point at. Dates relative to now, never fixed. (4) Selectors that depend on a card id use the card's real id format: the view prefix plus the full reserved UUID, e.g. `#ureq-card-ffffffff-ffff-4fff-8fff-000000000041`. (5) Never open a camera, file picker, cloud window or pop-up in `open`; those are described only (spec 6).
>
> Report back in under 120 words: the two file paths, any selector you could not find (with file and line you searched), any GET path the page's loader requested that your sample did not answer, and questions. Never paste file contents.

## Task 0: Orchestrator prep (anchors and comment)

**Goal:** Add the two missing anchors and fix one stale comment, before agents start.

**Files:** Modify `backend/static/pages/user-requests.html:11`, `backend/static/pages/saved-items.html` (after line 94, inside `#items-scan-section`), `backend/static/pages/integrations.html:2`.

**Steps:**
- [ ] A2: change line 11 to `<a id="user-requests-export-link" class="secondary-btn" href="/items/export">Export for print</a>`. (Not pointed at by any script in spec 3.3; add it anyway per spec A2, so later work can use it.)
- [ ] A3: add `<p id="items-scan-add-barcode-hint" class="hint">If a scan finds nothing, an Add Barcode panel opens so the scanned code can be attached to an existing item.</p>` between `.scan-controls` (closes line 94) and `#items-scan-chooser` (line 95). The script's own wording (spec 3.2 last row) is what the tutorial shows; the paragraph only needs to exist and be visible. Check `views/items.js` does not toggle `hidden` on sibling `.hint` elements of the scan section.
- [ ] Integrations comment: replace `Admin+ only (views/nav.js PAGE_ACCESS)` with `TechFM OA+ (views/nav.js PAGE_ACCESS)`.
- [ ] Verify in `tests/frontend` that no snapshot or markup test counts `<p class="hint">` in `saved-items.html`: `Grep` `hint` under `tests/frontend/views/items*.test.js` (if any hit asserts a count, update it).

**Test:** From PowerShell, `npx vitest run tests/frontend/views/items.test.js` (use the actual saved-items view test file names found) passes unchanged.

## Task 1: create-item (agent)

**Goal:** Two scripts for the Create Item page.

**Files:** Create `backend/static/tutorials/create-item.js`, `backend/static/tutorials/create-item.sample.js`.

**Steps (brief = Common brief plus):**
> Scripts: `create-item.add.item` (spec 3.1, 8 steps) and `create-item.add.tool` (spec 3.1, 5 steps). No `minRole`; the page is OA+ so every viewer sees every step. Read `backend/static/pages/create-item.html` and `backend/static/views/items.js` (and `itemEditor.js` only if the page loader calls it), plus tips `item.*` and `tool.*` in `backend/static/tips.js`. Sample: spec 4 says no GETs; read the create-item loader code and confirm it makes no GET on load. If it makes one, answer it with the matching empty shape and report the path; if none, `sample()` returns `{}`. Confirm `#item-scan-toggle-btn` and `#tool-scan-toggle-btn` are visible (not `hidden`) on first paint; if either starts hidden, report it.

**Test:** none of its own; covered by T8's guard run.

## Task 2: saved-items (agent, extends batch 1)

**Goal:** Add four office scripts and extend the sample for the Find tab menus.

**Files:** Modify (extend, never rewrite; keep every batch-1 script, key and sample route untouched) `backend/static/tutorials/saved-items.js`, `backend/static/tutorials/saved-items.sample.js`.

**Steps (brief = Common brief plus):**
> Open both existing files first and append. Scripts: `saved-items.find.edit-item` (`minRole: "techfm_oa"`), `saved-items.find.notes` (`minRole: "supervisor"`; that is the stored id shown to users as Team Lead, see `PAGE_ACCESS` in `views/nav.js`), `saved-items.find.correct-count` (`minRole: "techfm_oa"`), `saved-items.scan.add-barcode` (`minRole: "techfm_oa"`); wording spec 3.2. The last step of the add-barcode script targets `#items-scan-add-barcode-hint` (added by the orchestrator in T0; it exists). Read `pages/saved-items.html`, `views/items.js`, `itemEditor.js`, `notes.js`, `addBarcode.js`, `correction.js`, `menus.js`, and tips `item.*`. Sample: batch 1's file already answers `GET /items/`; extend its record set to the three items of spec 4 (ids ending 11 to 13: one with notes `{"Size":"3 in","Pack":100}`, one with an extra barcode, one unpriced; fields `price`, `product_link`, `barcodes`, `low_stock_threshold`, `notes`), keeping whatever batch 1 already put there if it is compatible, and make `sample(user)` return rows as the viewer's role may see them (price and notes fields as the real `/items/` route gives them: check `backend/app/routers/items.py` response model for what each role gets). Row menu items must exist for this role (`Edit`, `Notes`, `Correct Count` values `edit`, `notes`, `correct`: confirm the exact `data-value`s in `views/items.js`). Report: does the Scan-tab `open` (`.sub-nav-btn[data-feature="scan"]`) start the camera? If clicking it starts the stream, say so.

**Test:** covered by T8.

## Task 3: user-requests (agent)

**Goal:** Four scripts, one per request tab.

**Files:** Create `backend/static/tutorials/user-requests.js`, `backend/static/tutorials/user-requests.sample.js`.

**Steps (brief = Common brief plus):**
> Scripts: `user-requests.requests.material`, `.catalogue`, `.recount`, `.price` (spec 3.3). No `minRole`. `open` per spec 3.3: click `#user-requests-tabs [data-request-type="<type>"]` with types `material_request`, `catalogue_request`, `inventory_recount`, `missing_item_price`; the first card is found by its id (`#ureq-card-<id>` for ids ending 41 to 44). `here` is the tab's `aria-selected="true"`. Read `pages/user-requests.html`, `views/userRequests.js`, `views/userRequestCards.js` (card builder: `userRequestCards.js:378` for the id, parts at lines ~100-216 and 424-450), and tips `requests.*`. Sample paths: `GET /user-requests/counts` (see `apiListUserRequestCounts`, `api.js:359`; read the route in `backend/app/routers/user_requests.py` for the shape; each type 1) and `GET /user-requests/` (the list route; `apiListUserRequests` sends `?status=&type=`, which the sample ignores, so one body serves every tab: return all four cards under the one key, check whether `userRequests.js` filters the list by `request_type` and status client-side, and report what each tab then shows; do not invent a query-aware sample). One open card per type, ids ending 41 (material), 42 (catalogue, with a work order number), 43 (recount), 44 (missing price). Per-type `details` fields as in `tests/frontend/views/userRequestsLiveCensus.test.js:16-21` and `factories.js` `userRequest`; include `item_price`, `item_product_link`, the work-order fields and the on-hand quantity fields the builder reads for the stock line (spec 3.3 material step 4, which needs a stock button: check which condition draws `.user-request-stock` and satisfy it). Report the exact fields the builder reads for each type.

**Test:** covered by T8.

## Task 4: low-stock (agent)

**Goal:** One script, `low-stock.queue.reorder`.

**Files:** Create `backend/static/tutorials/low-stock.js`, `backend/static/tutorials/low-stock.sample.js`.

**Steps (brief = Common brief plus):**
> Script: `low-stock.queue.reorder` (spec 3.4, 6 steps). No `minRole`; no `here`. `open` is clicking `#low-stock-card-<id ending 51> summary` to expand the first card; the later steps target parts inside that open `<details>`. Read `pages/low-stock.html`, `views/lowStock.js` (card id at line 80, summary class at 87, threshold at 97), `views/lowStockCard.js` (`.low-stock-edit` at 42, `.low-stock-correction` at 67) and, for the response shape, `backend/app/routers/items.py` low-stock route (`apiGetLowStock` / `liveGet("/items/low-stock")`, `api.js:169`). Sample path: `GET /items/low-stock`: three rows, ids ending 51 to 53, each with `last_dispensed_at` computed from the current time so one lands in each tab (last 24 h, 2-7 days, never); read `lowStock.js` for the tab buckets and the 7-day usage fields the summary shows. Report whether the open `<details>` stays open if the page refreshes live while the tutorial runs (spec 7).

**Test:** covered by T8.

## Task 5: admin-review (agent)

**Goal:** One script, `admin-review.queue.review`.

**Files:** Create `backend/static/tutorials/admin-review.js`, `backend/static/tutorials/admin-review.sample.js`.

**Steps (brief = Common brief plus):**
> Script: `admin-review.queue.review` (spec 3.5, 6 steps). No `minRole`; no `here`. `open` is clicking `#review-card-<id ending 61>`, which builds the receipt. Read `pages/admin-review.html`, `views/adminReview.js` (list call at line 265 is `apiListWorkOrders({ status: "review" })`; detail call at 249 is `apiGetWorkOrder`; tile id at 79), `views/adminReviewReceipt.js`, `views/workOrderPresenters.js`, tips `review.*`. Sample paths: `GET /work-orders/` (list; the real call carries `?status=review`), `GET /work-orders/<id ending 61>`, `GET /work-orders/<id ending 62>`. List card shape from `factories.js` (work-order card) and the work-order list route; detail shape as the 0a pilot's In-Progress order in `backend/static/tutorials/work-orders.sample.js` with `status: "review"`; the ...61 order fully priced with at least one material line and one labor line, the ...62 order with `has_unpriced_items: true` (the tile then says Needs price). The receipt must render: report the minimum detail fields it needs. Confirm `#admin-review-netfacilities-btn` is visible once a receipt is built.

**Test:** covered by T8.

## Task 6: integrations (agent)

**Goal:** Two scripts, Import and Export.

**Files:** Create `backend/static/tutorials/integrations.js`, `backend/static/tutorials/integrations.sample.js`.

**Steps (brief = Common brief plus):**
> Scripts: `integrations.netfacilities.import` (4 steps) and `integrations.netfacilities.export` (2 steps), spec 3.6. No `minRole`, no `open`, no `here`. Do not point at or mention the SMR buttons: SMR is finished and gets no tutorials. Read `pages/integrations.html` (ids at lines 27-48), `views/workOrderIntegrations.js` (session probe at line 189, `apiGetNetFacilitiesCloudSession`), the matching route in `backend/app/routers/integrations.py`, tips `integrations.netfacilities`. Sample path: `GET /integrations/netfacilities/cloud/session` answering `{available:true, has_saved_session:true, status:{state:"idle"}}`, adjusted to the route's real field names so "Log in" and "Import Tasks and Priority" (`#wo-netfacilities-enrich-btn`) both show. List every other GET the page fires on load in your report; answer any that the page needs to draw `#wo-export-scope` and the export button. Close and Import-downloaded-CSV buttons appear only mid-session: they stay in a sentence, never a target.

**Test:** covered by T8.

## Task 7: tools (agent, extends batch 1)

**Goal:** Add the inventory lookup and checkout scripts.

**Files:** Modify (extend, never rewrite) `backend/static/tutorials/tools.js`, `backend/static/tutorials/tools.sample.js`.

**Steps (brief = Common brief plus):**
> Open both existing files first and append; keep batch 1's scripts, keys and routes. Scripts: `tools.inventory.lookup` (no `minRole`; the Actions-menu step is skipped for roles without that column, so no `textFor`) and `tools.custody.checkout` (`minRole: "techfm_oa"`), spec 3.7. The checkout `open` chain is exactly spec 3.7: `.sub-nav-btn[data-feature="custody"]`, `#tool-user-search`, `.tool-user-option[data-user-id="<id ending 21>"]`, `#tool-checkout-search`, `[data-checkout-tool-id="<id ending 71>"]` (confirmed to exist in `views/tools.js:249,278,365`); check whether the 0a `open` format needs a typed value for the two search inputs (0a 5.2) and, if the user list or tool results only render after typing, say how the sample makes them render. Read `pages/tools.html`, `views/tools.js`, `toolCheckout.js`, tips `tools.*`. Sample paths: `GET /tools/` (`api.js:188`; three tools, ids ending 71 to 73, one with a `custody` entry, one bulk count) and `GET /users/` (`apiListUsers`, `api.js:249`; three active users ending 21 to 23, shapes per `backend/app/routers/users.py`). Do not remove or alter any batch-1 route; if `/tools/` is already answered, merge records. Report whether the checkout form hides the user picker card once a person is chosen (spec 7).

**Test:** covered by T8.

## Task 8: Orchestrator finish

**Goal:** Register, prove, review, commit.

**Files:** Modify `backend/static/tutorials/index.js` (add `"<page>": { scripts: SCRIPTS, sample }` entries (two static imports each) as 0a T5 did; saved-items and tools are already registered, so only create-item, user-requests, low-stock, admin-review, integrations are new). Possibly `docs/current-state.md`.

**Steps:**
- [ ] Read all seven reports. Resolve each missing selector by fixing the owning page file's wording only if the spec's selector is right and the markup is wrong (an anchor add, as T0); otherwise tell the owning agent via `SendMessage` and let it edit its own file. Do not edit an agent's file while it runs.
- [ ] Add the new pages to `index.js`.
- [ ] Run the guard test from PowerShell: `npx vitest run tests/frontend/views/tutorialGuard.test.js`. Checks: targets exist for some role at or above `minRole` (0b), house limits (8 steps, 2 sentences, 240 characters), sample ids with the reserved prefix, `textFor` keys. Fix failures by editing the owning file.
- [ ] Run the targeted suites that touch edited pages: `npx vitest run tests/frontend/views/items.test.js tests/frontend/unit/staticImports.test.js` (adjust to real names); fix regressions in T0 edits only.
- [ ] Grep every script's wording against the spec tables for a verbatim match (a quick diff of step strings per key); any deviation goes back to its agent.
- [ ] Produce the single wording review table for the user: columns key / step target / wording, for all 16 scripts (copy from the spec; mark the C1 `minRole` scripts).
- [ ] Commit explicit paths only: the 7 pages' tutorial files, `index.js`, T0's three html files; message `feat(tutorials): office pages, batch 3`; no Co-Authored-By; no push.
- [ ] `docs/current-state.md`: update only if a fact changed (tutorial page count; the integrations access comment is not a fact there).

**Test:** the guard test and the targeted suites above pass; `git status` shows no unstaged edits to owned files.
