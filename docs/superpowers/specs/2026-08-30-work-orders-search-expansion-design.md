# Work Orders search expansion — location + task keyword search

Date: 2026-08-30
Status: draft, awaiting review

## Goal

The Work Orders page has one search bar that matches the work-order
number only. Add two more, each its own input doing its own thing:

- **Location search** — "2312" finds every work order with those digits
  anywhere in its location.
- **Task keyword search** — free-text keywords against the Task/Symptom
  field.

All three searches and the existing dropdown filters combine with AND,
like every filter on the page today.

## What exists today (review)

- `GET /work-orders/` (`backend/app/routers/work_orders.py:521`) takes
  `q` and hands it to `list_work_orders(search=q)`.
- `_apply_work_order_filters` (`backend/app/services/work_orders.py:1145`)
  turns `search` into a trimmed, LIKE-escaped `%…%` pattern via
  `_search_pattern` (L166) and applies it to **`WorkOrder.number` only**.
- The same helper serves `list_work_orders_for_export`, so the page's
  "Export filtered CSV" honors the same filters; the export route
  (L679) accepts its own `q`.
- Location data is split: imported rows carry the raw multi-line
  `location` text; hand-created rows carry structured `community` /
  `building_number` / `unit_number` instead. `_community_match` (L180)
  and the frontend `placeMeta` (workOrders.js:517) both already bridge
  the two shapes.
- "Tasks" is the `description` column — labeled "Symptom / task" in the
  UI and filled by the NetFacilities Task/Symptom enrichment. `notes`
  is a separate append-only log and is NOT part of this feature.
- Frontend: `#work-orders-search` sits in `.wo-number-search-row`
  (pages/work-orders.html:75) with a Search button; input is debounced
  250 ms, Enter/button fire immediately (workOrders.js:2580).
  `currentFilters()` collects everything; any truthy filter lifts the
  10-row browse cap so a search always returns the complete set.
  The number search alone additionally runs the exact-match archived
  lookup that offers Restore (Admin+).

## Design

### Backend

Two new optional query params on `GET /work-orders/` and
`GET /work-orders/export`:

- `location_q` — substring, case-insensitive, LIKE-escaped via the
  existing `_search_pattern`. Predicate: OR of `ilike` over
  `coalesce(location, '')`, `coalesce(community, '')`,
  `coalesce(building_number, '')`, `coalesce(unit_number, '')` — one
  bar finds both imported (raw text) and hand-created (structured)
  work orders, mirroring `_community_match` / `placeMeta`.
- `task_q` — substring, case-insensitive, LIKE-escaped, against
  `coalesce(description, '')` only.

Threading: router params -> `list_work_orders` /
`list_work_orders_for_export` keyword args (`location_search`,
`task_search`) -> `_apply_work_order_filters`. Both AND with all
existing predicates. No schema or model changes; no new indexes (the
number search is already an unindexed `ilike` of the same cost class,
and lists are server-scoped).

### Frontend

Two new inputs in the `wo-filter-grid` as ordinary `wo-filter-field`
entries (recommended placement — keeps the number-search row special,
since only it has the Search button and the archived-restore prompt):

- `#work-orders-location-search` — label "Location", placeholder
  "Search location".
- `#work-orders-task-search` — label "Task / symptom", placeholder
  "Search task keywords" (label matches the card's "Symptom / task"
  field so users connect the two).

Behavior, matching the number bar exactly except where noted:

- 250 ms debounce on input; Enter fires immediately. Both call plain
  `loadWorkOrders()` — **not** `checkArchivedSearch`, which stays a
  number-search-only behavior.
- `currentFilters()` gains `locationQ` / `taskQ`; `hasActiveFilters()`
  picks them up automatically, so either search lifts the browse cap
  and returns the complete matching set.
- "Clear filters" resets both (add to `resetFilterControls`).
- `apiListWorkOrders` and `apiExportWorkOrders` map them to
  `location_q` / `task_q`, so filtered CSV export keeps parity.

### Docs

Update `docs/endpoint-map.md` rows for `GET /work-orders/` and
`GET /work-orders/export` to name the two new filters. Vault mirror is
automated — no manual sync.

### Testing

Real-TestClient router tests (per the established FastAPI/TestClient
convention) in `backend/tests/test_work_orders_router.py`, service
tests in `test_work_orders_service.py`:

- `location_q` matches a substring of raw `location`; also matches
  structured `building_number` / `unit_number` / `community` on rows
  with no raw location.
- `task_q` matches a keyword inside `description`; misses `notes`.
- Both are case-insensitive and escape `%` / `_` literally.
- AND-composition: `q` + `location_q` + `task_q` together narrow, not
  widen; combined with `status` they still narrow.
- Blank/whitespace values are no-ops (same as `q`).
- Export route accepts both params and filters the CSV rows.
- Existing number-search and archived-restore tests stay green.

## Explicitly out of scope

- Searching `notes` (separate operational log).
- Any change to the number bar, `/work-orders/lookup`, or the
  archived-restore flow.
- The History page's own work-order filter.
- New DB indexes.

## Open questions (recommendations inline)

1. Placement: filter grid (recommended) vs. adding both to the
   number-search row. Grid keeps the special-cased number row clean.
2. Should task search also cover `notes`? Recommended no — different
   field with different semantics; easy follow-up if wanted.
3. Label wording: "Location" and "Task / symptom" as above, or
   something else?
