# Prior-work guardrail — plan

Spec: `docs/superpowers/specs/2026-10-14-work-order-prior-work-guardrail-design.md`.
Precondition: the self-assignment work (`2026-10-14-work-order-self-assignment.md`) is merged; rebase on it first, re-read `start_labor_session` and the card files before editing. No migration. Tests: targeted files only.

## T1 — prior-work query (service)
- Goal: `prior_work(db, work_order, viewer_id) -> {by, last_at} | None`.
- Files: `backend/app/services/work_orders.py`; `backend/tests/test_work_orders_service.py`.
- Steps: one function querying `WorkOrderLaborSession`, `WorkOrderLabor`, `WorkOrderItem` rows for the work order where the user id differs from the viewer; return distinct full names (users join) and the max timestamp across the three; `None` when empty. Check each model's actor column name in `models.py` (`technician_id` on sessions; confirm labor/item columns).
- Test: each source alone triggers; own rows alone return None; mixed own+other lists only the other; no rows None.

## T2 — gate in `start_labor_session`
- Goal: refuse an un-acknowledged start when others have worked and notes are non-empty.
- Files: `services/work_orders.py`, `backend/app/domain/work_orders.py` (error type if none fits); service tests.
- Steps: add kw `notes_acknowledged: bool = False`. Place the check after the idempotent "already running here" return and after the status guard, before crew sync and session creation, so a refused start assigns nobody and opens nothing. Raise a `WorkOrderStateError` subclass (or new `PriorWorkUnacknowledgedError`) carrying the `prior_work` payload; empty/whitespace `work_order.notes` skips the gate.
- Test: 409-path raises with no crew row and no session created; acknowledged succeeds; idempotent re-start exempt; empty notes exempt; own-only prior work exempt.

## T3 — router + schema
- Goal: `tracking/start` takes the flag; detail exposes `prior_work`; 409 shape.
- Files: `backend/app/schemas/work_orders.py`, `backend/app/routers/work_orders.py` (`start_work_order_tracking` ~L1079, `_detail`), `backend/tests/test_work_orders_router.py`.
- Steps: optional body model `{notes_acknowledged: bool = False}` (body optional so existing callers keep working); add `prior_work: Optional[PriorWork]` to `WorkOrderDetail`, filled in `_detail` via T1 using `viewer_id`; map the new error in `to_http` to 409 with `detail` + `prior_work`. Keep `attendance_service.ensure_punch_for_labor_start` ordering: gate must run before the punch is opened, or a refused start leaves a punch — move the punch call after the gate check (call a cheap `check_prior_work_gate` first, or catch and roll back; prefer the pre-check).
- Test: through real `TestClient` (not direct handler calls): 409 body shape; ack path 200; no punch opened on 409; detail carries `prior_work` for another viewer and null for the sole worker.

## T4 — frontend
- Goal: banner, auto-expanded Notes, disabled Begin Charging until acknowledged.
- Files: `backend/static/views/workOrderCardHtml.js` (`renderBody`, Notes `<details>` ~L527), `workOrderStatusActions.js` (`begin` button ~L24), `workOrderActions.js` (start call), `backend/static/api.js` (`apiStartWorkOrderTracking` — send body), `tips.js` (one tip line).
- Steps: `priorWorkBannerHtml(detail)` beside `crewLockHtml` in `workOrderPresenters.js`; when `detail.prior_work` and notes non-empty: add `open` to the Notes `<details>`, render an "I've read the notes" button, render Begin Charging disabled until it is tapped (module-level per-work-order flag, reset on re-render of a different order). Start call sends `notes_acknowledged: true` only after the tap. On 409, re-render with the banner. No inline `style=` (CSP drops it) — use a class in the existing stylesheet. No nested buttons.
- Test: `tests/frontend/views/` — banner shown with prior work, hidden without; button disabled until acknowledge; empty notes: banner, no gate; 409 re-renders.

## T5 — docs + verify
- Files: `docs/current-state.md` (one line under work orders), `docs/endpoint-map.md` (`tracking/start` body + 409), `docs/open-work.md` only if an item exists.
- Verify: `pytest backend/tests/test_work_orders_service.py backend/tests/test_work_orders_router.py` and the touched frontend test file; browser check is the user's (manual-validation preference — do not auto-start the server).

## Order and risk
T1 → T2 → T3 → T4 → T5, one commit per task on `main`. Main risk is merge overlap with self-assignment in `start_labor_session` and the card files; the punch-ordering note in T3 is the likeliest bug.
