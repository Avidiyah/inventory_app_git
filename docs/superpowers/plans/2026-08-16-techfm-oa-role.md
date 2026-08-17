# TechFM OA Role Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fifth role, TechFM OA, ranked between Supervisor and Admin, carrying the full Admin toolkit except the work-order Review handoff and authority over Admin/Owner roles.

**Architecture:** The role is inserted as a real rank (`technician 0 < supervisor 1 < techfm_oa 2 < admin 3 < owner 4`) rather than aliased onto Admin's rank, so both exclusions fall out of `role_at_least` and `can_manage` with no special-casing in the pure domain. The cost is that every gate meaning "the Admin toolkit" must move down one tier: 41 of the 42 `roles.ROLE_ADMIN` references in `backend/app` become `roles.ROLE_TECHFM_OA`, and the single survivor is the Review handoff.

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy 2.0 / Pydantic v2, Postgres, pytest. Frontend is static ES modules with no build step and no JS test harness.

**Spec:** `docs/superpowers/specs/2026-08-16-techfm-oa-role-design.md`

## Global Constraints

- Stored role value is the lowercase slug `techfm_oa`. Python constant `roles.ROLE_TECHFM_OA`. Display label `TechFM OA`, exactly that casing and spacing.
- Rank order is `technician 0 < supervisor 1 < techfm_oa 2 < admin 3 < owner 4`.
- `backend/static/roles.js` is a hand-maintained twin of `backend/app/domain/roles.py`. Any change to ranks, role list, or labels must land in both. Task 2 adds a test that enforces this.
- Exactly one `roles.ROLE_ADMIN` may remain in `backend/app` after Task 3: the floor inside `_require_review_handoff_permission` (`backend/app/services/work_orders.py`). Task 3 verifies the count.
- No database migration. `User.role` is `Column(Text, nullable=False)` with no enum or constraint (`backend/app/models.py:59`).
- Layer discipline (from `docs/project-summary.md:9`): `routers → schemas/services → domain/models → database`. `domain/` stays free of FastAPI, SQLAlchemy and Pydantic imports.
- Backend gates are authoritative; frontend role checks are UX only. Never rely on a hidden or disabled button as a permission control.
- **Test command.** `tests/conftest.py` imports `app.database`, which raises at import time when `DATABASE_URL` is unset, so *every* pytest invocation needs the prefix. From `backend/`:

  ```bash
  DATABASE_URL="postgresql://unused:unused@127.0.0.1:8801/unused" ./venv/Scripts/python.exe -m pytest tests/test_roles.py -q
  ```

  Port 8801 is the real local Postgres port. The placeholder credentials fail authentication immediately, so DB-backed tests skip fast. Do **not** substitute 5432 — that port is closed on this machine and each refused connect costs ~2s across ~244 DB-backed tests.
- **Always launch via `./venv/Scripts/python.exe -m pytest`**, never bare `pytest`. The venv is a copy and its `.exe` shims resolve to a different project's interpreter.
- Tasks 1–4 and 6–8 are verifiable locally. Task 5 is DB-backed and will **skip** locally without real Postgres credentials; it runs in CI. Do not report Task 5 as passing on the strength of a skip.

---

## File Structure

**Modified — backend domain and gates**

| File | Responsibility after the change |
| --- | --- |
| `backend/app/domain/roles.py` | Five-role vocabulary, ranks, `ROLE_LABELS` + `label()`, work-order eligibility sets |
| `backend/app/routers/{work_orders,netfacilities,items,tools,user_requests,transactions,users}.py` | Gates moved to the TechFM OA floor |
| `backend/app/services/{work_orders,mass_staging}.py` | Same, except the Review handoff floor |
| `backend/app/domain/{work_orders,realtime}.py` | Same |
| `backend/app/main.py` | Same (`/db-test`) |

**Modified — frontend**

| File | Responsibility after the change |
| --- | --- |
| `backend/static/roles.js` | Rank/label mirror of the Python domain, incl. new `ROLE_LABELS` |
| `backend/static/views/nav.js` | `PAGE_ACCESS` and `LANDING_PAGE_BY_ROLE` entries |
| `backend/static/views/{history,items,scan,tools,users,workOrders}.js` | Capability gates moved to the TechFM OA floor; label map consumers |

**Created — tests**

| File | Responsibility |
| --- | --- |
| `backend/tests/test_role_mirror_parity.py` | Asserts `static/roles.js` ranks and labels match `domain/roles.py` |

**Modified — tests and docs**

`backend/tests/{test_roles,test_route_role_gates,test_item_barcodes,test_work_orders_service,test_user_role_edit}.py`; `docs/{current-state,endpoint-map,project-summary}.md`.

---

### Task 1: Domain rank insert

**Files:**
- Modify: `backend/app/domain/roles.py:1-52`
- Test: `backend/tests/test_roles.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `roles.ROLE_TECHFM_OA` (`str`, `"techfm_oa"`); `roles.ROLE_RANK` (`dict[str, int]`) renumbered; `roles.ALL_ROLES` (`tuple[str, ...]`) of length 5; `roles.WORK_ORDER_SUPERVISOR_ROLES` including the new role; `roles.ROLE_LABELS` (`dict[str, str]`); `roles.label(role: str) -> str`. Every later task depends on these names.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_roles.py`:

```python
def test_techfm_oa_sits_between_supervisor_and_admin():
    assert (
        roles.rank(roles.ROLE_TECHNICIAN)
        < roles.rank(roles.ROLE_SUPERVISOR)
        < roles.rank(roles.ROLE_TECHFM_OA)
        < roles.rank(roles.ROLE_ADMIN)
        < roles.rank(roles.ROLE_OWNER)
    )
    assert roles.is_valid_role("techfm_oa") is True


def test_techfm_oa_clears_every_floor_below_admin():
    assert roles.role_at_least("techfm_oa", "supervisor") is True
    assert roles.role_at_least("techfm_oa", "techfm_oa") is True
    # The one floor it does not clear -- this is what removes Send to Review.
    assert roles.role_at_least("techfm_oa", "admin") is False


def test_techfm_oa_cannot_manage_admin_or_above():
    assert roles.can_manage("techfm_oa", "admin") is False
    assert roles.can_manage("techfm_oa", "owner") is False
    assert roles.can_manage("techfm_oa", "techfm_oa") is False
    # ...but it manages everything below.
    assert roles.can_manage("techfm_oa", "supervisor") is True
    assert roles.can_manage("techfm_oa", "technician") is True


def test_admin_retains_control_of_techfm_oa_accounts():
    # The reason the new role gets its own rank instead of sharing Admin's:
    # at equal rank an Admin could neither manage nor create one.
    assert roles.can_manage("admin", "techfm_oa") is True
    assert roles.can_manage("owner", "techfm_oa") is True
    assert roles.can_manage("supervisor", "techfm_oa") is False


def test_techfm_oa_is_a_work_order_supervisor_but_not_a_worker():
    assert roles.can_be_work_order_supervisor("techfm_oa") is True
    assert roles.can_be_work_order_technician("techfm_oa") is False


def test_techfm_oa_may_stock_and_dispense():
    assert roles.can_transact("techfm_oa", "dispense") is True
    assert roles.can_transact("techfm_oa", "stock") is True
    assert roles.can_transact("techfm_oa", "adjust") is False


def test_role_labels_cover_every_role_and_spell_techfm_oa_exactly():
    assert set(roles.ROLE_LABELS) == set(roles.ALL_ROLES)
    assert roles.label("techfm_oa") == "TechFM OA"
    assert roles.label("admin") == "Admin"
    # An unrecognised role must not crash a description string.
    assert roles.label("bogus") == "bogus"
```

Also update these three existing tests in the same file, which enumerate roles exhaustively and will otherwise fail:

```python
def test_assignable_roles():
    assert roles.assignable_roles("owner") == [
        "admin", "techfm_oa", "supervisor", "technician",
    ]
    assert roles.assignable_roles("admin") == [
        "techfm_oa", "supervisor", "technician",
    ]
    assert roles.assignable_roles("techfm_oa") == ["supervisor", "technician"]
    assert roles.assignable_roles("supervisor") == ["technician"]
    assert roles.assignable_roles("technician") == []


def test_can_transact_stock_requires_supervisor():
    assert roles.can_transact("owner", "stock") is True
    assert roles.can_transact("admin", "stock") is True
    assert roles.can_transact("techfm_oa", "stock") is True
    assert roles.can_transact("supervisor", "stock") is True
    # A Technician may not add stock.
    assert roles.can_transact("technician", "stock") is False


def test_rank_ordering():
    assert (
        roles.rank("owner")
        > roles.rank("admin")
        > roles.rank("techfm_oa")
        > roles.rank("supervisor")
        > roles.rank("technician")
    )
```

`test_no_one_can_manage_an_owner` and `test_can_transact_dispense_allowed_for_every_role` iterate `roles.ALL_ROLES` and need no edit — they pick the new role up automatically.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
DATABASE_URL="postgresql://unused:unused@127.0.0.1:8801/unused" ./venv/Scripts/python.exe -m pytest tests/test_roles.py -q
```

Expected: FAIL with `AttributeError: module 'app.domain.roles' has no attribute 'ROLE_TECHFM_OA'`.

- [ ] **Step 3: Implement the domain change**

In `backend/app/domain/roles.py`, replace lines 1–52 with:

```python
"""Role vocabulary and the subordinate-management hierarchy.

Layer: pure domain (no FastAPI, no SQLAlchemy, no Pydantic).

There are five roles. Authority is strictly ordered by rank, and the
single rule that drives every user-management decision is: *an actor
may create, reset, or delete a user only when the actor outranks that
user* (`can_manage`). The set of roles an actor may hand out is exactly
the set ranked below them (`assignable_roles`).

TechFM OA sits between Supervisor and Admin. It holds the whole Admin
toolkit with two subtractions, and both of them are consequences of its
rank rather than special cases written anywhere:

* it fails `role_at_least(role, ROLE_ADMIN)`, which is the floor
  `services.work_orders._require_review_handoff_permission` requires, so
  it cannot send a work order to Review; and
* `can_manage` is false against Admin and Owner, so it can neither
  re-role them nor hand those roles out.

Every *other* gate that once read "Admin or above" now reads
`ROLE_TECHFM_OA`. A new route written with `ROLE_ADMIN` out of habit
would silently lock TechFM OA out of a capability it is meant to have,
so `tests/test_route_role_gates.py` asserts that no route gate is left
at the Admin floor.

Owner is the top of the hierarchy and is created only by the bootstrap
script (`backend/scripts/create_owner.py`); no API caller can manage an
Owner because no role outranks it.
"""

ROLE_OWNER = "owner"
ROLE_ADMIN = "admin"
ROLE_TECHFM_OA = "techfm_oa"
ROLE_SUPERVISOR = "supervisor"
ROLE_TECHNICIAN = "technician"

# Higher number = more authority. Used only for `>` comparisons.
ROLE_RANK: dict[str, int] = {
    ROLE_TECHNICIAN: 0,
    ROLE_SUPERVISOR: 1,
    ROLE_TECHFM_OA: 2,
    ROLE_ADMIN: 3,
    ROLE_OWNER: 4,
}

# Newest-first is irrelevant here; this is the canonical list of every
# role the system recognises.
ALL_ROLES: tuple[str, ...] = (
    ROLE_OWNER,
    ROLE_ADMIN,
    ROLE_TECHFM_OA,
    ROLE_SUPERVISOR,
    ROLE_TECHNICIAN,
)

# Human-facing names. Every other role's label is just its capitalised
# slug, but "TechFM OA" is not derivable that way, so the mapping is
# explicit and the UI and the OpenAPI descriptions both read from it.
# `static/roles.js` carries the same table; the pair is pinned by
# `tests/test_role_mirror_parity.py`.
ROLE_LABELS: dict[str, str] = {
    ROLE_OWNER: "Owner",
    ROLE_ADMIN: "Admin",
    ROLE_TECHFM_OA: "TechFM OA",
    ROLE_SUPERVISOR: "Supervisor",
    ROLE_TECHNICIAN: "Technician",
}

# Work-order assignment roles are intentionally narrower than authority floors.
# Owners retain full access but are not operational routing/worker choices.
# TechFM OA is a routing choice for the same reason Admin is; it is not a
# worker, for the same reason Admin is not.
WORK_ORDER_SUPERVISOR_ROLES: tuple[str, ...] = (
    ROLE_ADMIN,
    ROLE_TECHFM_OA,
    ROLE_SUPERVISOR,
)
WORK_ORDER_TECHNICIAN_ROLES: tuple[str, ...] = (
    ROLE_SUPERVISOR,
    ROLE_TECHNICIAN,
)


def is_valid_role(role: str) -> bool:
    """True if `role` is one of the five recognised roles."""
    return role in ROLE_RANK


def label(role: str) -> str:
    """Human-facing name for `role`, for UI copy and OpenAPI descriptions.
    An unrecognised value is returned unchanged rather than raising -- a
    description string is never worth a 500."""
    return ROLE_LABELS.get(role, role)
```

Leave `rank`, `role_at_least`, `can_be_work_order_supervisor`, `can_be_work_order_technician`, `can_transact`, `can_manage` and `assignable_roles` exactly as they are.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
DATABASE_URL="postgresql://unused:unused@127.0.0.1:8801/unused" ./venv/Scripts/python.exe -m pytest tests/test_roles.py -q
```

Expected: PASS, all tests in the file.

- [ ] **Step 5: Commit**

```bash
git add backend/app/domain/roles.py backend/tests/test_roles.py
git commit -m "Insert the TechFM OA rank between Supervisor and Admin"
```

---

### Task 2: Frontend rank mirror and a parity guard

`static/roles.js` is maintained by hand against `domain/roles.py` and nothing has ever checked that the two agree. Renumbering both by hand is exactly when that bites, so the mirror moves in the same task as the test that pins it.

**Files:**
- Modify: `backend/static/roles.js:1-46`
- Create: `backend/tests/test_role_mirror_parity.py`

**Interfaces:**
- Consumes: `roles.ROLE_RANK`, `roles.ROLE_LABELS`, `roles.ALL_ROLES` from Task 1.
- Produces: JS exports `ROLE_RANK`, `ALL_ROLES`, `ROLE_LABELS`, `roleLabel(role)`, plus the unchanged `roleAtLeast`, `canBeWorkOrderSupervisor`, `canBeWorkOrderTechnician`, `canManage`, `assignableRoles`. Tasks 6 and 7 import `roleLabel` and `ROLE_LABELS` from here.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_role_mirror_parity.py`:

```python
"""`static/roles.js` is a hand-maintained twin of `app/domain/roles.py`.

Layer: unit (no DB, no browser). Nothing else checks that the two agree, and
they disagree silently: the frontend would simply gate the wrong things while
every backend test still passed. Parsing the JS is crude but it is the only
check that exists, and the alternative -- trusting two hand-edited rank tables
to stay in step -- is what this test is for.
"""

import ast
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.domain import roles

ROLES_JS = Path(__file__).resolve().parents[1] / "static" / "roles.js"


def _js_object_literal(source: str, name: str) -> dict:
    """Extract `export const <name> = { ... };` as a dict.

    The literals in roles.js are plain JSON once the unquoted keys are
    quoted and the trailing comma is dropped, so this stays a few lines
    rather than pulling in a JS parser.
    """
    match = re.search(
        rf"export const {name} = \{{(.*?)\}};", source, re.DOTALL
    )
    assert match, f"{name} object literal not found in roles.js"
    body = re.sub(r"(\w+):", r'"\1":', match.group(1))
    body = re.sub(r",(\s*)$", r"\1", body.strip())
    return json.loads("{" + body + "}")


def _js_array_literal(source: str, name: str) -> list:
    match = re.search(rf"export const {name} = \[(.*?)\];", source, re.DOTALL)
    assert match, f"{name} array literal not found in roles.js"
    return json.loads("[" + match.group(1).strip().rstrip(",") + "]")


def test_rank_table_matches_the_python_domain():
    source = ROLES_JS.read_text(encoding="utf-8")
    assert _js_object_literal(source, "ROLE_RANK") == roles.ROLE_RANK


def test_role_list_matches_the_python_domain():
    source = ROLES_JS.read_text(encoding="utf-8")
    assert _js_array_literal(source, "ALL_ROLES") == list(roles.ALL_ROLES)


def test_labels_match_the_python_domain():
    source = ROLES_JS.read_text(encoding="utf-8")
    assert _js_object_literal(source, "ROLE_LABELS") == roles.ROLE_LABELS
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
DATABASE_URL="postgresql://unused:unused@127.0.0.1:8801/unused" ./venv/Scripts/python.exe -m pytest tests/test_role_mirror_parity.py -q
```

Expected: FAIL. `test_rank_table_matches_the_python_domain` reports the old JS ranks (`admin: 2, owner: 3`) against the new Python ones; `test_labels_match_the_python_domain` fails its `assert` on the missing `ROLE_LABELS` literal.

- [ ] **Step 3: Update the mirror**

In `backend/static/roles.js`, replace lines 8–35 with:

```javascript
export const ROLE_RANK = {
  technician: 0,
  supervisor: 1,
  techfm_oa: 2,
  admin: 3,
  owner: 4,
};

// All roles, most-senior first.
export const ALL_ROLES = ["owner", "admin", "techfm_oa", "supervisor", "technician"];

// Human-facing names. Everything else in the UI used to capitalise the raw
// slug, which cannot produce "TechFM OA", so the mapping is explicit here and
// `roleLabel` is the single way to render a role. Mirrors ROLE_LABELS in
// app/domain/roles.py; the pair is pinned by tests/test_role_mirror_parity.py.
export const ROLE_LABELS = {
  owner: "Owner",
  admin: "Admin",
  techfm_oa: "TechFM OA",
  supervisor: "Supervisor",
  technician: "Technician",
};

// Human-facing name for `role`. Unrecognised values come back unchanged
// rather than blank, so a stale account still renders something readable.
export function roleLabel(role) {
  return ROLE_LABELS[role] || role || "";
}

function rank(role) {
  return role in ROLE_RANK ? ROLE_RANK[role] : -1;
}

// True if `role` has at least the authority of `minimum`.
export function roleAtLeast(role, minimum) {
  return rank(role) >= rank(minimum);
}

// Operational Work Order assignment eligibility mirrors app/domain/roles.py.
// Owner retains full authority but is not an assignment target. TechFM OA is
// a routing choice for the same reason Admin is.
export function canBeWorkOrderSupervisor(role) {
  return role === "admin" || role === "techfm_oa" || role === "supervisor";
}

export function canBeWorkOrderTechnician(role) {
  return role === "supervisor" || role === "technician";
}
```

Leave `canManage` and `assignableRoles` (lines 37–46) unchanged — they read `ROLE_RANK` and `ALL_ROLES` and pick the new role up automatically. Update the header comment on line 6 from "Keep the rank values in sync with the Python module" to "Keep the rank values and labels in sync with the Python module; tests/test_role_mirror_parity.py enforces it."

- [ ] **Step 4: Run the test to verify it passes**

```bash
DATABASE_URL="postgresql://unused:unused@127.0.0.1:8801/unused" ./venv/Scripts/python.exe -m pytest tests/test_role_mirror_parity.py tests/test_roles.py -q
```

Expected: PASS, 3 parity tests plus the Task 1 suite.

- [ ] **Step 5: Commit**

```bash
git add backend/static/roles.js backend/tests/test_role_mirror_parity.py
git commit -m "Mirror the TechFM OA rank in roles.js and pin the twin"
```

---

### Task 3: Move the capability floor off Admin

The mechanical core. 41 of the 42 `roles.ROLE_ADMIN` references in `backend/app` move down a tier; the Review handoff stays.

**Files:**
- Modify: `backend/app/main.py`, `backend/app/domain/{realtime,work_orders}.py`, `backend/app/services/{mass_staging,work_orders}.py`, `backend/app/routers/{items,netfacilities,tools,transactions,user_requests,users,work_orders}.py`
- Test: `backend/tests/test_route_role_gates.py`, `backend/tests/test_item_barcodes.py`

**Interfaces:**
- Consumes: `roles.ROLE_TECHFM_OA` and `roles.label()` from Task 1.
- Produces: no new symbols. After this task, `roles.ROLE_ADMIN` appears in `backend/app` exactly once, inside `_require_review_handoff_permission`.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_route_role_gates.py`, change `roles.ROLE_ADMIN` to `roles.ROLE_TECHFM_OA` on these assertion lines: 82, 92, 96, 101, 182, 197, 216, 217, 220, 247, 267, 304, 443, 447, 451, 455, 459. **Do not change line 145** — that one constructs an actor (`SimpleNamespace(role=roles.ROLE_ADMIN)`), it is not an assertion about a floor.

Update the comment above line 82 to reflect the new rule:

```python
def test_update_user_role_requires_techfm_oa():
    # Changing someone's role is TechFM OA+; the outranks-the-target rule inside
    # the handler is additional, not a substitute. That inner rule is what stops
    # a TechFM OA from touching an Admin, and what stops a Supervisor from
    # re-roling a Technician they do outrank.
    assert _min_role_for(users_router, "update_user_role") == roles.ROLE_TECHFM_OA
```

Rename the three other assertion functions whose names now misdescribe them: `test_archive_work_order_requires_admin` → `..._requires_techfm_oa` (line 181), `test_netfacilities_routes_require_admin_and_document_403` → `..._require_techfm_oa_and_document_403` (line 196), `test_user_request_routes_require_admin` → `..._require_techfm_oa` (line 303). Same for `test_update_item_requires_admin`, `test_delete_item_requires_admin`, `test_create_correction_requires_admin` (lines 91, 95, 99) and the five `tools_router` tests at 442–459.

Then append the guard test:

```python
def test_no_route_gate_is_left_at_the_admin_floor():
    # After the TechFM OA insert, every route that once read "Admin or above"
    # means "TechFM OA or above" -- the Admin floor survives in exactly one
    # place, and it is a service-level check inside the Review handoff, not a
    # route gate. A new route written with ROLE_ADMIN out of habit would
    # silently lock TechFM OA out of a capability it is supposed to have, and
    # nothing else in the suite would notice. This is that notice.
    #
    # If a genuinely Admin-only route is ever added, add its endpoint name to
    # the expected set here, deliberately and with a reason.
    from app.main import app as fastapi_app

    offenders = {
        route.endpoint.__name__
        for route in fastapi_app.routes
        if isinstance(route, APIRoute)
        and _find_min_role(route.dependant) == roles.ROLE_ADMIN
    }
    assert offenders == set()
```

In `backend/tests/test_item_barcodes.py`, change line 126 from `roles.ROLE_ADMIN` to `roles.ROLE_TECHFM_OA`. Leave lines 81 and 47-in-`test_item_price_gating.py` alone — those pass an actor, not a floor.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
DATABASE_URL="postgresql://unused:unused@127.0.0.1:8801/unused" ./venv/Scripts/python.exe -m pytest tests/test_route_role_gates.py tests/test_item_barcodes.py -q
```

Expected: FAIL, roughly 25 failures of the form `assert 'admin' == 'techfm_oa'`, plus `test_no_route_gate_is_left_at_the_admin_floor` failing with a large non-empty `offenders` set.

- [ ] **Step 3: Move the floor**

Replace across the twelve implementation files, then put the one exception back:

```bash
grep -rl 'roles\.ROLE_ADMIN' backend/app | xargs sed -i 's/roles\.ROLE_ADMIN/roles.ROLE_TECHFM_OA/g'
```

Now restore the Review handoff floor. In `backend/app/services/work_orders.py`, `_require_review_handoff_permission` (around line 271) must read `roles.ROLE_ADMIN` again, and its docstring is rewritten to record why:

```python
def _require_review_handoff_permission(
    work_order: WorkOrder, user: Optional[User]
) -> None:
    """Require a second person before a Completed work order enters Review.

    Internal callers retain their existing bypass. An authenticated caller may
    not review work they are assigned to perform, even when they are also the
    routed Supervisor. Otherwise Admin+ has global authority and the unassigned
    routed Supervisor owns the operational handoff.

    The `ROLE_ADMIN` floor below is the one place in the application that still
    means Admin rather than TechFM OA, and it is deliberate: the Review handoff
    is the single capability an Admin holds that a TechFM OA does not. A TechFM
    OA may be the routed supervisor on a work order and still cannot complete
    the handoff -- Review is a second-person control, so an Admin, the Owner, or
    another routed Supervisor closes it out.
    """
    if user is None:
        return
    if user.id in _assigned_technician_ids(work_order):
        raise RoleManagementError(
            "An assigned worker cannot send their own work order to Review. "
            "Another routed Supervisor, Admin, or Owner must review it."
        )
    if roles.role_at_least(user.role, roles.ROLE_ADMIN):
        return
    if (
        user.role == roles.ROLE_SUPERVISOR
        and work_order.supervisor_id == user.id
    ):
        return
    raise RoleManagementError(
        "Only the unassigned routed Supervisor, an Admin, or the Owner can "
        "send a work order to Review."
    )
```

Then fix the two OpenAPI description strings, which interpolate the raw slug and would otherwise read "Requires techfm_oa role or higher":

`backend/app/routers/netfacilities.py:46-47`

```python
def _forbidden() -> dict[int, dict[str, str]]:
    return {
        403: {
            "description": (
                f"Requires the {roles.label(roles.ROLE_TECHFM_OA)} role or higher."
            )
        }
    }
```

`backend/app/routers/work_orders.py:252`

```python
    return {403: {"description": f"Requires the {roles.label(minimum)} role or above."}}
```

Finally, sweep the prose. `sed` moved the constants but not the comments and error strings around them, several of which now say "Admin" where they mean the TechFM OA floor. Read each changed hunk and correct the wording — in particular `backend/app/services/work_orders.py:88-90` (the `_ADMIN_UPDATE_FIELDS` comment and the `_require_update_permissions` message "Only an Admin or Owner can edit imported work order details."), `backend/app/services/work_orders.py:1514` ("Only an Admin or Owner can archive a work order."), and the `_scoped_to_user` docstring at line 887.

- [ ] **Step 4: Verify the count, then run the tests**

```bash
grep -rn 'roles\.ROLE_ADMIN' backend/app
```

Expected: **exactly one line**, inside `_require_review_handoff_permission` in `backend/app/services/work_orders.py`. If more appear, they were missed; if none appears, the exception was overwritten.

```bash
DATABASE_URL="postgresql://unused:unused@127.0.0.1:8801/unused" ./venv/Scripts/python.exe -m pytest tests/test_route_role_gates.py tests/test_item_barcodes.py tests/test_roles.py tests/test_role_mirror_parity.py -q
```

Expected: PASS, including `test_no_route_gate_is_left_at_the_admin_floor`.

- [ ] **Step 5: Run the whole pure suite for collateral damage**

```bash
DATABASE_URL="postgresql://unused:unused@127.0.0.1:8801/unused" ./venv/Scripts/python.exe -m pytest -q
```

Expected: no new failures versus the pre-change baseline. DB-backed tests skip. If you did not capture a baseline before Task 1, capture one now from `git stash` and compare — do not assume a failure is pre-existing.

- [ ] **Step 6: Commit**

```bash
git add backend/app backend/tests/test_route_role_gates.py backend/tests/test_item_barcodes.py
git commit -m "Move the Admin capability floor down to TechFM OA"
```

---

### Task 4: Pin the Review exclusion

No production behaviour changes here — Task 3 already left the handoff at the Admin floor. This task proves it, as a pure unit test rather than a DB one, so the rule is verifiable on a machine with no database.

**Files:**
- Test: `backend/tests/test_work_orders_service.py`

**Interfaces:**
- Consumes: `services.work_orders._require_review_handoff_permission(work_order, user)` and `roles.ROLE_TECHFM_OA`.
- Produces: nothing.

- [ ] **Step 1: Write the failing test**

`_require_review_handoff_permission` reads only `user.id`, `user.role`, `work_order.supervisor_id`, and (via `_assigned_technician_ids`) `work_order.technician_assignments` and `work_order.assigned_to_id` — all through `getattr` with fallbacks. So it takes stand-ins and needs no database. Append to `backend/tests/test_work_orders_service.py`:

```python
def _review_stub_work_order(supervisor_id=None, assigned_to_id=None):
    """Minimal stand-in for the four attributes the handoff gate reads."""
    return SimpleNamespace(
        supervisor_id=supervisor_id,
        assigned_to_id=assigned_to_id,
        technician_assignments=(),
    )


def test_techfm_oa_cannot_send_a_work_order_to_review():
    # The single capability an Admin has and a TechFM OA does not. No special
    # case implements this -- it falls out of ranking below Admin -- so the
    # rule needs a test of its own or a future re-rank would silently grant it.
    actor = SimpleNamespace(id=uuid.uuid4(), role=roles.ROLE_TECHFM_OA)
    with pytest.raises(RoleManagementError):
        wos._require_review_handoff_permission(
            _review_stub_work_order(), actor
        )


def test_techfm_oa_cannot_review_even_as_the_routed_supervisor():
    # TechFM OA IS a valid routing target (WORK_ORDER_SUPERVISOR_ROLES), so
    # this is reachable in production: they own the work order operationally
    # and still hand the final step to an Admin, Owner, or routed Supervisor.
    actor = SimpleNamespace(id=uuid.uuid4(), role=roles.ROLE_TECHFM_OA)
    with pytest.raises(RoleManagementError):
        wos._require_review_handoff_permission(
            _review_stub_work_order(supervisor_id=actor.id), actor
        )


def test_admin_and_owner_still_send_work_orders_to_review():
    for role in (roles.ROLE_ADMIN, roles.ROLE_OWNER):
        actor = SimpleNamespace(id=uuid.uuid4(), role=role)
        wos._require_review_handoff_permission(
            _review_stub_work_order(), actor
        )


def test_unassigned_routed_supervisor_still_sends_to_review():
    actor = SimpleNamespace(id=uuid.uuid4(), role=roles.ROLE_SUPERVISOR)
    wos._require_review_handoff_permission(
        _review_stub_work_order(supervisor_id=actor.id), actor
    )
```

Check the file's existing imports before adding: it needs `uuid`, `pytest`, `SimpleNamespace` from `types`, `roles` from `app.domain`, `RoleManagementError`, and the `wos` alias for `app.services.work_orders`. Add only what is missing.

- [ ] **Step 2: Run the tests to verify the new ones fail for the right reason**

Temporarily flip the floor in `_require_review_handoff_permission` to `roles.ROLE_TECHFM_OA`, run, and confirm the two `techfm_oa` tests fail. Then put `roles.ROLE_ADMIN` back.

```bash
DATABASE_URL="postgresql://unused:unused@127.0.0.1:8801/unused" ./venv/Scripts/python.exe -m pytest tests/test_work_orders_service.py -q -k "review"
```

This step matters: with no production change in this task, a test that passes immediately proves nothing about whether it can fail.

- [ ] **Step 3: Run the tests to verify they pass**

With `roles.ROLE_ADMIN` restored:

```bash
DATABASE_URL="postgresql://unused:unused@127.0.0.1:8801/unused" ./venv/Scripts/python.exe -m pytest tests/test_work_orders_service.py -q -k "review"
```

Expected: the four new tests PASS. The pre-existing DB-backed review tests in the same file SKIP.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_work_orders_service.py
git commit -m "Pin the Review handoff as the one Admin-only capability"
```

---

### Task 5: Role-management rules end to end

**DB-backed — will SKIP locally.** Write it, confirm it is collected, and let CI run it. Do not claim it passes on the strength of a skip.

**Files:**
- Test: `backend/tests/test_user_role_edit.py`

**Interfaces:**
- Consumes: `_create_user(db, role)` (already in the file at line 29), `update_user_role_route`, `UserRoleUpdate`, `roles.ROLE_TECHFM_OA`.
- Produces: nothing.

- [ ] **Step 1: Write the tests**

Append to `backend/tests/test_user_role_edit.py`:

```python
def test_techfm_oa_cannot_change_an_admin_or_owner_role(db):
    actor = _create_user(db, roles.ROLE_TECHFM_OA)
    for target_role in (roles.ROLE_ADMIN, roles.ROLE_OWNER, roles.ROLE_TECHFM_OA):
        target = _create_user(db, target_role)
        with pytest.raises(HTTPException) as exc:
            update_user_role_route(
                target.id,
                UserRoleUpdate(role=roles.ROLE_SUPERVISOR),
                actor=actor,
                db=db,
            )
        assert exc.value.status_code == 403
        assert target.role == target_role


def test_techfm_oa_cannot_hand_out_admin_or_owner(db):
    actor = _create_user(db, roles.ROLE_TECHFM_OA)
    target = _create_user(db, roles.ROLE_TECHNICIAN)
    for role in (roles.ROLE_ADMIN, roles.ROLE_OWNER, roles.ROLE_TECHFM_OA):
        with pytest.raises(HTTPException) as exc:
            update_user_role_route(
                target.id, UserRoleUpdate(role=role), actor=actor, db=db
            )
        assert exc.value.status_code == 403
    assert target.role == roles.ROLE_TECHNICIAN


def test_techfm_oa_can_re_role_subordinates(db):
    actor = _create_user(db, roles.ROLE_TECHFM_OA)
    target = _create_user(db, roles.ROLE_TECHNICIAN)

    promoted = update_user_role_route(
        target.id,
        UserRoleUpdate(role=roles.ROLE_SUPERVISOR),
        actor=actor,
        db=db,
    )
    assert promoted.role == roles.ROLE_SUPERVISOR


def test_admin_can_promote_a_supervisor_to_techfm_oa(db):
    # The counterpart to the rank choice: Admins must retain control of these
    # accounts, which is exactly what a shared Admin rank would have broken.
    admin = _create_user(db, roles.ROLE_ADMIN)
    target = _create_user(db, roles.ROLE_SUPERVISOR)

    promoted = update_user_role_route(
        target.id,
        UserRoleUpdate(role=roles.ROLE_TECHFM_OA),
        actor=admin,
        db=db,
    )
    assert promoted.role == roles.ROLE_TECHFM_OA
```

Check how the file's existing 403 tests assert — `test_admin_cannot_assign_own_rank_or_above` around line 66 already uses `pytest.raises(HTTPException)`. Match whatever it does rather than the sketch above if they differ.

- [ ] **Step 2: Confirm the tests are collected and skip cleanly**

```bash
DATABASE_URL="postgresql://unused:unused@127.0.0.1:8801/unused" ./venv/Scripts/python.exe -m pytest tests/test_user_role_edit.py -q -rs
```

Expected: `4 skipped` for the new tests (plus the file's existing skips), with the skip reason naming the unreachable database — **not** `error` and not `0 collected`. A collection error means an import or signature mistake and must be fixed here.

- [ ] **Step 3: Also confirm the schema accepts the new role**

```bash
DATABASE_URL="postgresql://unused:unused@127.0.0.1:8801/unused" ./venv/Scripts/python.exe -m pytest tests/test_user_role_edit.py::test_role_payload_rejects_unknown_role -q
```

Expected: PASS. `UserRoleUpdate.role_recognised` (`app/schemas/users.py:100`) validates against `roles.is_valid_role`, so `techfm_oa` is accepted with no schema change — this test confirms the validator still rejects genuine garbage.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_user_role_edit.py
git commit -m "Cover TechFM OA role-management limits"
```

---

### Task 6: Frontend capability gates, navigation, and labels

No JS test harness exists in this repo, so verification is by reading plus the manual check in Task 8. Be correspondingly careful.

**Files:**
- Modify: `backend/static/views/history.js:263`, `backend/static/views/workOrders.js:130`, `backend/static/views/users.js:51,103,126,143`, `backend/static/views/items.js:156`, `backend/static/views/scan.js:284`, `backend/static/views/tools.js:101,108`, `backend/static/views/nav.js:57-93`

**Interfaces:**
- Consumes: `roleLabel` and `ROLE_LABELS` from `static/roles.js` (Task 2).
- Produces: nothing new.

- [ ] **Step 1: Move the six capability gates**

Change `"admin"` to `"techfm_oa"` in the `roleAtLeast` call at each of these lines, leaving the surrounding code alone:

| File:line | Current | Meaning |
| --- | --- | --- |
| `views/history.js:263` | `roleAtLeast(getRole(), "admin")` | price visibility |
| `views/workOrders.js:130` | `roleAtLeast(getRole(), "admin")` | admin work-order controls |
| `views/users.js:103` | `roleAtLeast(actorRole, "admin")` | Edit Role button |
| `views/items.js:156` | `roleAtLeast(role, "admin")` | admin item controls |
| `views/scan.js:284` | `roleAtLeast(getRole(), "admin")` | admin scan path |
| `views/tools.js:101` | `roleAtLeast(getRole(), "admin")` | tool custody management |

**Do not touch `views/workOrders.js:382`.** That is `canCurrentUserSendToReview`, and it must keep the `"admin"` floor — it is the Review gate, and Task 7 depends on it still returning false for a TechFM OA.

- [ ] **Step 2: Add the new role to navigation**

In `backend/static/views/nav.js`, add `"techfm_oa"` to every `PAGE_ACCESS` list that already contains `"admin"`, immediately after it (lines 58–76). All eleven entries qualify:

```javascript
export const PAGE_ACCESS = {
  "create-item": ["owner", "admin", "techfm_oa"],
  "saved-items": ["owner", "admin", "techfm_oa", "supervisor", "technician"],
  "create-user": ["owner", "admin", "techfm_oa", "supervisor"],
  "saved-users": ["owner", "admin", "techfm_oa", "supervisor"],
  // Technicians get scan-and-go too, but dispense-only (enforced server-side
  // in roles.can_transact; the UI hides the Stock toggle for them).
  "transaction": ["owner", "admin", "techfm_oa", "supervisor", "technician"],
  "mass-stage": ["owner", "admin", "techfm_oa", "supervisor"],
  // Work Orders is technician-facing (server scopes to assigned/created/all).
  "work-orders": ["owner", "admin", "techfm_oa", "supervisor", "technician"],
  // Operational exceptions such as inventory recounts are managed by Admin+.
  "user-requests": ["owner", "admin", "techfm_oa"],
  // Final billing/close queue. Cost detail and archive are Admin/Owner-only.
  // A TechFM OA works this queue; they just cannot put a work order into it.
  "admin-review": ["owner", "admin", "techfm_oa"],
  // Tools: every role sees its user-first custody card and can check in;
  // Admin+ can search active users and check out tools. The server retains
  // the existing gate on checkout and the authenticated-user return gate.
  "tools": ["owner", "admin", "techfm_oa", "supervisor", "technician"],
  "history": ["owner", "admin", "techfm_oa", "supervisor"],
};
```

Then add the landing page at line 88–93:

```javascript
const LANDING_PAGE_BY_ROLE = {
  technician: "transaction",
  supervisor: "work-orders",
  techfm_oa: "history",
  admin: "history",
  owner: "history",
};
```

- [ ] **Step 3: Route the three display sites through the label map**

`backend/static/views/tools.js` — replace the local `roleLabel` (lines 108–110) with the shared one. Delete the function and add `roleLabel` to the existing import from `../roles.js`. Confirm the import path matches the file's other imports before editing.

`backend/static/views/users.js:143` — inside `populateRoleSelect`, replace the inline capitalisation:

```javascript
    option.textContent = roleLabel(role);
```

`backend/static/views/users.js:126` — the Users table Role cell currently prints the raw slug:

```javascript
      <td data-label="Role">${escapeHtml(roleLabel(user.role))}</td>
```

Add `roleLabel` to the `../roles.js` import in `users.js` alongside the existing `canManage`, `roleAtLeast`, `assignableRoles`.

- [ ] **Step 4: Add the role description**

`backend/static/views/users.js:51-56`:

```javascript
const ROLE_DESCRIPTIONS = {
  technician: "Scan items and do basic work.",
  supervisor: "Record stock, edit notes, view history.",
  techfm_oa: "Everything an Admin does, except sending work orders to Review and changing Admin roles.",
  admin: "Manage items and corrections.",
  owner: "Top-level setup.",
};
```

- [ ] **Step 5: Verify no capability gate was missed**

```bash
grep -rn 'roleAtLeast(.*"admin"' backend/static
```

Expected: **exactly one line**, `backend/static/views/workOrders.js:382`.

```bash
grep -rn '"admin"' backend/static | grep -v roles.js | grep -v techfm_oa
```

Expected: no hits outside `views/workOrders.js:382`. Any `PAGE_ACCESS` list still lacking `techfm_oa` shows up here.

- [ ] **Step 6: Commit**

```bash
git add backend/static
git commit -m "Give TechFM OA the Admin frontend surface and a display label"
```

---

### Task 7: The disabled Send to Review button

**Files:**
- Modify: `backend/static/views/workOrders.js:888-894`

**Interfaces:**
- Consumes: `canCurrentUserSendToReview(detail)` (unchanged, still `"admin"`-floored), `getRole()` from `../state.js`.
- Produces: nothing.

- [ ] **Step 1: Make the change**

In `renderBody`, the `completed` branch currently emits the button only when permitted. Replace lines 891–894:

```javascript
  } else if (detail.status === "completed") {
    if (canSendToReview) {
      statusActions += `<button type="button" data-action="review-wo">Send to Review</button>`;
    } else if (getRole() === "techfm_oa") {
      // A TechFM OA holds the rest of the Admin toolkit, so a missing button
      // reads as a bug to them rather than as a rule. Show it, disabled, with
      // the reason. Every other role keeps the hidden treatment -- for them
      // Review was never on the menu. The server refuses the transition either
      // way (services/work_orders._require_review_handoff_permission).
      statusActions += `<button type="button" data-action="review-wo" disabled title="An Admin, Owner, or the routed Supervisor must send this to Review.">Send to Review</button>`;
    }
    if (sup) {
```

- [ ] **Step 2: Confirm the click handler cannot fire**

```bash
grep -n 'review-wo' backend/static/views/workOrders.js
```

A `disabled` button emits no click event, so the existing `data-action="review-wo"` delegate cannot be reached. Read the handler to confirm it is a plain delegated click listener and not something that inspects `data-action` on a parent or on keydown. If it is anything other than a click delegate, add an explicit `disabled` guard at the top of the handler and note it in the commit message.

- [ ] **Step 3: Confirm the import**

`getRole` must be imported in `workOrders.js`. Check the import block at the top of the file:

```bash
grep -n 'getRole' backend/static/views/workOrders.js
```

If `getRole` is not already imported from `../state.js`, add it to that import. Line 126 uses `roleAtLeast(getRole(), ...)`, so it almost certainly is.

- [ ] **Step 4: Commit**

```bash
git add backend/static/views/workOrders.js
git commit -m "Show TechFM OA a disabled Send to Review with the reason"
```

---

### Task 8: Documentation and manual verification

**Files:**
- Modify: `docs/current-state.md`, `docs/endpoint-map.md`, `docs/project-summary.md`

**Interfaces:**
- Consumes: everything above.
- Produces: nothing.

- [ ] **Step 1: Update `docs/current-state.md`**

- The role order block at ~L725 and the permission matrix at ~L734–746: add TechFM OA as the third rank, and add a matrix row making the Review exclusion explicit.
- L746 "Change a user's role | admin+ AND actor outranks both the current and the new role" → the floor is now TechFM OA+.
- L1276 (`PATCH /users/{user_id}/role`) and any other endpoint row reading "admin+".
- L186 (`backend/static/roles.js` description) — mention the labels and the new parity test.
- The tests table at ~L2405–2410: add `test_role_mirror_parity.py`, and update the `test_roles.py` and `test_route_role_gates.py` rows.
- The `PAGE_ACCESS` mirror if the doc reproduces it.

- [ ] **Step 2: Update `docs/endpoint-map.md`**

- L114 — the `PATCH /users/{id}/role` gate column.
- L1060–1062 — the ranks line becomes `technician 0 < supervisor 1 < techfm_oa 2 < admin 3 < owner 4`, and `can_be_work_order_supervisor` now lists three roles.
- L677–678 and L685 — the `role` field descriptions, if they enumerate roles.

- [ ] **Step 3: Update `docs/project-summary.md`**

L16, L21, L107, L125 all describe Admin-floored behaviour that is now TechFM OA-floored. L21's "change only strictly subordinate roles" is still accurate and needs no change.

- [ ] **Step 4: Search for stragglers**

```bash
grep -rn 'four roles\|Admin+\|admin+' docs/ backend/app backend/static
```

Read each hit and decide whether it now means TechFM OA+. Do not blanket-replace — several are about the Review handoff or the Owner bootstrap and are still correct.

- [ ] **Step 5: Full suite**

```bash
DATABASE_URL="postgresql://unused:unused@127.0.0.1:8801/unused" ./venv/Scripts/python.exe -m pytest -q
```

Expected: no failures beyond the pre-change baseline; DB-backed tests skip.

- [ ] **Step 6: Manual verification**

Do not start the server automatically — the user validates manually. Hand them this checklist:

1. Create a TechFM OA account from an Admin login. Confirm the role appears in the create-user dropdown, reads "TechFM OA", and shows its description.
2. Sign in as that account. Confirm it lands on History and sees the Admin nav set including Admin Review and User Requests.
3. Open a Completed work order. Confirm **Send to Review** is visible, greyed out, and shows the tooltip on hover.
4. On the Users page, confirm Edit Role appears for Supervisors and Technicians and **not** for Admins or other TechFM OAs.
5. Confirm the Users table Role column reads "TechFM OA", not "techfm_oa".
6. Hard-reload with Ctrl+Shift+R before testing — cached ES modules will otherwise serve the old `roles.js`.

- [ ] **Step 7: Commit**

```bash
git add docs/
git commit -m "Document the TechFM OA role"
```

---

## Notes for the executor

- **The `sed` in Task 3 is broad on purpose, and its comment sweep is not optional.** The constants move mechanically; the prose around them does not. Read every hunk.
- **Two floors look identical and are not.** `roleAtLeast(role, "admin")` at `workOrders.js:382` and `role_at_least(user.role, ROLE_ADMIN)` in `_require_review_handoff_permission` are the Review gate and must stay at Admin. Every other occurrence moves.
- **Task 5 cannot be verified on this machine.** The local Postgres credentials are unknown. If the user supplies them, re-run Task 5 and Task 3's full suite against the real database before calling the work done.
