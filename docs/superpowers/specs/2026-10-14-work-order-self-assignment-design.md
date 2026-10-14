# Work-order self-assignment, open visibility, and Team Lead rename — design

Status: decisions fixed by the user 2026-10-14 (every row below was answered
explicitly; none is inferred). Plan: `docs/superpowers/plans/2026-10-14-work-order-self-assignment.md`.

## Goal

Everyone sees every work order. Starting work (Begin Charging) puts the
worker on the crew. Technicians write to a work order only once they are on its
crew. Hand-keyed hours become Admin/Owner only. The word "Supervisor" is shown
as "Team Lead" everywhere a person reads it.

## Decisions

| # | Decision | Source |
|---|---|---|
| D1 | Every recognised role sees every live work order in Work Orders (Technician and Team Lead included). An unrecognised role stays assignment-only (fail closed). | Q: Team Lead view = all |
| D2 | Technician Hub and Scan/Stock list **assignments only**. The server no longer scopes them, so the client sends the filter. | request |
| D3 | An unassigned Technician is **read-only**: no notes, materials (add/remove), Material/Catalogue requests, witness signature, or Scan/Stock dispense against that work order, until Begin Charging adds them. Team Lead and above keep today's write access everywhere. | Q: read-only until Begin Charging |
| D4 | Begin Charging on any visible work order **adds the caller to the crew** (additive, never replaces; no notification). Applies to Technician, Team Lead, TechFM OA, Admin. | request + Q |
| D5 | **Owner is blocked** from Begin Charging (403). Owner is not assignable. | Q: Owner = block |
| D6 | Assignable roles: Technician, Team Lead, TechFM OA, Admin. Not Owner. | Q: assignable |
| D7 | Team Lead and above still assign technicians through the card editor (PATCH `assigned_to_ids`). Self-assignment by Begin Charging is an addition, not a replacement. | request |
| D8 | Hand-keying, editing and removing labor hours: **Admin and Owner only**. Team Lead, TechFM OA and Technician lose all three. Charged sessions are unaffected. | Q: Admin and Owner only (confirmed twice) |
| D9 | An assigned Admin/TechFM OA stays blocked from sending their own work order to Review (existing rule kept). | Q: keep the rule |
| D10 | Unassigned Technician card: input controls hidden, one hint line shown; existing notes, materials and sign-off stay readable. | Q: hide controls + hint |
| D11 | Rename "Supervisor" to "Team Lead" in all visible text: static pages/JS, role label, tooltips, server messages the UI shows, and the living docs. The stored role value `supervisor`, API field names (`supervisor_id`…), CSS classes, data-actions and code identifiers are unchanged. | Q: all text + docs |
| D12 | Roles tables updated: the permission matrix in `docs/current-state.md` (with the role columns in `endpoint-map.md` and `notification-events.md`) and the domain tables in code (`roles.py`, `roles.js`). The in-app role descriptions (`users.js`) are untouched. | Q: roles table |

## Role matrix after the change

| Capability | Technician | Team Lead | TechFM OA | Admin | Owner |
|---|---|---|---|---|---|
| See all work orders | yes | yes | yes | yes | yes |
| Begin Charging (auto-joins crew) | yes | yes | yes | yes | **blocked** |
| Assignable to a work order | yes | yes | yes | yes | no |
| Edit crew / routing in the card editor | no | yes | yes | yes | yes |
| Notes, materials, requests, sign-off, Scan/Stock dispense | only when on the crew | yes | yes | yes | yes |
| Hold / Resume / Finish | on the crew | on the crew | on the crew | on the crew | n/a |
| Hand-key / edit / remove labor hours | no | no | no | yes | yes |
| Send Completed to Review | no | no | no (not on own work) | yes (not on own work) | yes |

## Server design

- `domain/roles.py`: `ROLE_LABELS["supervisor"] = "Team Lead"`; new
  `WORK_ORDER_ASSIGNEE_ROLES = (admin, techfm_oa, supervisor, technician)` and
  `can_be_work_order_assignee`. `WORK_ORDER_TECHNICIAN_ROLES` is **unchanged**:
  attendance rosters and the Admin hub time buckets read it, and widening it
  would put Admins on the hours grid.
- Visibility: `domain.work_orders.can_view_work_order` and
  `services.work_orders._scoped_to_user` return everything for any recognised
  role (`roles.rank(role) >= rank(technician)`), assignment-only otherwise.
  `mine` and `assigned_to_id` list filters are unchanged and are what the clients
  use for D2.
- Write lock (D3): one helper, `require_crew_for_technician(work_order, user)`,
  raising `RoleManagementError` (403) only when `user.role == technician` and the
  user is not in `_assigned_technician_ids(work_order)`. Called from: notes in
  `update_work_order`; `add_work_order_item`; `delete_work_order_item`;
  `POST /user-requests/material-request`; `POST /user-requests/catalogue-request`
  when `work_order_id` is set; `work_order_signature.save_signature`;
  `POST /transactions/` dispense when it resolves to a work order. Reads are
  unaffected.
- Tracking (D4/D5): `start_labor_session` refuses the Owner, then — after the
  status guard, so a refused start assigns nobody — adds the caller via
  `_sync_technician_assignments(existing + caller)`. `_require_tracking_permission`
  is deleted: stop only ever closes the caller's own running session, and
  `start` no longer needs a crew precondition. The router checks the Owner
  *before* `ensure_punch_for_labor_start` so a refused start never opens a punch.
- Assignee validation (D6): `_validate_assignee(s)` use the assignee roles;
  Mass Stage inherits this through the same validator.
- Labor (D8): `_require_labor_author` becomes an Admin-floor check
  (`roles.role_at_least(role, ROLE_ADMIN)`; internal `None` caller allowed). This
  is the second place `ROLE_ADMIN` is used in services; it is a service check, not
  a route gate, so `test_route_role_gates` is unaffected. The credited
  technician must still be on the crew or be the recorder. The Technician
  note-log trail (`_log_manual_labor_note`, `_format_labor_duration`) becomes
  unreachable and is deleted.
- Messages shown by the UI change "Supervisor" to "Team Lead"; the Notify
  button's 400 text is matched by `workOrderActions.js`, so both change together.

## Client design

- `roles.js` mirrors the label and adds `canBeWorkOrderAssignee`; the work-order
  technician picker and Mass Stage use it.
- `workOrderPresenters.js`: `isCrewLocked(detail)`; `canEditLabor`/`canAddLabor`
  become the Admin-or-Owner check.
- Status actions: everyone but the Owner gets Begin Charging; the Owner keeps
  Mark Completed where Supervisor+ had it.
- Locked card (D10): notes box, add-material row, remove buttons, request form,
  stocked "Add requested material" line, and the Capture-signature button are not
  rendered; one `.wo-crew-lock` hint line is.
- Scan/Stock gate for a Technician sends `assignedToId`; the Hub "My Work
  Orders" tab sends `mine` for Technician as well as Team Lead.
- Labor card: add/edit/remove only for Admin/Owner; others see the read-only list
  and "Only an Admin or the Owner can add or change hours by hand."

## Out of scope (named so nobody assumes them)

- The Work Orders page filters for supervisor/technician stay hidden from
  Technicians. - Hub Priorities counts and the Hub "Start on…" picker stay
  assignment-scoped. - Admin hub minute buckets still exclude Admin/OA/Owner
  sessions. - Attendance punch editing is a separate system and is unchanged.
- Notification text contains no role word; no notification changes.
- History specs and plans under `docs/superpowers/` keep their original wording.

## Risks

1. Closing the Scan/Stock hole: today the API lets any Technician dispense against
   any `work_order_id`; D3 makes that a 403. Pinned by a router test.
2. Visibility widening changes list size for Technicians; `MAX_LIST_ROWS` still
   caps the response.
3. Owner loses Begin Charging; any e2e seed that starts tracking as Owner must
   use another user.
4. The rename must not touch identifiers; the diff is reviewed for `_`/camelCase.

## Verification

Targeted pytest (`test_roles`, `test_role_mirror_parity`, `test_work_orders_domain`,
`test_work_orders_service`, `test_work_orders_router`, `test_hub_service`,
`test_work_order_signature`, `test_material_requests`, `test_catalogue_requests`,
`test_mass_staging*`, `test_route_role_gates`) and the affected vitest files. The
in-app check is the user's.
