# Takeoff + Work-Order Top Bar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Per-work-order predicted material ("Takeoff") with one-tap dispense, an admin Takeoff page that tracks purchases, and a phone-friendly work-order card (pinned task + location, top icon bar, More menu).

**Architecture:** Two new tables (`work_order_takeoff_lines`, `takeoff_purchases`) behind a `services/takeoff.py` service; the overview is computed on read. Dispense reuses `add_work_order_item` with an optional `takeoff_line_id`; any `stock` transaction counts purchases down. Frontend: new `workOrderTopBar.js` and `workOrderTakeoff.js` card modules, new `views/takeoff.js` page.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic + Postgres; vanilla ES modules; pytest; Vitest + jsdom + MSW.

**Spec:** `docs/superpowers/specs/2026-11-25-takeoff-design.md` (visual reference: `docs/superpowers/specs/2026-11-25-takeoff-preview.html`)

## Global Constraints

- No SMR branches in new code; every service type is standard. Existing SMR UI is left alone except where the top bar moves it (Invoice → More).
- Predictions never touch stock, `work_order_items`, billing, invoices or materials totals.
- Service-type grouping uses `domain.work_orders.normalize_service_type` (blank → key `__unspecified__`, label "Unspecified").
- "Not counted" orders: `status == "completed"` or `archived_at IS NOT NULL`.
- Roles: takeoff lines write = `require_min_role(ROLE_SUPERVISOR)` (Team Lead+); Takeoff page + purchases = `require_min_role(ROLE_TECHFM_OA)`; dispense = today's add-material rule (`require_crew_for_technician`).
- CSP: no `style=` attributes; inline SVG icons only (no icon fonts).
- No horizontal scroll at any width; phone layouts reflow.
- `workOrder*.js` files may pass 500 lines but never 1,000; new code goes in new modules.
- Copy (exact): "Takeoff", "+ Takeoff item", "Dispense", "{n} left of {m}", "Order {n} more", "shared with other service types", "Ordered", "Covered by stock", "How many did you order?", "On the way", "Planned, not yet used · no stock moved".
- Commits: `git commit -m ... -- <paths>` only (a second orchestrator shares this checkout; see the coordination file); no `Co-Authored-By` trailer; never push without the owner's go-ahead (push to main deploys).
- Backend tests: `cd backend && venv/Scripts/python.exe -m pytest <file> -q` (Bash). Vitest: from **PowerShell** at `C:\Users\mcclu\Desktop\inventory_app_git`: `npx vitest run <file>`.

## Review Focus

1. **Stale takeoff line on dispense** (another user removed/used it): 409 "This takeoff line changed. Refresh and try again.", and nothing is dispensed. → T3 test.
2. **Service type edited after lines exist:** need moves to the new group on next read; the purchase stays on its old key. → T2 test.
3. **Item with `price` NULL:** row total `null`, group total skips it; page shows "—". → T2 + T6 tests.
4. **Decimal quantities** (2.5): kept exact through add, consume, count-down and display (no float drift, no trailing zeros). → T2 test.
5. **Delivery larger than what's on the way:** purchases go to zero/deleted, surplus ignored, stock still rises by the full amount. → T2 test.

---

## Execution lanes (orchestration)

**A second orchestrator runs at the same time** (`[flagged]`, plan `2026-11-25-flagged-time-step-through.md`). Follow `docs/superpowers/plans/2026-11-25-orchestrator-coordination.md`: this orchestrator's tag is `[takeoff]`; HELLO at start; check `ListAgents` + the claims ledger at every task boundary and before every commit; shared files only under a claim; commit by pathspec; no push.

| Lane | Tasks | Starts | Owns (exclusive) |
|---|---|---|---|
| A (backend) | T1 → T2 → T3 | now | `backend/app/models.py`, `backend/app/main.py`, `backend/app/services/{takeoff,work_orders,transactions}.py`, `backend/app/schemas/{takeoff,work_orders}.py`, `backend/app/routers/{takeoff,work_orders}.py`, `backend/alembic/versions/a8c0e2f4b6d8_add_takeoff.py`, `backend/tests/test_takeoff_*.py` |
| B (card UI) | T4 | now, parallel to A | `workOrderCardHtml.js`, `workOrderTopBar.js` (new), `workOrderActions.js`, `workOrderLiveBody.js`, `workOrderPhotos.js`, `tests/frontend/views/workOrders/**` |
| C | T5 | after T3 + T4 | `workOrderTakeoff.js` (new), `tests/frontend/helpers/{workOrders,factories}.js`, `backend/static/tutorials/*.sample.js` |
| D | T6 | after T5 | `views/takeoff.js` (new), `nav.js`, `shell-head.html`, `tests/frontend/helpers/handlers.js`, `tests/frontend/views/{takeoff,nav}.test.js` |
| E | T7 | last | `docs/open-work.md`, full verification |

**Shared with `[flagged]` (claim first, orchestrator edits, never a subagent):** `backend/static/api.js`, `tests/frontend/helpers/endpointTable.js`, `backend/static/styles.css`, `backend/scripts/memprobe_routes.py`, `backend/tests/{test_route_role_gates,test_realtime_emit,test_memprobe}.py`, `docs/current-state.md`. **Forbidden (theirs):** `backend/app/services/{labor_summary,attendance_compare,attendance}.py`, `backend/app/schemas/attendance.py`, `backend/app/routers/hub.py`, attendance/hub tests, `views/{flaggedTimeFlow,hubTimesheetsTab,hubHome,hubAttendanceDay,dayTimeline}.js`, `tutorials/user-hub.js`, their tests.

One Sonnet implementer per task, then one Sonnet reviewer per task (spec + this plan in hand) before the next task in that lane. Each brief carries the three file lists above. Subagents never commit; they report shared-file changes they need and the orchestrator applies them under a claim. Invoke the `swarming` skill before running lanes A and B together. `styles.css`: T4, T5, T6 each append one block at EOF (`/* Work-order top bar */`, `/* Takeoff section */`, `/* Takeoff page */`), each under its own claim. Before T1's `alembic upgrade/downgrade`, send `[takeoff] HEADS-UP alembic`. Send `[takeoff] DONE T<n>` after each commit.

---

### Task 1: Tables and models

**Goal:** Two tables with constraints, plus ORM relationships.

**Files:**
- Create: `backend/alembic/versions/a8c0e2f4b6d8_add_takeoff.py` (`down_revision = "f7b9d1e3a5c7"`)
- Modify: `backend/app/models.py` (new classes after `WorkOrderItem`; relationship on `WorkOrder`)
- Test: `backend/tests/test_takeoff_models.py`

**Interfaces — Produces:**
- `WorkOrderTakeoffLine`: `id UUID pk`, `work_order_id FK work_orders.id ON DELETE CASCADE`, `item_id FK items.id ON DELETE RESTRICT`, `quantity Numeric NOT NULL CHECK > 0`, `created_by_id FK users.id NULL`, `created_at`, `updated_at`; `UNIQUE(work_order_id, item_id)` named `uq_takeoff_line_order_item`; relationship `item`.
- `TakeoffPurchase`: `id`, `item_id FK RESTRICT`, `service_type_key Text NOT NULL`, `service_type_label Text NOT NULL`, `quantity_on_the_way Numeric NOT NULL CHECK > 0`, `created_by_id`, `created_at` (insert only), `updated_at`; `UNIQUE(item_id, service_type_key)` named `uq_takeoff_purchase_item_type`; relationship `item`.
- `WorkOrder.takeoff_lines` relationship, `order_by=WorkOrderTakeoffLine.created_at`, `cascade="all, delete-orphan"`.

- [ ] **Step 1: Write failing tests:** `test_duplicate_order_item_line_rejected` (second insert, same order + item → `IntegrityError`), `test_nonpositive_quantity_rejected` (quantity 0 → `IntegrityError`), `test_deleting_work_order_removes_its_lines`, `test_duplicate_purchase_pair_rejected`.
- [ ] **Step 2:** Run; expect FAIL (import error).
- [ ] **Step 3:** Add the models and migration (upgrade creates both tables + constraints; downgrade drops both).
- [ ] **Step 4:** `cd backend && venv/Scripts/alembic upgrade head && venv/Scripts/alembic downgrade -1 && venv/Scripts/alembic upgrade head` → no error; run the tests → PASS.
- [ ] **Step 5:** Commit `feat(takeoff): tables for takeoff lines and purchases`.

---

### Task 2: Takeoff service

**Goal:** All Takeoff rules in one module, no HTTP.

**Files:**
- Create: `backend/app/services/takeoff.py`, `backend/app/schemas/takeoff.py`
- Test: `backend/tests/test_takeoff_service.py`

**Interfaces — Consumes:** T1 models; `services.work_orders._get_visible`, `_locked_live_item`; `domain.work_orders.normalize_service_type`, `STATUS_COMPLETED`.

**Interfaces — Produces** (none of these commit unless marked; the caller owns the transaction):
- `add_line(db, work_order_id, *, user, item_id, quantity: Decimal) -> WorkOrderTakeoffLine`: **commits**; adds to an existing line for that item.
- `update_line(db, work_order_id, line_id, *, user, quantity: Decimal) -> WorkOrderTakeoffLine`: **commits**; sets quantity.
- `delete_line(db, work_order_id, line_id, *, user) -> None`: **commits**.
- `consume_line(db, *, line_id, work_order_id, item_id, quantity: Decimal) -> None`: subtracts; deletes at ≤ 0; raises `WorkOrderStateError("This takeoff line changed. Refresh and try again.")` if the line is missing, on another order, or for another item.
- `count_down_purchases(db, *, item_id, quantity: Decimal) -> None`: oldest `created_at` first across service types; deletes rows reaching 0; surplus ignored.
- `set_purchase(db, *, user, item_id, service_type_key, service_type_label, quantity: Decimal) -> None`: **commits**; upsert; `0` deletes; `created_at` untouched on update.
- `overview(db) -> TakeoffOverview`.
- Schemas: `TakeoffLineCreate{item_id: UUID, quantity: Decimal > 0}`, `TakeoffLineUpdate{quantity: Decimal > 0}`, `TakeoffLineOut{id, item_id, item_name: str, quantity: Decimal}`, `TakeoffPurchaseSet{item_id, service_type_key: str, service_type_label: str, quantity: Decimal >= 0}`, `TakeoffWorkOrderRef{id, number, quantity}`, `TakeoffRow{item_id, item_name, product_link: str|None, price: Decimal|None, need, total: Decimal|None, stock, on_the_way, shortfall, shared: bool, work_orders: list[TakeoffWorkOrderRef]}`, `TakeoffGroup{service_type_key, service_type_label, total: Decimal, rows: list[TakeoffRow]}`, `TakeoffOverview{groups: list[TakeoffGroup]}`.

**Overview rules:** need per (group, item) = sum of lines on counted orders; `on_the_way` = that pair's purchase; `shortfall` (per item, copied to each of its rows) = `max(0, Σneed over all groups − Item.quantity − Σpurchases for item)`; `shared` = item appears in more than one group; `total = need × price` (None if price None); group `total` = Σ non-null row totals; groups sorted by label (case-insensitive), rows by item name.

- [ ] **Step 1: Write failing tests** (values from the spec's example):
  - `test_add_line_aggregates_same_item`: add 4 then 3 → one line, 7.
  - `test_consume_line_counts_down_and_deletes_at_zero`: line 4; consume 3 → 1; consume 2 → line gone.
  - `test_consume_line_wrong_order_raises`.
  - `test_overview_need_excludes_completed_and_archived`.
  - `test_overview_shortfall_pools_across_service_types`: WMR toilet 110 + Plumbing toilet 8, stock 12, WMR purchase 100 → both rows `shortfall == 6`, `shared is True`.
  - `test_overview_covered_by_stock`: need 40, stock 60, no purchase → shortfall 0, on_the_way 0.
  - `test_service_type_change_moves_need` (Review Focus 2).
  - `test_null_price_row_total_none_and_group_skips_it` (Review Focus 3).
  - `test_decimal_quantities_exact`: add 2.5, consume 1.25 → 1.25; purchase 2.5, count down 1.25 → 1.25 (Review Focus 4).
  - `test_count_down_oldest_first_and_surplus_ignored`: Plumbing 10 (older), WMR 100; count down 50 → Plumbing gone, WMR 60; count down 500 → none left (Review Focus 5).
  - `test_set_purchase_adds_updates_and_clears`: set 100 → 100; set 0 → row deleted; `created_at` unchanged by update.
  - `test_blank_service_type_groups_as_unspecified`.
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement the service and schemas (one query: lines ⨝ work orders ⨝ items, grouped in Python).
- [ ] **Step 4:** Run; expect PASS.
- [ ] **Step 5:** Commit `feat(takeoff): service rules for lines, purchases and the overview`.

---

### Task 3: API, dispense hook, arrival hook, detail field

**Goal:** Expose T2 over HTTP and connect it to dispense and stock-in.

**Files:**
- Create: `backend/app/routers/takeoff.py` (no prefix; full paths)
- Modify: `backend/app/main.py` (`include_router(takeoff.router)` before `work_orders.router`); `backend/app/schemas/work_orders.py` (`WorkOrderItemCreate.takeoff_line_id: Optional[UUID] = None`; `WorkOrderDetail.takeoff: list[TakeoffLineOut] = []`); `backend/app/routers/work_orders.py` (`add_work_order_item` passes it; `_detail` fills `takeoff` from `getattr(work_order, "takeoff_lines", None) or ()`); `backend/app/services/work_orders.py` (`add_work_order_item(..., takeoff_line_id=None)` calls `takeoff.consume_line` before `db.commit()`); `backend/app/services/transactions.py` (`apply_transaction`: when `transaction_type == "stock"`, call `takeoff.count_down_purchases` under the existing item lock); `backend/scripts/memprobe_routes.py`; `backend/tests/test_route_role_gates.py`; `backend/tests/test_realtime_emit.py`
- Test: `backend/tests/test_takeoff_router.py`

**Interfaces — Produces (HTTP):**
- `POST /work-orders/{id}/takeoff` body `TakeoffLineCreate` → 201 `TakeoffLineOut` (Team Lead+)
- `PATCH /work-orders/{id}/takeoff/{line_id}` body `TakeoffLineUpdate` → 200 `TakeoffLineOut` (Team Lead+)
- `DELETE /work-orders/{id}/takeoff/{line_id}` → 204 (Team Lead+)
- `GET /takeoff/` → `TakeoffOverview` (OA+)
- `PUT /takeoff/purchases` body `TakeoffPurchaseSet` → 204 (OA+)
- Line routes emit `_emit_status_changed(work_order_id)` (import it from `routers.work_orders`) so open cards refresh.

- [ ] **Step 1: Write failing tests:**
  - `test_technician_cannot_add_takeoff_line` (403); `test_team_lead_adds_line` (201, quantity echoed).
  - `test_detail_includes_takeoff_lines`.
  - `test_dispense_with_takeoff_line_reduces_it`: line 4, POST items qty 3 + `takeoff_line_id` → line 1, material line 3, stock −3.
  - `test_dispense_with_stale_takeoff_line_409_and_no_stock_change` (Review Focus 1).
  - `test_stock_transaction_counts_down_purchase`: purchase 100; stock-in 50 via the existing stock route → on_the_way 50.
  - `test_overview_gate`: Team Lead 403, OA 200.
  - `test_put_purchase_zero_clears`.
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement the router + hooks; add the five routes to the memprobe CATALOGUE, the role-gate lists (with `responses={403: ...}` on gated routes) and the realtime emitter sets.
- [ ] **Step 4:** Run the new file plus `test_memprobe.py test_route_role_gates.py test_realtime_emit.py test_work_order_name_responses.py test_transactions*.py` → PASS.
- [ ] **Step 5:** Commit `feat(takeoff): API, dispense-from-takeoff and arrival count-down`.

---

### Task 4: Work-order top bar (lane B)

**Goal:** Pinned task + location and a top icon bar on every work order; More holds Details, extra sections and the old ⋯ contents.

**Files:**
- Create: `backend/static/views/workOrderTopBar.js`
- Modify: `backend/static/views/workOrderCardHtml.js` (`renderBody` uses the pin; `SECTION_BY_TAB` unchanged keys; `syncWorkOrderTabs` selector → `.wo-pin .wo-tab`; default open = Materials unless `hasUnreadPriorWork`); `workOrderActions.js:673-690` (tab click also closes `details.wo-more`; Edit details stays inside More); `workOrderLiveBody.js:92` selector; `workOrderPhotos.js:48` selector; `backend/static/styles.css` (append block)
- Test: create `tests/frontend/views/workOrders/topBar.test.js`; update `render.test.js`, `bodyLiveCensus.test.js`, `actionCoverage.test.js`, `visualClarity.test.js`, `smrLines.test.js`, `realtime.test.js` as they break.

**Interfaces — Produces:**
- `topBarHtml(detail, { showLabor: boolean, moreSections: Array<[key, label]>, toolsHtml: string, canEdit: boolean }) -> string`: `<nav class="wo-topbar">` with four `.wo-tab[data-wo-tab]` buttons (materials, labor if shown, notes, photos), each: inline SVG, word, `<small>` count; then `<details class="wo-more">` whose menu has `.wo-tab[data-wo-tab]` buttons for `details` + `moreSections`, an `<hr>`, `toolsHtml`, and `[data-wo-open-edit]` when `canEdit`.
- `pinHtml(detail, barHtml) -> string`: `<div class="wo-pin" id="wo-sec-pin">` with `.wo-pin-task` (description, or "No task on this work order" hint), `.wo-pin-place` (`placeParts` heading · detail), chips (`statusBadge`, `attentionPriorityBadge`, `overdueTag`) + "WO {number}", then the bar.
- `renderBody` passes `moreSections = [["invoice","Invoice"]]` only when the order has an invoice section; T5 adds `["takeoff", "Takeoff · N"]`.
- CSS: `.wo-pin` `position: sticky` with `top` = the app header's bottom (measure in the browser; use a custom property `--wo-pin-top`); `.wo-card.wo-solo > .wo-summary { display: none; }`; bar is a 4–5 column grid, min target 44 px; active tab: brand-red underline + red icon stroke; `summary` of More shows "More" plus the active More section's name when one is open.

- [ ] **Step 1: Write failing tests** in `topBar.test.js`: `pin shows task and location`; `bar lists materials, labor, notes, photos then More`; `labor hidden for an off-crew technician leaves four`; `card opens on Materials`; `unread prior-work notes open Notes instead`; `More lists Details and Invoice for an order with an invoice`; `picking Details from More closes all sections and marks More current`; `exactly one .wo-more per card`.
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement; update the six existing tests' frozen lists to the new structure (tab order `["materials","labor","notes","photos"]`; `wo-sec-pin` in `SECTION_ORDER`).
- [ ] **Step 4:** `npx vitest run tests/frontend/views/workOrders` → PASS.
- [ ] **Step 5:** Commit `feat(work-orders): pinned header and top icon bar`.

---

### Task 5: Takeoff section on the card

**Goal:** Team Lead+ builds the takeoff; anyone allowed to add material dispenses from it in one tap.

**Files:**
- Create: `backend/static/views/workOrderTakeoff.js`
- Modify: `workOrderCardHtml.js` (append section; `SECTION_BY_TAB.takeoff = ".wo-takeoff-section"`; More entry); `workOrderActions.js` (delegate takeoff actions; item chooser selectors at `:96` and `:150` accept `.wo-add-item, .wo-takeoff-add`); `workOrderLiveBody.js` (`LIVE_FORMS += ".wo-takeoff-add, .wo-takeoff-dispense"`, `LIVE_ROWS += ".wo-takeoff-line"`); `backend/static/api.js`; `tests/frontend/helpers/endpointTable.js`, `helpers/workOrders.js` (`installHandlers`), `factories.js` (`workOrderDetail.takeoff = []`); `backend/static/tutorials/*.sample.js` (add `takeoff: []` wherever `tutorialGuard.test.js` demands it); `styles.css` (append block)
- Test: create `tests/frontend/views/workOrders/takeoff.test.js`; update `actionCoverage.test.js`, `bodyLiveCensus.test.js`, `render.test.js`.

**Interfaces — Consumes:** T3 routes; T4 `topBarHtml` `moreSections`.
**Interfaces — Produces:**
- `api.js`: `apiAddTakeoffLine(workOrderId, { itemId, quantity })`, `apiUpdateTakeoffLine(workOrderId, lineId, quantity)`, `apiDeleteTakeoffLine(workOrderId, lineId)`; `apiAddWorkOrderItem(workOrderId, { itemId, quantity, materialRequestId = null, takeoffLineId = null })` sends `takeoff_line_id`.
- `workOrderTakeoff.js`: `takeoffSectionHtml(detail, { canEdit, canDispense }) -> string` (`<details class="wo-section-card wo-takeoff-section" id="wo-sec-takeoff">`; lines `.wo-takeoff-line#wo-tk-{id}`; heading hint "Planned, not yet used · no stock moved"); `takeoffMoreLabel(detail) -> "Takeoff · N" | "Takeoff"`; `handleTakeoffAction(action, btn, ctx) -> Promise<boolean>`.
- `data-action`s: `add-takeoff`, `edit-takeoff`, `remove-takeoff` (`confirmDialog` "Remove this takeoff line?"), `open-dispense-takeoff`, `dispense-takeoff`.
- Rules: `canEdit = isSupervisorPlus() && status !== "completed"`; `canDispense = !isCrewLocked(detail) && status !== "completed"`; More lists Takeoff when `canEdit` or lines exist. Dispense form pre-fills remaining, accepts any value > 0; success → `refreshCard(cardEl, ".wo-takeoff-section")`, message "Dispensed." (or the existing re-count message when stock goes negative); a 409 shows the server message.

- [ ] **Step 1: Write failing tests:** `team lead sees + Takeoff item, technician does not`; `line shows "1 left of 4"`; `dispense pre-fills the remaining quantity`; `dispense posts takeoff_line_id and refreshes on the Takeoff section`; `stale line 409 shows "This takeoff line changed. Refresh and try again."`; `completed order shows lines read-only`; `More shows "Takeoff · 3"`; `live patch keeps a half-typed dispense quantity`.
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement; add the new actions to `ACTIONS`/`EXPORTS`, `wo-sec-takeoff` to `SECTION_ORDER`, endpoint rows to `endpointTable.js`.
- [ ] **Step 4:** `npx vitest run tests/frontend/views/workOrders tests/frontend/unit/api.endpoints.test.js tests/frontend/views/tutorialGuard.test.js` → PASS.
- [ ] **Step 5:** Commit `feat(takeoff): takeoff section and one-tap dispense on the card`.

---

### Task 6: Takeoff page

**Goal:** OA+ page grouping need by service type, with purchase tracking.

**Files:**
- Create: `backend/static/views/takeoff.js`
- Modify: `backend/static/views/nav.js` (`PAGE_LOADERS.takeoff`, roles `["owner","admin","techfm_oa"]`); `backend/static/shell-head.html` (nav button after Admin Review, inline-SVG clipboard icon; grep-edit, the graph parses this file partially); `api.js` (`apiGetTakeoff()`, `apiSetTakeoffPurchase({ itemId, serviceTypeKey, serviceTypeLabel, quantity })`); `endpointTable.js`; `helpers/handlers.js` `pageHandlers()` default for `GET /takeoff/`; `styles.css` (append block)
- Test: create `tests/frontend/views/takeoff.test.js`; update `nav.test.js` (role/page lists) and `tutorialLeak.test.js` if it enumerates pages.

**Interfaces — Consumes:** T3 `GET /takeoff/`, `PUT /takeoff/purchases`.
**Interfaces — Produces:** `loadTakeoff() -> Promise<void>`.

**Rendering:** one markup per row that is a table row ≥ 600 px and a stacked card below (CSS grid areas, no second copy). Columns: Item (link to `product_link`, `target="_blank" rel="noopener"`, plain text when blank; "Show work orders" toggles `WO {number} ×{q}` links that open the card), Need, Price, Total ("—" when null), In stock, On the way ("—" when 0), Ordered. Ordered control: a button styled as a checkbox; shortfall > 0 → empty box + "Order {n} more" (+ "shared with other service types" when `shared`); shortfall 0 → ticked box + "Ordered" if `on_the_way > 0` else "Covered by stock". Tap empty → inline form "How many did you order?" pre-filled `n`, Save sends `quantity = on_the_way + entered`; tap ticked → inline form "On the way" pre-filled current value with Save (sends the entered value) and Clear (sends 0). After save, reload the overview. Group header: label + "{total} planned". Empty state: "No takeoff material on open work orders."

- [ ] **Step 1: Write failing tests:** `groups render in label order with row totals`; `shared item shows the same shortfall on both rows`; `blank product link renders plain text`; `null price shows —`; `tick sends on_the_way + entered and reloads`; `clear sends 0`; `technician and team lead cannot reach the page`; `empty state copy`.
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** `npx vitest run tests/frontend/views/takeoff.test.js tests/frontend/views/nav.test.js tests/frontend/unit/api.endpoints.test.js` → PASS.
- [ ] **Step 5:** Commit `feat(takeoff): admin Takeoff page with purchase tracking`.

---

### Task 7: Docs and full verification

**Goal:** Living docs match the code; the whole suite is green.

**Files:**
- Modify: `docs/current-state.md` (new tables, routes, role rows, card layout, arrival rule; stay within its word budget and delete anything stale you replace); `docs/open-work.md` (one backlog line: Takeoff page tutorial)

- [ ] **Step 1:** Update both docs (current truth only, tables/bullets).
- [ ] **Step 2:** Send `[takeoff] HEADS-UP full suite`; `cd backend && venv/Scripts/python.exe -m pytest -q` → all pass except the three known dev-DB cascade failures (environmental). Failures in `[flagged]` files go to that orchestrator as `FAILING`, not into fixes here.
- [ ] **Step 3:** `npx vitest run --coverage` (PowerShell) → all pass, coverage gate met.
- [ ] **Step 4:** Apply the migration to the local DB (`alembic upgrade head`) and hand the owner the in-app checklist (they validate manually; don't start the app server for them): card opens on Materials, pin stays put while scrolling, More → Takeoff → Dispense, Takeoff page tick/clear round-trip, phone and desktop widths.
- [ ] **Step 5:** Claim `docs/current-state.md`, commit `docs: takeoff and work-order top bar` by pathspec, release; send `[takeoff] READY TO PUSH`; report to the owner and **ask before pushing**.
