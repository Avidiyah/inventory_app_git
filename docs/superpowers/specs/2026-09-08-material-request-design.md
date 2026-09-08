# Material Request — design

A crew member on a work order needs a catalogue item the shelf does not have.
They file a **Material Request** from a new collapsible **Request** card on the
work order. TechFM OA+ are pushed at once. When the item is stocked, every
user tied to that work order is pushed and sees a persistent row on their
User Hub dashboard, and the work order's Materials card grows a one-tap line
that adds the requested material. The existing "item request" (material with
no catalogue row at all) is renamed **Catalogue Request** and remains a
separate flow, reachable from the same places plus the new card.

## 1. Decisions

Settled in brainstorming 2026-09-08; recorded so they are not re-argued.

| Question | Decision |
| --- | --- |
| Two request kinds | **Material Request** = catalogue item, shelf empty. **Catalogue Request** = no catalogue row (today's `item_request`). Never merged. |
| "Not in stock" | On-hand ≤ 0. Advisory only: a request on an item with alleged stock still files and pushes, because counts are sometimes wrong; staff verify and fire manually. |
| What the form takes | Item (catalogue search), quantity (required, default 1, decimals), optional product link. |
| Who files | Anyone who can see the work order (same rule as Catalogue Request). |
| Filing push | One new event `material_request.filed` to TechFM OA+ incl. actor. Low stock is **not** re-fired separately. |
| Low-stock rule | Unchanged: edge only, re-arms on restock. The filing push is the "each subsequent time" the owner asked for. |
| Stocked event | Any write taking on-hand from ≤ 0 to > 0: Add Stock, upward correction, voided dispense, Mass Stage return, work-order line reversal. |
| Manual fire | TechFM OA+ button **Mark stocked & notify** on the request card, allowed at any on-hand. |
| Stocked audience | Crew at the moment of stocking (assigned technicians + routed supervisor) + original requester. Actor not suppressed. |
| Stocked text | Title `Material in stock` · Body `{name} for {number} is now in stock.` |
| Filing text | Title `Material requested` · Body `{name} is needed for {number}.` |
| Lifecycle | `open → stocked → resolved`. Back to `open` if the item returns to ≤ 0 while stocked; re-fires on the next restock. |
| Dedupe | One open/stocked request per (work order, item). A second filing updates quantity/link/note. Other work orders get their own. |
| Resolution | Adding the material from the stocked line resolves it (any quantity). TechFM OA+ resolve/reopen on the page. Requester cancels own open request → `resolved`, note `Cancelled by requester`. |
| Closed WO at stocking | Auto-resolve with note, notify nobody. |
| Catalogue → Material chain | Fulfilling a Catalogue Request whose item ends at ≤ 0 auto-files a Material Request on that WO. Requester = the catalogue filer. No filing push. |
| Materials-card line | Only while `stocked`. Shows name, requested qty, on hand, requester. Anyone who can add materials can tap. Add follows the WO's entry mode, qty prefilled and editable. |
| Hub indicator | Section at the top of the Dashboard tab on all three role dashboards; refreshes live. Shown to associated users **and** every TechFM OA+. Cleared when the request leaves `stocked`. |
| User Requests page | Four type tabs with open counts: Material, Catalogue, Stock recounts, Missing price/link. Status control inside each tab; the Material tab offers Open / Stocked / Resolved. |
| Rename scope | Everywhere: `request_type` value, route, JS wrapper, labels, docs. Migration rewrites existing rows. |
| Detection architecture | Atomic in-service transition at the eight existing `low_stock.record` sites, buffered facts drained by the router flush (approach 1). |

## 2. Data model

One table, no new tables. `user_requests` gains no columns; the new type
uses the existing `item_id`, `work_order_id`, `status`, and `details`.

### 2.1 Type keys

| Key | Meaning |
| --- | --- |
| `material_request` | **new** — a catalogue item, out on the shelf |
| `catalogue_request` | **renamed** from `item_request` — no catalogue row |
| `inventory_recount`, `missing_item_price` | unchanged |

### 2.2 `material_request` row

| Column | Value |
| --- | --- |
| `item_id` | the requested item, never NULL. This is what distinguishes it from a Catalogue Request, whose `item_id` is NULL until fulfilled. |
| `work_order_id` | required. A Material Request without a work order has no crew to notify and no Materials card to land on, so the schema refuses it. |
| `status` | `open`, `stocked`, `resolved`. `stocked` is a **new status value** used by this type only. Every other type keeps `open`/`resolved`. |
| `message` | `Please stock this item` |
| `details.quantity` | requested quantity, string, > 0 |
| `details.product_link` | optional URL supplied by the requester (purpose: tells staff where to buy it) |
| `details.note` | optional free text |
| `details.work_order_number` | frozen at filing, for the fallback the response already uses |
| `details.stocked_at` | ISO timestamp of the latest `open → stocked`; cleared on `stocked → open` |
| `details.stocked_by` | `"auto"` or the user id that pressed Mark stocked & notify |
| `details.stock_cycles` | integer, how many times it has gone `open → stocked`; purpose: the card can say "stocked twice, still not added" |
| `details.origin` | `"request_card"` or `"catalogue_fulfilment"` |
| `details.added_quantity` | set at resolution from the stocked line: the quantity actually added |

`EDITABLE_DETAILS[material_request] = {quantity, product_link, note}`.

### 2.3 Migration

One Alembic revision:

1. `UPDATE user_requests SET request_type='catalogue_request' WHERE request_type='item_request'`; downgrade reverses it.
2. No DDL. `status` is `Text`, so `stocked` needs no schema change. A `CHECK` is deliberately not added; the domain layer owns the vocabulary, matching how the other statuses are enforced.

### 2.4 Domain module `domain/material_requests.py` (pure)

| Function | Purpose |
| --- | --- |
| `restocked(quantity_before, quantity_after) -> bool` | the single edge: `before <= 0 and after > 0` |
| `went_out(quantity_before, quantity_after) -> bool` | the reverse edge: `before > 0 and after <= 0`, used to send a stocked request back to open |
| `STATUS_STOCKED = "stocked"` | the third status, defined beside the two in `services/user_requests.py` and re-exported there |

Pure, no ORM, so both edges are tested in a domain test without a database,
like `domain/low_stock.py`.

## 3. Lifecycle and triggers

### 3.1 Filing — `POST /user-requests/material-request`

Open to any authenticated user. Body: `item_id`, `work_order_id`, `quantity`,
optional `product_link`, optional `note`.

1. Resolve the work order through `wo_service._get_visible(db, id, user)` so a Technician can only file against a job they are assigned to (the SEC-021 rule, applied here from day one rather than backfilled).
2. Reject an archived work order (404, same shape as Catalogue Request).
3. Lock the item row (`FOR UPDATE`), and read `item.quantity` for the response only. On-hand is never a gate.
4. `services/material_requests.create_or_update(db, ...)`: if an `open` or `stocked` request exists for `(work_order_id, item_id)`, overwrite `quantity`, `product_link`, `note` and return it with `updated=True`; otherwise insert.
5. Commit, then the router calls `notifications.notify_material_request_filed` **only for a new row**. An update re-pushes nobody; the staff already know.
6. Response: the `UserRequestResponse` plus `item_quantity` (so the card can say "3 on hand — staff will verify") and `updated`.

### 3.2 Automatic stocking — the eight stock-write sites

`services/material_requests.record_stock_change(db, item, quantity_before)` is
called immediately after every existing `low_stock.record(item, quantity_before=...)`
call (transactions ×3, mass_staging ×2, work_orders ×3). It imports models only
— `UserRequest`, `WorkOrder`, `work_order_technicians` — and nothing from
`app.services`, so it cannot close the import ring `low_stock` was designed
around.

- `restocked` edge: every `open` request for `item.id` becomes `stocked` in the **same transaction** as the stock write. For each, the function appends a plain-value `StockedFact(request_id, item_name, work_order_id, work_order_number, recipient_ids)` to a ContextVar buffer. Recipients are read now, while the session is alive: assigned technician ids (plural table with the legacy singular folded in, the same rule as `_assigned_technician_ids`), the routed `supervisor_id`, and `created_by_id`, deduplicated, actor included. If the work order is archived the request is instead set `resolved` with note `Work order was closed before the item was stocked.` and no fact is buffered.
- `went_out` edge: every `stocked` request for the item goes back to `open`; `stocked_at` cleared. Nothing buffered, nobody notified — the crew learns from the Hub row disappearing.
- Neither edge: return immediately. The common case costs one comparison.

The buffer follows `services/low_stock.py` exactly: one ContextVar, a 500-entry
ceiling, `drain()` returns a fresh list.

### 3.3 Draining — `routers/_low_stock.py` becomes `routers/_stock_events.py`

`flush_low_stock` is renamed `flush_stock_events` and does one more thing after
the low-stock branch: drain the stocked buffer, call
`notifications.notify_material_request_stocked` per fact, and emit
`user_request.changed` per request. Every caller already invokes this helper on
its success path after commit, so no route needs a second line. Swallow-and-log
contract unchanged: a failure here costs a push, never the write.

### 3.4 Manual stocking — `POST /user-requests/{id}/mark-stocked`

TechFM OA+. Calls the same service transition as 3.2 for one request, then
commit, then the same notify. Allowed while `open` at any on-hand. 409 when
`stocked` or `resolved`. Purpose: the shelf count in the app is sometimes
wrong; staff count, and if the item is really there they fire the crew's
notification without faking a stock transaction. A request fired manually
while the app still shows ≤ 0 stays `stocked` through a later ≤0 → >0 write:
the crew was already told, and only a `went_out` edge can send it back.

### 3.5 Adding from the stocked line — `POST /work-orders/{id}/items` with `material_request_id`

The existing add-line route accepts one new optional body field. When present:

1. The request must be `stocked`, belong to this work order, and name this item, else 409.
2. The line is added exactly as today (`add_work_order_item`, entry mode from the work order; a dispense that would go short still raises the recount request as it does now).
3. In the same transaction the request becomes `resolved`, `resolution_note` = `Added to {number}.`, `details.added_quantity` = the quantity added.
4. After commit: `user_request.changed` emit so every Hub dashboard and the User Requests page drop it.

### 3.6 Cancel — `POST /user-requests/{id}/cancel`

Any authenticated user, but only the request's own `created_by_id`, and only
while `open` (a stocked request has already cost staff work; cancelling it is
the page's job). Sets `resolved` with note `Cancelled by requester`.

### 3.7 Page resolve/reopen — `PATCH /user-requests/{id}`

Unchanged route. For a material request `status` may be `open` or `resolved`
only; `stocked` is reachable solely through 3.2 and 3.4. Reopening a resolved
material request lands on `open` and clears `stocked_at`.

### 3.8 Catalogue → Material chain

In `fulfill_item_request` (renamed `fulfill_catalogue_request`), after each
target request is resolved and its retroactive line attached, if the item's
quantity is ≤ 0 and the work order is live, call
`material_requests.create_or_update` with `origin="catalogue_fulfilment"`,
`created_by_id` = the catalogue request's filer, quantity = the catalogue
request's quantity. Same transaction as the fulfilment. No filing push; the
fulfilling TechFM OA is standing in the queue. The stocked push fires later
like any other.

### 3.9 State table

| From | Event | To | Side effects |
| --- | --- | --- | --- |
| — | filing (new) | open | filed push to TechFM OA+ |
| — | filing (duplicate) | unchanged | fields overwritten, no push |
| open | item ≤0 → >0 | stocked | stocked push, Hub row, Materials line |
| open | Mark stocked & notify | stocked | same |
| open | requester cancel | resolved | note |
| open / stocked | item stocked, WO archived | resolved | note, no push |
| stocked | item >0 → ≤0 | open | Hub row and line vanish |
| stocked | Add from Materials line | resolved | line added, note, `added_quantity` |
| open / stocked | page Mark resolved | resolved | note |
| resolved | page Reopen | open | stamps cleared |

## 4. Notifications

Two new push events, registered in `docs/notification-events.md` in the same
commit that wires them.

| Event | Raised by | Trigger site | Told | Text |
| --- | --- | --- | --- | --- |
| `material_request.filed` | any user who can see the WO | `POST /user-requests/material-request` (new rows only) | everyone at `MATERIAL_REQUEST_AUDIENCE_MIN_ROLE` (**TechFM OA**+), **including the actor** | `Material requested` / `{name} is needed for {number}.` |
| `material_request.stocked` | any stock write, or TechFM OA+ manual fire | the eight stock-write routes via `flush_stock_events`; `POST /user-requests/{id}/mark-stocked` | assigned technicians + routed supervisor at stocking time + `created_by_id`, **actor not suppressed** | `Material in stock` / `{name} for {number} is now in stock.` |

Why the actor is not suppressed in either: both are state alarms, not reports
of somebody's action. The filer wants confirmation their request went up the
chain; a supervisor who restocks and is also on the crew is exactly the person
who should see the line is ready. Expressed as `actor_id=None` in both
recipient rules so `select_recipients` still dedups and drops `None`.

`build_message` needs no wider signature: both bodies use `name` and `number`,
already allowed. No link, price, note, or quantity reaches a lock screen.

Rules in `domain/notifications.py`: `recipients_for_material_request_filed(recipient_ids)`
and `recipients_for_material_request_stocked(assignee_ids, supervisor_id, requester_id)`.
Service functions in `services/notifications.py` follow the existing
`_dispatch`/`_schedule` shape and read nothing lazy: 3.2 already froze every
id into the fact.

### 4.1 Realtime

One new envelope, `user_request.changed`, `entity_id` = request id, audience
**Technician** and above in `_AUDIENCE_MIN_ROLE`. Emitted on every transition
in §3.9. Subscribers: the User Hub dashboard (re-fetch the stocked section),
the User Requests page (reload when visible), and the open work-order card
(refresh the Materials and Request sections). A technician receives envelopes
for requests they cannot see; the re-fetch is authorised server-side, so the
mis-fit costs one request and discloses nothing.

## 5. Work-order card

### 5.1 New collapsible **Request** card

Placed after Materials, before Labor, as a `details.wo-section-card
wo-request-section` so `hasUnsavedInput` and `refreshCard` pick it up with one
selector addition.

Contents, top to bottom:

1. **Form.** Item search (the same `filterRanked` over `allItems` the Materials card uses), quantity (`min 0.01, step any, value 1`), product link (`type=url`, optional), note (optional), **Send request**. Picking an item shows its on-hand beside the field; on-hand above zero shows the hint "Staff will verify the count" and does not block. Empty search shows the Catalogue Request prompt with `source: "request_card"`, `workOrderId` set. After sending: `Request sent. Staff have been notified.`; a duplicate reply says `Updated your earlier request.`
2. **This work order's requests.** Every `material_request` and `catalogue_request` row for this WO, newest first, from a new `GET /work-orders/{id}/requests` (visibility-gated like the card itself). Each line: type tag, item name or searched text, quantity, status badge (`Open`, `Stocked`, `Resolved`), requester, filed time; a **Cancel** button on the current user's own open material requests. Resolved ones collapse under "Show resolved (n)". Purpose: the crew sees what they are waiting on without leaving the job.

Visible to every role that can open the card. Technicians file and cancel their own; nothing else is role-gated here.

### 5.2 Materials card — stocked lines

Above the add-material row, one `.wo-requested-line` per `stocked` request
on this WO: `{name} · requested {qty} · on hand {n} · by {requester}` and a
button **Add requested material** that prefills the existing add row
(item picked, qty) and stamps `material_request_id` on the container so the
Add sends it. Anyone who sees the Add row sees the button. Lines exist only
while `stocked`; an open request leaves the Materials card untouched, exactly
as the owner asked. Line data comes from the same `GET /work-orders/{id}/requests`
the Request card uses, fetched once per card open and refreshed by
`user_request.changed`.

### 5.3 Catalogue Request prompt

`itemRequest.js` becomes `catalogueRequest.js`; button text `Can't find it?
Request it for the catalogue`; sent text `Catalogue request sent to staff.`
`SOURCES` gains `request_card`. Mounted in three places: Materials empty
search, Find Item empty results, Request-card empty search.

## 6. User Requests page

### 6.1 Tabs

The Type dropdown is replaced by a tab strip in the same `role="tablist"`
pattern the User Hub uses:

| Tab | `request_type` | Status control |
| --- | --- | --- |
| Material requests | `material_request` | Open / Stocked / Resolved, default Open |
| Catalogue requests | `catalogue_request` | Open / Resolved |
| Stock recounts | `inventory_recount` | Open / Resolved |
| Missing price / link | `missing_item_price` | Open / Resolved |

Each tab label carries an open count from a new `GET /user-requests/counts`
(`{type: {open: n, stocked: n}}`), refreshed on load and on
`user_request.changed`. The list route gains `type=` and accepts
`status=stocked`. Default tab: Material requests. The page-level hint is
rewritten to describe four kinds in one sentence each.

### 6.2 Material request card

Heading: item name. Body: barcode, work order, quantity, product link (as a
link, `rel="noopener"`), note, on hand now, requested by, filed, stocked
(when set), stock cycles when > 1. Actions:

| Status | Actions |
| --- | --- |
| open | **Mark stocked & notify**, Mark resolved, Edit |
| stocked | Mark resolved, Edit, hint "Waiting for the crew to add it to {number}" |
| resolved | Reopen, Edit |

Edit exposes quantity, product link, note, message. A tip `requests.stocked`
explains the manual fire.

### 6.3 Catalogue request card

Unchanged behaviour; label `Catalogue request`; fulfilment hint gains "If the
item has no stock, a Material Request is opened for the crew automatically."

## 7. User Hub

New section **Requested material in stock** at the top of the Dashboard tab
on the Technician, Supervisor, and Admin dashboards. Data: a `stocked_requests`
list added to the existing `GET /hub` payload, built in `services/hub.py`:

- for every user: `stocked` requests whose WO they are assigned to, routed
  on, or which they filed;
- for TechFM OA+: additionally every `stocked` request.

Each row: item name, work-order number (a link to `/workorder_card/{number}`),
requested quantity, stocked time. Empty: the section is omitted, not rendered
empty. Rows disappear when the request leaves `stocked` — nothing is
dismissed by hand, so nothing is stored per user. The section re-fetches on
`user_request.changed`. Purpose: a push is gone once swiped; this is the
place that keeps saying "it is here, add it" until somebody does.

## 8. Rename: `item_request` → `catalogue_request`

| Layer | Change |
| --- | --- |
| DB | migration in §2.3 |
| Service | constant `REQUEST_CATALOGUE`, functions `create_catalogue_request`, `fulfill_catalogue_request`, `find_sibling_catalogue_requests` |
| Routes | `POST /user-requests/catalogue-request`; `/siblings` and `/fulfill` unchanged paths |
| Schemas | `CatalogueRequestCreate`, `CatalogueRequestFulfill` |
| JS | `apiCreateCatalogueRequest`, `apiFulfillCatalogueRequest`; view file `catalogueRequest.js` |
| Text | every "item request" string becomes "Catalogue request"; the Request-card and Materials-card prompts say "for the catalogue" |
| Docs | `current-state.md`, `endpoint-map.md`, `notification-events.md`, `open-work.md` (retire N11 item 4; note N-ITEM-RESTORE now also applies to the chain) |
| Tests | `test_item_requests.py` → `test_catalogue_requests.py` |

No compatibility alias for the old route: the frontend ships in the same
deploy.

## 9. Roles summary

| Action | Minimum |
| --- | --- |
| File material or catalogue request | any authenticated user who can see the WO |
| Cancel own open material request | the filer |
| Read a WO's requests list | whoever can see the WO |
| Add from a stocked line | whoever can add materials (Technician+ on a visible WO) |
| List, counts, edit, resolve, reopen, Mark stocked & notify, fulfil | TechFM OA |
| Receive filed push | TechFM OA+ |
| Receive stocked push | crew + supervisor + requester |
| Hub section | associated users; all TechFM OA+ |

`test_route_role_gates.py` gains a row per new route.

## 10. Error handling

| Case | Result |
| --- | --- |
| Material request on archived or invisible WO | 404 `Work order not found.` |
| Item id unknown or archived | 404 `Item not found.` |
| Quantity ≤ 0, link not http(s), note > 500 | 422 |
| Mark stocked on non-open | 409 `ItemRequestStateError` |
| Cancel by non-filer or non-open | 403 / 409 |
| Add with a `material_request_id` that is not stocked / wrong WO / wrong item | 409 |
| `PATCH status=stocked` | 422 |
| Push or emit failure anywhere | logged, write already committed |
| Buffer over 500 facts in one request | warning, later crossings dropped (same as low stock) |

## 11. Testing

| File | Covers |
| --- | --- |
| `test_material_requests_domain.py` | both edges, incl. negative counts and exact zero |
| `test_material_requests.py` (DB) | file, dedupe-update, visibility gate, auto-stock on each of the five write kinds, back-to-open, archived-WO auto-resolve, manual fire, cancel rules, add-from-line resolves with `added_quantity`, catalogue chain files with the right requester, reopen clears stamps |
| `test_notifications_domain.py` | both recipient rules; actor kept; dedupe of supervisor-who-is-assignee |
| `test_notifications.py` | filed schedules once to TechFM OA+; stocked schedules once with frozen ids; nothing when empty |
| `test_stock_events_flush.py` | one request that crosses low **and** restocks a request drains both; a raise in one branch does not lose the other |
| `test_route_role_gates.py` | new routes |
| `test_hub_service.py` | `stocked_requests` per role |
| `test_catalogue_requests.py` | renamed suite green; migration round-trip |
| Manual (§ adding-a-notification-trigger step 5) | both pushes on a phone from a different account |

## 12. Out of scope

Purchase-order tracking, supplier data, per-user dismissal of Hub rows,
digests, a global "any work order" material request, and per-request
subscriptions. Item restore (N-ITEM-RESTORE) stays open.
