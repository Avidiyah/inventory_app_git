# TechFM OA role — design

Date: 2026-08-16
Status: approved, ready for implementation planning

## Problem

The system has four roles in a strictly ordered hierarchy. There is no tier
between Supervisor and Admin, so granting someone the Admin toolkit today also
grants them two things the business does not want to hand out together:
authority over other Admins' roles, and the Review handoff on work orders.

## Goal

Add a fifth role, **TechFM OA**, that sits between Supervisor and Admin. It
carries the full Admin toolkit with exactly two subtractions:

1. It cannot send a work order to Review.
2. It cannot change the role of an Admin or Owner, and cannot assign the Admin
   or Owner role to anyone.

Everything else an Admin can do, a TechFM OA can do.

## Identifier and display name

| Aspect | Value |
| --- | --- |
| Stored value (DB, API, CSV) | `techfm_oa` |
| Python constant | `roles.ROLE_TECHFM_OA` |
| Display label | `TechFM OA` |

Every other role's display label is derived by capitalising the stored slug
(`roleLabel()` in `static/views/tools.js:108`, `populateRoleSelect()` in
`static/views/users.js:143`), and the Users table prints `user.role` raw
(`static/views/users.js:126`). `TechFM OA` cannot be derived that way, so this
design adds an explicit label map and routes those three sites through it.

The stored value stays a lowercase single token for consistency with the other
four, and because the raw value reaches API responses, CSV exports and the docs
tables.

## Design

### 1. Rank insert (`backend/app/domain/roles.py`)

```
technician 0 < supervisor 1 < techfm_oa 2 < admin 3 < owner 4
```

`ROLE_TECHFM_OA = "techfm_oa"` is added; `ROLE_RANK` renumbers Admin to 3 and
Owner to 4; `ALL_ROLES` gains the entry in senior-first position between
`ROLE_ADMIN` and `ROLE_SUPERVISOR`.

`WORK_ORDER_SUPERVISOR_ROLES` gains `ROLE_TECHFM_OA` — a TechFM OA is a valid
routed supervisor on a work order, as an Admin is.

`WORK_ORDER_TECHNICIAN_ROLES` is unchanged. Admin is not an assignable worker
and neither is TechFM OA.

No other function in this module changes. Both goals fall out of the rank
position alone, with no special case in the pure domain:

- `can_manage("techfm_oa", "admin")` → `2 > 3` → false. Cannot re-role an Admin
  or Owner. `routers/users.py:135` also runs `can_manage` against the *requested*
  role, so a TechFM OA cannot assign Admin or Owner either.
- `can_manage("admin", "techfm_oa")` → true. Admins retain full control over
  these accounts, and `assignable_roles("admin")` picks the new role up with no
  further change, so Admins can create them.
- `role_at_least("techfm_oa", "admin")` → false. This is what removes the
  Review handoff (see section 3).

### 2. Backend gates — capability floor vs. authority floor

There are **42 `roles.ROLE_ADMIN` references across 12 files** under
`backend/app`. **41 move to `roles.ROLE_TECHFM_OA`. Exactly one stays.**

| File | Count | Disposition |
| --- | --- | --- |
| `routers/work_orders.py` | 9 | all move |
| `routers/netfacilities.py` | 7 | all move |
| `routers/items.py` | 5 | all move |
| `routers/tools.py` | 5 | all move |
| `routers/user_requests.py` | 4 | all move |
| `services/work_orders.py` | 4 | **3 move, 1 stays** |
| `routers/transactions.py` | 3 | all move |
| `routers/users.py` | 1 | moves |
| `domain/work_orders.py` | 1 | moves |
| `domain/realtime.py` | 1 | moves |
| `services/mass_staging.py` | 1 | moves |
| `main.py` | 1 | moves |

Notes on the non-obvious ones:

- `routers/users.py:116` — the `PATCH /users/{id}/role` route gate moves to
  `ROLE_TECHFM_OA`, so a TechFM OA can re-role subordinates. The two
  `can_manage` checks inside the handler are what stop them reaching Admins;
  the route gate is not the mechanism.
- `routers/transactions.py:213` and `routers/items.py:50` — price redaction.
  A TechFM OA sees prices, as an Admin does.
- `domain/realtime.py:58` — `EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED` moves, so
  the Admin Review page stays live for a TechFM OA. They can work the review
  queue; they just cannot put a work order into it.
- `services/work_orders.py:891` (`_scoped_to_user`) and `domain/work_orders.py:450`
  (`can_view_work_order`) — global work-order visibility, mirrored pair. Both
  move; they must stay in agreement.
- `main.py:404` (`/db-test`) — moves, for consistency with "clone of Admin".

`ROLE_OWNER` gates (legacy work-order archive preview and re-archive) are
untouched.

**The one that stays:** `services/work_orders.py:271`, inside
`_require_review_handoff_permission`. Its docstring is rewritten to record that
the Admin floor here is deliberate and is the sole capability an Admin holds
that a TechFM OA does not.

### 3. Send to Review

**Backend — no code change.** `_require_review_handoff_permission` grants the
handoff to `role_at_least(user.role, ROLE_ADMIN)` or to the unassigned routed
Supervisor (`user.role == ROLE_SUPERVISOR`). A TechFM OA matches neither, so the
existing `RoleManagementError` → 403 path already refuses them. This is the
authoritative gate; the button is cosmetic.

Consequence, accepted deliberately: a TechFM OA may be the routed supervisor on
a work order and still cannot perform the final handoff. Review is a
second-person control, and an Admin, Owner, or another routed Supervisor
completes it.

**Frontend** — `static/views/workOrders.js:892`. Today the control is omitted
when `canSendToReview` is false. For TechFM OA it is instead rendered with the
`disabled` attribute and a `title` reading:

> An Admin, Owner, or the routed Supervisor must send this to Review.

Every other role keeps today's hidden behaviour, so this is one added `else if`
branch and not a UX change for Technicians or Supervisors.

The disabled button renders for a TechFM OA whenever the enabled one would not,
whatever the reason — including the edge case where a TechFM OA is themselves in
the assigned technician set on a legacy work order. One message covers both
cases rather than branching on which rule refused.

`canCurrentUserSendToReview()` (`static/views/workOrders.js:379`) is unchanged.
It keeps `roleAtLeast(user.role, "admin")`, which now correctly excludes TechFM
OA under the new ranks.

### 4. Frontend mirror (`backend/static/`)

`roles.js` is the hand-maintained twin of `domain/roles.py` and mirrors the new
`ROLE_RANK`, `ALL_ROLES`, and `canBeWorkOrderSupervisor`.

Six `roleAtLeast(..., "admin")` call sites move to `"techfm_oa"`:

| Site | Meaning |
| --- | --- |
| `views/history.js:263` | price visibility |
| `views/workOrders.js:130` | admin-level work-order controls |
| `views/users.js:103` | Edit Role button |
| `views/items.js:156` | admin item controls |
| `views/scan.js:284` | admin scan path |
| `views/tools.js:101` | tool custody management |

`views/workOrders.js:382` stays at `"admin"` — that is the Review gate.

`views/nav.js`:

- `PAGE_ACCESS` — `techfm_oa` joins every list that currently contains
  `"admin"`, including `admin-review` and `user-requests`.
- `LANDING_PAGE_BY_ROLE` — `techfm_oa: "history"`, matching Admin.

`roles.js` gains `ROLE_LABELS`, a slug → display-string map covering all five
roles. Three sites read from it instead of capitalising the raw slug:
`views/tools.js:108` (`roleLabel`), `views/users.js:143`
(`populateRoleSelect`), and `views/users.js:126` (the Users table Role cell).

`views/users.js:51` `ROLE_DESCRIPTIONS` gains a plain-language entry.

### 5. Persistence

`User.role` is `Column(Text, nullable=False)` with no enum, no check constraint,
and no foreign key (`backend/app/models.py:59`). **No migration is required.**

Nothing at the database level rejects an unrecognised role value. That is
pre-existing and out of scope here; `rank()` already defends against it by
ranking unknown roles at `-1`, below everything.

## Testing

Test-first, then the change.

**`tests/test_roles.py`** — extend to five roles: rank ordering,
`role_at_least`, `can_manage` (both directions across the new boundary),
`assignable_roles` for each actor, `can_be_work_order_supervisor`, and
`can_transact`.

**`tests/test_route_role_gates.py`** — 17 per-route min-role assertions move
from `ROLE_ADMIN` to `ROLE_TECHFM_OA` (lines 82, 92, 96, 101, 182, 197, 216,
217, 220, 247, 267, 304, 443, 447, 451, 455, 459); two of those, 197 and 304,
are parametrised and cover several routes each. Line 145 uses `ROLE_ADMIN` as an
actor, not an assertion, and is unaffected.

**`tests/test_item_barcodes.py:126`** — same, one assertion.

**New guard test.** Walk every `APIRoute` on the application, extract each
route's static minimum role via the existing `_find_min_role` helper, and assert
the set of routes gated at exactly `ROLE_ADMIN` matches a short explicit
allow-list. Rationale: after this change, `ROLE_ADMIN` at a route gate is almost
always a mistake, and a future route written with `ROLE_ADMIN` out of habit
would silently lock TechFM OA out of a capability it is supposed to have. The
guard turns that into a failing test.

**New service tests.**

- A TechFM OA is refused by `_require_review_handoff_permission` with 403,
  including when they are the routed supervisor on the work order.
- A TechFM OA cannot change an Admin's role (403) and cannot assign the Admin
  role (403), but can re-role a Supervisor and a Technician.
- An Admin can create, manage, and re-role a TechFM OA.

Tests that pass `roles.ROLE_ADMIN` as an *actor* (`test_realtime_emit.py`,
`test_upload_limits.py`, `test_work_order_import.py`, `test_user_role_edit.py`)
continue to pass unchanged: Admin retains every capability it has today.

## Documentation

- `docs/current-state.md` — role order, the permission matrix around L725–746,
  the endpoint tables, the `PAGE_ACCESS` mirror, and the tests table.
- `docs/endpoint-map.md` — L114 (`PATCH /users/{id}/role`) and the role
  glossary at L1060–1062.
- `docs/project-summary.md` — L16, L21, L107, L125.
- `docs/open-work.md` — no change expected.

The Obsidian vault mirror under
`John_Vault/4. Notes/Repository-Docs/inventory-app-git/` is automated. Do not
edit it by hand.

## Rejected alternative

**Give TechFM OA the same rank as Admin (both 2).** This needs zero gate
changes, which is tempting at 42 call sites. It was rejected because:

- `can_manage("admin", "techfm_oa")` becomes false at equal rank, so only the
  Owner could create or manage a TechFM OA, and `assignable_roles("admin")`
  would not offer the role.
- `role_at_least("techfm_oa", "admin")` becomes true, so Send to Review would
  need an explicit deny special-case rather than falling out of the hierarchy.
- It contradicts the stated ordering, in which TechFM OA sits strictly below
  Admin.

Renumbering is the honest cost of a genuine intermediate tier.

## Out of scope

- Any change to how Technicians or Supervisors see the Send to Review button.
- A database-level constraint on `users.role`.
- Making TechFM OA an assignable work-order technician.
- Any change to the `ROLE_OWNER` gates.
