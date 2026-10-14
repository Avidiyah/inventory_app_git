# Work-order self-assignment Implementation Plan

> **For agentic workers:** use superpowers:executing-plans, task by task; steps use `- [ ]`.

**Goal:** open work-order visibility, auto-assign on Begin Charging, lock Technician writes until on the crew, Admin/Owner-only hand-keyed hours, rename Supervisor → Team Lead in visible text.

**Architecture:** server rules live in `services/work_orders.py` + `domain/roles.py`/`domain/work_orders.py`; clients adapt. No migration: the stored role value and every column stay.

**Tech Stack:** FastAPI/SQLAlchemy/pytest (`backend/venv`), vanilla JS modules + vitest (`tests/`).

**Spec:** `docs/superpowers/specs/2026-10-14-work-order-self-assignment-design.md`

## Global Constraints

- Role value `supervisor`, `supervisor_id`, CSS classes, `data-action`s, identifiers: unchanged. Only visible text becomes "Team Lead".
- `WORK_ORDER_TECHNICIAN_ROLES` is **not** widened (attendance rosters read it).
- Owner is not assignable and cannot Begin Charging. Hand-keyed hours: `ROLE_ADMIN` floor.
- Edit files with Edit/Write, never `Set-Content`/`>` (a real `.env` was destroyed that way). No push; the user decides.
- Run targeted tests after each task; fix tests whose old rule is intentionally replaced.

## Review Focus

- Unassigned Technician hitting each locked endpoint directly (not via UI) → 403.
- Refused start (Owner, finished work order) must not add a crew row or open a punch.
- Legacy-only assignee (`assigned_to_id` set, no `work_order_technicians` row) then Begin Charging by someone else.
- Technician Scan/Stock gate and Hub tab list assignments only after visibility opens.
- Unrecognised role value stays assignment-only.

---

### Task 1: Role tables and rename of the label
**Files:** `backend/app/domain/roles.py`, `backend/static/roles.js`, `backend/tests/test_roles.py`, `backend/tests/test_role_mirror_parity.py`
- [ ] `ROLE_LABELS` supervisor → "Team Lead" in both files; add `WORK_ORDER_ASSIGNEE_ROLES`, `can_be_work_order_assignee`; JS `canBeWorkOrderAssignee`; update the module comment on assignment roles.
- [ ] Tests: assignee roles (admin/OA/supervisor/technician true, owner false); `WORK_ORDER_TECHNICIAN_ROLES` still excludes admin; label "Team Lead"; parity test already pins labels.
- [ ] `pytest tests/test_roles.py tests/test_role_mirror_parity.py -q`

### Task 2: Open visibility
**Files:** `backend/app/domain/work_orders.py` (`can_view_work_order`), `backend/app/services/work_orders.py` (`_scoped_to_user`, docstrings), `tests/test_work_orders_domain.py`, `tests/test_work_orders_service.py`, `tests/test_work_orders_router.py`
- [ ] Any role with `roles.rank(role) >= rank(technician)` (or `None`) → visible; else assignment-only. Same for `_scoped_to_user`.
- [ ] Rewrite the scoping tests (Technician now sees all; unknown role sees assigned only).
- [ ] `pytest` the three files.

### Task 3: Technician write lock
**Files:** `services/work_orders.py` (`require_crew_for_technician`, notes branch in `update_work_order`, `add_work_order_item`, `delete_work_order_item`), `services/work_order_signature.py`, `routers/user_requests.py`, `routers/transactions.py`, tests in `test_work_orders_service.py`, `test_work_order_signature.py`, `test_catalogue_requests.py`/`test_material_requests.py`, `test_work_orders_router.py` (dispense)
- [ ] Helper raises `RoleManagementError("Begin Charging on this work order first.")` for an unassigned Technician only.
- [ ] Wire each call site named in the spec; dispense check happens when `work_order_id` resolves to a row.
- [ ] Tests: unassigned Technician → 403 on each; assigned Technician and Team Lead → allowed.

### Task 4: Begin Charging auto-assigns; Owner blocked
**Files:** `services/work_orders.py` (`start_labor_session`, `stop_labor_session`, delete `_require_tracking_permission`, new `require_tracking_role`), `routers/work_orders.py` (call before `ensure_punch_for_labor_start`; docstrings), `tests/test_work_orders_service.py`, `tests/test_work_orders_router.py`
- [ ] Owner → `RoleManagementError("The Owner cannot track time on work orders.")` before any write.
- [ ] After the status guard, add the caller to the crew with `_sync_technician_assignments(existing + [caller], assigned_by_id=caller)`; no notification.
- [ ] Tests: Technician unassigned starts → assigned, status In-Progress, crew row has `assigned_by_id`; existing crew kept; legacy-only assignee kept; Owner 403 and no punch; start on Completed refuses and adds no row; repeat start idempotent; Admin start → assigned.

### Task 5: Assignable roles and validation messages
**Files:** `services/work_orders.py` (`_validate_assignee(s)`, `_validate_supervisor`, messages), `tests/test_work_orders_service.py`, `tests/test_mass_staging*.py`, `tests/test_hub_service.py` (comment at the OA/Admin/Owner test)
- [ ] Use `WORK_ORDER_ASSIGNEE_ROLES`; messages name Technician, Team Lead, TechFM OA or Admin; routing message says Team Lead.
- [ ] Tests: Admin and OA accepted; Owner rejected.

### Task 6: Hand-keyed hours Admin/Owner only
**Files:** `services/work_orders.py` (`_require_labor_author`, `add/update/delete_work_order_labor`, delete `_log_manual_labor_note` and `_format_labor_duration`), `routers/work_orders.py` docstrings, `tests/test_work_orders_service.py`, `tests/e2e/_seed.py` (uses Owner: stays valid)
- [ ] Floor `ROLE_ADMIN`; message "Only an Admin or the Owner can add, edit, or remove labor hours."
- [ ] Replace Technician self-service tests with refusals; Team Lead and OA refused; Admin and Owner allowed; credit-target rule kept.

### Task 7: Server visible-string rename
**Files:** `services/work_orders.py` (lines naming "Supervisor" in raised messages), `domain/roles.py` docstrings as needed
- [ ] "Only a Team Lead, Admin, or Owner can edit work order operations." / "...edit logged materials." / "All Users must Stop Charging before a Team Lead can be notified." / routing and assignee messages.
- [ ] Update asserting tests by `rg "Supervisor" backend/tests`.

### Task 8: Frontend behavior
**Files:** `static/roles.js`, `views/workOrderPresenters.js`, `workOrderStatusActions.js`, `workOrderCardHtml.js`, `workOrderRequests.js`, `workOrderSignature.js`, `workOrderReferenceData.js`, `massStage.js`, `transactions.js`, `hubTechnician.js`, `workOrderList.js` (comments), tests in `tests/`
- [ ] `isCrewLocked`, Admin/Owner `canEditLabor`/`canAddLabor`; Begin Charging for all but Owner; Owner keeps Mark Completed.
- [ ] Locked card hides inputs + shows `.wo-crew-lock`; labor card read-only below Admin.
- [ ] Technician gate sends `assignedToId`; hub tab sends `mine` for Technician.
- [ ] Vitest: locked/unlocked card, status buttons per role, labor controls per role, gate param, hub param.

### Task 9: Frontend visible-string rename
**Files:** `static/format.js`, `tips.js`, `pages/work-orders.html`, `hubHome.js`, `hubAdmin.js`, `hubTechnician.js`, `workOrderFilterChips.js`, `workOrderFilters.js`, `workOrderStatusActions.js`, `workOrderCardHtml.js`, `workOrderSignature.js`, `workOrderIntegrations.js`, `workOrderActions.js`, existing vitest assertions
- [ ] Edit only user-read strings; tooltips updated for the new behavior (`tips.js` work-order routing and role tips).
- [ ] `npx vitest run` on affected files.

### Task 10: Docs
**Files:** `docs/current-state.md` (matrix + roles prose), `docs/endpoint-map.md`, `docs/notification-events.md`, `docs/open-work.md`, `docs/adding-a-notification-trigger.md`, `docs/project-summary.md`, `docs/design-system.md`
- [ ] Rewrite the affected matrix rows and endpoint role columns to the spec's role matrix (current truth only).
- [ ] Prose rename Supervisor → Team Lead outside code spans and fences, via a one-off script written with Write and run from the scratchpad; review `git diff --stat` and grep leftovers.
- [ ] Do not hand-sync the Obsidian mirror (Stop hook does it).

### Task 11: Verify
- [ ] Targeted pytest list from the spec, `npx vitest run`, `rg` for stray "Supervisor" in visible strings, `git diff --stat`. Report; no push.
