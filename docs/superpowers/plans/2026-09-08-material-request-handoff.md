# Material Request — Session Handoff (after Phase 3)

**Plan:** `docs/superpowers/plans/2026-09-08-material-request.md` · **Spec:** `docs/superpowers/specs/2026-09-08-material-request-design.md`
**Branch:** `main`, local only, **not pushed** (pushing deploys). `origin/main` is at `0b446ca`.

## Done (Tasks 1–10, one commit each)

| Commit | Task |
| --- | --- |
| `30d8229` | 1 — `item_request` → `catalogue_request` everywhere; migration `d1e3f5a7b9c2` applied locally |
| `4356413` | 2 — `domain/material_requests.py` (edges + vocabulary) |
| `14054ac` | 3 — two push events, `MATERIAL_REQUEST_AUDIENCE_MIN_ROLE`, two recipient rules, `realtime.EVENT_USER_REQUEST_CHANGED` |
| `c4f6799` | 4 — `services/material_requests.py`; `MaterialRequestOwnershipError → 403`; reopen clears stamps; 27 tests |
| `6b680b4` | 5 — `notify_material_request_filed` / `notify_material_request_stocked` |
| `3857219` | 6 — `routers/_low_stock.py` → `_stock_events.py`, `flush_stock_events` drains both buffers, `emit_user_request_changed`; eight `record_stock_change` sites |
| `4b8d3c7` | 7 — `POST /user-requests/material-request`, `/{id}/mark-stocked`, `/{id}/cancel`, `GET /user-requests/counts`, list `status=stocked` + `type=` filter; `MaterialRequestCreate`; `UserRequestResponse.item_quantity/updated`; `build_response`; `wo_service.get_visible_work_order` |
| `605a785` | 8 — `GET /work-orders/{id}/requests`; `WorkOrderItemCreate.material_request_id` resolves the stocked request inside `add_work_order_item` |
| `4be6d3f` | 9 — catalogue fulfilment on an empty shelf opens a `material_request` (`origin=catalogue_fulfilment`) |
| `cbdfd8d` | 10 — `HubPayload.stocked_requests` / `HubStockedRequest` on `GET /hub` |

Plan checkboxes for Tasks 1–10 are ticked. Every step's verification ran as written; no plan deviations in Phase 3.

## Notes for the next session

- **`ItemRequestStateError` was NOT renamed.** `docs/endpoint-map.md:923` still lists it; leave until Task 14.
- Two comments still say "item request" meaning an HTTP request for items: `static/views/items.js:85`, `static/views/nav.js:64`. Deliberate.
- `hubAdmin.js` exception row is `["catalogue_requests", "Catalogue requests", true]`; schemas match.
- `_live_requests_for_item` re-checks status in Python after the SQL filter (autoflush is off); docstring in the service explains it.
- Line endings: files are LF in the working tree; CRLF warnings on commit are noise.
- Heredocs longer than a screen or containing apostrophes fail in this Bash tool; write scripts/snippets with the Write tool into the scratchpad, then run or `cat >>` them.

## Test status (full suite after Task 10: 1730 passed, 2 failed)

Both failures are pre-existing and unrelated:

- `test_route_role_gates.py::test_work_order_list_forwards_joinable_filters` — fails on clean tree too (sort-toggle commit `0b446ca`).
- `test_work_orders_router.py::test_only_the_solo_card_suppresses_its_own_click` — known (memory).

## Next: Phase 4 = Tasks 11–14 (frontend + docs)

Start at plan line ~3441 (Task 11: `api.js` wrappers and the User Requests page). Every endpoint the frontend tasks call now exists and is tested over HTTP in `tests/test_material_requests.py`. Task 14 owns the docs sweep (`endpoint-map.md`, `current-state.md`, `open-work.md`) and the manual phone check.

Commands: `cd backend && ./venv/Scripts/python.exe -m pytest <file> -q -p no:cacheprovider`. Postgres on 8801 must be up for DB tests.
