# Material Request Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A crew member files a Material Request for a catalogue item the shelf lacks from a new Request card on the work order; TechFM OA+ are pushed at filing, the crew is pushed when the item is stocked, a persistent Hub row and a one-tap Materials line carry the request until it is added; the old `item_request` becomes `catalogue_request` everywhere.

**Architecture:** One table, no DDL. A pure `domain/material_requests.py` owns the two stock edges (`restocked`, `went_out`). A thin `services/material_requests.py` (models + domain only, nothing from `app.services`) transitions requests inside the same transaction as each of the eight existing stock writes and buffers plain-value `StockedFact`s in a ContextVar, exactly the shape `services/low_stock.py` already uses. `routers/_low_stock.py` becomes `routers/_stock_events.py`; its one `flush_stock_events` call drains both buffers on every stock route's success path. Two push events and one realtime envelope are added through the registered three-step trigger procedure. The frontend adds a `workOrderRequests.js` module beside the 2,828-line `workOrders.js` rather than growing it.

**Tech Stack:** FastAPI 0.136.3, SQLAlchemy 2.x, Pydantic 2.13, PostgreSQL + Alembic, pytest, vanilla ES modules (no build step, no JS test harness — UI contracts are pinned by Python source-assertion tests as `test_work_orders_router.py` already does).

**Spec:** `docs/superpowers/specs/2026-09-08-material-request-design.md` — the plan argues from it; executors read both.

## Global Constraints

- **Type keys:** `material_request` (new), `catalogue_request` (renamed from `item_request`), `inventory_recount`, `missing_item_price` unchanged. The migration rewrites existing rows; **no compatibility alias** for the old route or old key.
- **Status vocabulary:** `open`, `stocked`, `resolved`. `stocked` is reachable only through the stock-write edge and `POST /user-requests/{id}/mark-stocked`; `PATCH status=stocked` is 422 (the existing `Literal["open","resolved"]` already does this — do not widen it).
- **Push text, verbatim:** filed = `Material requested` / `{name} is needed for {number}.`; stocked = `Material in stock` / `{name} for {number} is now in stock.` Neither suppresses the actor (`actor_id=None` through `select_recipients`).
- **Filed audience constant:** `MATERIAL_REQUEST_AUDIENCE_MIN_ROLE = roles.ROLE_TECHFM_OA` — a fourth constant, never a reuse of `LOW_STOCK_AUDIENCE_MIN_ROLE`.
- **Stocked edge:** `before <= 0 and after > 0`. Reverse edge: `before > 0 and after <= 0`. Nothing else moves a request between `open` and `stocked` automatically.
- **Resolution notes, verbatim:** `Added to {number}.` · `Cancelled by requester` · `Work order was closed before the item was stocked.`
- **`message` for a material request:** `Please stock this item`.
- **`details` keys:** `quantity` (str), `product_link`, `note`, `work_order_number`, `stocked_at`, `stocked_by` (`"auto"` or user id str), `stock_cycles` (int), `origin` (`"request_card"` | `"catalogue_fulfilment"`), `added_quantity`. `EDITABLE_DETAILS[material_request] = {quantity, product_link, note}`.
- **Realtime:** one new envelope `user_request.changed`, `id` = request id, audience **Technician**+. Emitted on every transition in spec §3.9.
- **Buffer ceiling:** 500 facts per request context, warning on overflow, later facts dropped — same as `MAX_BUFFERED_CROSSINGS`.
- **Import ring:** `services/material_requests.py` imports **only** `app.models` and `app.domain.*`. Never `from app.services import …` there.
- **Alembic head today is `c6e8a0b2d4f7`** (verified with `alembic heads`; `docs/current-state.md` still says `a2c4e6b8d0f1` — fix it in the docs task).
- **Windows venv:** every test command below is `cd backend && ./venv/Scripts/python.exe -m pytest …`. DB tests need the local Postgres on port 8801 (`.env` already holds `DATABASE_URL`; never truncate that file).
- **Pre-existing failures to ignore:** `test_cascade_deletes_with_user` (env: real cloud-session rows) and the solo-card test in `test_work_orders_router.py` (stash and re-run before investigating anything there).
- **Frontend rules:** no inline `style=` (CSP drops them; use classes); no `<button>` inside `<button>`; every server string through `escapeHtml` before `innerHTML`; new files under 500 lines.
- **Commit trailers:** end each commit message with the two trailer lines the session requires (`Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_01Rj5dKhZSJLx5wvJMfBTimY`). Lowercase imperative subject, no `feat:` prefix (matches `git log`).
- **Do not push.** Pushing `main` deploys to production; the user decides when.

---

## Facts confirmed against the code (and where the spec drifted)

| Spec says | Code says | Plan does |
| --- | --- | --- |
| eight `low_stock.record` sites: transactions ×3, mass_staging ×2, work_orders ×3 | confirmed: `transactions.py:133,229,367`, `mass_staging.py:500,558`, `work_orders.py:2899,2957,3035`; `test_every_item_quantity_mutation_has_a_recorder` pins `records == 8` | add `material_requests.record_stock_change(item, quantity_before=…)` on the line after each; extend that test to count the new call ×8 |
| `flush_low_stock` called by every stock route | confirmed: `transactions.py:96,126,182`, `mass_stages.py:389,413`, `work_orders.py:1173,1193,1245`, `items.py:256` (threshold route — a ninth caller, harmless) | rename module + function; update 4 routers and 2 test files that import `_low_stock` |
| `hasUnsavedInput` selector in `workOrders.js` | no such name; the held-card guard is `EDITOR_SECTIONS` (line 1333) read by `isHeld` | add `.wo-request-section` to `EDITOR_SECTIONS` |
| `wo_service._get_visible` | exists (`work_orders.py:518`), private | add a public `get_visible_work_order = _get_visible` reader (repo precedent: `assigned_technician_ids`) |
| `STATUS_STOCKED` defined in `services/user_requests.py` and re-exported | `STATUS_OPEN/RESOLVED` are literals in the service | define all three plus `REQUEST_MATERIAL` in the pure domain module; the service imports and re-exports them so `material_requests.py` needs nothing from `app.services` |
| `_dispatch` shape for the two notifiers | `_dispatch` takes a `WorkOrder`; our facts are plain values | call `policy.build_message` + `_schedule` directly (what `notify_item_low_stock` already does) |
| `GET /hub` payload gains `stocked_requests` | router builds `HubResponse` field by field; `HubPayload` is a frozen dataclass | add to dataclass, schema (default `[]`), and router |
| hub Exceptions tile counts `item_requests` | `AdminExceptionCounts.item_requests`, `HubAdminExceptions.item_requests`, `hubAdmin.js` row label "Item requests" | rename to `catalogue_requests` / "Catalogue requests" (rename scope is "everywhere") |
| `UserRequestResponse` + `item_quantity` + `updated` | neither field exists | add both (`item_quantity` populated for every response — the User Requests card and the stocked line both need "on hand") |
| 403 on cancel by non-filer | only 403-mapped error is `RoleManagementError` (user management) | add `MaterialRequestOwnershipError → 403` |
| `test_item_requests.py` → `test_catalogue_requests.py` | 10 tests, `git mv` | plus `test_user_requests.py::test_item_request_fields_are_editable` and `test_hub_service.py` reference `REQUEST_ITEM` |
| `itemRequest.js` → `catalogueRequest.js` | CSS classes `.item-request*` at `styles.css:1741-1785`; `SOURCES = {"work_orders","find_item"}` | rename classes too; add `request_card` source; `ItemRequestCreate.source` Literal gains `"request_card"` |
| CSP note in memory | `hubTechnician.js` sets `block.style.left` via CSSOM — allowed; string `style=` is not | keep every new style in classes |

---

## File Structure

**Created**

| Path | Responsibility |
| --- | --- |
| `backend/alembic/versions/d1e3f5a7b9c2_rename_item_request_to_catalogue_request.py` | the one data migration |
| `backend/app/domain/material_requests.py` | pure: the two edges, the type key, the three status strings |
| `backend/app/services/material_requests.py` | create/dedupe, the in-transaction transitions, the `StockedFact` buffer, mark-stocked, cancel, resolve-from-line, per-WO list, counts, hub rows. Models + domain only. |
| `backend/app/routers/_stock_events.py` | `git mv` of `_low_stock.py`; `flush_stock_events` drains both buffers; `emit_user_request_changed` |
| `backend/static/views/catalogueRequest.js` | `git mv` of `itemRequest.js`, three sources |
| `backend/static/views/workOrderRequests.js` | the Request card body, the stocked Materials lines, their delegated handlers, the card's `user_request.changed` refresh |
| `backend/tests/test_material_requests_domain.py` | both edges |
| `backend/tests/test_material_requests.py` | DB + TestClient: file, dedupe, visibility, auto-stock ×5 write kinds, back-to-open, archived auto-resolve, manual fire, cancel, add-from-line, chain, reopen |
| `backend/tests/test_stock_events_flush.py` | both buffers drain; one branch raising does not lose the other |
| `backend/tests/test_catalogue_requests.py` | `git mv` of `test_item_requests.py` + migration round-trip + UI source pins |

**Modified** (line refs are pre-change)

| Path | Change |
| --- | --- |
| `backend/app/services/user_requests.py` | constants from domain; `REQUEST_CATALOGUE`; `create_catalogue_request`, `find_sibling_catalogue_requests`, `fulfill_catalogue_request`, `_resolve_one_catalogue_request` (+ chain); `EDITABLE_DETAILS`; `list_user_requests(type=…)`; reopen clears stamps |
| `backend/app/routers/user_requests.py` | `build_response` (+`item_quantity`, `updated`); `/catalogue-request`; `/material-request`; `/counts`; `/{id}/mark-stocked`; `/{id}/cancel`; list `type`/`stocked`; emits |
| `backend/app/schemas/user_requests.py` | `CatalogueRequestCreate`, `CatalogueRequestFulfill`, `MaterialRequestCreate`, response fields |
| `backend/app/domain/notifications.py` | two events, one constant, two rules, two messages |
| `backend/app/services/notifications.py` | `notify_material_request_filed`, `notify_material_request_stocked` |
| `backend/app/domain/realtime.py` | `EVENT_USER_REQUEST_CHANGED`, audience |
| `backend/app/domain/errors.py`, `backend/app/routers/_errors.py` | `MaterialRequestOwnershipError → 403` |
| `backend/app/services/{transactions,mass_staging,work_orders}.py` | eight `record_stock_change` calls; `add_work_order_item(material_request_id=)`; `get_visible_work_order` |
| `backend/app/routers/{transactions,mass_stages,work_orders,items}.py` | import rename; `GET /work-orders/{id}/requests`; `material_request_id` pass-through + emit |
| `backend/app/schemas/work_orders.py:105-117` | `WorkOrderItemCreate.material_request_id` |
| `backend/app/services/hub.py`, `schemas/hub.py`, `routers/hub.py` | `stocked_requests`; `catalogue_requests` rename |
| `backend/static/api.js:305-360, 731-736` | wrappers |
| `backend/static/views/{userRequests,userRequestCards,workOrders,items,hubTechnician,hubAdmin,userHub}.js`, `main.js`, `tips.js`, `pages/user-requests.html`, `styles.css` | UI |
| `backend/tests/{test_route_role_gates,test_notifications_domain,test_notifications,test_realtime_domain,test_hub_service,test_user_requests,test_low_stock_triggers,test_items_low_stock}.py` | extended / renamed refs |
| `docs/{notification-events,adding-a-notification-trigger,endpoint-map,current-state,open-work}.md` | registry + docs |

## Running the tests

From the repo root:

```bash
cd backend && ./venv/Scripts/python.exe -m pytest tests/test_material_requests_domain.py -q      # one file
cd backend && ./venv/Scripts/python.exe -m pytest -q                                              # everything (~minutes; needs Postgres 8801)
```

Syntax-check a JS module without a harness: `node --check backend/static/views/workOrderRequests.js`.

## Why the tasks run in this order

1. **Rename first** (Task 1). Every later task writes `catalogue_request`; doing the rename last would mean touching the same lines twice and reviewing a diff that mixes rename noise with new behaviour.
2. **Pure domain before anything with a session** (Tasks 2, 3). The edges, the recipient rules, the message text and the realtime audience are all testable in milliseconds with no database; the service layer then imports names that already exist and are already pinned.
3. **Service before wiring** (Task 4 before 5-6). `record_stock_change` must be correct in isolation before it is called from eight places; a bug found at a call site is eight times harder to localise.
4. **Notifier functions before the flush** (Task 5 before 6). `flush_stock_events` calls `notify_material_request_stocked`; write the callee first so the flush test is a real integration, not a mock of something that does not exist yet.
5. **Flush + eight sites in one task** (Task 6). Half-wired stock sites would leave some restocks silent — a state that is worse than either endpoint. The flush rename lands in the same commit because the eight routers' imports change together.
6. **Routes after the service they call** (Tasks 7-9). Filing, manual fire, cancel, the add-from-line hook and the catalogue chain are all thin; each has a service function to call by then.
7. **Hub last on the backend** (Task 10). It is a read model over state every earlier task produces; writing it earlier means testing against rows nothing yet creates.
8. **Frontend after the API is stable** (Tasks 11-13), page by page: User Requests (the staff side, where the manual fire lives) → work-order card (the crew side) → Hub (a read of both).
9. **Docs last, except the registry** (Task 14). `notification-events.md` is updated inside Task 6's commit because the spec and that file's own header demand it; everything else describes the finished shape.

---

### Task 1: Rename `item_request` → `catalogue_request` everywhere

**Why now:** every later task writes the new name. One atomic commit keeps backend and frontend in step (no alias exists, so a split would leave one deploy broken between commits).

**Files:**
- Create: `backend/alembic/versions/d1e3f5a7b9c2_rename_item_request_to_catalogue_request.py`
- Modify: `backend/app/services/user_requests.py` (constant `REQUEST_ITEM`, functions `create_item_request`, `find_sibling_item_requests`, `_resolve_one_item_request`, `fulfill_item_request`, docstrings)
- Modify: `backend/app/schemas/user_requests.py` (`ItemRequestCreate`, `ItemRequestFulfill`)
- Modify: `backend/app/routers/user_requests.py` (imports, `/item-request` route + handler names, `fulfill_item_request`, `find_sibling_item_requests`)
- Modify: `backend/app/services/hub.py:612-666` (`item_requests` → `catalogue_requests`), `backend/app/schemas/hub.py` (`HubAdminExceptions.item_requests`)
- Modify: `backend/static/api.js:325-341,349-360`; `backend/static/views/itemRequest.js` → `catalogueRequest.js` (git mv); `backend/static/views/items.js:45,279`; `backend/static/views/workOrders.js:62,1877`; `backend/static/views/userRequests.js`; `backend/static/views/userRequestCards.js`; `backend/static/views/hubAdmin.js:90`; `backend/static/main.js:31`; `backend/static/pages/user-requests.html`; `backend/static/tips.js:180-191`; `backend/static/styles.css:1741-1785`
- Test: `backend/tests/test_item_requests.py` → `test_catalogue_requests.py` (git mv); `test_user_requests.py:482-506`; `test_hub_service.py:985-1013`; `test_route_role_gates.py:355-380`

**Interfaces:**
- Produces: `request_service.REQUEST_CATALOGUE == "catalogue_request"`, `create_catalogue_request(...)`, `find_sibling_catalogue_requests(db, request)`, `fulfill_catalogue_request(db, request_id, *, item_id, sibling_ids, resolved_by_id)`, `_resolve_one_catalogue_request(...)`; schemas `CatalogueRequestCreate`, `CatalogueRequestFulfill`; route `POST /user-requests/catalogue-request` (handler `create_catalogue_request`), handler `fulfill_catalogue_request`; JS `apiCreateCatalogueRequest`, `apiFulfillCatalogueRequest`, `catalogueRequestPromptHtml({searchedText, workOrderId, source})`; CSS classes `.catalogue-request*`.

- [x] **Step 1: Write the failing migration round-trip test**

`git mv backend/tests/test_item_requests.py backend/tests/test_catalogue_requests.py`, then in the new file replace every `create_item_request` → `create_catalogue_request`, `find_sibling_item_requests` → `find_sibling_catalogue_requests`, `fulfill_item_request` → `fulfill_catalogue_request`, and the assertion `request.request_type == "item_request"` → `"catalogue_request"`. Rewrite the module docstring's first line to `"""Catalogue Requests: material the app has no catalogue row for at all.`. Append:

```python
# --------------------------------------------------------------------------
# The rename
# --------------------------------------------------------------------------

def test_the_type_key_is_catalogue_request():
    assert request_service.REQUEST_CATALOGUE == "catalogue_request"
    assert not hasattr(request_service, "REQUEST_ITEM")


def test_the_migration_rewrites_old_rows_both_ways(db):
    """The revision's upgrade/downgrade are plain UPDATEs, so they can be run
    against the fixture's savepoint connection through the module's own
    `op` proxy. Round-trip proves downgrade really reverses upgrade."""
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text

    tech = _user(db)
    row = UserRequest(
        request_type="item_request",
        status="open",
        message="legacy",
        created_by_id=tech.id,
        details={},
    )
    db.add(row)
    db.flush()

    path = (
        Path(__file__).resolve().parents[1]
        / "alembic" / "versions"
        / "d1e3f5a7b9c2_rename_item_request_to_catalogue_request.py"
    )
    spec = importlib.util.spec_from_file_location("rename_rev", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    ctx = MigrationContext.configure(db.connection())
    with Operations.context(ctx):
        module.upgrade()
    assert db.execute(
        text("SELECT request_type FROM user_requests WHERE id = :id"), {"id": row.id}
    ).scalar() == "catalogue_request"

    with Operations.context(ctx):
        module.downgrade()
    assert db.execute(
        text("SELECT request_type FROM user_requests WHERE id = :id"), {"id": row.id}
    ).scalar() == "item_request"
```

- [x] **Step 2: Run it to verify it fails**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_catalogue_requests.py -q`
Expected: FAIL — `AttributeError: module 'app.services.user_requests' has no attribute 'create_catalogue_request'`.

- [x] **Step 3: Write the migration**

Create `backend/alembic/versions/d1e3f5a7b9c2_rename_item_request_to_catalogue_request.py`:

```python
"""rename item_request rows to catalogue_request

Revision ID: d1e3f5a7b9c2
Revises: c6e8a0b2d4f7
Create Date: 2026-09-08 12:00:00.000000

Data only, no DDL. `user_requests.status` and `request_type` are Text and
the domain layer owns their vocabulary; a CHECK is deliberately not added,
matching how the other statuses are enforced.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "d1e3f5a7b9c2"
down_revision: Union[str, Sequence[str], None] = "c6e8a0b2d4f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE user_requests SET request_type = 'catalogue_request' "
        "WHERE request_type = 'item_request'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE user_requests SET request_type = 'item_request' "
        "WHERE request_type = 'catalogue_request'"
    )
```

- [x] **Step 4: Rename the service layer**

In `backend/app/services/user_requests.py`:

```python
REQUEST_CATALOGUE = "catalogue_request"      # was REQUEST_ITEM = "item_request"
```

Rename `create_item_request` → `create_catalogue_request` (body: `request_type=REQUEST_CATALOGUE`), `find_sibling_item_requests` → `find_sibling_catalogue_requests` (filter `REQUEST_CATALOGUE`), `_resolve_one_item_request` → `_resolve_one_catalogue_request`, `fulfill_item_request` → `fulfill_catalogue_request` (both `REQUEST_CATALOGUE` filters; error text `"This is not a catalogue request."` / `"This catalogue request is already resolved."`). `EDITABLE_DETAILS` key becomes `REQUEST_CATALOGUE`. Update the module docstring: replace the paragraph starting "``item_request`` is the third type" with:

```
``catalogue_request`` is the third type and the only one raised by a *person*
rather than by a stock operation: a user searched for a material and the
catalogue had no row for it at all. An in-app item sitting at zero is still
findable, so a short count is ``inventory_recount`` territory and an empty
shelf for a real catalogue item is a ``material_request``
(``services/material_requests.py``). A catalogue request carries a NULL
``item_id`` until a reviewer fulfils it, and that NULL is exactly what
distinguishes "not in the app" from "in the app, count is wrong".
```

In `backend/app/services/hub.py` rename the dataclass field `item_requests` → `catalogue_requests` and the lookup `open_counts.get(user_requests_service.REQUEST_CATALOGUE, 0)`. In `backend/app/schemas/hub.py` rename `HubAdminExceptions.item_requests` → `catalogue_requests`.

- [x] **Step 5: Rename schemas and router**

`backend/app/schemas/user_requests.py`: `ItemRequestCreate` → `CatalogueRequestCreate` (docstring first line `"""File a request for a material that has no catalogue row at all.`), `ItemRequestFulfill` → `CatalogueRequestFulfill`. Keep `source: Literal["work_orders", "find_item"]` for now (Task 12 adds `request_card`).

`backend/app/routers/user_requests.py`: import the renamed schemas; `@router.post("/catalogue-request", …)` with handler `create_catalogue_request` calling `request_service.create_catalogue_request`; `list_request_siblings` calls `find_sibling_catalogue_requests`; handler `fulfill_item_request` → `fulfill_catalogue_request` calling `request_service.fulfill_catalogue_request`. Module docstring: "filing a catalogue request is open to any authenticated session".

- [x] **Step 6: Update the other backend tests that name the old symbols**

`backend/tests/test_user_requests.py:482-489`: `create_item_request` → `create_catalogue_request`; rename the test `test_catalogue_request_fields_are_editable`.
`backend/tests/test_hub_service.py:985-1013`: `REQUEST_ITEM` → `REQUEST_CATALOGUE` (three places); `exceptions.item_requests` → `exceptions.catalogue_requests` (two places).
`backend/tests/test_route_role_gates.py`: in the parametrize at line ~355 `"fulfill_item_request"` → `"fulfill_catalogue_request"`; `test_filing_an_item_request_has_no_static_min_role` → assert `"create_catalogue_request"` and rename to `test_filing_a_catalogue_request_has_no_static_min_role`; the `["list_request_siblings", "fulfill_item_request"]` list → `"fulfill_catalogue_request"`.

- [x] **Step 7: Run the backend suite slices**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_catalogue_requests.py tests/test_user_requests.py tests/test_hub_service.py tests/test_route_role_gates.py -q`
Expected: PASS (the hub-service test file may skip if Postgres is down; it must not error).

- [x] **Step 8: Rename the frontend**

`git mv backend/static/views/itemRequest.js backend/static/views/catalogueRequest.js`. In it: `export function catalogueRequestPromptHtml(...)`, error text `catalogueRequestPromptHtml: unknown source`, import `apiCreateCatalogueRequest`, every CSS class `item-request` → `catalogue-request` (container, `-open`, `-form`, `-label`, `-text`, `-qty`, `-note`, `-actions`, `-submit`, `-cancel`, `-message`, `-sent`), button text `Can't find it? Request it for the catalogue` (both places), hint `Send this to staff to add to the catalogue.`, sent text `Catalogue request sent to staff.`. Header comment: "View: file a Catalogue Request from a search that found nothing."

`backend/static/api.js`: `apiCreateItemRequest` → `apiCreateCatalogueRequest` posting to `/user-requests/catalogue-request`; `apiFulfillItemRequest` → `apiFulfillCatalogueRequest` (path unchanged). Update both comments ("Other open catalogue requests naming the same material").

`backend/static/main.js:31`: `import "./views/catalogueRequest.js";`
`backend/static/views/items.js:45,279`: import and call `catalogueRequestPromptHtml`.
`backend/static/views/workOrders.js:62,1877`: same.
`backend/static/views/userRequests.js`: imports `apiFulfillCatalogueRequest`; `card.dataset.requestType === "catalogue_request"`; confirm text `Fulfil this catalogue request?`; header comment line → `catalogue_request  -- the material has no catalogue row at all`.
`backend/static/views/userRequestCards.js`: `requestTypeLabel`: `if (type === "catalogue_request") return "Catalogue request";`; every `=== "item_request"` → `=== "catalogue_request"`; rename `itemRequestBody`/`itemRequestActions` → `catalogueRequestBody`/`catalogueRequestActions`; header comment.
`backend/static/views/hubAdmin.js:90`: `["catalogue_requests", "Catalogue requests", true],`.
`backend/static/pages/user-requests.html`: option `value="catalogue_request"` label `Catalogue requests`; in the hint and comment replace "item requests report … could not find" with "catalogue requests report material a user searched for but could not find"; "Fulfilling an item request" → "Fulfilling a catalogue request".
`backend/static/tips.js:180-191`: in `requests.types` and `requests.siblings` replace "Item requests"/"item requests" with "Catalogue requests"/"catalogue requests"; label `Closing matching catalogue requests`.
`backend/static/styles.css:1741-1785`: rename the `.item-request*` selectors to `.catalogue-request*`.

- [x] **Step 9: Verify no old name survives, and syntax-check**

Run: `grep -rn "item_request\|itemRequest\|ItemRequest\|item-request\|REQUEST_ITEM" backend/app backend/static backend/tests --include=*.py --include=*.js --include=*.html --include=*.css`
Expected: **no output** (the migration file mentions `item_request` deliberately — it lives under `backend/alembic`, outside the grep).
Run: `for f in backend/static/views/catalogueRequest.js backend/static/views/items.js backend/static/views/workOrders.js backend/static/views/userRequests.js backend/static/views/userRequestCards.js backend/static/views/hubAdmin.js backend/static/api.js backend/static/main.js; do node --check "$f" || echo "FAIL $f"; done`
Expected: no `FAIL` lines.

- [x] **Step 10: Apply the migration locally and run the full suite**

Run: `cd backend && ./venv/Scripts/python.exe -m alembic upgrade head && ./venv/Scripts/python.exe -m alembic current`
Expected: `d1e3f5a7b9c2 (head)`.
Run: `cd backend && ./venv/Scripts/python.exe -m pytest -q`
Expected: PASS apart from the two pre-existing failures named in Global Constraints.

- [x] **Step 11: Commit**

```bash
git add -A backend/alembic/versions/d1e3f5a7b9c2_rename_item_request_to_catalogue_request.py backend/app backend/static backend/tests
git commit -m "rename item requests to catalogue requests across the stack

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Rj5dKhZSJLx5wvJMfBTimY"
```

---

### Task 2: The pure domain module and the shared constants

**Why now:** the two edges are the whole feature's trigger logic and cost nothing to test. Putting the status/type strings here (not in the service) is what lets `services/material_requests.py` import nothing from `app.services` later.

**Files:**
- Create: `backend/app/domain/material_requests.py`
- Modify: `backend/app/services/user_requests.py:31-46` (constants + `EDITABLE_DETAILS`)
- Test: `backend/tests/test_material_requests_domain.py`

**Interfaces:**
- Produces: `domain.material_requests.REQUEST_MATERIAL = "material_request"`, `STATUS_OPEN`, `STATUS_STOCKED = "stocked"`, `STATUS_RESOLVED`, `restocked(quantity_before, quantity_after) -> bool`, `went_out(quantity_before, quantity_after) -> bool`. `services.user_requests` re-exports `REQUEST_MATERIAL`, `STATUS_OPEN`, `STATUS_STOCKED`, `STATUS_RESOLVED` and has `EDITABLE_DETAILS[REQUEST_MATERIAL] == frozenset({"quantity", "product_link", "note"})`.

- [x] **Step 1: Write the failing tests**

Create `backend/tests/test_material_requests_domain.py`:

```python
"""The two stock edges a Material Request lives on.

Pure, like `test_low_stock_domain.py`: numbers in, bool out, no session.
The interesting cases are the boundaries -- exact zero and a negative
count (Scan / Stock records real usage past the recorded balance).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decimal import Decimal

import pytest

from app.domain import material_requests as policy


@pytest.mark.parametrize(
    "before,after",
    [("0", "1"), ("0", "0.5"), ("-3", "1"), ("-3", "0.01")],
)
def test_restocked_is_the_edge_from_nonpositive_to_positive(before, after):
    assert policy.restocked(Decimal(before), Decimal(after)) is True


@pytest.mark.parametrize(
    "before,after",
    [("1", "5"), ("0", "0"), ("-2", "0"), ("-2", "-1"), ("5", "0"), ("5", "4")],
)
def test_restocked_ignores_every_other_move(before, after):
    assert policy.restocked(Decimal(before), Decimal(after)) is False


@pytest.mark.parametrize(
    "before,after",
    [("1", "0"), ("5", "-2"), ("0.5", "0")],
)
def test_went_out_is_the_edge_from_positive_to_nonpositive(before, after):
    assert policy.went_out(Decimal(before), Decimal(after)) is True


@pytest.mark.parametrize(
    "before,after",
    [("0", "1"), ("0", "-1"), ("5", "3"), ("0", "0"), ("-1", "-2")],
)
def test_went_out_ignores_every_other_move(before, after):
    assert policy.went_out(Decimal(before), Decimal(after)) is False


def test_the_two_edges_never_both_fire():
    for before in ("-2", "0", "1"):
        for after in ("-2", "0", "1"):
            b, a = Decimal(before), Decimal(after)
            assert not (policy.restocked(b, a) and policy.went_out(b, a))


def test_the_vocabulary_is_shared_with_the_queue_service():
    from app.services import user_requests as request_service

    assert policy.REQUEST_MATERIAL == "material_request"
    assert policy.STATUS_STOCKED == "stocked"
    assert request_service.STATUS_STOCKED is policy.STATUS_STOCKED
    assert request_service.STATUS_OPEN is policy.STATUS_OPEN
    assert request_service.STATUS_RESOLVED is policy.STATUS_RESOLVED
    assert request_service.REQUEST_MATERIAL is policy.REQUEST_MATERIAL
    assert request_service.EDITABLE_DETAILS[policy.REQUEST_MATERIAL] == frozenset(
        {"quantity", "product_link", "note"}
    )
```

- [x] **Step 2: Run to verify it fails**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_material_requests_domain.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.domain.material_requests'`.

- [x] **Step 3: Write the domain module**

Create `backend/app/domain/material_requests.py`:

```python
"""Material Request policy: the two stock edges a request lives on.

Layer: pure domain (no SQLAlchemy, no FastAPI, no models). Same shape as
`domain/low_stock.py`: the interesting rule is an *edge*, not a state, so
it is a comparison of a before and an after and needs no armed-state
column anywhere.

A Material Request says "a catalogue item the shelf does not have". It
becomes `stocked` the moment any write takes the item's on-hand from
`<= 0` to `> 0`, and falls back to `open` on the reverse move. Which
write did it -- Add Stock, an upward correction, a voided dispense, a
Mass Stage return, a work-order line reversal -- is irrelevant here; the
eight stock-writing sites all ask the same two questions.

The vocabulary lives here rather than in `services/user_requests.py` so
that `services/material_requests.py` can import it without importing
anything from `app.services`, which is the import-ring discipline
`services/low_stock.py` established.
"""

from decimal import Decimal

REQUEST_MATERIAL = "material_request"

STATUS_OPEN = "open"
STATUS_STOCKED = "stocked"
STATUS_RESOLVED = "resolved"


def restocked(quantity_before: Decimal, quantity_after: Decimal) -> bool:
    """Whether this write is the moment the item came back onto the shelf.

    `<= 0` before, not `== 0`: Scan / Stock records real usage past the
    recorded balance, so an item can sit at -3 and a restock to +2 is
    still the edge the crew is waiting for.
    """
    return Decimal(quantity_before) <= 0 and Decimal(quantity_after) > 0


def went_out(quantity_before: Decimal, quantity_after: Decimal) -> bool:
    """The reverse edge: a stocked item ran out again before the crew
    added it. Sends a `stocked` request back to `open` so the Hub row and
    the Materials line stop promising something the shelf no longer has."""
    return Decimal(quantity_before) > 0 and Decimal(quantity_after) <= 0
```

- [x] **Step 4: Point the queue service at the shared vocabulary**

In `backend/app/services/user_requests.py` replace lines 31-35 (the constants) with:

```python
from app.domain.material_requests import (  # noqa: F401 - re-exported for callers
    REQUEST_MATERIAL,
    STATUS_OPEN,
    STATUS_RESOLVED,
    STATUS_STOCKED,
)

REQUEST_INVENTORY_RECOUNT = "inventory_recount"
REQUEST_MISSING_ITEM_PRICE = "missing_item_price"
REQUEST_CATALOGUE = "catalogue_request"
```

(Move the import up with the other `from app.domain …` imports.) Extend `EDITABLE_DETAILS`:

```python
EDITABLE_DETAILS: dict[str, frozenset[str]] = {
    REQUEST_CATALOGUE: frozenset({"searched_text", "quantity", "note"}),
    REQUEST_MATERIAL: frozenset({"quantity", "product_link", "note"}),
    REQUEST_INVENTORY_RECOUNT: frozenset(),
    REQUEST_MISSING_ITEM_PRICE: frozenset(),
}
```

- [x] **Step 5: Run the tests**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_material_requests_domain.py tests/test_user_requests.py tests/test_catalogue_requests.py -q`
Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add backend/app/domain/material_requests.py backend/app/services/user_requests.py backend/tests/test_material_requests_domain.py
git commit -m "add the material request stock edges and shared status vocabulary

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Rj5dKhZSJLx5wvJMfBTimY"
```

---

### Task 3: Notification and realtime policy (pure)

**Why now:** Step 1 of `docs/adding-a-notification-trigger.md`. The service functions in Task 5 and the flush in Task 6 need these names; writing the rules first means the text and audience are pinned before anything can send them.

**Files:**
- Modify: `backend/app/domain/notifications.py:37-52` (events + `ALL_EVENTS`), `:75-87` (audience constant), `:89-129` (`_MESSAGES`), after `recipients_for_low_stock` (two rules)
- Modify: `backend/app/domain/realtime.py:27-40` (`__all__`), `:72-92` (event constants), `:94-106` (`_AUDIENCE_MIN_ROLE`)
- Test: `backend/tests/test_notifications_domain.py:212-236,427-480`, `backend/tests/test_realtime_domain.py`

**Interfaces:**
- Produces: `notif.EVENT_MATERIAL_REQUEST_FILED = "material_request.filed"`, `notif.EVENT_MATERIAL_REQUEST_STOCKED = "material_request.stocked"`, `notif.MATERIAL_REQUEST_AUDIENCE_MIN_ROLE`, `notif.recipients_for_material_request_filed(*, recipient_ids)`, `notif.recipients_for_material_request_stocked(*, assignee_ids, supervisor_id, requester_id)`, `build_message(event, name=…, number=…)` for both; `realtime.EVENT_USER_REQUEST_CHANGED = "user_request.changed"` at Technician+.

- [x] **Step 1: Write the failing notification-domain tests**

In `backend/tests/test_notifications_domain.py`, after `_LOW_STOCK_EVENTS` (line ~233) add and rewire the partition:

```python
# The two material-request events name an item AND a work order, so they
# fit neither the number-only nor the item-only parametrizations; they have
# their own coverage below.
_MATERIAL_REQUEST_EVENTS = (
    notif.EVENT_MATERIAL_REQUEST_FILED,
    notif.EVENT_MATERIAL_REQUEST_STOCKED,
)
_NUMBER_EVENTS = tuple(
    event
    for event in notif.ALL_EVENTS
    if event
    not in _COUNT_EVENTS + _CHAIN_EVENTS + _LOW_STOCK_EVENTS + _MATERIAL_REQUEST_EVENTS
)
```

Rewrite `test_every_event_is_either_a_number_a_count_a_chain_or_a_low_stock_event` to include the new tuple in the union and in the pairwise disjointness checks (add `_MATERIAL_REQUEST_EVENTS` against each of the other four). Then append at the end of the file:

```python
# --- material requests ---------------------------------------------------


def test_material_request_filed_names_the_item_and_the_work_order():
    title, body = notif.build_message(
        notif.EVENT_MATERIAL_REQUEST_FILED, name="3M Blue Tape", number="WO-1234"
    )
    assert title == "Material requested"
    assert body == "3M Blue Tape is needed for WO-1234."


def test_material_request_stocked_names_the_item_and_the_work_order():
    title, body = notif.build_message(
        notif.EVENT_MATERIAL_REQUEST_STOCKED, name="3M Blue Tape", number="WO-1234"
    )
    assert title == "Material in stock"
    assert body == "3M Blue Tape for WO-1234 is now in stock."


@pytest.mark.parametrize("event", _MATERIAL_REQUEST_EVENTS)
def test_material_request_text_refuses_a_missing_field(event):
    with pytest.raises(ValueError):
        notif.build_message(event, name="3M Blue Tape")
    with pytest.raises(ValueError):
        notif.build_message(event, number="WO-1234")


def test_material_request_filed_keeps_the_actor():
    """A state alarm, like low stock: the filer wants confirmation the
    request went up the chain."""
    actor = uuid.uuid4()
    other = uuid.uuid4()
    assert notif.recipients_for_material_request_filed(
        recipient_ids=[actor, other, None, actor]
    ) == [actor, other]


def test_material_request_stocked_addresses_crew_supervisor_and_requester():
    tech, supervisor, requester = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    assert notif.recipients_for_material_request_stocked(
        assignee_ids=[tech], supervisor_id=supervisor, requester_id=requester
    ) == [tech, supervisor, requester]


def test_material_request_stocked_dedupes_a_supervising_assignee_who_also_filed():
    person = uuid.uuid4()
    assert notif.recipients_for_material_request_stocked(
        assignee_ids=[person], supervisor_id=person, requester_id=person
    ) == [person]


def test_material_request_stocked_tolerates_an_unrouted_work_order_and_no_filer():
    tech = uuid.uuid4()
    assert notif.recipients_for_material_request_stocked(
        assignee_ids=[tech], supervisor_id=None, requester_id=None
    ) == [tech]


def test_material_request_audience_floor_is_techfm_oa():
    """Two constants, one value today. Pinned separately from the low-stock
    floor so that changing one is a deliberate act, not a side effect."""
    assert notif.MATERIAL_REQUEST_AUDIENCE_MIN_ROLE == roles.ROLE_TECHFM_OA


def test_material_request_events_are_registered():
    assert notif.EVENT_MATERIAL_REQUEST_FILED in notif.ALL_EVENTS
    assert notif.EVENT_MATERIAL_REQUEST_STOCKED in notif.ALL_EVENTS
```

And in `backend/tests/test_realtime_domain.py` append:

```python
def test_user_request_events_reach_every_role():
    """Technicians file and cancel material requests and see the stocked
    line on their own cards, so the envelope is the whole hierarchy. Noise,
    not security -- P2 keeps row data out of the envelope."""
    for role in ("technician", "supervisor", "techfm_oa", "admin", "owner"):
        assert (
            realtime.audience_allows(realtime.EVENT_USER_REQUEST_CHANGED, role)
            is True
        ), role


def test_user_request_changed_is_its_own_event_type():
    assert realtime.EVENT_USER_REQUEST_CHANGED == "user_request.changed"
    assert realtime.EVENT_USER_REQUEST_CHANGED != realtime.EVENT_ITEM_LOW_STOCK_CHANGED
```

- [x] **Step 2: Run to verify they fail**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_notifications_domain.py tests/test_realtime_domain.py -q`
Expected: FAIL — `AttributeError: … has no attribute 'EVENT_MATERIAL_REQUEST_FILED'` (collection error on the module-level tuple) and `'EVENT_USER_REQUEST_CHANGED'`.

- [x] **Step 3: Add the notification policy**

In `backend/app/domain/notifications.py`:

After `EVENT_ITEM_LOW_STOCK = "item.low_stock"`:
```python
EVENT_MATERIAL_REQUEST_FILED = "material_request.filed"
EVENT_MATERIAL_REQUEST_STOCKED = "material_request.stocked"
```
Append both to `ALL_EVENTS`.

After `LOW_STOCK_AUDIENCE_MIN_ROLE`:
```python
# Who hears that a crew needs a material the shelf does not have. TechFM OA
# and above -- the rank that works the User Requests page and can press
# "Mark stocked & notify". A fourth constant rather than a reuse of
# LOW_STOCK_AUDIENCE_MIN_ROLE: "who reorders" and "who fields a crew's
# request" are different questions and must be able to diverge.
MATERIAL_REQUEST_AUDIENCE_MIN_ROLE = roles.ROLE_TECHFM_OA
```

In `_MESSAGES`, after the low-stock entry:
```python
    EVENT_MATERIAL_REQUEST_FILED: (
        "Material requested",
        "{name} is needed for {number}.",
    ),
    EVENT_MATERIAL_REQUEST_STOCKED: (
        "Material in stock",
        "{name} for {number} is now in stock.",
    ),
```

After `recipients_for_low_stock`:
```python
def recipients_for_material_request_filed(
    *,
    recipient_ids: Sequence[Optional[uuid.UUID]],
) -> list[uuid.UUID]:
    """A crew member asked for a material the shelf lacks -- tell the staff.

    Does not suppress the actor, for the low-stock reason: this is a state
    alarm, not a report of somebody's action, and the filer wants to see
    their request went up the chain. `actor_id=None` keeps the dedup and
    the `None`-dropping.
    """
    return select_recipients(recipient_ids, actor_id=None)


def recipients_for_material_request_stocked(
    *,
    assignee_ids: Sequence[uuid.UUID],
    supervisor_id: Optional[uuid.UUID],
    requester_id: Optional[uuid.UUID],
) -> list[uuid.UUID]:
    """The requested material is back on the shelf -- tell the crew.

    Assignees first, then the routed supervisor, then the original filer,
    so a person holding two of those hats lands in the most specific
    position once. Actor not suppressed: a supervisor who restocks and is
    also on the crew is exactly the person who should see the line is ready.
    """
    return select_recipients(
        [*assignee_ids, supervisor_id, requester_id], actor_id=None
    )
```

Update the module docstring's `build_message` paragraph: "`build_message` accepts a `number`, a `count`, an item `name`, and a `quantity` … The two material-request events use `name` and `number` together — still catalogue identifier plus opaque work-order number, no widening."

- [x] **Step 4: Add the realtime event**

In `backend/app/domain/realtime.py`: add `"EVENT_USER_REQUEST_CHANGED",` to `__all__`; after `EVENT_ITEM_LOW_STOCK_CHANGED`:

```python
# A User Request moved: filed, stocked, back to open, resolved, reopened.
# `id` names the request. Subscribers -- the User Hub dashboard, the User
# Requests page, an open work-order card -- refetch through REST, which
# re-applies visibility; a technician receiving an envelope for a request
# they cannot see costs one request and discloses nothing.
EVENT_USER_REQUEST_CHANGED = "user_request.changed"
```

and in `_AUDIENCE_MIN_ROLE`:
```python
    # Technicians file, cancel, and add from the stocked line, so the whole
    # hierarchy subscribes. Not a security boundary (P2).
    EVENT_USER_REQUEST_CHANGED: roles.ROLE_TECHNICIAN,
```

- [x] **Step 5: Run the tests**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_notifications_domain.py tests/test_realtime_domain.py tests/test_notifications.py -q`
Expected: PASS (`test_notifications.py` proves nothing existing broke under the widened `ALL_EVENTS`).

- [x] **Step 6: Commit**

```bash
git add backend/app/domain/notifications.py backend/app/domain/realtime.py backend/tests/test_notifications_domain.py backend/tests/test_realtime_domain.py
git commit -m "add material request push rules and the user_request.changed envelope

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Rj5dKhZSJLx5wvJMfBTimY"
```

---

### Task 4: `services/material_requests.py` — create, transition, buffer

**Why now:** every route and every stock site calls into this module. Proving the transitions in isolation (calling `record_stock_change` with an item object directly, as `test_low_stock_buffer.py` does) means Task 6 can wire eight sites knowing the callee is right.

**Files:**
- Create: `backend/app/services/material_requests.py`
- Modify: `backend/app/domain/errors.py` (after `ItemRequestStateError`), `backend/app/routers/_errors.py` (import + `_STATUS_MAP`)
- Test: `backend/tests/test_material_requests.py` (created here; later tasks append)

**Interfaces:**
- Consumes: Task 2 constants and edges.
- Produces (all in `app.services.material_requests`):
  - `StockedFact(request_id, item_name, work_order_id, work_order_number, assignee_ids: tuple, supervisor_id, requester_id)` frozen dataclass; `MAX_BUFFERED_FACTS = 500`; `drain() -> list[StockedFact]`
  - `lock_live_item(db, item_id) -> Item` (raises `ItemNotFoundError`)
  - `create_or_update(db, *, item_id, work_order, quantity, product_link, note, created_by_id, origin) -> tuple[UserRequest, bool]` (`True` = created)
  - `record_stock_change(db, item, *, quantity_before) -> None`
  - `mark_stocked(db, request_id, *, actor_id) -> UserRequest`
  - `cancel(db, request_id, *, actor_id) -> UserRequest`
  - `resolve_from_line(db, *, request_id, work_order_id, work_order_number, item_id, quantity, resolved_by_id) -> UserRequest`
  - `clear_stocked_stamps(request) -> None`
  - `list_for_work_order(db, work_order_id) -> list[UserRequest]`
  - `open_counts(db) -> dict[str, dict[str, int]]`
  - `stocked_requests_for_user(db, user) -> list[UserRequest]`
  - `errors.MaterialRequestOwnershipError` → HTTP 403.

- [x] **Step 1: Write the failing tests**

Create `backend/tests/test_material_requests.py`:

```python
"""Material Requests: a catalogue item the shelf does not have.

Distinct from a Catalogue Request (no row at all) and a recount (count is
wrong): here the row exists, `item_id` is never NULL, and the interesting
behaviour is the automatic `open -> stocked -> open` movement driven by
the item's on-hand crossing zero.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.domain.errors import ItemRequestStateError, MaterialRequestOwnershipError
from app.models import Item, User, UserRequest, WorkOrderTechnician
from app.services import auth
from app.services import material_requests as material_service
from app.services import user_requests as request_service
from app.services import work_orders as wos


@pytest.fixture(autouse=True)
def _clean_buffer():
    material_service.drain()
    yield
    material_service.drain()


def _user(db, role="technician"):
    user = User(
        username=f"mreq-{uuid.uuid4().hex[:10]}",
        first_name="Test",
        last_name=role.title(),
        password_hash=auth.hash_password("hunter2"),
        role=role,
    )
    db.add(user)
    db.flush()
    return user


def _work_order(db, creator, *, assigned_to=None, supervisor=None):
    return wos.get_or_create_work_order(
        db,
        number=f"WO-MR-{uuid.uuid4().hex[:8]}",
        created_by_id=creator.id,
        assigned_to_id=assigned_to.id if assigned_to else None,
        supervisor_id=supervisor.id if supervisor else None,
    )


def _item(db, quantity="0", name=None):
    item = Item(
        barcode=f"MR-{uuid.uuid4().hex[:10]}",
        name=name or f"Widget {uuid.uuid4().hex[:6]}",
        quantity=Decimal(quantity),
        location="Shelf C",
        price=Decimal("3.50"),
        product_link="https://example.com/widget",
    )
    db.add(item)
    db.flush()
    return item


def _file(db, tech, work_order, item, quantity="1", link=None, note=None):
    request, created = material_service.create_or_update(
        db,
        item_id=item.id,
        work_order=work_order,
        quantity=Decimal(quantity),
        product_link=link,
        note=note,
        created_by_id=tech.id,
        origin="request_card",
    )
    db.flush()
    return request, created


# --------------------------------------------------------------------------
# Filing and dedupe
# --------------------------------------------------------------------------

def test_filing_stores_the_item_work_order_and_details(db):
    tech = _user(db)
    work_order = _work_order(db, tech)
    item = _item(db)

    request, created = _file(
        db, tech, work_order, item, quantity="2.5",
        link="https://shop.example/x", note="  blue one  ",
    )

    assert created is True
    assert request.request_type == "material_request"
    assert request.status == "open"
    assert request.item_id == item.id
    assert request.work_order_id == work_order.id
    assert request.message == "Please stock this item"
    assert request.details["quantity"] == "2.5"
    assert request.details["product_link"] == "https://shop.example/x"
    assert request.details["note"] == "blue one"
    assert request.details["work_order_number"] == work_order.number
    assert request.details["origin"] == "request_card"
    assert request.details["stock_cycles"] == 0


def test_a_second_filing_for_the_same_pair_updates_instead_of_inserting(db):
    tech = _user(db)
    work_order = _work_order(db, tech)
    item = _item(db)
    first, _ = _file(db, tech, work_order, item, quantity="1")

    second, created = _file(db, tech, work_order, item, quantity="4", note="more")

    assert created is False
    assert second.id == first.id
    assert second.details["quantity"] == "4"
    assert second.details["note"] == "more"
    assert (
        db.query(UserRequest)
        .filter(UserRequest.request_type == "material_request", UserRequest.item_id == item.id)
        .count()
        == 1
    )


def test_other_work_orders_get_their_own_request(db):
    tech = _user(db)
    item = _item(db)
    first, _ = _file(db, tech, _work_order(db, tech), item)
    second, created = _file(db, tech, _work_order(db, tech), item)

    assert created is True
    assert second.id != first.id


def test_a_resolved_request_does_not_absorb_a_new_filing(db):
    tech = _user(db)
    work_order = _work_order(db, tech)
    item = _item(db)
    old, _ = _file(db, tech, work_order, item)
    old.status = "resolved"
    db.flush()

    fresh, created = _file(db, tech, work_order, item)

    assert created is True
    assert fresh.id != old.id


def test_filing_is_allowed_when_the_app_shows_stock(db):
    """Advisory only: counts are sometimes wrong, staff verify."""
    tech = _user(db)
    item = _item(db, quantity="3")
    request, created = _file(db, tech, _work_order(db, tech), item)
    assert created is True
    assert request.status == "open"


# --------------------------------------------------------------------------
# The automatic edges
# --------------------------------------------------------------------------

def _restock(db, item, to="5"):
    """Simulate what every stock service does: mutate under the lock, then
    call the recorder before commit."""
    before = item.quantity
    item.quantity = Decimal(to)
    material_service.record_stock_change(db, item, quantity_before=before)
    db.flush()


def test_a_restock_moves_every_open_request_for_the_item_to_stocked(db):
    tech = _user(db)
    supervisor = _user(db, "supervisor")
    wo_a = _work_order(db, tech, assigned_to=tech, supervisor=supervisor)
    wo_b = _work_order(db, tech)
    item = _item(db)
    a, _ = _file(db, tech, wo_a, item)
    b, _ = _file(db, tech, wo_b, item)

    _restock(db, item)

    assert a.status == "stocked"
    assert b.status == "stocked"
    assert a.details["stocked_by"] == "auto"
    assert a.details["stock_cycles"] == 1
    datetime.fromisoformat(a.details["stocked_at"])  # parses
    facts = material_service.drain()
    assert {f.request_id for f in facts} == {a.id, b.id}
    fact_a = next(f for f in facts if f.request_id == a.id)
    assert fact_a.item_name == item.name
    assert fact_a.work_order_number == wo_a.number
    assert fact_a.assignee_ids == (tech.id,)
    assert fact_a.supervisor_id == supervisor.id
    assert fact_a.requester_id == tech.id


def test_the_fact_reads_plural_assignments_with_the_legacy_column_folded_in(db):
    tech = _user(db)
    second = _user(db)
    work_order = _work_order(db, tech, assigned_to=tech)
    db.add(WorkOrderTechnician(work_order_id=work_order.id, technician_id=second.id))
    db.flush()
    db.refresh(work_order)
    item = _item(db)
    _file(db, tech, work_order, item)

    _restock(db, item)

    (fact,) = material_service.drain()
    assert set(fact.assignee_ids) == {tech.id, second.id}


def test_a_negative_count_coming_back_positive_is_a_restock(db):
    tech = _user(db)
    item = _item(db, quantity="-3")
    request, _ = _file(db, tech, _work_order(db, tech), item)

    _restock(db, item, to="1")

    assert request.status == "stocked"
    assert len(material_service.drain()) == 1


def test_a_move_that_stays_positive_or_stays_nonpositive_changes_nothing(db):
    tech = _user(db)
    item = _item(db, quantity="0")
    request, _ = _file(db, tech, _work_order(db, tech), item)

    _restock(db, item, to="-2")
    assert request.status == "open"
    assert material_service.drain() == []

    item.quantity = Decimal("4")
    db.flush()
    request.status = "stocked"
    db.flush()
    _restock(db, item, to="9")
    assert request.status == "stocked"
    assert material_service.drain() == []


def test_running_out_again_sends_a_stocked_request_back_to_open(db):
    tech = _user(db)
    item = _item(db)
    request, _ = _file(db, tech, _work_order(db, tech), item)
    _restock(db, item, to="2")
    material_service.drain()

    _restock(db, item, to="0")

    assert request.status == "open"
    assert "stocked_at" not in request.details
    assert "stocked_by" not in request.details
    assert request.details["stock_cycles"] == 1
    assert material_service.drain() == []


def test_a_second_restock_counts_a_second_cycle(db):
    tech = _user(db)
    item = _item(db)
    request, _ = _file(db, tech, _work_order(db, tech), item)
    _restock(db, item, to="2")
    _restock(db, item, to="0")
    _restock(db, item, to="2")

    assert request.status == "stocked"
    assert request.details["stock_cycles"] == 2


def test_a_restock_against_a_closed_work_order_resolves_quietly(db):
    tech = _user(db)
    work_order = _work_order(db, tech)
    item = _item(db)
    request, _ = _file(db, tech, work_order, item)
    work_order.archived_at = datetime.now(timezone.utc)
    db.flush()

    _restock(db, item)

    assert request.status == "resolved"
    assert request.resolution_note == "Work order was closed before the item was stocked."
    assert material_service.drain() == []


def test_the_buffer_is_bounded(db):
    from types import SimpleNamespace

    tech = _user(db)
    item = _item(db)
    for _ in range(3):
        _file(db, tech, _work_order(db, tech), item)
    # Fill the buffer by hand, then prove the real transition drops overflow.
    for _ in range(material_service.MAX_BUFFERED_FACTS):
        material_service._buffer_fact(
            material_service.StockedFact(
                request_id=uuid.uuid4(), item_name="x", work_order_id=None,
                work_order_number="WO", assignee_ids=(), supervisor_id=None,
                requester_id=None,
            )
        )
    _restock(db, item)
    assert len(material_service.drain()) == material_service.MAX_BUFFERED_FACTS


# --------------------------------------------------------------------------
# Manual fire, cancel, resolve-from-line, reopen
# --------------------------------------------------------------------------

def test_mark_stocked_fires_at_any_on_hand_and_buffers_one_fact(db):
    tech = _user(db)
    staff = _user(db, "techfm_oa")
    item = _item(db, quantity="0")
    request, _ = _file(db, tech, _work_order(db, tech, assigned_to=tech), item)

    marked = material_service.mark_stocked(db, request.id, actor_id=staff.id)

    assert marked.status == "stocked"
    assert marked.details["stocked_by"] == str(staff.id)
    assert marked.details["stock_cycles"] == 1
    assert len(material_service.drain()) == 1


def test_mark_stocked_refuses_a_stocked_or_resolved_request(db):
    tech = _user(db)
    staff = _user(db, "techfm_oa")
    request, _ = _file(db, tech, _work_order(db, tech), _item(db))
    material_service.mark_stocked(db, request.id, actor_id=staff.id)
    with pytest.raises(ItemRequestStateError):
        material_service.mark_stocked(db, request.id, actor_id=staff.id)


def test_a_manually_stocked_request_stays_stocked_through_a_later_restock_edge(db):
    """The crew was already told; only `went_out` can send it back."""
    tech = _user(db)
    staff = _user(db, "techfm_oa")
    item = _item(db, quantity="0")
    request, _ = _file(db, tech, _work_order(db, tech), item)
    material_service.mark_stocked(db, request.id, actor_id=staff.id)
    material_service.drain()

    _restock(db, item, to="5")

    assert request.status == "stocked"
    assert request.details["stock_cycles"] == 1
    assert material_service.drain() == []


def test_the_filer_can_cancel_their_own_open_request(db):
    tech = _user(db)
    request, _ = _file(db, tech, _work_order(db, tech), _item(db))

    cancelled = material_service.cancel(db, request.id, actor_id=tech.id)

    assert cancelled.status == "resolved"
    assert cancelled.resolution_note == "Cancelled by requester"
    assert cancelled.resolved_by_id == tech.id


def test_someone_else_cannot_cancel_it(db):
    tech = _user(db)
    other = _user(db)
    request, _ = _file(db, tech, _work_order(db, tech), _item(db))
    with pytest.raises(MaterialRequestOwnershipError):
        material_service.cancel(db, request.id, actor_id=other.id)


def test_a_stocked_request_cannot_be_cancelled(db):
    tech = _user(db)
    item = _item(db)
    request, _ = _file(db, tech, _work_order(db, tech), item)
    _restock(db, item)
    with pytest.raises(ItemRequestStateError):
        material_service.cancel(db, request.id, actor_id=tech.id)


def test_resolve_from_line_records_the_added_quantity(db):
    tech = _user(db)
    work_order = _work_order(db, tech)
    item = _item(db)
    request, _ = _file(db, tech, work_order, item, quantity="4")
    _restock(db, item)

    resolved = material_service.resolve_from_line(
        db,
        request_id=request.id,
        work_order_id=work_order.id,
        work_order_number=work_order.number,
        item_id=item.id,
        quantity=Decimal("3"),
        resolved_by_id=tech.id,
    )

    assert resolved.status == "resolved"
    assert resolved.resolution_note == f"Added to {work_order.number}."
    assert resolved.details["added_quantity"] == "3"


@pytest.mark.parametrize("wrong", ["status", "work_order", "item"])
def test_resolve_from_line_refuses_a_mismatch(db, wrong):
    tech = _user(db)
    work_order = _work_order(db, tech)
    item = _item(db)
    request, _ = _file(db, tech, work_order, item)
    if wrong != "status":
        _restock(db, item)
    wo_id = _work_order(db, tech).id if wrong == "work_order" else work_order.id
    item_id = _item(db).id if wrong == "item" else item.id

    with pytest.raises(ItemRequestStateError):
        material_service.resolve_from_line(
            db, request_id=request.id, work_order_id=wo_id,
            work_order_number=work_order.number, item_id=item_id,
            quantity=Decimal("1"), resolved_by_id=tech.id,
        )


def test_reopening_a_resolved_material_request_clears_the_stamps(db):
    tech = _user(db)
    staff = _user(db, "techfm_oa")
    item = _item(db)
    request, _ = _file(db, tech, _work_order(db, tech), item)
    _restock(db, item)
    request_service.update_user_request(
        db, request.id, status="resolved", resolution_note=None, resolved_by_id=staff.id
    )

    reopened = request_service.update_user_request(
        db, request.id, status="open", resolution_note=None, resolved_by_id=staff.id
    )

    assert reopened.status == "open"
    assert "stocked_at" not in reopened.details
    assert "stocked_by" not in reopened.details


# --------------------------------------------------------------------------
# Reads
# --------------------------------------------------------------------------

def test_list_for_work_order_returns_material_and_catalogue_rows_newest_first(db):
    tech = _user(db)
    work_order = _work_order(db, tech)
    material, _ = _file(db, tech, work_order, _item(db))
    catalogue = request_service.create_catalogue_request(
        db, searched_text="grommet", quantity=Decimal("1"), note=None,
        work_order_id=work_order.id, work_order_number=work_order.number,
        source="work_orders", created_by_id=tech.id,
    )
    db.flush()
    _file(db, tech, _work_order(db, tech), _item(db))  # other WO, excluded

    rows = material_service.list_for_work_order(db, work_order.id)

    assert [r.id for r in rows] == [catalogue.id, material.id]


def test_open_counts_groups_by_type_and_status(db):
    tech = _user(db)
    item = _item(db)
    a, _ = _file(db, tech, _work_order(db, tech), item)
    b, _ = _file(db, tech, _work_order(db, tech), item)
    baseline = material_service.open_counts(db)
    _restock(db, item)  # both to stocked

    counts = material_service.open_counts(db)

    mat_before = baseline.get("material_request", {})
    mat_after = counts["material_request"]
    assert mat_after.get("stocked", 0) - mat_before.get("stocked", 0) == 2
    assert mat_before.get("open", 0) - mat_after.get("open", 0) == 2


def test_stocked_requests_for_user_scope(db):
    tech = _user(db)
    other_tech = _user(db)
    supervisor = _user(db, "supervisor")
    staff = _user(db, "techfm_oa")
    item = _item(db)
    mine, _ = _file(db, tech, _work_order(db, other_tech, assigned_to=tech), item)
    routed, _ = _file(db, other_tech, _work_order(db, other_tech, supervisor=supervisor), item)
    filed, _ = _file(db, tech, _work_order(db, other_tech), item)
    theirs, _ = _file(db, other_tech, _work_order(db, other_tech, assigned_to=other_tech), item)
    _restock(db, item)
    still_open, _ = _file(db, tech, _work_order(db, other_tech, assigned_to=tech), _item(db))

    ids = lambda rows: {r.id for r in rows}
    assert ids(material_service.stocked_requests_for_user(db, tech)) == {mine.id, filed.id}
    assert ids(material_service.stocked_requests_for_user(db, supervisor)) == {routed.id}
    assert {mine.id, routed.id, filed.id, theirs.id} <= ids(
        material_service.stocked_requests_for_user(db, staff)
    )
    assert still_open.id not in ids(material_service.stocked_requests_for_user(db, staff))
```

- [x] **Step 2: Run to verify it fails**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_material_requests.py -q`
Expected: FAIL at import — `ImportError: cannot import name 'MaterialRequestOwnershipError'`.

- [x] **Step 3: Add the error and its status**

`backend/app/domain/errors.py`, after `ItemRequestStateError`:

```python
class MaterialRequestOwnershipError(DomainError):
    """Raised when someone other than the filer tries to cancel a Material
    Request. An authorization failure, not a state one, so it maps to 403
    like `RoleManagementError` rather than to the 409 of
    `ItemRequestStateError`."""
```

`backend/app/routers/_errors.py`: add `MaterialRequestOwnershipError,` to the import list and `MaterialRequestOwnershipError: 403,` to `_STATUS_MAP` beside `RoleManagementError`.

- [x] **Step 4: Write the service**

Create `backend/app/services/material_requests.py`:

```python
"""Material Requests: a catalogue item the shelf does not have.

Layer: services, and -- like `services/low_stock.py` -- deliberately the
thinnest kind. **This module imports only `app.models` and `app.domain`.**
Three stock-writing services (`transactions`, `mass_staging`,
`work_orders`) call `record_stock_change` from inside their transactions,
and `services.notifications` imports `work_orders`; one `from app.services
import ...` here would close that ring.

**The transition is atomic with the stock write.** `record_stock_change`
runs after the caller has mutated `item.quantity` under the item's
`FOR UPDATE` lock and before the caller's `db.commit()`. The request rows
move in the same transaction, so a rollback takes the transition with it
and the queue can never disagree with the count.

**Notifying is not this module's job.** It freezes everything a push will
need -- ids and strings, never ORM objects -- into a `StockedFact` on a
per-request ContextVar buffer, and `routers/_stock_events.py` drains it
after commit. Same invariant as the low-stock buffer: `record` before the
commit while the rows are loaded, `drain` only on the router's success path.
"""

import logging
import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload, selectinload

from app.domain import material_requests as policy
from app.domain import roles
from app.domain.errors import (
    ItemNotFoundError,
    ItemRequestStateError,
    MaterialRequestOwnershipError,
    UserRequestNotFoundError,
)
from app.models import Item, User, UserRequest, WorkOrder, WorkOrderTechnician

logger = logging.getLogger(__name__)

MESSAGE = "Please stock this item"
NOTE_CANCELLED = "Cancelled by requester"
NOTE_WORK_ORDER_CLOSED = "Work order was closed before the item was stocked."

ORIGIN_REQUEST_CARD = "request_card"
ORIGIN_CATALOGUE_FULFILMENT = "catalogue_fulfilment"

# Same ceiling and same reasoning as `low_stock.MAX_BUFFERED_CROSSINGS`.
MAX_BUFFERED_FACTS = 500

_LIVE_STATUSES = (policy.STATUS_OPEN, policy.STATUS_STOCKED)
_LISTED_TYPES = (policy.REQUEST_MATERIAL, "catalogue_request")


@dataclass(frozen=True)
class StockedFact:
    """One request that just became `stocked`, as plain values.

    The recipient *parts* are frozen separately (assignees, supervisor,
    requester) so the pure rule in `domain/notifications.py` does the
    dedup and the actor decision, and stays testable on its own.
    """

    request_id: uuid.UUID
    item_name: str
    work_order_id: Optional[uuid.UUID]
    work_order_number: str
    assignee_ids: tuple
    supervisor_id: Optional[uuid.UUID]
    requester_id: Optional[uuid.UUID]


_buffer: ContextVar[Optional[list]] = ContextVar("stocked_facts_buffer", default=None)


def _buffer_fact(fact: StockedFact) -> None:
    entries = _buffer.get()
    if entries is None:
        entries = []
        _buffer.set(entries)
    if len(entries) >= MAX_BUFFERED_FACTS:
        logger.warning(
            "material-request buffer full at %s entries; dropping further facts",
            MAX_BUFFERED_FACTS,
        )
        return
    entries.append(fact)


def drain() -> list:
    """Take every buffered fact and empty the buffer. Total by contract."""
    entries = _buffer.get()
    if not entries:
        return []
    taken = list(entries)
    entries.clear()
    return taken


# --- helpers ---------------------------------------------------------------


def lock_live_item(db: Session, item_id: uuid.UUID) -> Item:
    """The item row under `FOR UPDATE`, or `ItemNotFoundError`. Mirrors
    `services.work_orders._locked_live_item`, re-declared here rather than
    imported for the import-ring reason in the module docstring."""
    item = (
        db.query(Item)
        .filter(Item.id == item_id, Item.archived_at.is_(None))
        .with_for_update()
        .first()
    )
    if item is None:
        raise ItemNotFoundError("Item not found.")
    return item


def _assignee_ids(work_order: WorkOrder) -> tuple:
    """Plural assignments with the legacy singular folded in -- the same
    rule as `services.work_orders._assigned_technician_ids`, restated here
    for the import-ring reason."""
    assigned = [row.technician_id for row in (work_order.technician_assignments or ())]
    legacy = work_order.assigned_to_id
    if legacy is not None and legacy not in assigned:
        assigned.insert(0, legacy)
    return tuple(assigned)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _set_stocked(request: UserRequest, *, stocked_by: str) -> None:
    details = dict(request.details or {})
    details["stocked_at"] = _now_iso()
    details["stocked_by"] = stocked_by
    details["stock_cycles"] = int(details.get("stock_cycles") or 0) + 1
    request.details = details
    request.status = policy.STATUS_STOCKED


def clear_stocked_stamps(request: UserRequest) -> None:
    """Drop `stocked_at` / `stocked_by`; keep `stock_cycles` (history)."""
    details = dict(request.details or {})
    details.pop("stocked_at", None)
    details.pop("stocked_by", None)
    request.details = details


def _resolve(request: UserRequest, *, note: str, resolved_by_id: Optional[uuid.UUID]) -> None:
    request.status = policy.STATUS_RESOLVED
    request.resolved_at = datetime.now(timezone.utc)
    request.resolved_by_id = resolved_by_id
    request.resolution_note = note


def _locked(db: Session, request_id: uuid.UUID) -> UserRequest:
    request = (
        db.query(UserRequest)
        .filter(UserRequest.id == request_id)
        .with_for_update()
        .first()
    )
    if request is None:
        raise UserRequestNotFoundError("User request not found.")
    if request.request_type != policy.REQUEST_MATERIAL:
        raise ItemRequestStateError("This is not a material request.")
    return request


# --- filing ----------------------------------------------------------------


def create_or_update(
    db: Session,
    *,
    item_id: uuid.UUID,
    work_order: WorkOrder,
    quantity: Decimal,
    product_link: Optional[str],
    note: Optional[str],
    created_by_id: Optional[uuid.UUID],
    origin: str,
) -> tuple[UserRequest, bool]:
    """One live request per (work order, item). Returns `(request, created)`.

    A second filing overwrites quantity, link, and note rather than adding a
    row: the staff already know, and two rows would mean two Hub lines for
    one shelf. Pending objects are checked first because `SessionLocal`
    disables autoflush and a catalogue fulfilment can create several
    requests before its single commit (see `create_or_update_missing_price_request`).
    """
    def _matches(candidate) -> bool:
        return (
            isinstance(candidate, UserRequest)
            and candidate.request_type == policy.REQUEST_MATERIAL
            and candidate.status in _LIVE_STATUSES
            and candidate.item_id == item_id
            and candidate.work_order_id == work_order.id
        )

    request = next((c for c in db.new if _matches(c)), None)
    if request is None:
        request = (
            db.query(UserRequest)
            .filter(
                UserRequest.request_type == policy.REQUEST_MATERIAL,
                UserRequest.status.in_(_LIVE_STATUSES),
                UserRequest.item_id == item_id,
                UserRequest.work_order_id == work_order.id,
            )
            .first()
        )

    cleaned_note = (note or "").strip() or None
    cleaned_link = (product_link or "").strip() or None

    if request is None:
        request = UserRequest(
            request_type=policy.REQUEST_MATERIAL,
            status=policy.STATUS_OPEN,
            message=MESSAGE,
            item_id=item_id,
            work_order_id=work_order.id,
            created_by_id=created_by_id,
            details={
                "quantity": str(quantity),
                "product_link": cleaned_link,
                "note": cleaned_note,
                "work_order_number": work_order.number,
                "stock_cycles": 0,
                "origin": origin,
            },
        )
        db.add(request)
        return request, True

    details = dict(request.details or {})
    details["quantity"] = str(quantity)
    details["product_link"] = cleaned_link
    details["note"] = cleaned_note
    request.details = details
    return request, False


# --- the automatic edges ---------------------------------------------------


def _live_requests_for_item(db: Session, item_id: uuid.UUID, status: str) -> list[UserRequest]:
    return (
        db.query(UserRequest)
        .options(
            joinedload(UserRequest.work_order).selectinload(WorkOrder.technician_assignments)
        )
        .filter(
            UserRequest.request_type == policy.REQUEST_MATERIAL,
            UserRequest.status == status,
            UserRequest.item_id == item_id,
        )
        .all()
    )


def _stock_request(db: Session, request: UserRequest, item: Item, *, stocked_by: str) -> None:
    """`open -> stocked` for one request, buffering the fact -- or a quiet
    resolve when its work order is already closed."""
    work_order = request.work_order
    if work_order is None or work_order.archived_at is not None:
        _resolve(request, note=NOTE_WORK_ORDER_CLOSED, resolved_by_id=None)
        return
    _set_stocked(request, stocked_by=stocked_by)
    _buffer_fact(
        StockedFact(
            request_id=request.id,
            item_name=item.name,
            work_order_id=work_order.id,
            work_order_number=work_order.number,
            assignee_ids=_assignee_ids(work_order),
            supervisor_id=work_order.supervisor_id,
            requester_id=request.created_by_id,
        )
    )


def record_stock_change(db: Session, item: Item, *, quantity_before: Decimal) -> None:
    """Move this item's requests across whichever zero edge this write took.

    Call immediately after `low_stock.record(...)` at each stock-writing
    site, before the commit. No row lock of its own: every caller already
    holds the item row `FOR UPDATE`, which serialises stock writes per item,
    and `mark_stocked` locks the request row it touches.

    Neither edge: return after one comparison each -- the common case.
    """
    after = Decimal(item.quantity)
    if policy.restocked(quantity_before, after):
        for request in _live_requests_for_item(db, item.id, policy.STATUS_OPEN):
            _stock_request(db, request, item, stocked_by="auto")
    elif policy.went_out(quantity_before, after):
        for request in _live_requests_for_item(db, item.id, policy.STATUS_STOCKED):
            clear_stocked_stamps(request)
            request.status = policy.STATUS_OPEN


# --- staff and requester actions --------------------------------------------


def mark_stocked(db: Session, request_id: uuid.UUID, *, actor_id: uuid.UUID) -> UserRequest:
    """TechFM OA+ pressed "Mark stocked & notify". Allowed while `open` at any
    on-hand; 409 otherwise. Buffers the same fact the automatic edge would,
    so the router's `flush_stock_events` sends the same push."""
    request = _locked(db, request_id)
    if request.status == policy.STATUS_STOCKED:
        raise ItemRequestStateError("This material request is already stocked.")
    if request.status != policy.STATUS_OPEN:
        raise ItemRequestStateError("This material request is already resolved.")
    item = db.get(Item, request.item_id)
    if item is None:
        raise ItemNotFoundError("Item not found.")
    # Load the work order with assignments the same way the edge does.
    request = (
        db.query(UserRequest)
        .options(
            joinedload(UserRequest.work_order).selectinload(WorkOrder.technician_assignments)
        )
        .filter(UserRequest.id == request_id)
        .populate_existing()
        .one()
    )
    _stock_request(db, request, item, stocked_by=str(actor_id))
    return request


def cancel(db: Session, request_id: uuid.UUID, *, actor_id: uuid.UUID) -> UserRequest:
    """The filer withdraws their own open request. A stocked one has already
    cost staff work, so cancelling it is the page's job (409)."""
    request = _locked(db, request_id)
    if request.created_by_id != actor_id:
        raise MaterialRequestOwnershipError("Only the person who filed this request can cancel it.")
    if request.status != policy.STATUS_OPEN:
        raise ItemRequestStateError("Only an open material request can be cancelled.")
    _resolve(request, note=NOTE_CANCELLED, resolved_by_id=actor_id)
    return request


def resolve_from_line(
    db: Session,
    *,
    request_id: uuid.UUID,
    work_order_id: uuid.UUID,
    work_order_number: str,
    item_id: uuid.UUID,
    quantity: Decimal,
    resolved_by_id: Optional[uuid.UUID],
) -> UserRequest:
    """The crew tapped "Add requested material". Must be `stocked`, on this
    work order, for this item -- anything else is a stale button (409)."""
    request = _locked(db, request_id)
    if request.status != policy.STATUS_STOCKED:
        raise ItemRequestStateError("This material request is not waiting to be added.")
    if request.work_order_id != work_order_id or request.item_id != item_id:
        raise ItemRequestStateError("This material request belongs to a different work order or item.")
    details = dict(request.details or {})
    details["added_quantity"] = str(quantity)
    request.details = details
    _resolve(request, note=f"Added to {work_order_number}.", resolved_by_id=resolved_by_id)
    return request


# --- reads -------------------------------------------------------------------


def _with_context(query):
    return query.options(
        joinedload(UserRequest.item),
        joinedload(UserRequest.work_order),
        joinedload(UserRequest.creator),
        joinedload(UserRequest.resolver),
    )


def list_for_work_order(db: Session, work_order_id: uuid.UUID) -> list[UserRequest]:
    """Every material and catalogue request on one work order, newest first.
    Visibility is the caller's job (the route resolves the work order through
    the scoped reader first)."""
    return (
        _with_context(db.query(UserRequest))
        .filter(
            UserRequest.work_order_id == work_order_id,
            UserRequest.request_type.in_(_LISTED_TYPES),
        )
        .order_by(UserRequest.created_at.desc())
        .all()
    )


def open_counts(db: Session) -> dict[str, dict[str, int]]:
    """`{request_type: {"open": n, "stocked": n}}` for the tab labels."""
    from sqlalchemy import func

    rows = (
        db.query(UserRequest.request_type, UserRequest.status, func.count(UserRequest.id))
        .filter(UserRequest.status.in_(_LIVE_STATUSES))
        .group_by(UserRequest.request_type, UserRequest.status)
        .all()
    )
    counts: dict[str, dict[str, int]] = {}
    for request_type, status, n in rows:
        counts.setdefault(request_type, {})[status] = n
    return counts


def stocked_requests_for_user(db: Session, user: User) -> list[UserRequest]:
    """The Hub's "Requested material in stock" rows.

    Everyone: `stocked` requests whose work order they are assigned to,
    routed on, or which they filed. TechFM OA+: every `stocked` request.
    """
    query = _with_context(db.query(UserRequest)).filter(
        UserRequest.request_type == policy.REQUEST_MATERIAL,
        UserRequest.status == policy.STATUS_STOCKED,
    )
    if not roles.role_at_least(user.role, roles.ROLE_TECHFM_OA):
        assigned = (
            db.query(WorkOrderTechnician.work_order_id)
            .filter(WorkOrderTechnician.technician_id == user.id)
        )
        query = query.join(WorkOrder, WorkOrder.id == UserRequest.work_order_id).filter(
            or_(
                UserRequest.created_by_id == user.id,
                WorkOrder.supervisor_id == user.id,
                WorkOrder.assigned_to_id == user.id,
                WorkOrder.id.in_(assigned),
            )
        )
    return query.order_by(UserRequest.created_at.desc()).all()
```

- [x] **Step 5: Make reopen clear the stamps**

In `backend/app/services/user_requests.py::update_user_request`, in the `else:` branch (status back to `open`), add before `db.commit()`:

```python
        if request.request_type == REQUEST_MATERIAL:
            from app.services.material_requests import clear_stocked_stamps

            clear_stocked_stamps(request)
```

(Lazy import: `material_requests` imports domain + models only, so a module-level import would also be safe; the lazy form keeps this module's import block honest about what it needs at load.)

- [x] **Step 6: Run the tests**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_material_requests.py tests/test_material_requests_domain.py -q`
Expected: PASS. If `test_the_fact_reads_plural_assignments…` fails on a stale `technician_assignments` collection, add `db.expire(work_order, ["technician_assignments"])` before `_restock` in the test — the fixture session has autoflush off.

- [x] **Step 7: Commit**

```bash
git add backend/app/services/material_requests.py backend/app/services/user_requests.py backend/app/domain/errors.py backend/app/routers/_errors.py backend/tests/test_material_requests.py
git commit -m "add the material request service with in-transaction stock edges

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Rj5dKhZSJLx5wvJMfBTimY"
```

---

### Task 5: The two notifier functions

**Why now:** Step 2 of the trigger procedure. The flush in Task 6 calls `notify_material_request_stocked`; the filing route in Task 7 calls `notify_material_request_filed`. Both must resolve recipients inside the request (rule 4 in `adding-a-notification-trigger.md`).

**Files:**
- Modify: `backend/app/services/notifications.py` (append after `notify_item_low_stock`)
- Test: `backend/tests/test_notifications.py` (append)

**Interfaces:**
- Consumes: `policy.EVENT_MATERIAL_REQUEST_*`, `policy.MATERIAL_REQUEST_AUDIENCE_MIN_ROLE`, the two recipient rules (Task 3); `material_requests.StockedFact` (Task 4) — passed in, never imported (keeps `services.notifications` free of the new module).
- Produces: `notify_material_request_filed(db, background, *, item_name, work_order_number)`, `notify_material_request_stocked(db, background, *, facts: Sequence)`.

- [x] **Step 1: Write the failing tests**

Append to `backend/tests/test_notifications.py`:

```python
# --- material requests ---------------------------------------------------


def _fact(**overrides):
    from app.services.material_requests import StockedFact

    base = dict(
        request_id=uuid.uuid4(),
        item_name="3M Blue Tape",
        work_order_id=uuid.uuid4(),
        work_order_number="WO-77",
        assignee_ids=(),
        supervisor_id=None,
        requester_id=None,
    )
    base.update(overrides)
    return StockedFact(**base)


def test_a_filed_material_request_is_pushed_once_to_techfm_oa_and_above(db, configured):
    techfm = _seed_user(db, "techfm_oa")
    admin = _seed_user(db, "admin")
    supervisor = _seed_user(db, "supervisor")
    background = BackgroundTasks()

    notifications_service.notify_material_request_filed(
        db, background, item_name="3M Blue Tape", work_order_number="WO-77"
    )

    assert len(_scheduled(background)) == 1
    user_ids, title, body = _scheduled(background)[0]
    assert techfm.id in user_ids
    assert admin.id in user_ids
    assert supervisor.id not in user_ids
    assert title == "Material requested"
    assert body == "3M Blue Tape is needed for WO-77."


def test_a_stocked_fact_is_pushed_to_its_frozen_ids(db, configured):
    tech, supervisor, requester = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    background = BackgroundTasks()

    notifications_service.notify_material_request_stocked(
        db,
        background,
        facts=[_fact(assignee_ids=(tech,), supervisor_id=supervisor, requester_id=requester)],
    )

    assert len(_scheduled(background)) == 1
    user_ids, title, body = _scheduled(background)[0]
    assert user_ids == [tech, supervisor, requester]
    assert title == "Material in stock"
    assert body == "3M Blue Tape for WO-77 is now in stock."


def test_each_stocked_fact_schedules_its_own_push(db, configured):
    background = BackgroundTasks()
    notifications_service.notify_material_request_stocked(
        db,
        background,
        facts=[
            _fact(item_name="Tape", requester_id=uuid.uuid4()),
            _fact(item_name="Caulk", work_order_number="WO-78", requester_id=uuid.uuid4()),
        ],
    )
    bodies = [body for _ids, _title, body in _scheduled(background)]
    assert bodies == ["Tape for WO-77 is now in stock.", "Caulk for WO-78 is now in stock."]


def test_a_stocked_fact_with_nobody_to_tell_schedules_nothing(db, configured):
    background = BackgroundTasks()
    notifications_service.notify_material_request_stocked(db, background, facts=[_fact()])
    assert _scheduled(background) == []


def test_no_facts_schedules_nothing(db, configured):
    background = BackgroundTasks()
    notifications_service.notify_material_request_stocked(db, background, facts=[])
    assert _scheduled(background) == []
```

- [x] **Step 2: Run to verify it fails**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_notifications.py -q -k material`
Expected: FAIL — `AttributeError: … has no attribute 'notify_material_request_filed'`.

- [x] **Step 3: Write the two functions**

Append to `backend/app/services/notifications.py`:

```python
def notify_material_request_filed(
    db: Session,
    background: BackgroundTasks,
    *,
    item_name: str,
    work_order_number: str,
) -> None:
    """A crew member filed a Material Request -- tell TechFM OA and above.

    Called by the filing route for a *new* row only; a duplicate filing
    updates fields and re-pushes nobody. The actor is kept (state alarm,
    see the policy rule). Takes strings rather than the request row so the
    caller decides what is read while the session is alive.
    """
    recipients = policy.recipients_for_material_request_filed(
        recipient_ids=push_service.user_ids_for_min_role(
            db, policy.MATERIAL_REQUEST_AUDIENCE_MIN_ROLE
        ),
    )
    title, body = policy.build_message(
        policy.EVENT_MATERIAL_REQUEST_FILED, name=item_name, number=work_order_number
    )
    _schedule(background, recipients, title, body)


def notify_material_request_stocked(
    db: Session,
    background: BackgroundTasks,
    *,
    facts: Sequence,
) -> None:
    """Requested material is back on the shelf -- tell each request's crew.

    One push per fact, never a digest. `facts` are
    `services.material_requests.StockedFact`s: every id was frozen inside the
    stock write's transaction, so nothing here touches a session-bound row
    and nothing can detach in the background task. `db` is accepted for
    signature symmetry with the other notifiers and is not read.
    """
    for fact in facts:
        recipients = policy.recipients_for_material_request_stocked(
            assignee_ids=fact.assignee_ids,
            supervisor_id=fact.supervisor_id,
            requester_id=fact.requester_id,
        )
        if not recipients:
            continue
        title, body = policy.build_message(
            policy.EVENT_MATERIAL_REQUEST_STOCKED,
            name=fact.item_name,
            number=fact.work_order_number,
        )
        _schedule(background, recipients, title, body)
```

- [x] **Step 4: Run the tests**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_notifications.py -q`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add backend/app/services/notifications.py backend/tests/test_notifications.py
git commit -m "add the filed and stocked material request notifiers

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Rj5dKhZSJLx5wvJMfBTimY"
```

---

### Task 6: `_stock_events.py` — one flush, two buffers, eight sites

**Why now:** the callee (Task 4) and the notifier (Task 5) exist, so this is pure wiring plus the rename. All eight sites land in one commit because a partially-wired shelf is worse than an unwired one. The registry (`docs/notification-events.md`) is updated in this same commit, as its header requires.

**Files:**
- `git mv backend/app/routers/_low_stock.py backend/app/routers/_stock_events.py`, then modify
- Modify: `backend/app/routers/items.py:27,256`, `mass_stages.py:26,389,413`, `transactions.py:27,96,126,182`, `work_orders.py:52,1173,1193,1245`
- Modify: `backend/app/services/transactions.py:133,229,367`, `mass_staging.py:500,558`, `work_orders.py:2899,2957,3035` + the `from app.services import low_stock` import lines
- Modify: `backend/tests/test_low_stock_triggers.py:149-204,405-420`, `backend/tests/test_items_low_stock.py:421,454`
- Create: `backend/tests/test_stock_events_flush.py`
- Modify: `docs/notification-events.md` (Part 1 both tables, Part 2 table, trigger-site layer table)

**Interfaces:**
- Produces: `routers._stock_events.flush_stock_events(db, background)`, `routers._stock_events.emit_low_stock_changed(item_id)` (unchanged), `routers._stock_events.emit_user_request_changed(request_id)`. Each of the eight sites calls `material_requests.record_stock_change(item, quantity_before=quantity_before)` on the line after `low_stock.record(...)`.

- [x] **Step 1: Write the failing flush tests**

Create `backend/tests/test_stock_events_flush.py`:

```python
"""One flush, two buffers.

The low-stock crossing buffer and the material-request fact buffer are
drained by the same router helper on every stock route's success path.
What matters: both drain on one call, and a raise in either branch costs
that branch's push -- never the other's, never the committed write.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks

from app.domain import realtime as realtime_policy
from app.routers import _stock_events
from app.services import low_stock as low_stock_service
from app.services import material_requests as material_service
from app.services import push as push_service


@pytest.fixture(autouse=True)
def _clean():
    low_stock_service.drain()
    material_service.drain()
    yield
    low_stock_service.drain()
    material_service.drain()


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(push_service, "VAPID_PRIVATE_KEY", "test-private-key")


def _capture_emits(monkeypatch):
    envelopes = []
    monkeypatch.setattr(
        _stock_events.realtime_service, "emit", lambda envelope: envelopes.append(envelope)
    )
    return envelopes


def _low_item():
    return SimpleNamespace(id=uuid.uuid4(), name="Tape", quantity=Decimal("5"), low_stock_threshold=6)


def _fact():
    return material_service.StockedFact(
        request_id=uuid.uuid4(), item_name="Tape", work_order_id=uuid.uuid4(),
        work_order_number="WO-1", assignee_ids=(uuid.uuid4(),), supervisor_id=None,
        requester_id=None,
    )


def test_one_flush_drains_both_buffers(db, configured, monkeypatch):
    envelopes = _capture_emits(monkeypatch)
    low_stock_service.record(_low_item(), quantity_before=Decimal("7"))
    fact = _fact()
    material_service._buffer_fact(fact)
    background = BackgroundTasks()

    _stock_events.flush_stock_events(db, background)

    titles = sorted(task.args[1] for task in background.tasks)
    assert titles == ["Low stock", "Material in stock"]
    types = sorted(e["type"] for e in envelopes)
    assert types == [
        realtime_policy.EVENT_ITEM_LOW_STOCK_CHANGED,
        realtime_policy.EVENT_USER_REQUEST_CHANGED,
    ]
    assert any(e["id"] == str(fact.request_id) for e in envelopes)
    assert low_stock_service.drain() == []
    assert material_service.drain() == []


def test_a_low_stock_failure_does_not_lose_the_stocked_push(db, configured, monkeypatch):
    _capture_emits(monkeypatch)

    def boom(*args, **kwargs):
        raise RuntimeError("low stock exploded")

    monkeypatch.setattr(_stock_events.notifications_service, "notify_item_low_stock", boom)
    low_stock_service.record(_low_item(), quantity_before=Decimal("7"))
    material_service._buffer_fact(_fact())
    background = BackgroundTasks()

    _stock_events.flush_stock_events(db, background)  # must not raise

    assert [task.args[1] for task in background.tasks] == ["Material in stock"]


def test_a_stocked_failure_does_not_lose_the_low_stock_push(db, configured, monkeypatch):
    _capture_emits(monkeypatch)

    def boom(*args, **kwargs):
        raise RuntimeError("stocked exploded")

    monkeypatch.setattr(
        _stock_events.notifications_service, "notify_material_request_stocked", boom
    )
    low_stock_service.record(_low_item(), quantity_before=Decimal("7"))
    material_service._buffer_fact(_fact())
    background = BackgroundTasks()

    _stock_events.flush_stock_events(db, background)  # must not raise

    assert [task.args[1] for task in background.tasks] == ["Low stock"]


def test_an_empty_flush_does_nothing(db, configured, monkeypatch):
    envelopes = _capture_emits(monkeypatch)
    background = BackgroundTasks()
    _stock_events.flush_stock_events(db, background)
    assert background.tasks == []
    assert envelopes == []


def test_every_stock_route_still_calls_the_renamed_flush():
    """The seven stock routes and the threshold route each call the helper
    exactly where they called `flush_low_stock`. A grep, not an import: the
    thing that breaks is a route forgetting the call, and that is textual."""
    from pathlib import Path

    routers = Path(__file__).resolve().parents[1] / "app" / "routers"
    counts = {
        name: (routers / name).read_text(encoding="utf-8").count("flush_stock_events(db, background)")
        for name in ("transactions.py", "mass_stages.py", "work_orders.py", "items.py")
    }
    assert counts == {"transactions.py": 3, "mass_stages.py": 2, "work_orders.py": 3, "items.py": 1}
    for name in ("transactions.py", "mass_stages.py", "work_orders.py", "items.py"):
        assert "flush_low_stock" not in (routers / name).read_text(encoding="utf-8")
```

Also extend `backend/tests/test_low_stock_triggers.py::test_every_item_quantity_mutation_has_a_recorder`: add a third counter

```python
    stock_changes = 0
    ...
        stock_changes += source.count("material_requests.record_stock_change(")
    ...
    assert records == 8
    # The material-request recorder rides beside every low-stock recorder.
    assert stock_changes == 8
```

and replace the four `from app.routers import _low_stock` / `_low_stock.flush_low_stock` / `_low_stock.realtime_service` / `_low_stock.notifications_service` references in that file and the two in `test_items_low_stock.py` with `_stock_events` / `flush_stock_events`.

- [x] **Step 2: Run to verify failure**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_stock_events_flush.py tests/test_low_stock_triggers.py -q`
Expected: FAIL — `ImportError: cannot import name '_stock_events'` and the recorder-count assertion `0 == 8`.

- [x] **Step 3: Rename and extend the flush helper**

`git mv backend/app/routers/_low_stock.py backend/app/routers/_stock_events.py`. Rewrite the module as:

```python
"""The one call every stock-writing route makes after its commit.

Layer: routers (shared helper), alongside `_errors.py` and `_uploads.py`.
It exists so the three routers that move stock -- transactions, mass
stages, work orders -- each add exactly one line instead of several, and so
the swallow-and-log contract is written once.

Two buffers drain here, filled by two thin services that import nothing
from `app.services`: `services.low_stock` (crossings of an item's
threshold) and `services.material_requests` (requests that just became
`stocked`). Each branch has its own try/except so a failure in one costs
that branch's push and never the other's.

Why the drain lives here rather than in a service: emitting realtime
invalidations from the router is the convention this repo already follows
(`routers/work_orders.py::_emit_status_changed`), and pulling
`services.realtime` into a service that `services.notifications` imports
would close an import ring.
"""

import logging
import uuid
from typing import Optional

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from app.domain import realtime as realtime_policy
from app.logging_config import current_request_id
from app.services import low_stock as low_stock_service
from app.services import material_requests as material_requests_service
from app.services import notifications as notifications_service
from app.services import realtime as realtime_service

logger = logging.getLogger(__name__)


def emit_low_stock_changed(item_id: Optional[uuid.UUID]) -> None:
    """Invalidate the Low Stock page for one item. Best-effort by contract."""
    realtime_service.emit(
        realtime_policy.build_envelope(
            event_type=realtime_policy.EVENT_ITEM_LOW_STOCK_CHANGED,
            entity_id=item_id,
            request_id=current_request_id(),
        )
    )


def emit_user_request_changed(request_id: Optional[uuid.UUID]) -> None:
    """Tell every connected client one User Request moved. Subscribers -- the
    Hub dashboard, the User Requests page, an open work-order card -- refetch
    through REST, which re-applies visibility. Best-effort by contract."""
    realtime_service.emit(
        realtime_policy.build_envelope(
            event_type=realtime_policy.EVENT_USER_REQUEST_CHANGED,
            entity_id=request_id,
            request_id=current_request_id(),
        )
    )


def flush_stock_events(db: Session, background: BackgroundTasks) -> None:
    """Drain this request's crossings and stocked facts, push what should be
    pushed, and invalidate what changed.

    Call once, on the success path, after the service returned -- the
    durable write has committed by then, which is what makes swallowing
    correct rather than lazy. A failure here costs a notification; raising
    would cost the user a save that actually succeeded.
    """
    try:
        crossings = low_stock_service.drain()
        if crossings:
            notifications_service.notify_item_low_stock(db, background, crossings=crossings)
            for crossing in crossings:
                emit_low_stock_changed(crossing.item_id)
    except Exception:  # noqa: BLE001 - best-effort by contract
        logger.exception("low-stock notification failed")

    try:
        facts = material_requests_service.drain()
        if facts:
            notifications_service.notify_material_request_stocked(db, background, facts=facts)
            for fact in facts:
                emit_user_request_changed(fact.request_id)
    except Exception:  # noqa: BLE001 - best-effort by contract
        logger.exception("material-request stocked notification failed")
```

- [x] **Step 4: Repoint the four routers**

- `backend/app/routers/items.py:27` → `from app.routers._stock_events import emit_low_stock_changed, flush_stock_events`; line 256 → `flush_stock_events(db, background)`.
- `backend/app/routers/mass_stages.py:26` → `from app.routers._stock_events import flush_stock_events`; lines 389, 413.
- `backend/app/routers/transactions.py:27`; lines 96, 126, 182.
- `backend/app/routers/work_orders.py:52`; lines 1173, 1193, 1245.

- [x] **Step 5: Wire the eight sites**

In each service add `from app.services import material_requests` beside `from app.services import low_stock`, then on the line after every `low_stock.record(item, quantity_before=quantity_before)`:

```python
    material_requests.record_stock_change(db, item, quantity_before=quantity_before)
```

Sites: `services/transactions.py` — `apply_transaction` (~133), `void_transaction` inside the `if txn.affects_stock:` branch (~229), `apply_correction` (~367). `services/mass_staging.py` — `load_item` (~500, after the allocation loop, before `db.commit()` inside the `try`), `return_item` (~558). `services/work_orders.py` — `add_work_order_item` (~2899), `update_work_order_item` (~2957), `delete_work_order_item` (~3035).

Why the same line and not a wrapper: `test_every_item_quantity_mutation_has_a_recorder` counts textual calls per service, so a ninth stock site that forgets either recorder fails loudly.

- [x] **Step 6: Run the tests**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_stock_events_flush.py tests/test_low_stock_triggers.py tests/test_items_low_stock.py tests/test_material_requests.py -q`
Expected: PASS.
Run: `grep -rn "_low_stock\b\|flush_low_stock" backend/app backend/tests` — Expected: no output.

- [x] **Step 7: Prove the edge end to end on each write kind**

Append to `backend/tests/test_material_requests.py` (uses that file's helpers):

```python
# --------------------------------------------------------------------------
# The eight sites, through the real services
# --------------------------------------------------------------------------

def _stocked_after(db, request, fn):
    material_service.drain()
    fn()
    db.refresh(request)
    return request.status, material_service.drain()


def test_add_stock_stocks_the_request(db):
    from app.services import transactions as txn_service

    supervisor = _user(db, "supervisor")
    item = _item(db, quantity="0")
    request, _ = _file(db, supervisor, _work_order(db, supervisor), item)
    db.commit()

    status, facts = _stocked_after(
        db, request,
        lambda: txn_service.apply_transaction(
            db, item_id=item.id, transaction_type="stock", quantity=Decimal("6"),
            user_id=supervisor.id, work_order_number=None,
        ),
    )
    assert status == "stocked"
    assert len(facts) == 1


def test_an_upward_correction_stocks_the_request(db):
    from app.services import transactions as txn_service

    staff = _user(db, "techfm_oa")
    item = _item(db, quantity="-2")
    request, _ = _file(db, staff, _work_order(db, staff), item)
    db.commit()

    status, facts = _stocked_after(
        db, request,
        lambda: txn_service.apply_correction(
            db, item_id=item.id, new_quantity=Decimal("4"), reason="Recount", user_id=staff.id
        ),
    )
    assert status == "stocked"
    assert len(facts) == 1


def test_voiding_the_dispense_that_emptied_the_shelf_stocks_the_request(db):
    from app.services import transactions as txn_service

    supervisor = _user(db, "supervisor")
    item = _item(db, quantity="2")
    txn = txn_service.apply_transaction(
        db, item_id=item.id, transaction_type="dispense", quantity=Decimal("2"),
        user_id=supervisor.id, work_order_number=None,
    )
    request, _ = _file(db, supervisor, _work_order(db, supervisor), item)
    db.commit()

    status, facts = _stocked_after(
        db, request,
        lambda: txn_service.void_transaction(
            db, transaction_id=txn.id, user_id=supervisor.id, user_role="supervisor"
        ),
    )
    assert status == "stocked"
    assert len(facts) == 1


def test_a_mass_stage_return_stocks_the_request(db):
    from app.services.mass_staging import (
        add_item, add_work_order_to_stage, create_stage, load_item, return_item, update_stage,
    )

    supervisor = _user(db, "supervisor")
    item = _item(db, quantity="5")
    stage = create_stage(db, community="Scholars", building_name=f"B-{uuid.uuid4().hex[:6]}", created_by_id=None)
    number = f"WO-MS-{uuid.uuid4().hex[:8]}"
    wos.get_or_create_work_order(db, number=number, created_by_id=supervisor.id)
    slot = add_work_order_to_stage(db, stage.id, work_order_number=number)
    add_item(db, stage.id, slot.id, item_id=item.id, planned_quantity=Decimal("5"))
    update_stage(db, stage.id, status="loading")
    load_item(db, stage.id, item_id=item.id, quantity=Decimal("5"), user_id=supervisor.id)
    request, _ = _file(db, supervisor, _work_order(db, supervisor), item)
    db.commit()

    status, facts = _stocked_after(
        db, request,
        lambda: return_item(db, stage.id, item_id=item.id, quantity=Decimal("2")),
    )
    assert status == "stocked"
    assert len(facts) == 1


def test_removing_a_work_order_line_stocks_the_request(db):
    supervisor = _user(db, "supervisor")
    item = _item(db, quantity="3")
    consuming = _work_order(db, supervisor)
    line = wos.add_work_order_item(db, consuming.id, user=supervisor, item_id=item.id, quantity=Decimal("3"))
    request, _ = _file(db, supervisor, _work_order(db, supervisor), item)
    db.commit()

    status, facts = _stocked_after(
        db, request,
        lambda: wos.delete_work_order_item(db, consuming.id, line.id, user=supervisor),
    )
    assert status == "stocked"
    assert len(facts) == 1


def test_a_dispense_that_empties_the_shelf_sends_a_stocked_request_back_to_open(db):
    supervisor = _user(db, "supervisor")
    item = _item(db, quantity="0")
    request, _ = _file(db, supervisor, _work_order(db, supervisor), item)
    from app.services import transactions as txn_service
    txn_service.apply_transaction(
        db, item_id=item.id, transaction_type="stock", quantity=Decimal("2"),
        user_id=supervisor.id, work_order_number=None,
    )
    material_service.drain()
    consuming = _work_order(db, supervisor)

    status, facts = _stocked_after(
        db, request,
        lambda: wos.add_work_order_item(db, consuming.id, user=supervisor, item_id=item.id, quantity=Decimal("2")),
    )
    assert status == "open"
    assert facts == []
```

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_material_requests.py -q` — Expected: PASS.

- [x] **Step 8: Register both events**

In `docs/notification-events.md`:

Layer table (line ~22): `Trigger sites` cell → add `backend/app/routers/_stock_events.py`, `backend/app/routers/user_requests.py`.

*Who is told* table, after the `item.low_stock` row:

```
| `material_request.filed` | any user who can see the work order (Technician+) | `POST /user-requests/material-request`, **new rows only** — a duplicate filing updates fields and pushes nobody | everyone at `MATERIAL_REQUEST_AUDIENCE_MIN_ROLE` (**TechFM OA** and above), **including the actor** |
| `material_request.stocked` | any stock write, or a TechFM OA+ pressing **Mark stocked & notify** | the eight stock-writing sites drained by `flush_stock_events` (same routes as `item.low_stock`, minus the threshold route); `POST /user-requests/{id}/mark-stocked` | the work order's assigned technicians + routed supervisor **at stocking time** + the original filer, **actor not suppressed** |
```

Below the `item.low_stock` actor paragraph add: "`material_request.filed` and `material_request.stocked` keep the actor for the same reason: both are state alarms. The filer wants confirmation the request went up the chain; a supervisor who restocks and is also on the crew is exactly who should see the line is ready."

*What each one says* table:

```
| `material_request.filed` | Material requested | `{name}` is needed for `{number}`. |
| `material_request.stocked` | Material in stock | `{name}` for `{number}` is now in stock. |
```

and amend the `name` / `quantity` paragraph: "The two material-request events use `name` and `number` together — still a catalogue string plus an opaque identifier."

Part 2 table:

```
| `user_request.changed` | any caller authorized for the write | filing, `mark-stocked`, `cancel`, `PATCH /user-requests/{id}`, every stock write that stocks or un-stocks a request, adding from a stocked Materials line, catalogue fulfilment | connected clients at **Technician** and above |
```

- [x] **Step 9: Full suite, then commit**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest -q`
Expected: PASS except the two known failures.

```bash
git add -A backend/app/routers backend/app/services backend/tests docs/notification-events.md
git commit -m "stock material requests from every stock write through one flush

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Rj5dKhZSJLx5wvJMfBTimY"
```

---

### Task 7: User Requests routes — file, mark stocked, cancel, counts, list filters

**Why now:** Step 3 of the trigger procedure for the filed event, plus the staff side of the manual fire. The service functions exist; each handler is a few lines of translation. Filing is tested over real HTTP because the visibility gate (`get_visible_work_order`) and Pydantic's 422s only exist on that path.

**Files:**
- Modify: `backend/app/schemas/user_requests.py` (add `MaterialRequestCreate`; `UserRequestResponse` + `item_quantity`, `updated`)
- Modify: `backend/app/routers/user_requests.py` (imports; `_response` → `build_response`; list params; five new/changed handlers)
- Modify: `backend/app/services/user_requests.py::list_user_requests` (add `request_type` filter)
- Modify: `backend/app/services/work_orders.py` after `_get_visible` (public reader)
- Test: `backend/tests/test_material_requests.py` (append HTTP tests), `backend/tests/test_route_role_gates.py` (append)

**Interfaces:**
- Produces: `POST /user-requests/material-request` (201, `MaterialRequestCreate` → `UserRequestResponse` with `item_quantity`, `updated`); `POST /user-requests/{id}/mark-stocked` (TechFM OA+); `POST /user-requests/{id}/cancel` (any session, filer only); `GET /user-requests/counts` (TechFM OA+, `dict[str, dict[str, int]]`); `GET /user-requests/?status=open|stocked|resolved&type=…`; `wo_service.get_visible_work_order(db, work_order_id, user)`; `routers.user_requests.build_response(request, *, skipped=None, item_quantity=None, updated=False)`.

- [x] **Step 1: Write the failing tests**

Append to `backend/tests/test_route_role_gates.py`:

```python
@pytest.mark.parametrize(
    "endpoint_name", ["mark_request_stocked", "list_request_counts"]
)
def test_new_staff_request_routes_require_techfm_oa(endpoint_name):
    assert _min_role_for(user_requests_router, endpoint_name) == roles.ROLE_TECHFM_OA
    assert 403 in _route(user_requests_router, endpoint_name).responses


@pytest.mark.parametrize(
    "endpoint_name", ["create_material_request", "cancel_material_request"]
)
def test_filing_and_cancelling_a_material_request_have_no_static_min_role(endpoint_name):
    # Gated by what the caller can see (the visible-work-order reader) and by
    # ownership (the filer), both decided inside the service -- same shape as
    # the catalogue-request filing route.
    assert _min_role_for(user_requests_router, endpoint_name) is None
```

Append to `backend/tests/test_material_requests.py`:

```python
# --------------------------------------------------------------------------
# Over real HTTP
# --------------------------------------------------------------------------

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.services import push as push_service


def _client(db):
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def _as(db, user):
    return auth.create_session(db, user)


def _post(db, user, path, json=None):
    token = _as(db, user)
    try:
        with _client(db) as client:
            client.cookies.set("session", token)
            return client.post(path, json=json or {})
    finally:
        del app.dependency_overrides[get_db]


def _get(db, user, path):
    token = _as(db, user)
    try:
        with _client(db) as client:
            client.cookies.set("session", token)
            return client.get(path)
    finally:
        del app.dependency_overrides[get_db]


def test_filing_over_http_returns_the_on_hand_and_pushes_once(db, monkeypatch):
    monkeypatch.setattr(push_service, "VAPID_PRIVATE_KEY", "test-private-key")
    sent = []
    monkeypatch.setattr(
        push_service, "send_to_users",
        lambda session, ids, title, body: sent.append((title, body)) or {"sent": 1, "dropped": 0, "failed": 0},
    )
    _user(db, "techfm_oa")
    tech = _user(db)
    work_order = _work_order(db, tech, assigned_to=tech)
    item = _item(db, quantity="3")
    db.commit()

    response = _post(db, tech, "/user-requests/material-request", {
        "item_id": str(item.id), "work_order_id": str(work_order.id),
        "quantity": "2", "product_link": "https://shop.example/x", "note": "blue",
    })

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["request_type"] == "material_request"
    assert body["status"] == "open"
    assert body["item_quantity"] == "3"
    assert body["updated"] is False
    assert body["work_order_number"] == work_order.number
    assert sent == [("Material requested", f"{item.name} is needed for {work_order.number}.")]


def test_a_duplicate_filing_over_http_says_updated_and_pushes_nobody(db, monkeypatch):
    monkeypatch.setattr(push_service, "VAPID_PRIVATE_KEY", "test-private-key")
    sent = []
    monkeypatch.setattr(
        push_service, "send_to_users",
        lambda session, ids, title, body: sent.append(title) or {"sent": 1, "dropped": 0, "failed": 0},
    )
    _user(db, "techfm_oa")
    tech = _user(db)
    work_order = _work_order(db, tech, assigned_to=tech)
    item = _item(db)
    db.commit()
    payload = {"item_id": str(item.id), "work_order_id": str(work_order.id), "quantity": "1"}
    first = _post(db, tech, "/user-requests/material-request", payload)
    sent.clear()

    second = _post(db, tech, "/user-requests/material-request", {**payload, "quantity": "5"})

    assert second.status_code == 201
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["updated"] is True
    assert second.json()["details"]["quantity"] == "5"
    assert sent == []


def test_a_technician_cannot_file_against_a_work_order_they_are_not_on(db):
    tech = _user(db)
    other = _user(db)
    work_order = _work_order(db, other, assigned_to=other)
    item = _item(db)
    db.commit()

    response = _post(db, tech, "/user-requests/material-request", {
        "item_id": str(item.id), "work_order_id": str(work_order.id), "quantity": "1",
    })

    assert response.status_code == 404
    assert response.json()["detail"] == "Work order not found."
    assert work_order.number not in response.text
    assert db.query(UserRequest).filter(UserRequest.item_id == item.id).count() == 0


def test_filing_against_an_archived_work_order_is_404(db):
    tech = _user(db)
    work_order = _work_order(db, tech, assigned_to=tech)
    work_order.archived_at = datetime.now(timezone.utc)
    item = _item(db)
    db.commit()
    response = _post(db, tech, "/user-requests/material-request", {
        "item_id": str(item.id), "work_order_id": str(work_order.id), "quantity": "1",
    })
    assert response.status_code == 404


def test_filing_an_unknown_item_is_404(db):
    tech = _user(db)
    work_order = _work_order(db, tech, assigned_to=tech)
    db.commit()
    response = _post(db, tech, "/user-requests/material-request", {
        "item_id": str(uuid.uuid4()), "work_order_id": str(work_order.id), "quantity": "1",
    })
    assert response.status_code == 404
    assert response.json()["detail"] == "Item not found."


@pytest.mark.parametrize(
    "bad",
    [
        {"quantity": "0"},
        {"quantity": "-1"},
        {"product_link": "ftp://nope"},
        {"product_link": "shop.example"},
        {"note": "x" * 501},
    ],
)
def test_bad_filing_bodies_are_422(db, bad):
    tech = _user(db)
    work_order = _work_order(db, tech, assigned_to=tech)
    item = _item(db)
    db.commit()
    payload = {"item_id": str(item.id), "work_order_id": str(work_order.id), "quantity": "1", **bad}
    assert _post(db, tech, "/user-requests/material-request", payload).status_code == 422


def test_mark_stocked_over_http_pushes_the_crew(db, monkeypatch):
    monkeypatch.setattr(push_service, "VAPID_PRIVATE_KEY", "test-private-key")
    sent = []
    monkeypatch.setattr(
        push_service, "send_to_users",
        lambda session, ids, title, body: sent.append((list(ids), title)) or {"sent": 1, "dropped": 0, "failed": 0},
    )
    staff = _user(db, "techfm_oa")
    tech = _user(db)
    item = _item(db, quantity="0")
    request, _ = _file(db, tech, _work_order(db, tech, assigned_to=tech), item)
    db.commit()

    response = _post(db, staff, f"/user-requests/{request.id}/mark-stocked")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "stocked"
    assert sent == [([tech.id], "Material in stock")]
    again = _post(db, staff, f"/user-requests/{request.id}/mark-stocked")
    assert again.status_code == 409


def test_cancel_over_http_is_filer_only(db):
    tech = _user(db)
    other = _user(db)
    request, _ = _file(db, tech, _work_order(db, tech, assigned_to=tech), _item(db))
    db.commit()

    assert _post(db, other, f"/user-requests/{request.id}/cancel").status_code == 403
    mine = _post(db, tech, f"/user-requests/{request.id}/cancel")
    assert mine.status_code == 200
    assert mine.json()["resolution_note"] == "Cancelled by requester"
    assert _post(db, tech, f"/user-requests/{request.id}/cancel").status_code == 409


def test_list_filters_by_type_and_accepts_stocked(db):
    staff = _user(db, "techfm_oa")
    tech = _user(db)
    item = _item(db)
    request, _ = _file(db, tech, _work_order(db, tech), item)
    _restock(db, item)
    material_service.drain()
    db.commit()

    stocked = _get(db, staff, "/user-requests/?status=stocked&type=material_request")
    assert stocked.status_code == 200
    assert request.id.__str__() in {row["id"] for row in stocked.json()}
    assert all(row["request_type"] == "material_request" for row in stocked.json())

    other_type = _get(db, staff, "/user-requests/?status=stocked&type=inventory_recount")
    assert other_type.status_code == 200
    assert other_type.json() == []

    assert _get(db, staff, "/user-requests/?status=stocked&type=bogus").status_code == 422


def test_counts_over_http_group_open_and_stocked(db):
    staff = _user(db, "techfm_oa")
    tech = _user(db)
    item = _item(db)
    _file(db, tech, _work_order(db, tech), item)
    db.commit()

    response = _get(db, staff, "/user-requests/counts")

    assert response.status_code == 200, response.text
    assert response.json()["material_request"]["open"] >= 1


def test_patch_to_stocked_is_422(db):
    staff = _user(db, "techfm_oa")
    tech = _user(db)
    request, _ = _file(db, tech, _work_order(db, tech), _item(db))
    db.commit()
    token = _as(db, staff)
    try:
        with _client(db) as client:
            client.cookies.set("session", token)
            response = client.patch(f"/user-requests/{request.id}", json={"status": "stocked"})
    finally:
        del app.dependency_overrides[get_db]
    assert response.status_code == 422
```

- [x] **Step 2: Run to verify failure**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_material_requests.py tests/test_route_role_gates.py -q -k "http or counts or stocked or cancel or material"`
Expected: FAIL — 404s on unknown routes, `route 'mark_request_stocked' not found`.

- [x] **Step 3: Schemas**

In `backend/app/schemas/user_requests.py` add after `CatalogueRequestCreate`:

```python
class MaterialRequestCreate(BaseModel):
    """File a request for a catalogue item the shelf does not have.

    The item exists (`item_id` is required); a search that found nothing is a
    `CatalogueRequestCreate`. On-hand is never checked here -- counts are
    sometimes wrong, so a request on an item with alleged stock still files
    and the staff verify.
    """

    item_id: UUID
    work_order_id: UUID
    quantity: Decimal = Field(default=Decimal("1"), gt=0)
    product_link: Optional[str] = Field(default=None, max_length=2000)
    note: Optional[str] = Field(default=None, max_length=500)

    @field_validator("product_link", "note")
    @classmethod
    def _trim(cls, value):
        if value is None:
            return None
        return value.strip() or None

    @field_validator("product_link")
    @classmethod
    def _http_only(cls, value):
        if value is None:
            return None
        if not (value.startswith("http://") or value.startswith("https://")):
            raise ValueError("Product link must start with http:// or https://.")
        return value
```

Extend `UserRequestResponse` (after `item_product_link`):

```python
    # The item's on-hand right now. Lets the card say "3 on hand -- staff will
    # verify" and the Materials line say "on hand 4". None for a catalogue
    # request that has not been linked to an item yet.
    item_quantity: Optional[Decimal] = None
```

and at the end (after `skipped`):

```python
    # True when a material-request filing matched an existing open/stocked
    # request for the same (work order, item) and updated it instead.
    updated: bool = False
```

- [x] **Step 4: Public visible reader in the work-orders service**

In `backend/app/services/work_orders.py`, directly after `_get_visible`:

```python
def get_visible_work_order(
    db: Session, work_order_id: uuid.UUID, user: Optional[User]
) -> WorkOrder:
    """Public reader for `_get_visible`. Filing a material request from
    another router needs the same "not found rather than 403" scoping the
    Work Orders page applies, and reaching for the private helper from
    another module would make that rule someone else's problem to remember."""
    return _get_visible(db, work_order_id, user)
```

- [x] **Step 5: List filter in the queue service**

`backend/app/services/user_requests.py::list_user_requests` gains a `request_type: Optional[str] = None` keyword and, after the status filter:

```python
    if request_type is not None:
        query = query.filter(UserRequest.request_type == request_type)
```

- [x] **Step 6: Router**

In `backend/app/routers/user_requests.py`:

Imports: add `BackgroundTasks` to the fastapi import; `from decimal import Decimal`; `from app.routers._stock_events import emit_user_request_changed, flush_stock_events`; `from app.schemas.user_requests import (CatalogueRequestCreate, CatalogueRequestFulfill, MaterialRequestCreate, UserRequestResponse, UserRequestUpdate)`; `from app.services import material_requests as material_service`; `from app.services import notifications as notifications_service`; `from app.services import work_orders as wo_service`.

Rename `_response` → `build_response` with two extra keywords, keep the alias:

```python
def build_response(
    request: UserRequest,
    *,
    skipped: Optional[list[str]] = None,
    item_quantity: Optional[Decimal] = None,
    updated: bool = False,
) -> UserRequestResponse:
    fallback_number = (request.details or {}).get("work_order_number")
    on_hand = item_quantity if item_quantity is not None else (
        request.item.quantity if request.item else None
    )
    return UserRequestResponse(
        ...existing fields...,
        item_quantity=on_hand,
        skipped=skipped or [],
        updated=updated,
    )


_response = build_response
```

List route:

```python
_LIST_STATUSES = ("open", "stocked", "resolved")
_LIST_TYPES = (
    request_service.REQUEST_MATERIAL,
    request_service.REQUEST_CATALOGUE,
    request_service.REQUEST_INVENTORY_RECOUNT,
    request_service.REQUEST_MISSING_ITEM_PRICE,
)


@router.get("/", response_model=list[UserRequestResponse])
def list_user_requests(
    status: str = Query("open"),
    type: Optional[str] = Query(None),
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    db: Session = Depends(get_db),
):
    """List queue-visible requests, optionally one type. Plain `str` with a
    manual check rather than `Literal`: the User Requests tabs send both
    params on every load, and the manual check gives one 422 shape for both."""
    if status not in _LIST_STATUSES:
        raise HTTPException(status_code=422, detail="status must be open, stocked, or resolved")
    if type is not None and type not in _LIST_TYPES:
        raise HTTPException(status_code=422, detail="unknown request type")
    return [
        build_response(row)
        for row in request_service.list_user_requests(db, status=status, request_type=type)
    ]
```

(add `from fastapi import HTTPException`.) Place `GET /counts` **before** any `/{request_id}` route:

```python
@router.get(
    "/counts",
    response_model=dict[str, dict[str, int]],
    responses={403: {"description": "Requires the TechFM OA role or above."}},
)
def list_request_counts(
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    db: Session = Depends(get_db),
):
    """`{request_type: {"open": n, "stocked": n}}` for the tab labels."""
    return material_service.open_counts(db)
```

Filing:

```python
@router.post("/material-request", response_model=UserRequestResponse, status_code=201)
def create_material_request(
    payload: MaterialRequestCreate,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """File a request for a catalogue item the shelf does not have.

    Open to any authenticated session, scoped by the same visible-work-order
    reader the Work Orders page uses (SEC-021 applied from day one): a
    Technician can only file against a job they are assigned to, and an
    invisible or archived work order is 404, not 403. On-hand is read for
    the response only -- never a gate.
    """
    try:
        work_order = wo_service.get_visible_work_order(db, payload.work_order_id, user)
        item = material_service.lock_live_item(db, payload.item_id)
        request, created = material_service.create_or_update(
            db,
            item_id=item.id,
            work_order=work_order,
            quantity=payload.quantity,
            product_link=payload.product_link,
            note=payload.note,
            created_by_id=user.id,
            origin=material_service.ORIGIN_REQUEST_CARD,
        )
        db.commit()
        on_hand = item.quantity
        request = request_service.get_user_request(db, request.id)
        if created:
            notifications_service.notify_material_request_filed(
                db, background, item_name=item.name, work_order_number=work_order.number
            )
        emit_user_request_changed(request.id)
        return build_response(request, item_quantity=on_hand, updated=not created)
    except DomainError as exc:
        raise to_http(exc)
```

Manual fire and cancel (after `/fulfill`):

```python
@router.post(
    "/{request_id}/mark-stocked",
    response_model=UserRequestResponse,
    responses={403: {"description": "Requires the TechFM OA role or above."}},
)
def mark_request_stocked(
    request_id: uuid.UUID,
    background: BackgroundTasks,
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    db: Session = Depends(get_db),
):
    """Staff counted the shelf and the item is really there: fire the crew's
    stocked notification without faking a stock transaction. Same service
    transition and same flush as the automatic edge."""
    try:
        material_service.mark_stocked(db, request_id, actor_id=user.id)
        db.commit()
        flush_stock_events(db, background)
        return build_response(request_service.get_user_request(db, request_id))
    except DomainError as exc:
        raise to_http(exc)


@router.post("/{request_id}/cancel", response_model=UserRequestResponse)
def cancel_material_request(
    request_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The filer withdraws their own open request (403 for anyone else, 409
    once it is stocked or resolved)."""
    try:
        material_service.cancel(db, request_id, actor_id=user.id)
        db.commit()
        emit_user_request_changed(request_id)
        return build_response(request_service.get_user_request(db, request_id))
    except DomainError as exc:
        raise to_http(exc)
```

In the existing `update_user_request` handler add `emit_user_request_changed(request_id)` after the service calls succeed (before `return`). In `fulfill_catalogue_request` add `emit_user_request_changed(request_id)` after the service returns (Task 9's chain makes this envelope matter).

- [x] **Step 7: Run the tests**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_material_requests.py tests/test_route_role_gates.py tests/test_user_requests.py tests/test_catalogue_requests.py -q`
Expected: PASS.

- [x] **Step 8: Commit**

```bash
git add backend/app/schemas/user_requests.py backend/app/routers/user_requests.py backend/app/services/user_requests.py backend/app/services/work_orders.py backend/tests/test_material_requests.py backend/tests/test_route_role_gates.py
git commit -m "add material request filing, manual stocking, cancel, and queue counts

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Rj5dKhZSJLx5wvJMfBTimY"
```

---

### Task 8: Work-order routes — the requests list and adding from a stocked line

**Why now:** the crew side of the loop. `GET /work-orders/{id}/requests` feeds both the Request card and the Materials lines; `material_request_id` on the add route is what closes a request the moment the material is logged.

**Files:**
- Modify: `backend/app/schemas/work_orders.py:105-117` (`WorkOrderItemCreate.material_request_id`)
- Modify: `backend/app/services/work_orders.py::add_work_order_item` (~2837-2902)
- Modify: `backend/app/routers/work_orders.py` (imports; `add_work_order_item` handler; new `list_work_order_requests`)
- Test: `backend/tests/test_material_requests.py` (append), `backend/tests/test_route_role_gates.py` (parametrize list)

**Interfaces:**
- Consumes: `material_service.resolve_from_line`, `list_for_work_order`; `routers.user_requests.build_response`; `emit_user_request_changed`.
- Produces: `GET /work-orders/{id}/requests → list[UserRequestResponse]` (handler `list_work_order_requests`, any session, visibility-scoped); `POST /work-orders/{id}/items` body accepts `material_request_id: UUID | null`; `wo_service.add_work_order_item(..., material_request_id=None)`.

- [x] **Step 1: Write the failing tests**

In `backend/tests/test_route_role_gates.py` add `"list_work_order_requests",` to the `test_work_order_routes_have_no_static_min_role` parametrize list.

Append to `backend/tests/test_material_requests.py`:

```python
# --------------------------------------------------------------------------
# The work-order side
# --------------------------------------------------------------------------

def test_the_work_order_requests_list_is_visibility_scoped(db):
    tech = _user(db)
    other = _user(db)
    work_order = _work_order(db, tech, assigned_to=tech)
    request, _ = _file(db, tech, work_order, _item(db))
    db.commit()

    mine = _get(db, tech, f"/work-orders/{work_order.id}/requests")
    assert mine.status_code == 200
    assert [row["id"] for row in mine.json()] == [str(request.id)]
    assert mine.json()[0]["item_quantity"] == "0"

    assert _get(db, other, f"/work-orders/{work_order.id}/requests").status_code == 404


def test_adding_from_the_stocked_line_resolves_the_request(db, monkeypatch):
    tech = _user(db)
    work_order = _work_order(db, tech, assigned_to=tech)
    item = _item(db, quantity="0")
    request, _ = _file(db, tech, work_order, item, quantity="4")
    _restock(db, item, to="10")
    material_service.drain()
    db.commit()

    response = _post(db, tech, f"/work-orders/{work_order.id}/items", {
        "item_id": str(item.id), "quantity": "3", "material_request_id": str(request.id),
    })

    assert response.status_code == 201, response.text
    db.refresh(request)
    assert request.status == "resolved"
    assert request.resolution_note == f"Added to {work_order.number}."
    assert request.details["added_quantity"] == "3"
    db.refresh(item)
    assert item.quantity == Decimal("7")


def test_adding_with_a_stale_request_id_is_409_and_adds_nothing(db):
    tech = _user(db)
    work_order = _work_order(db, tech, assigned_to=tech)
    item = _item(db, quantity="5")
    request, _ = _file(db, tech, work_order, item)  # still open, not stocked
    db.commit()

    response = _post(db, tech, f"/work-orders/{work_order.id}/items", {
        "item_id": str(item.id), "quantity": "1", "material_request_id": str(request.id),
    })

    assert response.status_code == 409
    db.refresh(item)
    assert item.quantity == Decimal("5")
    assert db.query(WorkOrderItem).filter(WorkOrderItem.work_order_id == work_order.id).count() == 0


def test_adding_without_a_request_id_is_unchanged(db):
    tech = _user(db)
    work_order = _work_order(db, tech, assigned_to=tech)
    item = _item(db, quantity="5")
    db.commit()
    response = _post(db, tech, f"/work-orders/{work_order.id}/items", {
        "item_id": str(item.id), "quantity": "1",
    })
    assert response.status_code == 201
```

Add `WorkOrderItem` to the models import at the top of the file.

- [x] **Step 2: Run to verify failure**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_material_requests.py -q -k "work_order_requests or stocked_line or stale_request or without_a_request"`
Expected: FAIL — 404 on `/requests`; the stocked-line test's request stays `stocked` (the unknown body field is ignored).

- [x] **Step 3: Schema**

`backend/app/schemas/work_orders.py::WorkOrderItemCreate`:

```python
    item_id: UUID
    quantity: Decimal
    # Set when the Add came from a stocked Material Request's one-tap line.
    # The service resolves that request in the same transaction as the line;
    # a stale id (not stocked, wrong work order, wrong item) is 409 and adds
    # nothing.
    material_request_id: Optional[UUID] = None
```

- [x] **Step 4: Service**

`backend/app/services/work_orders.py::add_work_order_item` signature gains `material_request_id: Optional[uuid.UUID] = None`. Immediately after `item = _locked_live_item(db, item_id)` (so a stale request fails before any stock moves):

```python
    if material_request_id is not None:
        material_requests.resolve_from_line(
            db,
            request_id=material_request_id,
            work_order_id=work_order.id,
            work_order_number=work_order.number,
            item_id=item.id,
            quantity=quantity,
            resolved_by_id=user.id if user else None,
        )
```

Docstring addition: "With `material_request_id`, the stocked Material Request that offered this line is resolved in the same transaction (`Added to {number}.`); it must be `stocked`, on this work order, for this item."

- [x] **Step 5: Router**

`backend/app/routers/work_orders.py`: import `from app.routers._stock_events import emit_user_request_changed, flush_stock_events` (replacing the Task 6 import line), `from app.routers.user_requests import build_response as build_request_response`, `from app.schemas.user_requests import UserRequestResponse`, `from app.services import material_requests as material_service`.

`add_work_order_item` handler:

```python
        line = wo_service.add_work_order_item(
            db,
            work_order_id,
            user=user,
            item_id=payload.item_id,
            quantity=payload.quantity,
            material_request_id=payload.material_request_id,
        )
        flush_stock_events(db, background)
        if payload.material_request_id is not None:
            emit_user_request_changed(payload.material_request_id)
        return _line_detail(line, include_price=_can_see_price(user))
```

New route, placed just before `add_work_order_item`:

```python
@router.get("/{work_order_id}/requests", response_model=list[UserRequestResponse])
def list_work_order_requests(
    work_order_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Every Material and Catalogue Request on one work order, newest first.
    Scoped exactly like the card itself: the visible-work-order reader
    answers 404 for an archived or out-of-scope row before anything is
    listed. Feeds the card's Request section and its stocked Materials lines."""
    try:
        work_order = wo_service.get_visible_work_order(db, work_order_id, user)
        return [
            build_request_response(row)
            for row in material_service.list_for_work_order(db, work_order.id)
        ]
    except DomainError as exc:
        raise to_http(exc)
```

- [x] **Step 6: Run the tests**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_material_requests.py tests/test_route_role_gates.py tests/test_realtime_emit.py tests/test_work_orders_service.py -q`
Expected: PASS (`test_realtime_emit.py` pins emitter sets by source inspection; `emit_user_request_changed` is a different event and must not join the status/review sets).

- [x] **Step 7: Commit**

```bash
git add backend/app/schemas/work_orders.py backend/app/services/work_orders.py backend/app/routers/work_orders.py backend/tests/test_material_requests.py backend/tests/test_route_role_gates.py
git commit -m "list a work order's requests and resolve a stocked one when its material is added

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Rj5dKhZSJLx5wvJMfBTimY"
```

---

### Task 9: Catalogue → Material chain

**Why now:** the last write path. It depends on both the renamed fulfilment (Task 1) and `create_or_update` (Task 4), and must run inside the fulfilment's transaction.

**Files:**
- Modify: `backend/app/services/user_requests.py::_resolve_one_catalogue_request` (the `else:` branch that attaches the retroactive line)
- Test: `backend/tests/test_material_requests.py` (append)

**Interfaces:**
- Consumes: `material_requests.create_or_update(origin=ORIGIN_CATALOGUE_FULFILMENT)`.
- Produces: after fulfilment, a `material_request` row per live work order whose item ends at `<= 0`, `created_by_id` = the catalogue filer, `quantity` = the catalogue request's quantity, `origin = "catalogue_fulfilment"`.

- [x] **Step 1: Write the failing tests**

```python
# --------------------------------------------------------------------------
# Catalogue -> Material chain
# --------------------------------------------------------------------------

def test_fulfilling_a_catalogue_request_for_an_empty_item_files_a_material_request(db):
    staff = _user(db, "techfm_oa")
    tech = _user(db)
    work_order = _work_order(db, tech, assigned_to=tech)
    catalogue = request_service.create_catalogue_request(
        db, searched_text="copper elbow", quantity=Decimal("6"), note=None,
        work_order_id=work_order.id, work_order_number=work_order.number,
        source="work_orders", created_by_id=tech.id,
    )
    item = _item(db, quantity="0", name="3/4 Copper Elbow")
    db.flush()

    request_service.fulfill_catalogue_request(
        db, catalogue.id, item_id=item.id, sibling_ids=[], resolved_by_id=staff.id
    )

    chained = (
        db.query(UserRequest)
        .filter(UserRequest.request_type == "material_request", UserRequest.work_order_id == work_order.id)
        .one()
    )
    assert chained.status == "open"
    assert chained.item_id == item.id
    assert chained.created_by_id == tech.id
    assert chained.details["quantity"] == "6"
    assert chained.details["origin"] == "catalogue_fulfilment"


def test_the_chain_skips_a_stocked_item_and_a_closed_work_order(db):
    staff = _user(db, "techfm_oa")
    tech = _user(db)
    live = _work_order(db, tech, assigned_to=tech)
    closed = _work_order(db, tech, assigned_to=tech)
    closed.archived_at = datetime.now(timezone.utc)
    first = request_service.create_catalogue_request(
        db, searched_text="grommet", quantity=Decimal("1"), note=None,
        work_order_id=live.id, work_order_number=live.number, source="work_orders", created_by_id=tech.id,
    )
    second = request_service.create_catalogue_request(
        db, searched_text="grommet", quantity=Decimal("1"), note=None,
        work_order_id=closed.id, work_order_number=closed.number, source="work_orders", created_by_id=tech.id,
    )
    stocked_item = _item(db, quantity="9")
    db.flush()

    request_service.fulfill_catalogue_request(
        db, first.id, item_id=stocked_item.id, sibling_ids=[second.id], resolved_by_id=staff.id
    )

    assert db.query(UserRequest).filter(UserRequest.request_type == "material_request", UserRequest.item_id == stocked_item.id).count() == 0
```

- [x] **Step 2: Run to verify failure**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_material_requests.py -q -k chain`
Expected: FAIL — `NoResultFound` on `.one()`.

- [x] **Step 3: Implement**

In `backend/app/services/user_requests.py::_resolve_one_catalogue_request`, inside the `else:` branch after `attach_dispense_line(...)` and `details["auto_add"] = "added"`:

```python
            # The material was already used, but if the shelf is empty the
            # crew will need more: open a Material Request on their behalf so
            # the stocked push reaches them like any other. No filing push --
            # the fulfilling TechFM OA is standing in the queue.
            from app.services import material_requests

            item = db.get(Item, item_id)
            if item is not None and Decimal(item.quantity) <= 0:
                material_requests.create_or_update(
                    db,
                    item_id=item_id,
                    work_order=work_order,
                    quantity=quantity,
                    product_link=None,
                    note=None,
                    created_by_id=request.created_by_id,
                    origin=material_requests.ORIGIN_CATALOGUE_FULFILMENT,
                )
```

Add `Item` to the local `from app.models import WorkOrder` import in that function. (`Decimal` is already imported at module top.)

- [x] **Step 4: Run the tests**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_material_requests.py tests/test_catalogue_requests.py -q`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add backend/app/services/user_requests.py backend/tests/test_material_requests.py
git commit -m "open a material request when a catalogue fulfilment lands on an empty shelf

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Rj5dKhZSJLx5wvJMfBTimY"
```

---

### Task 10: Hub `stocked_requests`

**Why now:** a read model over rows every previous task can now produce.

**Files:**
- Modify: `backend/app/services/hub.py:108-136,206-281` (`StockedRequest` dataclass, `HubPayload.stocked_requests`, `personal_hub`)
- Modify: `backend/app/schemas/hub.py` (`HubStockedRequest`, `HubResponse.stocked_requests`)
- Modify: `backend/app/routers/hub.py::get_hub`
- Test: `backend/tests/test_hub_service.py` (append), `backend/tests/test_hub_router.py` (nothing to change; the field defaults)

**Interfaces:**
- Consumes: `material_requests.stocked_requests_for_user`.
- Produces: `HubResponse.stocked_requests: list[HubStockedRequest]` where `HubStockedRequest = {request_id, item_name, work_order_id, work_order_number, quantity: str, stocked_at: datetime | None}`.

- [x] **Step 1: Write the failing test**

Append to `backend/tests/test_hub_service.py`:

```python
# --- stocked material requests (Dashboard section) --------------------------


def test_personal_hub_lists_stocked_requests_i_am_associated_with(db):
    from app.services import material_requests as material_service

    tech = _seed_user(db)
    other = _seed_user(db)
    item = _seed_item(db)
    item.quantity = Decimal("0")
    mine = _seed_work_order(db, created_by=other, assigned_to=tech)
    theirs = _seed_work_order(db, created_by=other, assigned_to=other)
    for wo, filer in ((mine, other), (theirs, other)):
        material_service.create_or_update(
            db, item_id=item.id, work_order=wo, quantity=Decimal("2"), product_link=None,
            note=None, created_by_id=filer.id, origin="request_card",
        )
    db.flush()
    before = item.quantity
    item.quantity = Decimal("5")
    material_service.record_stock_change(db, item, quantity_before=before)
    material_service.drain()
    db.flush()

    payload = hub_service.personal_hub(db, tech)

    assert [r.work_order_number for r in payload.stocked_requests] == [mine.number]
    row = payload.stocked_requests[0]
    assert row.item_name == item.name
    assert row.quantity == "2"
    assert row.stocked_at is not None

    staff = _seed_user(db, roles.ROLE_TECHFM_OA)
    numbers = {r.work_order_number for r in hub_service.personal_hub(db, staff).stocked_requests}
    assert {mine.number, theirs.number} <= numbers
```

(`_seed_item` exists at line 74 of that file.)

- [x] **Step 2: Run to verify failure**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_hub_service.py -q -k stocked`
Expected: FAIL — `AttributeError: 'HubPayload' object has no attribute 'stocked_requests'`.

- [x] **Step 3: Service**

`backend/app/services/hub.py`: import `from app.services import material_requests as material_requests_service`. After `ToolOut`:

```python
@dataclass(frozen=True)
class StockedRequest:
    """One row of the Dashboard's "Requested material in stock" section: a
    Material Request that is `stocked` and waiting for the crew to add it."""

    request_id: uuid.UUID
    item_name: str
    work_order_id: Optional[uuid.UUID]
    work_order_number: str
    quantity: str
    stocked_at: Optional[datetime]
```

`HubPayload` gains `stocked_requests: list[StockedRequest]`. In `personal_hub`, before the `return HubPayload(...)`:

```python
    stocked_requests = [
        StockedRequest(
            request_id=r.id,
            item_name=r.item.name if r.item else "Unknown item",
            work_order_id=r.work_order_id,
            work_order_number=(
                r.work_order.number if r.work_order else (r.details or {}).get("work_order_number") or ""
            ),
            quantity=str((r.details or {}).get("quantity") or "1"),
            stocked_at=_parse_iso((r.details or {}).get("stocked_at")),
        )
        for r in material_requests_service.stocked_requests_for_user(db, user)
    ]
```

and pass `stocked_requests=stocked_requests`. Add a module helper:

```python
def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
```

- [x] **Step 4: Schema and router**

`backend/app/schemas/hub.py`, before `HubResponse`:

```python
class HubStockedRequest(BaseModel):
    """A stocked Material Request the viewer is associated with (or every
    one, for TechFM OA+). Nothing is dismissed by hand: the row leaves when
    the request leaves `stocked`."""

    request_id: uuid.UUID
    item_name: str
    work_order_id: Optional[uuid.UUID] = None
    work_order_number: str
    quantity: str
    stocked_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
```

`HubResponse` gains `stocked_requests: list[HubStockedRequest] = []` after `tools_out`. `backend/app/routers/hub.py::get_hub` passes `stocked_requests=payload.stocked_requests,`.

- [x] **Step 5: Run the tests**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_hub_service.py tests/test_hub_router.py -q`
Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add backend/app/services/hub.py backend/app/schemas/hub.py backend/app/routers/hub.py backend/tests/test_hub_service.py
git commit -m "surface stocked material requests on the hub payload

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Rj5dKhZSJLx5wvJMfBTimY"
```

---

### Task 11: Frontend — api.js wrappers and the User Requests page

**Why now:** the staff page is where the manual fire lives and where every later UI piece can be checked against real rows. The API is stable, so the wrappers are written once here and reused by Tasks 12-13. There is no JS harness; contracts are pinned by Python source-assertion tests (the repo's existing pattern in `test_work_orders_router.py`).

**Files:**
- Modify: `backend/static/api.js:305-323,731-736` (list params, counts, material request, mark stocked, cancel, WO requests, add-item request id)
- Modify: `backend/static/realtime.js` — nothing; constants live in subscribers
- Modify: `backend/static/pages/user-requests.html`
- Modify: `backend/static/views/userRequests.js`, `backend/static/views/userRequestCards.js`, `backend/static/tips.js`, `backend/static/styles.css`
- Test: `backend/tests/test_catalogue_requests.py` (append source pins)

**Interfaces:**
- Produces (api.js): `apiListUserRequests(status = "open", type = null)`, `apiListUserRequestCounts()`, `apiCreateMaterialRequest({ itemId, workOrderId, quantity = 1, productLink = null, note = null })`, `apiMarkRequestStocked(requestId)`, `apiCancelMaterialRequest(requestId)`, `apiListWorkOrderRequests(workOrderId)`, `apiAddWorkOrderItem(workOrderId, { itemId, quantity, materialRequestId = null })`.
- Produces (userRequestCards.js): `requestTypeLabel` knows `material_request`; `statusLabel(status)` → `Open` / `Stocked` / `Resolved`; `buildRequestCard` renders the material card per spec §6.2; `editFormHtml` material branch with `.user-request-edit-qty`, `.user-request-edit-link`, `.user-request-edit-note`.
- DOM contract: tab strip `#user-requests-tabs` with `button.hub-tab[data-request-type]` and a `.user-requests-tab-count` span each; status `<select id="user-requests-status">` whose options are rebuilt per tab; card buttons `.user-request-stock` (Mark stocked & notify), existing `.user-request-action[data-status]`.

- [x] **Step 1: Write the failing source pins**

Append to `backend/tests/test_catalogue_requests.py`:

```python
# --------------------------------------------------------------------------
# UI contract pins (no JS harness; same approach as test_work_orders_router)
# --------------------------------------------------------------------------

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[1] / "static"


def _src(rel):
    return (_STATIC / rel).read_text(encoding="utf-8")


def test_api_client_has_the_material_request_wrappers():
    api = _src("api.js")
    assert 'jsonRequest("/user-requests/material-request", "POST"' in api
    assert "/user-requests/counts" in api
    assert "/mark-stocked`" in api
    assert "/cancel`" in api
    assert "/requests`" in api
    assert "material_request_id: materialRequestId" in api
    assert 'params.set("type", type)' in api


def test_the_user_requests_page_has_four_type_tabs_with_counts():
    html = _src("pages/user-requests.html")
    assert 'id="user-requests-tabs"' in html
    assert 'role="tablist"' in html
    for key in ("material_request", "catalogue_request", "inventory_recount", "missing_item_price"):
        assert f'data-request-type="{key}"' in html
    assert 'id="user-requests-type"' not in html  # the dropdown is gone
    assert "user-requests-tab-count" in html


def test_the_material_card_offers_the_manual_fire_and_the_stocked_status():
    cards = _src("views/userRequestCards.js")
    assert "Mark stocked &amp; notify" in cards
    assert 'class="user-request-stock"' in cards
    assert 'if (status === "stocked") return "Stocked"' in cards
    assert 'if (type === "material_request") return "Material request"' in cards
    assert "user-request-edit-link" in cards
    controller = _src("views/userRequests.js")
    assert "apiMarkRequestStocked" in controller
    assert "apiListUserRequestCounts" in controller
    assert 'subscribe("user_request.changed"' in controller or "USER_REQUEST_CHANGED_EVENT" in controller
    tips = _src("tips.js")
    assert '"requests.stocked"' in tips
```

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_catalogue_requests.py -q -k "api_client or four_type_tabs or material_card"` — Expected: FAIL on every assertion.

- [x] **Step 2: api.js**

Replace `apiListUserRequests` and add the new wrappers in the `// --- User Requests ---` block:

```js
export async function apiListUserRequests(status = "open", type = null) {
  const params = new URLSearchParams({ status });
  if (type) params.set("type", type);
  return liveGet(`/user-requests/?${params}`);
}

export async function apiListUserRequestCounts() {
  // `{ request_type: { open: n, stocked: n } }` for the tab labels.
  return liveGet("/user-requests/counts");
}

export async function apiCreateMaterialRequest({
  itemId,
  workOrderId,
  quantity = 1,
  productLink = null,
  note = null,
}) {
  // A catalogue item the shelf does not have. Open to any signed-in role;
  // the server scopes by work-order visibility. A second filing for the same
  // (work order, item) updates the earlier request and answers `updated: true`.
  return jsonRequest("/user-requests/material-request", "POST", {
    item_id: itemId,
    work_order_id: workOrderId,
    quantity,
    product_link: productLink,
    note,
  });
}

export async function apiMarkRequestStocked(requestId) {
  // TechFM OA+: the shelf really has it; push the crew without faking stock.
  return jsonRequest(`/user-requests/${requestId}/mark-stocked`, "POST", {});
}

export async function apiCancelMaterialRequest(requestId) {
  // Filer only, while open.
  return jsonRequest(`/user-requests/${requestId}/cancel`, "POST", {});
}
```

In the work-orders block, after `apiGetWorkOrder`:

```js
export async function apiListWorkOrderRequests(workOrderId) {
  // Material + catalogue requests on one work order, newest first, scoped
  // like the card. Feeds the Request card and the stocked Materials lines.
  return liveGet(`/work-orders/${workOrderId}/requests`);
}
```

and change `apiAddWorkOrderItem`:

```js
export async function apiAddWorkOrderItem(workOrderId, { itemId, quantity, materialRequestId = null }) {
  return jsonRequest(`/work-orders/${workOrderId}/items`, "POST", {
    item_id: itemId,
    quantity,
    material_request_id: materialRequestId,
  });
}
```

- [x] **Step 3: Page shell**

Replace the `<div class="filter-row user-requests-controls">…</div>` block in `backend/static/pages/user-requests.html` with:

```html
            <nav id="user-requests-tabs" class="hub-tabs user-requests-tabs" role="tablist" aria-label="Request types">
                <button type="button" class="hub-tab active" role="tab" aria-selected="true" data-request-type="material_request">Material requests <span class="user-requests-tab-count" aria-label="open"></span></button>
                <button type="button" class="hub-tab" role="tab" aria-selected="false" data-request-type="catalogue_request">Catalogue requests <span class="user-requests-tab-count"></span></button>
                <button type="button" class="hub-tab" role="tab" aria-selected="false" data-request-type="inventory_recount">Stock recounts <span class="user-requests-tab-count"></span></button>
                <button type="button" class="hub-tab" role="tab" aria-selected="false" data-request-type="missing_item_price">Missing price / link <span class="user-requests-tab-count"></span></button>
            </nav>

            <div class="filter-row user-requests-controls">
                <label for="user-requests-status">Status<button type="button" class="tip-btn" data-tip="requests.types">?</button></label>
                <select id="user-requests-status">
                    <option value="open">Open</option>
                    <option value="stocked">Stocked</option>
                    <option value="resolved">Resolved</option>
                </select>
                <button id="user-requests-refresh" type="button" class="secondary-btn">Refresh</button>
            </div>
```

Rewrite the page hint to one sentence per kind:

```html
            <p class="hint">Material requests ask staff to stock a catalogue item a crew needs; when it is stocked the crew is notified and can add it in one tap. Catalogue requests report material with no catalogue row at all; fulfilling one adds it and logs it retroactively on its work order. Stock recounts flag a dispense that came up short. Missing price / link collects a price and product link for unpriced material used on a work order.</p>
```

Update the HTML comment above the page similarly (four kinds).

- [x] **Step 4: Cards**

In `backend/static/views/userRequestCards.js`:

```js
export function requestTypeLabel(type) {
  if (type === "material_request") return "Material request";
  if (type === "catalogue_request") return "Catalogue request";
  if (type === "inventory_recount") return "Stock recount";
  if (type === "missing_item_price") return "Missing price / link";
  return type.replaceAll("_", " ");
}

export function statusLabel(status) {
  if (status === "stocked") return "Stocked";
  if (status === "resolved") return "Resolved";
  return "Open";
}

function linkLine(label, url) {
  if (!url) return "";
  const safe = escapeHtml(url);
  return `<span><strong>${escapeHtml(label)}:</strong> <a href="${safe}" target="_blank" rel="noopener">${safe}</a></span>`;
}

function materialRequestBody(request, details) {
  const cycles = Number(details.stock_cycles || 0);
  return (
    detailLine("Barcode", request.item_barcode) +
    detailLine("Work order", request.work_order_number) +
    detailLine("Quantity requested", details.quantity) +
    linkLine("Product link", details.product_link) +
    detailLine("Note", details.note) +
    detailLine("On hand now", request.item_quantity) +
    detailLine("Requested by", request.created_by_name || "Unknown") +
    detailLine("Filed", formatDate(request.created_at)) +
    (details.stocked_at ? detailLine("Stocked", formatDate(details.stocked_at)) : "") +
    (cycles > 1 ? detailLine("Stock cycles", `${cycles} — stocked ${cycles} times, still not added`) : "")
  );
}

function materialRequestActions(request) {
  const edit = `<button type="button" class="secondary-btn user-request-edit-open">Edit</button>`;
  if (request.status === "open") {
    return (
      `<button type="button" class="user-request-stock">Mark stocked &amp; notify</button>${tipHtml("requests.stocked")}` +
      `<button type="button" class="user-request-action secondary-btn" data-status="resolved">Mark resolved</button>` +
      edit
    );
  }
  if (request.status === "stocked") {
    return (
      `<span class="hint">Waiting for the crew to add it to ${escapeHtml(request.work_order_number || "the work order")}.</span>` +
      `<button type="button" class="user-request-action secondary-btn" data-status="resolved">Mark resolved</button>` +
      edit
    );
  }
  return (
    `<button type="button" class="user-request-action secondary-btn" data-status="open">Reopen</button>` + edit
  );
}
```

In `editFormHtml`, add a material branch before the catalogue one:

```js
  const materialFields =
    request.request_type === "material_request"
      ? `<label class="user-request-label">Quantity requested
           <input type="number" class="user-request-edit-qty" min="0.01" step="any" value="${escapeHtml(details.quantity || "1")}">
         </label>
         <label class="user-request-label">Product link
           <input type="url" class="user-request-edit-link" maxlength="2000" value="${escapeHtml(details.product_link || "")}" placeholder="https://...">
         </label>
         <label class="user-request-label">Note
           <input type="text" class="user-request-edit-note" maxlength="500" value="${escapeHtml(details.note || "")}">
         </label>`
      : "";
```

and render `${materialFields}${itemFields}` where `itemFields` (the catalogue branch) now returns `""` for a material request rather than the snapshot hint — restructure as: catalogue → its three fields; material → `materialFields`; else → the snapshot hint.

In `buildRequestCard`: add the branch `else if (request.request_type === "material_request") { heading = request.item_name || "Unknown item"; body = materialRequestBody(request, details); actions = materialRequestActions(request); }`; render the status badge as `escapeHtml(statusLabel(request.status))`; the card class already carries `user-request-${status}` so `user-request-stocked` exists for CSS.

- [x] **Step 5: Controller**

In `backend/static/views/userRequests.js`:

- Imports: add `apiCancelMaterialRequest` (unused here; leave out), `apiListUserRequestCounts`, `apiMarkRequestStocked`; `import { subscribe } from "../realtime.js";`; `import { getActivePage } from "./nav.js"` is **not** available (nav imports this module) — read the active page from the socket notification instead, as `userHub.js` does.
- Replace `typeEl` with:

```js
const tabsEl = document.getElementById("user-requests-tabs");
const USER_REQUESTS_PAGE = "user-requests";
const USER_REQUEST_CHANGED_EVENT = "user_request.changed";
const STATUS_OPTIONS = {
  material_request: [["open", "Open"], ["stocked", "Stocked"], ["resolved", "Resolved"]],
  default: [["open", "Open"], ["resolved", "Resolved"]],
};
let activeType = "material_request";

function rebuildStatusOptions() {
  const options = STATUS_OPTIONS[activeType] || STATUS_OPTIONS.default;
  const current = statusEl.value;
  statusEl.innerHTML = options
    .map(([value, label]) => `<option value="${value}">${label}</option>`)
    .join("");
  statusEl.value = options.some(([v]) => v === current) ? current : "open";
}

function selectTab(type) {
  activeType = type;
  tabsEl.querySelectorAll(".hub-tab").forEach((btn) => {
    const on = btn.dataset.requestType === type;
    btn.classList.toggle("active", on);
    btn.setAttribute("aria-selected", String(on));
  });
  rebuildStatusOptions();
}

async function refreshCounts() {
  try {
    const counts = await apiListUserRequestCounts();
    tabsEl.querySelectorAll(".hub-tab").forEach((btn) => {
      const open = counts[btn.dataset.requestType]?.open || 0;
      btn.querySelector(".user-requests-tab-count").textContent = open ? `(${open})` : "";
    });
  } catch {
    // Counts are decoration; the list is the truth.
  }
}
```

- `visibleRequests()` becomes `return loaded;` (the server filters by type now) and `render()` uses `requestTypeLabel(activeType)` in its empty message: `No ${status} ${label.toLowerCase()}s.`
- `loadUserRequests`: `loaded = await apiListUserRequests(status, activeType); render(); void refreshCounts();`
- Wire: `tabsEl.addEventListener("click", (e) => { const btn = e.target.closest(".hub-tab[data-request-type]"); if (!btn) return; selectTab(btn.dataset.requestType); void loadUserRequests(); });` and call `selectTab(activeType)` once at module load so the status options match the default tab.
- Edit save: add the material branch before the catalogue one:

```js
      if (card.dataset.requestType === "material_request") {
        const link = panel.querySelector(".user-request-edit-link");
        if (link.value.trim() && !link.checkValidity()) {
          setMessage(messageEl, "Enter a valid product link.", "error");
          return;
        }
        details = {
          quantity: panel.querySelector(".user-request-edit-qty").value.trim() || "1",
          product_link: link.value.trim() || null,
          note: panel.querySelector(".user-request-edit-note").value.trim() || null,
        };
      }
```

- Manual fire, before the `// --- resolve / reopen` block:

```js
    const stockBtn = event.target.closest(".user-request-stock");
    if (stockBtn) {
      if (!(await confirmDialog("Mark this item as stocked and notify the crew?"))) return;
      stockBtn.disabled = true;
      try {
        await apiMarkRequestStocked(card.dataset.id);
        await loadUserRequests();
      } catch (err) {
        stockBtn.disabled = false;
        setMessage(messageEl, friendlyError(err, "Could not mark that request stocked."), "error");
      }
      return;
    }
```

- Realtime, at module end:

```js
// Any request moved: reload when this page is showing. Background reload --
// a socket signal, not a user action.
subscribe(USER_REQUEST_CHANGED_EVENT, ({ activePage }) => {
  if (activePage !== USER_REQUESTS_PAGE) return;
  void loadUserRequests();
});
```

- [x] **Step 6: Tips and CSS**

`backend/static/tips.js`, in the User Requests block: rewrite `requests.types` text to the four-kind sentence from Step 3 and add

```js
  "requests.stocked": {
    label: "Mark stocked & notify",
    text: "Use this when the shelf really has the item but the app's count says otherwise. It notifies the crew and puts the one-tap Add line on their work order without recording a stock transaction. Correct the count separately if it is wrong.",
  },
```

`backend/static/styles.css`, after `.user-request-resolved .user-request-status`:

```css
.user-request-stocked { border-left-color: var(--color-success); }
.user-request-stocked .user-request-status { color: var(--color-success); }
.user-requests-tabs { flex-wrap: wrap; }
.user-requests-tab-count { color: var(--text-panel-mute); font-weight: var(--fw-semibold); }
```

- [x] **Step 7: Verify**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_catalogue_requests.py -q` — Expected: PASS.
Run: `for f in backend/static/api.js backend/static/views/userRequests.js backend/static/views/userRequestCards.js backend/static/tips.js; do node --check "$f" || echo "FAIL $f"; done` — Expected: no `FAIL`.
Manual (hand to the user; do not start the server yourself): as TechFM OA open User Requests → four tabs with counts; Material tab default; Status offers Open/Stocked/Resolved; a filed request's card shows Mark stocked & notify; pressing it moves the card to the Stocked filter and the crew phone buzzes `Material in stock`.

- [x] **Step 8: Commit**

```bash
git add backend/static/api.js backend/static/pages/user-requests.html backend/static/views/userRequests.js backend/static/views/userRequestCards.js backend/static/tips.js backend/static/styles.css backend/tests/test_catalogue_requests.py
git commit -m "give the User Requests page type tabs and the material request card

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Rj5dKhZSJLx5wvJMfBTimY"
```

---

### Task 12: Frontend — the Request card and stocked Materials lines on the work order

**Why now:** the crew side. Depends on Task 8's endpoints and Task 11's wrappers. Lives in a new module so `workOrders.js` grows by a handful of lines, not hundreds.

**Files:**
- Create: `backend/static/views/workOrderRequests.js`
- Modify: `backend/static/views/workOrders.js` (`EDITOR_SECTIONS:1333`, `renderBody:1793-1811`, `paintDetail:1641`, add-item input/pick handlers `:1848-1897,1904-1912`, add-item click `:2143-2160`, import)
- Modify: `backend/static/views/catalogueRequest.js` (`SOURCES` + `request_card`), `backend/app/schemas/user_requests.py` (`CatalogueRequestCreate.source` Literal), `backend/static/main.js` (side-effect import), `backend/static/styles.css`
- Test: `backend/tests/test_catalogue_requests.py` (source pins), `backend/tests/test_material_requests.py` (schema pin)

**Interfaces:**
- Produces: `mountWorkOrderRequests(cardEl, detail, { items })` — fills `.wo-requested-lines` (inside Materials) and `.wo-request-section .wo-section-content`; registers document-level delegated handlers for `.wo-request-*` and `.wo-requested-line` controls; subscribes to `user_request.changed` and re-mounts every open, unheld card.
- DOM contract in `renderBody`: Materials section gains `<div class="wo-requested-lines"></div>` above `.wo-add-item`; after Materials: `<details class="wo-section-card wo-request-section"><summary class="wo-section-summary">Request</summary><div class="wo-section-content"></div></details>`.
- The one-tap Add: sets `.wo-add-item` `dataset.itemId`, `dataset.materialRequestId`, the search text and qty; `workOrders.js` add-item passes `materialRequestId` and clears it; picking a different item or editing the search clears `materialRequestId`.

- [ ] **Step 1: Write the failing pins**

Append to `backend/tests/test_catalogue_requests.py`:

```python
def test_the_work_order_card_mounts_the_request_section_and_stocked_lines():
    wo = _src("views/workOrders.js")
    assert "wo-request-section" in wo
    assert '".wo-edit-card, .wo-notes-section, .wo-materials-section, .wo-labor-section, .wo-request-section"' in wo
    assert 'class="wo-requested-lines"' in wo
    assert "mountWorkOrderRequests(" in wo
    assert "materialRequestId: container.dataset.materialRequestId || null" in wo
    module = _src("views/workOrderRequests.js")
    assert "apiListWorkOrderRequests" in module
    assert "apiCreateMaterialRequest" in module
    assert "apiCancelMaterialRequest" in module
    assert "Add requested material" in module
    assert "Request sent. Staff have been notified." in module
    assert "Updated your earlier request." in module
    assert "Staff will verify the count" in module
    assert 'source: "request_card"' in module
    assert '"user_request.changed"' in module
    assert 'import "./views/workOrderRequests.js";' in _src("main.js")
    assert '"request_card"' in _src("views/catalogueRequest.js")
```

And to `backend/tests/test_material_requests.py`:

```python
def test_a_catalogue_request_can_come_from_the_request_card():
    from app.schemas.user_requests import CatalogueRequestCreate

    payload = CatalogueRequestCreate(searched_text="grommet", source="request_card")
    assert payload.source == "request_card"
```

Run both files `-k "request_section or request_card"` — Expected: FAIL.

- [ ] **Step 2: Backend one-liner**

`backend/app/schemas/user_requests.py::CatalogueRequestCreate`: `source: Literal["work_orders", "find_item", "request_card"]`.
`backend/static/views/catalogueRequest.js`: `const SOURCES = new Set(["work_orders", "find_item", "request_card"]);` and the header comment: "Mounted at three empty states — the Materials add-material picker, Find Item's results, and the Request card's item search".

- [ ] **Step 3: The new module**

Create `backend/static/views/workOrderRequests.js`:

```js
// View: the work-order card's Request section and its stocked Materials lines.
//
// Layer: views. Owns everything Material-Request-shaped inside a work-order
// card so `workOrders.js` (already 2,800 lines) gains only a mount call and
// two placeholders. Imports nothing from `workOrders.js` -- that module
// imports this one -- and reads `allItems` through the mount options.
//
// One fetch (`GET /work-orders/{id}/requests`) serves both surfaces: the
// "This work order's requests" list under the form, and the one-tap
// `Add requested material` lines above the Materials add row. Lines exist
// only while a request is `stocked`; an open request leaves Materials alone.
//
// Delegated document listeners, like `catalogueRequest.js`: the card body is
// rebuilt by `innerHTML` on every repaint, so per-instance wiring would leak.

import {
  apiCancelMaterialRequest,
  apiCreateMaterialRequest,
  apiListWorkOrderRequests,
} from "../api.js";
import { confirmDialog, setMessage } from "../dom.js";
import { escapeHtml, filterRanked, friendlyError } from "../format.js";
import { subscribe } from "../realtime.js";
import { getCurrentUser } from "../state.js";
import { catalogueRequestPromptHtml } from "./catalogueRequest.js";

const USER_REQUEST_CHANGED_EVENT = "user_request.changed";

// Per-card reference data handed in by the mount call.
const itemsByCard = new WeakMap();

function formatWhen(value) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

function statusLabel(status) {
  if (status === "stocked") return "Stocked";
  if (status === "resolved") return "Resolved";
  return "Open";
}

function typeTag(type) {
  return type === "catalogue_request" ? "Catalogue" : "Material";
}

// --- markup ---------------------------------------------------------------

export function requestFormHtml() {
  return `<div class="wo-request-form">
      <p class="hint">Need a catalogue item the shelf does not have? Staff are notified as soon as you send it.</p>
      <div class="wo-request-row">
        <input type="text" class="wo-request-search" placeholder="Search item by name or barcode" autocomplete="off">
        <input type="number" class="wo-request-qty" value="1" min="0.01" step="any" inputmode="decimal" aria-label="Quantity needed">
      </div>
      <div class="wo-request-results scan-chooser" hidden></div>
      <p class="wo-request-onhand hint" aria-live="polite"></p>
      <input type="url" class="wo-request-link" placeholder="Product link (optional)" inputmode="url">
      <input type="text" class="wo-request-note" maxlength="500" placeholder="Note (optional)">
      <div class="wo-request-actions">
        <button type="button" data-request-action="send">Send request</button>
      </div>
      <p class="wo-request-message" aria-live="polite"></p>
    </div>`;
}

function requestLineHtml(request, currentUserId) {
  const details = request.details || {};
  const name =
    request.request_type === "catalogue_request"
      ? details.searched_text || "Unnamed item"
      : request.item_name || "Unknown item";
  const cancel =
    request.request_type === "material_request" &&
    request.status === "open" &&
    request.created_by_id === currentUserId
      ? `<button type="button" class="secondary-btn" data-request-action="cancel" data-request-id="${escapeHtml(request.id)}">Cancel</button>`
      : "";
  return `<div class="wo-request-line wo-request-${escapeHtml(request.status)}">
      <span class="wo-request-type">${escapeHtml(typeTag(request.request_type))}</span>
      <span class="wo-request-name">${escapeHtml(name)}</span>
      <span class="hint">qty ${escapeHtml(details.quantity || "1")}</span>
      <span class="wo-request-status">${escapeHtml(statusLabel(request.status))}</span>
      <span class="hint">${escapeHtml(request.created_by_name || "Unknown")} · ${escapeHtml(formatWhen(request.created_at))}</span>
      ${cancel}
    </div>`;
}

export function requestListHtml(requests, currentUserId) {
  const live = requests.filter((r) => r.status !== "resolved");
  const resolved = requests.filter((r) => r.status === "resolved");
  const liveHtml = live.length
    ? live.map((r) => requestLineHtml(r, currentUserId)).join("")
    : `<p class="hint">No open requests on this work order.</p>`;
  const resolvedHtml = resolved.length
    ? `<details class="wo-request-resolved-group"><summary class="hint">Show resolved (${resolved.length})</summary>${resolved
        .map((r) => requestLineHtml(r, currentUserId))
        .join("")}</details>`
    : "";
  return `<h4 class="wo-request-heading">This work order's requests</h4>${liveHtml}${resolvedHtml}`;
}

export function stockedLinesHtml(requests) {
  return requests
    .filter((r) => r.request_type === "material_request" && r.status === "stocked")
    .map((r) => {
      const details = r.details || {};
      return `<div class="wo-requested-line" data-request-id="${escapeHtml(r.id)}" data-item-id="${escapeHtml(r.item_id)}" data-item-name="${escapeHtml(r.item_name || "")}" data-quantity="${escapeHtml(details.quantity || "1")}">
          <span class="wo-requested-text">${escapeHtml(r.item_name || "Unknown item")} · requested ${escapeHtml(details.quantity || "1")} · on hand ${escapeHtml(r.item_quantity ?? "?")} · by ${escapeHtml(r.created_by_name || "Unknown")}</span>
          <button type="button" data-request-action="add-requested">Add requested material</button>
        </div>`;
    })
    .join("");
}

// --- mount ----------------------------------------------------------------

export async function mountWorkOrderRequests(cardEl, detail, { items = [] } = {}) {
  itemsByCard.set(cardEl, items);
  const section = cardEl.querySelector(".wo-request-section .wo-section-content");
  const lines = cardEl.querySelector(".wo-requested-lines");
  if (!section) return;
  section.innerHTML = requestFormHtml() + `<div class="wo-request-list"><p class="hint">Loading requests…</p></div>`;
  let requests = [];
  try {
    requests = await apiListWorkOrderRequests(detail.id);
  } catch (err) {
    section.querySelector(".wo-request-list").innerHTML =
      `<p class="error">${escapeHtml(friendlyError(err, "Could not load requests."))}</p>`;
    return;
  }
  const me = getCurrentUser()?.id || null;
  const list = section.querySelector(".wo-request-list");
  if (list) list.innerHTML = requestListHtml(requests, me);
  if (lines) lines.innerHTML = stockedLinesHtml(requests);
}

// --- search inside the Request form ----------------------------------------

document.addEventListener("input", (event) => {
  const input = event.target;
  if (!input.classList?.contains("wo-request-search")) return;
  const form = input.closest(".wo-request-form");
  const cardEl = input.closest(".wo-card");
  const results = form.querySelector(".wo-request-results");
  const onHand = form.querySelector(".wo-request-onhand");
  delete form.dataset.itemId;
  onHand.textContent = "";
  const q = input.value.trim().toLowerCase();
  if (!q) {
    results.hidden = true;
    results.innerHTML = "";
    return;
  }
  const matches = filterRanked(itemsByCard.get(cardEl) || [], (it) => [it.name, it.barcode], q).slice(0, 8);
  results.innerHTML = matches.length
    ? matches
        .map(
          (it) =>
            `<button type="button" class="secondary-btn scan-choice-btn" data-request-action="pick" data-item-id="${escapeHtml(it.id)}" data-item-name="${escapeHtml(it.name)}" data-item-quantity="${escapeHtml(it.quantity)}">${escapeHtml(it.name)} <span class="ms-pick-barcode">${escapeHtml(it.barcode)}</span></button>`
        )
        .join("")
    : `<p class="hint">No matching items.</p>` +
      catalogueRequestPromptHtml({
        searchedText: input.value.trim(),
        workOrderId: cardEl ? cardEl.dataset.id : null,
        source: "request_card",
      });
  results.hidden = false;
});

// --- actions ------------------------------------------------------------------

document.addEventListener("click", async (event) => {
  const btn = event.target.closest("[data-request-action]");
  if (!btn) return;
  const action = btn.dataset.requestAction;
  const cardEl = btn.closest(".wo-card");
  if (!cardEl) return;

  if (action === "pick") {
    const form = btn.closest(".wo-request-form");
    form.dataset.itemId = btn.dataset.itemId;
    form.querySelector(".wo-request-search").value = btn.dataset.itemName;
    const results = form.querySelector(".wo-request-results");
    results.hidden = true;
    results.innerHTML = "";
    const onHand = Number(btn.dataset.itemQuantity);
    form.querySelector(".wo-request-onhand").textContent =
      onHand > 0 ? `${onHand} on hand — Staff will verify the count.` : `${onHand} on hand.`;
    form.querySelector(".wo-request-qty").focus();
    return;
  }

  if (action === "send") {
    const form = btn.closest(".wo-request-form");
    const msg = form.querySelector(".wo-request-message");
    const itemId = form.dataset.itemId;
    const qty = Number(form.querySelector(".wo-request-qty").value);
    const linkInput = form.querySelector(".wo-request-link");
    if (!itemId) {
      setMessage(msg, "Search and pick an item first.", "error");
      return;
    }
    if (!Number.isFinite(qty) || qty <= 0) {
      setMessage(msg, "Enter a quantity greater than zero.", "error");
      return;
    }
    if (linkInput.value.trim() && !linkInput.checkValidity()) {
      setMessage(msg, "Enter a valid product link.", "error");
      linkInput.focus();
      return;
    }
    btn.disabled = true;
    setMessage(msg, "Sending…", "");
    try {
      const result = await apiCreateMaterialRequest({
        itemId,
        workOrderId: cardEl.dataset.id,
        quantity: qty,
        productLink: linkInput.value.trim() || null,
        note: form.querySelector(".wo-request-note").value.trim() || null,
      });
      await mountWorkOrderRequests(cardEl, { id: cardEl.dataset.id }, { items: itemsByCard.get(cardEl) || [] });
      const fresh = cardEl.querySelector(".wo-request-message");
      if (fresh) {
        setMessage(
          fresh,
          result.updated ? "Updated your earlier request." : "Request sent. Staff have been notified.",
          "success"
        );
      }
    } catch (err) {
      btn.disabled = false;
      setMessage(msg, friendlyError(err, "Could not send that request."), "error");
    }
    return;
  }

  if (action === "cancel") {
    if (!(await confirmDialog("Cancel this material request?"))) return;
    btn.disabled = true;
    try {
      await apiCancelMaterialRequest(btn.dataset.requestId);
      await mountWorkOrderRequests(cardEl, { id: cardEl.dataset.id }, { items: itemsByCard.get(cardEl) || [] });
    } catch (err) {
      btn.disabled = false;
      const msg = cardEl.querySelector(".wo-message");
      if (msg) setMessage(msg, friendlyError(err, "Could not cancel that request."), "error");
    }
    return;
  }

  if (action === "add-requested") {
    // Prefill the existing add row and stamp the request id so the Add sends
    // it; the add itself stays `workOrders.js`'s job (entry mode, refresh).
    const line = btn.closest(".wo-requested-line");
    const container = cardEl.querySelector(".wo-add-item");
    if (!line || !container) return;
    container.dataset.itemId = line.dataset.itemId;
    container.dataset.materialRequestId = line.dataset.requestId;
    container.querySelector(".ms-item-search").value = line.dataset.itemName;
    const qty = container.querySelector(".wo-item-qty");
    qty.value = line.dataset.quantity;
    const results = container.querySelector(".ms-item-results");
    results.hidden = true;
    results.innerHTML = "";
    const materials = cardEl.querySelector(".wo-materials-section");
    if (materials) materials.open = true;
    qty.focus();
  }
});

// A request moved somewhere: refresh both surfaces on every open card that
// is not holding unsaved input. The envelope names a request, not a work
// order, so every open card refetches -- one small request each.
subscribe(USER_REQUEST_CHANGED_EVENT, () => {
  document.querySelectorAll("details.wo-card[open]").forEach((cardEl) => {
    const held = Array.from(
      cardEl.querySelectorAll(".wo-edit-card, .wo-notes-section, .wo-materials-section, .wo-labor-section, .wo-request-section")
    ).some((s) => s.open && s.querySelector("input:focus, textarea:focus"));
    if (held || !cardEl.querySelector(".wo-request-section")) return;
    void mountWorkOrderRequests(cardEl, { id: cardEl.dataset.id }, { items: itemsByCard.get(cardEl) || [] });
  });
});
```

Add `import "./views/workOrderRequests.js";` to `backend/static/main.js` after the `catalogueRequest.js` import.

- [ ] **Step 4: Integrate in `workOrders.js`**

- Import: `import { mountWorkOrderRequests } from "./workOrderRequests.js";`
- `EDITOR_SECTIONS` → `".wo-edit-card, .wo-notes-section, .wo-materials-section, .wo-labor-section, .wo-request-section"`.
- In `renderBody`, inside the Materials `.wo-section-content`, insert `<div class="wo-requested-lines"></div>` immediately before `<div class="wo-add-item">`. After the Materials `</details>` and before the labor section add:

```js
    `<details class="wo-section-card wo-request-section">
       <summary class="wo-section-summary">Request</summary>
       <div class="wo-section-content"></div>
     </details>` +
```

- In `paintDetail`, after `renderBody(detail, bodyEl);` add `if (cardEl) void mountWorkOrderRequests(cardEl, detail, { items: allItems });` (solo cards pass `cardEl` too — `showSoloCard` calls `paintDetail` with the card element).
- In the add-material `input` handler (line ~1855) add `delete container.dataset.materialRequestId;` beside `delete container.dataset.itemId;`. In the `pick-item` click handler add the same line.
- In the `add-item` click handler:

```js
      const addedLine = await apiAddWorkOrderItem(workOrderId, {
        itemId,
        quantity: qty,
        materialRequestId: container.dataset.materialRequestId || null,
      });
      delete container.dataset.materialRequestId;
```

- [ ] **Step 5: CSS**

Append to `backend/static/styles.css` near `.wo-add-item-row`:

```css
.wo-requested-line {
    display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); flex-wrap: wrap;
    margin-bottom: var(--space-2); padding: var(--space-2) var(--space-3);
    border: 1px solid var(--color-success); border-radius: var(--radius-sm);
}
.wo-requested-line button { margin-top: 0; min-height: var(--btn-h-sm); }
.wo-request-row { display: flex; gap: var(--space-2); flex-wrap: wrap; }
.wo-request-row .wo-request-search { flex: 1 1 160px; margin-top: 0; }
.wo-request-row .wo-request-qty { flex: 0 0 90px; width: 90px; margin-top: 0; }
.wo-request-actions { display: flex; margin-top: var(--space-2); }
.wo-request-actions button { margin-top: 0; min-height: var(--btn-h-sm); }
.wo-request-heading { margin: var(--space-4) 0 var(--space-2); font-size: var(--fs-sm); text-transform: uppercase; letter-spacing: 0.04em; color: var(--text-panel-mute); }
.wo-request-line { display: flex; align-items: center; gap: var(--space-3); flex-wrap: wrap; padding: var(--space-2) 0; border-top: 1px solid var(--panel-rule); }
.wo-request-line button { margin-top: 0; min-height: var(--btn-h-sm); }
.wo-request-type, .wo-request-status { font-size: var(--fs-sm); font-weight: var(--fw-bold); text-transform: uppercase; letter-spacing: 0.04em; }
.wo-request-stocked .wo-request-status { color: var(--color-success); }
.wo-request-open .wo-request-status { color: var(--color-error); }
.wo-request-resolved { opacity: 0.75; }
.wo-request-message:empty { display: none; }
```

- [ ] **Step 6: Verify**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_catalogue_requests.py tests/test_material_requests.py tests/test_work_orders_router.py -q` — Expected: PASS (the solo-card test may already fail on main; see Global Constraints).
Run: `for f in backend/static/views/workOrderRequests.js backend/static/views/workOrders.js backend/static/views/catalogueRequest.js backend/static/main.js; do node --check "$f" || echo "FAIL $f"; done`.
`wc -l backend/static/views/workOrderRequests.js` — Expected: under 500.
Manual (user): open a work order card as a Technician → Request card after Materials, before Labor; pick an item at 0 → send → `Request sent. Staff have been notified.`; send again → `Updated your earlier request.`; empty search shows `Can't find it? Request it for the catalogue`; after a TechFM OA restocks or presses Mark stocked & notify, the Materials card shows the green line; tapping Add requested material prefills the add row; Add resolves the request and the line vanishes.

- [ ] **Step 7: Commit**

```bash
git add backend/static/views/workOrderRequests.js backend/static/views/workOrders.js backend/static/views/catalogueRequest.js backend/static/main.js backend/static/styles.css backend/app/schemas/user_requests.py backend/tests/test_catalogue_requests.py backend/tests/test_material_requests.py
git commit -m "add the Request card and one-tap stocked lines to the work-order card

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Rj5dKhZSJLx5wvJMfBTimY"
```

---

### Task 13: Frontend — the Hub "Requested material in stock" section

**Why now:** a read of state Tasks 6-12 produce; the payload field landed in Task 10.

**Files:**
- Modify: `backend/static/views/hubTechnician.js:146-163` (`mountHubDashboard`)
- Modify: `backend/static/views/userHub.js:31-36,533-550` (event constant + subscription)
- Modify: `backend/static/styles.css`
- Test: `backend/tests/test_catalogue_requests.py` (source pins)

**Interfaces:**
- Consumes: `payload.stocked_requests` (Task 10 schema).
- Produces: `stockedRequestsHtml(stockedRequests)` at the top of the Dashboard tab for every role; omitted (empty string) when the list is empty; each row links to `/workorder_card/{number}` through the existing `focusWorkOrderNumber` path.

- [ ] **Step 1: Write the failing pins**

Append to `backend/tests/test_catalogue_requests.py`:

```python
def test_the_hub_dashboard_lists_stocked_requests_first_and_refreshes_live():
    tech = _src("views/hubTechnician.js")
    assert "Requested material in stock" in tech
    assert "stockedRequestsHtml(payload.stocked_requests)" in tech
    assert "hub-stocked-requests" in tech
    hub = _src("views/userHub.js")
    assert 'const USER_REQUEST_CHANGED_EVENT = "user_request.changed";' in hub
    assert "subscribe(USER_REQUEST_CHANGED_EVENT" in hub
```

Run `-k hub_dashboard_lists` — Expected: FAIL.

- [ ] **Step 2: Render the section**

In `backend/static/views/hubTechnician.js`, before `mountHubDashboard`:

```js
// The persistent half of the stocked notification: a push is gone once
// swiped; this stays until somebody adds the material. Omitted, not rendered
// empty -- a Dashboard that opens with "nothing here" says nothing useful.
function stockedRequestsHtml(stockedRequests) {
  if (!stockedRequests || !stockedRequests.length) return "";
  const rows = stockedRequests
    .map(
      (row) => `<li class="hub-stocked-request">
        <span class="hub-stocked-item">${escapeHtml(row.item_name)}</span>
        <button type="button" class="hub-link-btn hub-stocked-wo" data-number="${escapeHtml(row.work_order_number)}">${escapeHtml(row.work_order_number)}</button>
        <span class="hint">requested ${escapeHtml(row.quantity)}${row.stocked_at ? ` · stocked ${escapeHtml(new Date(row.stocked_at).toLocaleString())}` : ""}</span>
      </li>`
    )
    .join("");
  return `
    <section class="hub-stocked-requests">
      <p class="hub-tile-label">Requested material in stock</p>
      <ul class="hub-stocked-list">${rows}</ul>
    </section>`;
}
```

In `mountHubDashboard`, make the section the first thing in the container:

```js
  container.innerHTML =
    stockedRequestsHtml(payload.stocked_requests) +
    `<div id="hub-priorities-mount"></div>` +
    ...
```

and after the timeline-block loop add the click wiring (the same hand-off `mountHubWorkOrders` uses):

```js
  container.querySelectorAll(".hub-stocked-wo").forEach((btn) => {
    btn.addEventListener("click", () => {
      focusWorkOrderNumber(btn.dataset.number);
      showPage("work-orders");
    });
  });
```

(Same order as `mountHubWorkOrders` at line ~205: focus first, then `showPage`, so the pending number is armed before the page loader runs.)

- [ ] **Step 3: Live refresh**

In `backend/static/views/userHub.js`, beside the other event constants:

```js
const USER_REQUEST_CHANGED_EVENT = "user_request.changed";
```

and beside the other subscriptions:

```js
// A request was stocked, added, cancelled, or reopened: the Dashboard's
// "Requested material in stock" rows come from the personal payload, so
// refetch it. Background: a socket signal, not a user action.
subscribe(USER_REQUEST_CHANGED_EVENT, ({ activePage }) => {
  if (activePage !== HUB_PAGE) return;
  void refreshPersonal({ background: true });
});
```

- [ ] **Step 4: CSS**

Append to `backend/static/styles.css` near `.hub-attention`:

```css
.hub-stocked-requests { margin-bottom: var(--space-4); }
.hub-stocked-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--space-2); }
.hub-stocked-request {
    display: flex; align-items: center; gap: var(--space-3); flex-wrap: wrap;
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--color-success); border-radius: var(--radius-sm);
    background: var(--panel-nested);
}
.hub-stocked-item { font-weight: var(--fw-semibold); }
```

`.hub-link-btn` does not exist yet (verified); add it beside the block above: `.hub-link-btn { background: none; border: none; padding: 0; margin: 0; min-height: 0; color: var(--color-brand); text-decoration: underline; cursor: pointer; font: inherit; }`.

- [ ] **Step 5: Verify**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_catalogue_requests.py -q` — Expected: PASS.
Run: `node --check backend/static/views/hubTechnician.js && node --check backend/static/views/userHub.js`.
Manual (user): as the assigned Technician, after a restock the Hub Dashboard opens with the green section at the top; after Add requested material it is gone without a reload; a TechFM OA sees every stocked request there.

- [ ] **Step 6: Commit**

```bash
git add backend/static/views/hubTechnician.js backend/static/views/userHub.js backend/static/styles.css backend/tests/test_catalogue_requests.py
git commit -m "show stocked material requests at the top of the hub dashboard

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Rj5dKhZSJLx5wvJMfBTimY"
```

---

### Task 14: Docs and the manual phone check

**Why last:** these describe the finished shape. `notification-events.md` was already updated in Task 6; this task covers the rest. Follow the conventions in `CLAUDE.md` → Documentation conventions: current truth only, tables for enumerable facts, delete anything now stale in the same edit.

**Files:**
- Modify: `docs/current-state.md` (lines 18 + 1557 Alembic head; Task Routing Map rows 97, 101; Roles And Access rows ~730-731; `user_requests` data model 959-987; Frontend Feature Context "User Requests" paragraph ~1442-1452 and the Work Orders/Hub paragraphs; Test Map rows; Migration History table)
- Modify: `docs/endpoint-map.md` (Master Endpoint Index rows 67-68c; `### User requests` flow 203-210; contracts 502-530; Real-time table ~709-716; Error Catalog 923; Per-Table Index for `user_requests`)
- Modify: `docs/open-work.md` (N11 item 4 → retired; N-ITEM-RESTORE note; SEC-021 → done)
- Modify: `docs/adding-a-notification-trigger.md` (`## Currently wired` list)

- [ ] **Step 1: `current-state.md`**

- Lines 18 and 1557: Alembic head is **`d1e3f5a7b9c2`** (36 revisions). Migration History table: add `| d1e3f5a7b9c2 | rename user_requests.request_type item_request → catalogue_request (data only) |` and, if `c6e8a0b2d4f7` is missing from that table, add it too.
- Task Routing Map row 97 (Low stock): `routers/_low_stock.py` → `routers/_stock_events.py`. Row 101 (User Requests): add `domain/material_requests.py`, `services/material_requests.py`, `routers/_stock_events.py`, `static/views/workOrderRequests.js`, `static/views/catalogueRequest.js` (replacing `itemRequest.js`); tests `test_catalogue_requests.py` (replacing `test_item_requests.py`), `test_material_requests.py`, `test_material_requests_domain.py`, `test_stock_events_flush.py`.
- Roles And Access: replace the "File an item request" row with

```
| File a material or catalogue request | any authenticated user who can see the work order (material) / any authenticated user (catalogue) |
| Cancel own open material request | the filer |
| Mark a material request stocked & notify | techfm_oa+ |
| Read a work order's requests | whoever can see the work order |
| Add from a stocked Materials line | whoever can add materials |
```

- `### user_requests` rules: replace the first bullet with

```
- Types: `inventory_recount`, `missing_item_price`, `catalogue_request` (no
  catalogue row; NULL `item_id` until fulfilled), `material_request` (a
  catalogue item at `<= 0` on the shelf; `item_id` and `work_order_id`
  required). Statuses `open`/`resolved`; `material_request` alone also uses
  `stocked`. Vocabulary is owned by `domain/material_requests.py`; no CHECK.
- Material request lifecycle: one live row per (work order, item); a second
  filing overwrites quantity/link/note. Any stock write taking on-hand from
  `<= 0` to `> 0` moves every open request for that item to `stocked` in the
  same transaction and pushes `material_request.stocked` to the crew at that
  moment + the filer; `> 0` to `<= 0` sends `stocked` back to `open`
  silently. `POST /user-requests/{id}/mark-stocked` (TechFM OA+) fires the
  same transition at any on-hand. Adding the material from the stocked
  Materials line resolves it (`Added to {number}.`, `details.added_quantity`).
  Stocking against an archived work order resolves with a note and notifies
  nobody. Fulfilling a catalogue request whose item ends `<= 0` auto-files a
  material request on that work order (`origin = catalogue_fulfilment`, no
  filing push).
```

- Frontend Feature Context, "User Requests:" paragraph → four type tabs with open counts, status control per tab (Material adds Stocked), material card actions, the manual-fire tip. Work Orders paragraph: add one sentence — the card has a collapsible **Request** card (after Materials) filing material requests and listing this work order's material/catalogue requests, and the Materials card shows a one-tap `Add requested material` line per stocked request. Hub paragraph: "Dashboard opens with **Requested material in stock** rows (associated users; all TechFM OA+), refreshed by `user_request.changed`."
- Realtime sentence ~1499: add `user_request.changed` to the list of envelopes the app emits and where it is consumed.
- Test Map: add rows for `test_material_requests_domain.py`, `test_material_requests.py`, `test_stock_events_flush.py`; rename `test_item_requests.py` row to `test_catalogue_requests.py` ("+ migration round-trip + UI source pins").

- [ ] **Step 2: `endpoint-map.md`**

Master Endpoint Index: row 67 gate cell → `techfm_oa+ (status=open|stocked|resolved, type=)`; row 68a → `POST /user-requests/catalogue-request` … `apiCreateCatalogueRequest` | `catalogueRequest.js`; row 68c → `user_requests.fulfill_catalogue_request` (+ `material_requests.create_or_update` chain); add rows:

```
| 68d | POST | `/user-requests/material-request` | session, WO-visible | `user_requests.py` → `work_orders.get_visible_work_order` + `material_requests.create_or_update` (+ `notifications.notify_material_request_filed` on create) | user_requests (w), items (r, row lock), work_orders (r), push_subscriptions (r) | `apiCreateMaterialRequest` | `workOrderRequests.js` |
| 68e | POST | `/user-requests/{id}/mark-stocked` | techfm_oa+ | `user_requests.py` → `material_requests.mark_stocked` → `_stock_events.flush_stock_events` | user_requests (r/w, row lock), work_orders (r), work_order_technicians (r), push_subscriptions (r) | `apiMarkRequestStocked` | `userRequests.js` |
| 68f | POST | `/user-requests/{id}/cancel` | session, filer only | `user_requests.py` → `material_requests.cancel` | user_requests (r/w, row lock) | `apiCancelMaterialRequest` | `workOrderRequests.js` |
| 68g | GET | `/user-requests/counts` | techfm_oa+ | `user_requests.py` → `material_requests.open_counts` | user_requests (r) | `apiListUserRequestCounts` | `userRequests.js` |
| 72a | GET | `/work-orders/{id}/requests` | session scoped | `work_orders.py` → `work_orders.get_visible_work_order` + `material_requests.list_for_work_order` | user_requests (r), items (r), work_orders (r), users (r) | `apiListWorkOrderRequests` | `workOrderRequests.js` |
```

Row for `POST /work-orders/{id}/items`: add `material_request_id?` to the service cell (`+ material_requests.resolve_from_line`) and `user_requests (w when material_request_id)` to Tables. Every stock-write row's Tables cell: add `user_requests (w: material_request stocked/open edges)`.

`### User requests` flow: add three bullets (file/dedupe; stocked edge + manual fire + flush; add-from-line resolves; `PATCH status=stocked` is 422).

Contracts: rename `ItemRequestCreate`/`ItemRequestFulfill` entries; `source` gains `"request_card"`; add **`MaterialRequestCreate`** (`item_id: UUID`, `work_order_id: UUID`, `quantity: Decimal=1 (>0)`, `product_link: str?` (≤2000, http(s) only), `note: str?` (≤500)); `UserRequestResponse` gains `item_quantity: Decimal?` and `updated: bool=false`; `WorkOrderItemCreate` gains `material_request_id: UUID?=null`; `HubResponse` gains `stocked_requests: list[HubStockedRequest]` with the six fields.

Real-time table: add `| user_request.changed | Technician+ | filing, mark-stocked, cancel, PATCH, fulfil, every stock write that crosses zero for a requested item, add-from-line | userRequests.js, userHub.js, workOrderRequests.js |` and change the "three types" wording to "five".

Error Catalog: `ItemRequestStateError` cell → add "mark-stocked on a non-open material request; cancel of a non-open one; add with a `material_request_id` that is not stocked / wrong work order / wrong item"; add `| MaterialRequestOwnershipError | 403 | cancelling a material request you did not file |`.

- [ ] **Step 3: `open-work.md`**

- N11: item (4) is now built for material requests — rewrite the list as four candidates and add one line: "(4) retired 2026-09-08: `material_request.filed` / `.stocked` shipped; a recount/missing-price push remains unbuilt and unrequested."
- N-ITEM-RESTORE: append "Also applies to the catalogue → material chain: a fulfilment that links an archived item is impossible today, so the chain never runs for one."
- SEC-021: mark `Done 2026-09-08` — `POST /user-requests/material-request` uses `get_visible_work_order`; the catalogue-request route still resolves by existence only (unchanged scope; note it explicitly so the item does not read as fully closed unless the executor also applies the reader there — **do not** widen scope; record the residual).

- [ ] **Step 4: `adding-a-notification-trigger.md`**

`## Currently wired`: add the two events with their trigger sites; under *What you can address a notification to* add a row `| material_requests.StockedFact | services/material_requests.py | frozen assignee/supervisor/requester ids for a request that just became stocked |`. In the "three places" preamble, mention the buffered variant: "Events raised several frames below a router (stock writes) buffer plain facts in a ContextVar and are drained by `routers/_stock_events.py`; see `services/low_stock.py` and `services/material_requests.py`."

- [ ] **Step 5: Word budgets and staleness**

Run: `wc -w docs/current-state.md docs/endpoint-map.md docs/open-work.md` — budgets 16,500 / 11,000 / 12,000. If a file breaches, delete something stale in the same edit (candidates: any remaining "item request" narrative, the superseded Alembic-head sentence) before trimming anything load-bearing.

- [ ] **Step 6: Manual phone verification (the user's step, per the trigger procedure §Step 5)**

Hand the user this checklist — do not start the preview server yourself:

1. Two phones/accounts, both subscribed to push: A = Technician assigned to WO-X, B = TechFM OA.
2. On A, open WO-X → Request → pick an item at 0 → Send. **B buzzes `Material requested` / `{name} is needed for WO-X.`** A does not.
3. On B, User Requests → Material tab shows `(1)`; card shows the request.
4. On B, Scan/Stock → Add Stock for that item. **A buzzes `Material in stock` / `{name} for WO-X is now in stock.`** A's Hub Dashboard shows the green row; WO-X Materials shows the green line.
5. On A, tap Add requested material → Add. Row and line vanish on both devices without reload; B's card is under Resolved with `Added to WO-X.`
6. Repeat 2, then on B press Mark stocked & notify with the item still at 0 → step 4's push arrives.

- [ ] **Step 7: Full suite and commit**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest -q` — Expected: PASS except the two known failures.

```bash
git add docs/current-state.md docs/endpoint-map.md docs/open-work.md docs/adding-a-notification-trigger.md
git commit -m "document material requests, the catalogue rename, and the stock-events flush

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Rj5dKhZSJLx5wvJMfBTimY"
```

Then tell the user the branch is ready and that pushing `main` deploys (CI gate memory) — the push is their call.

---

## Self-review

**Spec coverage** (section → task): §1 decisions → Global Constraints + Tasks 4, 6, 7; §2.1-2.2 data model → Tasks 2, 4; §2.3 migration → Task 1; §2.4 domain → Task 2; §3.1 filing → Task 7; §3.2 automatic stocking → Tasks 4, 6; §3.3 draining → Task 6; §3.4 manual fire → Tasks 4, 7; §3.5 add from line → Task 8; §3.6 cancel → Tasks 4, 7; §3.7 reopen clears stamps → Task 4 step 5; §3.8 chain → Task 9; §3.9 state table → covered across 4/6/7/8; §4 notifications → Tasks 3, 5, 6 (registry); §4.1 realtime → Tasks 3, 6, 7, 8, 11, 12, 13; §5.1 Request card → Task 12; §5.2 stocked lines → Task 12; §5.3 catalogue prompt → Tasks 1, 12; §6 User Requests page → Task 11; §7 Hub → Tasks 10, 13; §8 rename → Task 1 (+ docs Task 14); §9 roles → role-gate tests in Tasks 7, 8; §10 errors → Tasks 4, 7, 8 tests; §11 testing table → every named file exists in the plan (`test_hub_service.py` extended rather than a new file, as the spec lists it); §12 out of scope — nothing added.

**Deliberate deviations from the spec, recorded once:** (a) `hasUnsavedInput` does not exist; the equivalent is `EDITOR_SECTIONS`. (b) The status vocabulary is defined in the domain module and re-exported by the service, not the reverse, so the service module can honour the "imports nothing from `app.services`" rule. (c) A public `get_visible_work_order` wraps `_get_visible` rather than calling the private name cross-module. (d) The hub Exceptions tile's `item_requests` field is renamed to `catalogue_requests` under the "everywhere" rename rule. (e) `UserRequestResponse.item_quantity` is populated for every response, not only the filing one, because the stocked line and the staff card both need it.

**Placeholder scan:** no TBD/TODO; every code step has its code; every test step has its command and expected result. The one "match the existing call" instruction (Task 13's hub hand-off) was checked against `hubTechnician.js:205` and the order written into the step.

**Type consistency:** `StockedFact` fields (`request_id, item_name, work_order_id, work_order_number, assignee_ids, supervisor_id, requester_id`) match across Tasks 4, 5, 6; `create_or_update(db, *, item_id, work_order, quantity, product_link, note, created_by_id, origin) -> (request, created)` is called identically in Tasks 4, 7, 9, 10; `flush_stock_events(db, background)` / `emit_user_request_changed(request_id)` are the only names used in Tasks 6-8; `build_response(request, *, skipped, item_quantity, updated)` is used in Tasks 7 and 8; `apiAddWorkOrderItem(workOrderId, { itemId, quantity, materialRequestId })` matches Tasks 11 and 12; `payload.stocked_requests[*].{request_id,item_name,work_order_id,work_order_number,quantity,stocked_at}` matches Tasks 10 and 13.
