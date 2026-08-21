# Hub Priorities Card & Admin Priority Graphs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task (this repo's CLAUDE.md disables the Agent tool by default, so superpowers:subagent-driven-development is not available here unless the user explicitly opts in). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every role a live "Priorities" card at the top of the User Hub Dashboard tab showing High-priority work-order counts scoped to that role (Technician: assigned to them; Supervisor/Admin+: assigned within their scope and unassigned within their scope), and give TechFM OA+ two new status-breakdown pie charts — High priority and Medium priority — at the top of the existing Graphs tab.

**Architecture:** Add one shared priority-bucketing rule to `app/domain/work_orders.py` (extends the existing free-text keyword classification already used by the JS `priorityBucket()` badge helper) so the card and the graphs can never disagree about what counts as "High" or "Medium." Extend the three existing hub service functions (`personal_hub`, `crew_hub`, `admin_hub`) and the existing `graphs_hub` function with new fields on their existing payload dataclasses — no new endpoints. Extend the matching Pydantic schemas and let the existing `model_validate`/field-by-field router code pick the new fields up. On the frontend, add one new view module (`hubPriorities.js`) and one new mount point inside the existing Dashboard tab body, wire it into the existing crew/admin render and refresh functions in `userHub.js`, and widen the existing live-refresh plumbing (safety timer, `work_order.status.changed` subscription) so it runs for every role instead of only TechFM OA+.

**Tech Stack:** FastAPI + SQLAlchemy + Pydantic (backend), plain ES modules with no build step under CSP `default-src 'self'` (frontend), pytest for all tests (no JS test runner in this repo).

**Spec:** No separate spec document — this plan is written directly from the brainstorming conversation on 2026-08-21 (the user explicitly asked to skip the spec-writing step). The agreed decisions it implements:

- **Priority mapping:** High = raw priority text containing `high`, `urgent`, or `emergency` (case-insensitive substring). Medium = raw priority text containing `normal`, `routine`, or `standard`. This extends (does not replace) the existing `priorityBucket()` keyword logic in `backend/static/views/workOrders.js:479-488`, which is left untouched.
- **Supervisor "assigned to them"** = work orders they lead (`supervisor_id = them`), the same set `_led_work_orders` already returns for the crew board — not work orders where they're personally an assigned technician.
- **Supervisor "unassigned"** = within that led set, High-priority work orders with no technician assigned (no `assigned_to_id` and no `work_order_technicians` row).
- **Admin+ (TechFM OA, Admin, Owner)** gets the same two-number shape as Supervisor (assigned / unassigned), but company-wide and unscoped, mirroring how `admin_hub` already widens `crew_hub`'s scope.
- **Technician** sees one number only: High-priority work orders assigned to them personally (the existing `_assigned_work_orders` definition), no unassigned count.
- **Placement:** top of the Dashboard tab, above the existing counts tiles.
- **Live updates:** same plumbing as the rest of the hub — refresh on `work_order.status.changed` and the 60-second visible-page safety timer, not load-once.
- **Graphs tab:** two new donut cards, "High priority" and "Medium priority," each the same 7-status breakdown format as the existing community/service-type donuts, scoped to live (non-archived) work orders in that priority bucket, company-wide, placed above the existing "Status by community" section.

## Global Constraints

- **No new endpoints.** Every new field rides on `GET /hub`, `GET /hub/crew`, `GET /hub/admin`, and `GET /hub/graphs`, which already exist and are already gated at `any authenticated` / `supervisor+` / `techfm_oa+` / `techfm_oa+` respectively (`backend/app/routers/hub.py`).
- **No new dependencies, no build step.** Same CSP (`default-src 'self'`) and plain-ES-module constraint as the rest of `backend/static/`.
- **Test command** (run from `backend/`, never the repo root): `venv/Scripts/python.exe -m pytest tests/<file> -v`. Always the venv's `python.exe -m pytest`, never the bare `pytest.exe` shim.
- **The repository's DB test fixture shares one local PostgreSQL database** (port 8801) rather than resetting per test. Every new service-layer test must assert on a **before/after delta**, exactly like `test_graphs_hub_counts_live_statuses_by_community_and_service_type` in `backend/tests/test_hub_service.py:588-622` — never on an absolute count.
- **`weeks: int` stays plain `int`, not `Literal[12, 26, 52]`, in the graphs router** (`backend/app/routers/hub.py:127-130`) — a documented FastAPI/Pydantic bug in this pinned version 422s a `Literal` query param on every real request. Do not "fix" this while touching the file.
- **Every hub payload field must be `from_attributes`-compatible.** The service returns frozen dataclasses; schemas use `model_config = {"from_attributes": True}` and most routes call `model_validate` directly on the dataclass. Field names must match exactly between a service dataclass and its schema, or the value silently serializes as `null` instead of erroring (see `backend/app/schemas/hub.py:1-12`'s own docstring on this).
- **Do not weaken the CI gate.** Merging to `main` deploys to production. Do not merge without asking.
- **The owner validates UI manually** and prefers the preview server not be auto-started (per project memory). Hand off manual-check steps at the end rather than starting a server yourself.

---

## File Structure

| File | Responsibility |
|---|---|
| **Modify** `backend/app/domain/work_orders.py` | Add `priority_bucket()`, `PRIORITY_HIGH`, `PRIORITY_MEDIUM` — the one shared High/Medium classification rule. |
| **Modify** `backend/app/services/hub.py` | Add `PriorityCounts` dataclass; extend `personal_hub`, `crew_hub`, `admin_hub` to compute it; extend `graphs_hub` to add two priority distributions. |
| **Modify** `backend/app/schemas/hub.py` | Add `HubPriorityCounts`; add `priority` field to `HubResponse`/`HubCrewResponse`/`HubAdminResponse`; add `priority_high`/`priority_medium` to `HubGraphsResponse`. |
| **Modify** `backend/app/routers/hub.py` | Pass the new field through in `get_hub`'s field-by-field construction (the other three routes already use `model_validate` and need no route-body change). |
| **Create** `backend/static/views/hubPriorities.js` | Renders the role-scoped Priorities card. |
| **Modify** `backend/static/views/hubTechnician.js` | Add the `#hub-priorities-mount` placeholder at the top of `mountHubDashboard`'s markup. |
| **Modify** `backend/static/views/hubGraphs.js` | Render the two new priority donut cards above "Status by community." |
| **Modify** `backend/static/views/userHub.js` | Wire `mountHubPriorities` into the existing render/refresh functions; widen the safety timer and the `work_order.status.changed` subscription to run for every role, not just TechFM OA+. |
| **Modify** `backend/static/styles.css` | One small `.hub-priorities` rule (spacing only — the tile/donut CSS already exists). |
| **Modify** `backend/tests/test_work_orders_domain.py` | Cover `priority_bucket()`. |
| **Modify** `backend/tests/test_hub_service.py` | Cover the three services' new priority counts. |
| **Modify** `backend/tests/test_hub_graphs_domain.py` | Cover the two new graph distributions. |
| **Modify** `backend/tests/test_hub_router.py` | Cover the new fields serializing through `GET /hub` and `GET /hub/graphs`. |

---

### Task 1: Add the shared priority-bucket domain rule

**Files:**
- Modify: `backend/app/domain/work_orders.py` (add near `normalize_priority_filter`, around line 245)
- Test: `backend/tests/test_work_orders_domain.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `priority_bucket(value: Optional[str]) -> str`, returning one of `PRIORITY_HIGH`, `PRIORITY_MEDIUM`, `PRIORITY_LOW`, `PRIORITY_NONE`, `PRIORITY_UNKNOWN`. `PRIORITY_HIGH = "high"` and `PRIORITY_MEDIUM = "medium"` are the two constants every later task imports.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_work_orders_domain.py`:

```python
def test_priority_bucket_folds_urgent_and_emergency_into_high():
    assert wo.priority_bucket("High") == wo.PRIORITY_HIGH
    assert wo.priority_bucket("URGENT") == wo.PRIORITY_HIGH
    assert wo.priority_bucket("Emergency Call-Out") == wo.PRIORITY_HIGH


def test_priority_bucket_folds_routine_and_standard_into_medium():
    assert wo.priority_bucket("Normal") == wo.PRIORITY_MEDIUM
    assert wo.priority_bucket("Routine Maintenance") == wo.PRIORITY_MEDIUM
    assert wo.priority_bucket("Standard") == wo.PRIORITY_MEDIUM


def test_priority_bucket_low_and_unknown_and_none():
    assert wo.priority_bucket("Low") == wo.PRIORITY_LOW
    assert wo.priority_bucket("Priority 3") == wo.PRIORITY_UNKNOWN
    assert wo.priority_bucket(None) == wo.PRIORITY_NONE
    assert wo.priority_bucket("") == wo.PRIORITY_NONE
    assert wo.priority_bucket("   ") == wo.PRIORITY_NONE


def test_priority_bucket_is_case_and_whitespace_insensitive():
    assert wo.priority_bucket("  hIgH  ") == wo.PRIORITY_HIGH
```

Check the top of `backend/tests/test_work_orders_domain.py` already imports `from app.domain import work_orders as wo` (it does, following the same pattern `test_hub_graphs_domain.py` uses) — if the file under a different alias, match the existing import instead of adding a second one.

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `backend/`):
```bash
venv/Scripts/python.exe -m pytest tests/test_work_orders_domain.py -v -k priority_bucket
```
Expected: all FAIL with `AttributeError: module 'app.domain.work_orders' has no attribute 'priority_bucket'`.

- [ ] **Step 3: Implement it**

In `backend/app/domain/work_orders.py`, add immediately after `normalize_priority_filter` (after line 244):

```python
# The severity classification the Priorities card and the Graphs-tab priority
# pies both key off. Deliberately narrower than `priorityBucket()` in
# `static/views/workOrders.js` (which also distinguishes "emergency" and
# "urgent" as their own badge colors) -- this rule folds all three into one
# High bucket, and normal/routine/standard into one Medium bucket, because
# neither surface this feeds needs a finer severity ladder than the vendor's
# free text actually supports.
PRIORITY_HIGH = "high"
PRIORITY_MEDIUM = "medium"
PRIORITY_LOW = "low"
PRIORITY_NONE = "none"
PRIORITY_UNKNOWN = "unknown"

_PRIORITY_HIGH_KEYWORDS = ("high", "urgent", "emergency")
_PRIORITY_MEDIUM_KEYWORDS = ("normal", "routine", "standard")


def priority_bucket(value: Optional[str]) -> str:
    """Classify raw vendor priority text into one shared severity bucket.

    Order matters: high keywords are checked before "low" and before medium
    keywords, matching `priorityBucket()` in workOrders.js, so a value like
    "High/Urgent" cannot be mis-read as anything but High.
    """
    if value is None or not value.strip():
        return PRIORITY_NONE
    normalized = value.strip().casefold()
    if any(keyword in normalized for keyword in _PRIORITY_HIGH_KEYWORDS):
        return PRIORITY_HIGH
    if "low" in normalized:
        return PRIORITY_LOW
    if any(keyword in normalized for keyword in _PRIORITY_MEDIUM_KEYWORDS):
        return PRIORITY_MEDIUM
    return PRIORITY_UNKNOWN
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (from `backend/`):
```bash
venv/Scripts/python.exe -m pytest tests/test_work_orders_domain.py -v -k priority_bucket
```
Expected: 5 passed.

- [ ] **Step 5: Run the full domain test file**

Run (from `backend/`):
```bash
venv/Scripts/python.exe -m pytest tests/test_work_orders_domain.py -v
```
Expected: everything passes, same count as before plus 5.

- [ ] **Step 6: Commit**

```bash
git add backend/app/domain/work_orders.py backend/tests/test_work_orders_domain.py
git commit -m "feat(hub): add shared High/Medium priority bucket rule"
```

---

### Task 2: Personal hub — Technician's "assigned to me" priority count

**Files:**
- Modify: `backend/app/services/hub.py` (add `PriorityCounts` dataclass near `AssignedCounts`, extend `HubPayload` and `personal_hub`)
- Test: `backend/tests/test_hub_service.py`

**Interfaces:**
- Consumes: `wo.priority_bucket`, `wo.PRIORITY_HIGH` from Task 1.
- Produces: `PriorityCounts(assigned: int, unassigned: Optional[int] = None)` — the shared dataclass Tasks 3 and 4 also return. `HubPayload.priority: PriorityCounts`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_hub_service.py` (near the other personal-hub tests, after `test_counts_include_work_assigned_through_the_technician_table` around line 145):

```python
def test_personal_hub_counts_high_priority_work_assigned_to_me(db):
    tech = _seed_user(db, roles.ROLE_TECHNICIAN)
    other = _seed_user(db, roles.ROLE_TECHNICIAN, first_name="Other")
    baseline = hub_service.personal_hub(db, tech).priority.assigned

    mine_high = _seed_work_order(db, created_by=tech, assigned_to=tech, status=wo.STATUS_ASSIGNED)
    mine_high.priority = "High"
    mine_low = _seed_work_order(db, created_by=tech, assigned_to=tech, status=wo.STATUS_ASSIGNED)
    mine_low.priority = "Low"
    someone_elses_high = _seed_work_order(db, created_by=tech, assigned_to=other, status=wo.STATUS_ASSIGNED)
    someone_elses_high.priority = "Emergency"
    db.flush()

    payload = hub_service.personal_hub(db, tech)

    assert payload.priority.assigned == baseline + 1
    assert payload.priority.unassigned is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from `backend/`):
```bash
venv/Scripts/python.exe -m pytest tests/test_hub_service.py -v -k test_personal_hub_counts_high_priority_work_assigned_to_me
```
Expected: FAIL with `AttributeError: 'HubPayload' object has no attribute 'priority'`.

- [ ] **Step 3: Add the shared dataclass and extend `HubPayload`**

In `backend/app/services/hub.py`, add the import and the new dataclass. First, extend the existing `app.domain.work_orders` import — it is already imported as `wo` (line 29), so no import change is needed there.

Add immediately after the `AssignedCounts` dataclass (after line 67):

```python
@dataclass(frozen=True)
class PriorityCounts:
    """High-priority live-work-order counts for the Priorities card.

    `assigned` and `unassigned` share one denominator that differs by scope:
    a Technician's own assignments (personal_hub), a Supervisor's led work
    orders (crew_hub), or every live work order company-wide (admin_hub).
    `unassigned` is `None` for a Technician's card, which has no such number
    -- a Technician only ever sees what is assigned to them.
    """

    assigned: int
    unassigned: Optional[int] = None
```

Then add `priority: PriorityCounts` to `HubPayload` (after line 109, `tools_out: list[ToolOut]`):

```python
@dataclass(frozen=True)
class HubPayload:
    user: User
    server_now: datetime
    day: date
    counts: AssignedCounts
    priority: PriorityCounts
    clock: labor_summary.DaySummary
    startable: list[StartableWorkOrder]
    tools_out: list[ToolOut]
```

- [ ] **Step 4: Compute it in `personal_hub`**

In `personal_hub` (around line 178), after `counts = _assigned_counts(mine)`, add:

```python
    mine = _assigned_work_orders(db, user.id)
    counts = _assigned_counts(mine)
    priority = PriorityCounts(
        assigned=sum(1 for w in mine if wo.priority_bucket(w.priority) == wo.PRIORITY_HIGH)
    )
```

Then add `priority=priority,` to the `HubPayload(...)` construction at the bottom of `personal_hub` (around line 201), alongside `counts=counts,`.

- [ ] **Step 5: Run the test to verify it passes**

Run (from `backend/`):
```bash
venv/Scripts/python.exe -m pytest tests/test_hub_service.py -v -k test_personal_hub_counts_high_priority_work_assigned_to_me
```
Expected: PASS.

- [ ] **Step 6: Run the full personal-hub tests**

Run (from `backend/`):
```bash
venv/Scripts/python.exe -m pytest tests/test_hub_service.py -v -k "not crew and not admin and not graphs and not timesheet"
```
Expected: everything passes, including `test_an_empty_hub_is_all_zeros_and_empty_lists` and `test_the_payload_serialises_into_the_response_schema` — the latter will start failing once Task 6 adds the schema field without the router change; if it fails here, that's expected until Task 6 lands. Note that in your run log so Task 6 is not skipped.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/hub.py backend/tests/test_hub_service.py
git commit -m "feat(hub): add high-priority assigned count to the personal hub payload"
```

---

### Task 3: Crew hub — Supervisor's led/unassigned priority counts

**Files:**
- Modify: `backend/app/services/hub.py` (extend `HubCrewPayload` and `crew_hub`)
- Test: `backend/tests/test_hub_service.py`

**Interfaces:**
- Consumes: `PriorityCounts` from Task 2.
- Produces: `HubCrewPayload.priority: PriorityCounts`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_hub_service.py` (near `test_led_counts_are_a_total_and_two_subsets`, around line 369):

```python
def test_crew_hub_counts_high_priority_led_and_unassigned(db):
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    tech = _seed_user(db, roles.ROLE_TECHNICIAN)
    baseline = hub_service.crew_hub(db, supervisor, now=NOW).priority

    led_assigned_high = _seed_work_order(
        db, created_by=supervisor, supervisor=supervisor, assigned_to=tech, status=wo.STATUS_ASSIGNED
    )
    led_assigned_high.priority = "High"
    led_unassigned_high = _seed_work_order(
        db, created_by=supervisor, supervisor=supervisor, status=wo.STATUS_CREATED
    )
    led_unassigned_high.priority = "Urgent"
    led_low = _seed_work_order(
        db, created_by=supervisor, supervisor=supervisor, status=wo.STATUS_CREATED
    )
    led_low.priority = "Low"
    db.flush()

    payload = hub_service.crew_hub(db, supervisor, now=NOW)

    assert payload.priority.assigned == baseline.assigned + 2
    assert payload.priority.unassigned == baseline.unassigned + 1


def test_crew_hub_priority_counts_exclude_other_supervisors_led_work(db):
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    other_supervisor = _seed_user(db, roles.ROLE_SUPERVISOR, first_name="Other")
    baseline = hub_service.crew_hub(db, supervisor, now=NOW).priority

    not_mine = _seed_work_order(
        db, created_by=supervisor, supervisor=other_supervisor, status=wo.STATUS_CREATED
    )
    not_mine.priority = "High"
    db.flush()

    payload = hub_service.crew_hub(db, supervisor, now=NOW)

    assert payload.priority.assigned == baseline.assigned
    assert payload.priority.unassigned == baseline.unassigned
```

Check `NOW` is already defined near the top of the test file (it is, used by the graphs tests above) — if not found by that exact name, use whatever fixed `datetime` constant the graphs tests already reference instead of introducing a second one.

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `backend/`):
```bash
venv/Scripts/python.exe -m pytest tests/test_hub_service.py -v -k "test_crew_hub_counts_high_priority or test_crew_hub_priority_counts_exclude"
```
Expected: both FAIL with `AttributeError: 'HubCrewPayload' object has no attribute 'priority'`.

- [ ] **Step 3: Add `priority` to `HubCrewPayload`**

In `backend/app/services/hub.py`, add `priority: PriorityCounts` to `HubCrewPayload` (after line 269, `crew_minutes_today: int`):

```python
@dataclass(frozen=True)
class HubCrewPayload:
    server_now: datetime
    led: LedCounts
    priority: PriorityCounts
    crew_on_clock: int
    crew_total: int
    crew_minutes_today: int
    technicians: list[CrewTechnician] = field(default_factory=list)
    attention: list[AttentionItem] = field(default_factory=list)
```

- [ ] **Step 4: Compute it in `crew_hub`**

Add a helper right after `_led_work_orders` (after line 324):

```python
def _priority_counts(work_orders: list[WorkOrder]) -> PriorityCounts:
    """Shared by `crew_hub` (already has `technicians` eager-loaded on each
    row via `_led_work_orders`'s `joinedload`) -- `admin_hub` cannot reuse
    this directly because hydrating every company-wide WorkOrder row with
    that join would be far more expensive than the narrow projection it uses
    instead (see `_company_wide_priority_counts`)."""
    high = [w for w in work_orders if wo.priority_bucket(w.priority) == wo.PRIORITY_HIGH]
    unassigned = sum(1 for w in high if w.assigned_to_id is None and not w.technicians)
    return PriorityCounts(assigned=len(high), unassigned=unassigned)
```

In `crew_hub`, after `led_work_orders = _led_work_orders(db, user.id)` (line 374) and the `led = LedCounts(...)` block, add:

```python
    priority = _priority_counts(led_work_orders)
```

Then add `priority=priority,` to the `HubCrewPayload(...)` construction at the bottom of `crew_hub` (around line 461), alongside `led=led,`.

- [ ] **Step 5: Run the tests to verify they pass**

Run (from `backend/`):
```bash
venv/Scripts/python.exe -m pytest tests/test_hub_service.py -v -k "test_crew_hub_counts_high_priority or test_crew_hub_priority_counts_exclude"
```
Expected: both PASS.

- [ ] **Step 6: Run the full crew-hub test slice**

Run (from `backend/`):
```bash
venv/Scripts/python.exe -m pytest tests/test_hub_service.py -v -k "crew or attention or stale or idle"
```
Expected: everything passes except `test_the_crew_payload_serialises_into_the_response_schema`, which is expected to fail until Task 6.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/hub.py backend/tests/test_hub_service.py
git commit -m "feat(hub): add high-priority led/unassigned counts to the crew hub payload"
```

---

### Task 4: Admin hub — company-wide priority counts

**Files:**
- Modify: `backend/app/services/hub.py` (extend `HubAdminPayload` and `admin_hub`)
- Test: `backend/tests/test_hub_service.py`

**Interfaces:**
- Consumes: `PriorityCounts` from Task 2; `WorkOrderTechnician` (already imported at the top of `hub.py`, line 31).
- Produces: `HubAdminPayload.priority: PriorityCounts`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_hub_service.py` (near the other admin-hub tests, after `test_admin_hub_pipeline_counts_are_company_wide_and_unscoped` around line 754):

```python
def test_admin_hub_counts_high_priority_company_wide_assigned_and_unassigned(db):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    tech = _seed_user(db, roles.ROLE_TECHNICIAN)
    baseline = hub_service.admin_hub(db, admin, now=NOW).priority

    assigned_high = _seed_work_order(db, created_by=admin, assigned_to=tech, status=wo.STATUS_ASSIGNED)
    assigned_high.priority = "High"
    unassigned_high = _seed_work_order(db, created_by=admin, status=wo.STATUS_CREATED)
    unassigned_high.priority = "Emergency"
    low = _seed_work_order(db, created_by=admin, status=wo.STATUS_CREATED)
    low.priority = "Low"
    db.flush()

    payload = hub_service.admin_hub(db, admin, now=NOW)

    assert payload.priority.assigned == baseline.assigned + 2
    assert payload.priority.unassigned == baseline.unassigned + 1


def test_admin_hub_priority_counts_exclude_archived_work_orders(db):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    baseline = hub_service.admin_hub(db, admin, now=NOW).priority

    archived = _seed_work_order(db, created_by=admin, status=wo.STATUS_CREATED)
    archived.priority = "High"
    archived.archived_at = NOW
    db.flush()

    payload = hub_service.admin_hub(db, admin, now=NOW)

    assert payload.priority.assigned == baseline.assigned
    assert payload.priority.unassigned == baseline.unassigned
```

`roles.ROLE_ADMIN` matches the constant already used elsewhere in this file's admin tests (check `test_admin_hub_sums_supervisors_and_technicians_separately` around line 641 for the exact viewer role/helper it uses, and match it rather than introducing a new one).

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `backend/`):
```bash
venv/Scripts/python.exe -m pytest tests/test_hub_service.py -v -k "test_admin_hub_counts_high_priority or test_admin_hub_priority_counts_exclude_archived"
```
Expected: both FAIL with `AttributeError: 'HubAdminPayload' object has no attribute 'priority'`.

- [ ] **Step 3: Add `priority` to `HubAdminPayload`**

In `backend/app/services/hub.py`, add `priority: PriorityCounts` to `HubAdminPayload` (after line 731, `billing: AdminBilling`):

```python
@dataclass(frozen=True)
class HubAdminPayload:
    server_now: datetime
    supervisor_minutes_today: int
    technician_minutes_today: int
    pipeline: AdminPipelineCounts
    priority: PriorityCounts
    on_the_clock: list[OnClockEntry]
    exceptions: AdminExceptionCounts
    billing: AdminBilling
```

- [ ] **Step 4: Compute it company-wide**

Add a new function right after `_pipeline_counts` (after line 505):

```python
def _company_wide_priority_counts(db: Session) -> PriorityCounts:
    """Every live work order, unscoped -- the Admin+ mirror of `_priority_counts`.

    A narrow two-query projection rather than hydrating full `WorkOrder` rows
    with a `technicians` join (the way `_priority_counts` does for a
    supervisor's much smaller led set): company-wide, that join would be the
    most expensive read on this payload for no benefit, since only
    `priority`, `assigned_to_id`, and technician-assignment existence are
    needed.
    """
    rows = (
        db.query(WorkOrder.id, WorkOrder.priority, WorkOrder.assigned_to_id)
        .filter(WorkOrder.archived_at.is_(None))
        .all()
    )
    high_ids = {row.id for row in rows if wo.priority_bucket(row.priority) == wo.PRIORITY_HIGH}
    if not high_ids:
        return PriorityCounts(assigned=0, unassigned=0)
    technician_assigned_ids = {
        row.work_order_id
        for row in db.query(WorkOrderTechnician.work_order_id)
        .filter(WorkOrderTechnician.work_order_id.in_(high_ids))
        .distinct()
        .all()
    }
    unassigned = sum(
        1
        for row in rows
        if row.id in high_ids
        and row.assigned_to_id is None
        and row.id not in technician_assigned_ids
    )
    return PriorityCounts(assigned=len(high_ids), unassigned=unassigned)
```

In `admin_hub`, after `pipeline = _pipeline_counts(db)` (line 770), add:

```python
    priority = _company_wide_priority_counts(db)
```

Then add `priority=priority,` to the `HubAdminPayload(...)` construction at the bottom of `admin_hub` (around line 772), alongside `pipeline=pipeline,`.

- [ ] **Step 5: Run the tests to verify they pass**

Run (from `backend/`):
```bash
venv/Scripts/python.exe -m pytest tests/test_hub_service.py -v -k "test_admin_hub_counts_high_priority or test_admin_hub_priority_counts_exclude_archived"
```
Expected: both PASS.

- [ ] **Step 6: Run the full admin-hub test slice**

Run (from `backend/`):
```bash
venv/Scripts/python.exe -m pytest tests/test_hub_service.py -v -k admin_hub
```
Expected: everything passes except `test_the_admin_payload_serialises_into_the_response_schema`, expected to fail until Task 6.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/hub.py backend/tests/test_hub_service.py
git commit -m "feat(hub): add company-wide high-priority counts to the admin hub payload"
```

---

### Task 5: Graphs hub — High/Medium priority status donuts

**Files:**
- Modify: `backend/app/services/hub.py` (extend `HubGraphsPayload` and `graphs_hub`)
- Test: `backend/tests/test_hub_service.py`

**Interfaces:**
- Consumes: `GraphDistribution`, `_empty_graph_counts`, `wo.priority_bucket`, `wo.PRIORITY_HIGH`, `wo.PRIORITY_MEDIUM`.
- Produces: `HubGraphsPayload.priority_high: GraphDistribution`, `HubGraphsPayload.priority_medium: GraphDistribution`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_hub_service.py` (right after `test_graphs_hub_counts_live_statuses_by_community_and_service_type`, around line 622):

```python
def test_graphs_hub_adds_high_and_medium_priority_status_distributions(db):
    creator = _seed_user(db, roles.ROLE_TECHFM_OA)
    baseline = hub_service.graphs_hub(db, creator, weeks=12, now=NOW)

    high = _seed_work_order(db, created_by=creator, status=wo.STATUS_ASSIGNED)
    high.priority = "Emergency"
    medium = _seed_work_order(db, created_by=creator, status=wo.STATUS_CREATED)
    medium.priority = "Routine"
    low = _seed_work_order(db, created_by=creator, status=wo.STATUS_CREATED)
    low.priority = "Low"
    archived_high = _seed_work_order(db, created_by=creator, status=wo.STATUS_COMPLETED)
    archived_high.priority = "High"
    archived_high.archived_at = NOW
    db.flush()

    payload = hub_service.graphs_hub(db, creator, weeks=12, now=NOW)

    assert payload.priority_high.key == wo.PRIORITY_HIGH
    assert payload.priority_high.total == baseline.priority_high.total + 1
    assert payload.priority_high.counts[wo.STATUS_ASSIGNED] == baseline.priority_high.counts[wo.STATUS_ASSIGNED] + 1
    assert payload.priority_medium.key == wo.PRIORITY_MEDIUM
    assert payload.priority_medium.total == baseline.priority_medium.total + 1
    assert payload.priority_medium.counts[wo.STATUS_CREATED] == baseline.priority_medium.counts[wo.STATUS_CREATED] + 1
    assert payload.priority_high.total == sum(payload.priority_high.counts.values())
    assert payload.priority_medium.total == sum(payload.priority_medium.counts.values())
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from `backend/`):
```bash
venv/Scripts/python.exe -m pytest tests/test_hub_service.py -v -k test_graphs_hub_adds_high_and_medium_priority
```
Expected: FAIL with `AttributeError: 'HubGraphsPayload' object has no attribute 'priority_high'`.

- [ ] **Step 3: Add the two fields to `HubGraphsPayload`**

In `backend/app/services/hub.py`, add `priority_high` and `priority_medium` to `HubGraphsPayload` (after line 829, `service_types: list[GraphDistribution]`):

```python
@dataclass(frozen=True)
class HubGraphsPayload:
    generated_at: datetime
    weeks: int
    statuses: list[GraphStatus]
    priority_high: GraphDistribution
    priority_medium: GraphDistribution
    communities: list[GraphDistribution]
    service_types: list[GraphDistribution]
    duration: GraphDuration
```

- [ ] **Step 4: Compute it in `graphs_hub`**

The existing query at line 878-882 selects `(status, community, location, service_type)`. Widen it to also select `priority`, and add the widened select as a fifth column everywhere it's unpacked:

```python
    live_rows = (
        db.query(
            WorkOrder.status,
            WorkOrder.community,
            WorkOrder.location,
            WorkOrder.service_type,
            WorkOrder.priority,
        )
        .filter(WorkOrder.archived_at.is_(None))
        .all()
    )
    priority_counts = {
        wo.PRIORITY_HIGH: _empty_graph_counts(),
        wo.PRIORITY_MEDIUM: _empty_graph_counts(),
    }
    for status, community, location, service_type, priority in live_rows:
        # A defensive unknown-status guard preserves an exhaustive response if
        # a legacy row predates today's validation vocabulary.
        if status not in wo.ALL_STATUSES:
            continue
        for key in wo.community_memberships(community, location):
            community_counts[key][status] += 1
        service_key, service_label = wo.normalize_service_type(service_type)
        service_counts.setdefault(service_key, _empty_graph_counts())[status] += 1
        prior_label = service_labels.get(service_key)
        if prior_label is None or service_label.casefold() < prior_label.casefold():
            service_labels[service_key] = service_label
        bucket = wo.priority_bucket(priority)
        if bucket in priority_counts:
            priority_counts[bucket][status] += 1
```

This replaces the existing `for status, community, location, service_type in live_rows:` loop body (lines 883-894) in place — keep every line inside it, just add the `priority` unpack and the trailing `bucket = ...` block.

Then, right before the `return HubGraphsPayload(...)` at the end of the function, add:

```python
    priority_high = GraphDistribution(
        key=wo.PRIORITY_HIGH,
        label="High priority",
        total=sum(priority_counts[wo.PRIORITY_HIGH].values()),
        counts=priority_counts[wo.PRIORITY_HIGH],
    )
    priority_medium = GraphDistribution(
        key=wo.PRIORITY_MEDIUM,
        label="Medium priority",
        total=sum(priority_counts[wo.PRIORITY_MEDIUM].values()),
        counts=priority_counts[wo.PRIORITY_MEDIUM],
    )
```

And add `priority_high=priority_high, priority_medium=priority_medium,` to the `HubGraphsPayload(...)` construction, alongside `statuses=statuses,`.

- [ ] **Step 5: Run the test to verify it passes**

Run (from `backend/`):
```bash
venv/Scripts/python.exe -m pytest tests/test_hub_service.py -v -k test_graphs_hub_adds_high_and_medium_priority
```
Expected: PASS.

- [ ] **Step 6: Run the full graphs-hub test slice**

Run (from `backend/`):
```bash
venv/Scripts/python.exe -m pytest tests/test_hub_service.py -v -k graphs_hub
venv/Scripts/python.exe -m pytest tests/test_hub_graphs_domain.py -v
```
Expected: everything passes.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/hub.py backend/tests/test_hub_service.py
git commit -m "feat(hub): add high/medium priority status distributions to the graphs payload"
```

---

### Task 6: Schemas and router — wire the new fields onto the wire

**Files:**
- Modify: `backend/app/schemas/hub.py`
- Modify: `backend/app/routers/hub.py` (only `get_hub` needs a body change; `get_hub_crew`, `get_hub_admin`, `get_hub_graphs` already use `model_validate` and pick the new dataclass fields up automatically once the schema has them)
- Test: `backend/tests/test_hub_router.py`, plus re-running the four "serialises into the response schema" tests from Tasks 2-5 that were left failing

**Interfaces:**
- Consumes: `PriorityCounts` (service), the `priority`/`priority_high`/`priority_medium` fields from Tasks 2-5.
- Produces: `HubPriorityCounts` schema, used by all four response schemas.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_hub_router.py`:

```python
def test_graphs_route_serializes_the_two_priority_distributions(monkeypatch):
    payload = SimpleNamespace(
        generated_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
        weeks=12,
        statuses=[],
        priority_high=SimpleNamespace(key="high", label="High priority", total=3, counts={"created": 3}),
        priority_medium=SimpleNamespace(key="medium", label="Medium priority", total=1, counts={"created": 1}),
        communities=[],
        service_types=[],
        duration=SimpleNamespace(
            range=SimpleNamespace(start=date(2026, 2, 23), end=date(2026, 8, 23)),
            buckets=[],
        ),
    )
    monkeypatch.setattr(hub_router.hub_service, "graphs_hub", lambda db, user, *, weeks: payload)

    body = hub_router.get_hub_graphs(weeks=12, user=SimpleNamespace(), db=None).model_dump()

    assert body["priority_high"]["total"] == 3
    assert body["priority_medium"]["counts"]["created"] == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from `backend/`):
```bash
venv/Scripts/python.exe -m pytest tests/test_hub_router.py -v -k test_graphs_route_serializes_the_two_priority_distributions
```
Expected: FAIL — `HubGraphsResponse` rejects the extra unmodeled fields, or `pydantic.ValidationError` for missing `priority_high`/`priority_medium` (Pydantic ignores extra dataclass attributes by default when using `model_validate` unless the schema doesn't declare the field, so more precisely: `body["priority_high"]` raises `KeyError` because the schema silently dropped a field it never declared). Either way, the assertion fails.

- [ ] **Step 3: Add `HubPriorityCounts` to the schema module**

In `backend/app/schemas/hub.py`, add after `HubCounts` (after line 115):

```python
class HubPriorityCounts(BaseModel):
    """High-priority live-work-order counts for the Priorities card.
    `unassigned` is omitted (stays `None`) for a Technician's personal
    payload, which has no such number."""

    assigned: int
    unassigned: Optional[int] = None

    model_config = {"from_attributes": True}
```

- [ ] **Step 4: Add `priority` to `HubResponse`**

In `HubResponse` (after line 157, `counts: HubCounts`):

```python
class HubResponse(BaseModel):
    user: HubUser
    server_now: datetime
    day: date
    clock: HubClock
    timeline: list[HubTimelineEntry] = []
    counts: HubCounts
    priority: HubPriorityCounts
    startable: list[HubStartable] = []
    tools_out: list[HubToolOut] = []

    model_config = {"from_attributes": True}
```

- [ ] **Step 5: Add `priority` to `HubCrewResponse`**

In `HubCrewResponse` (after line 212, `led: HubLedCounts`):

```python
class HubCrewResponse(BaseModel):
    server_now: datetime
    led: HubLedCounts
    priority: HubPriorityCounts
    crew_on_clock: int
    crew_total: int
    crew_minutes_today: int
    technicians: list[HubCrewTechnician] = []
    attention: list[HubAttentionItem] = []

    model_config = {"from_attributes": True}
```

- [ ] **Step 6: Add `priority` to `HubAdminResponse`**

In `HubAdminResponse` (after line 289, `pipeline: HubAdminPipeline`):

```python
class HubAdminResponse(BaseModel):
    server_now: datetime
    supervisor_minutes_today: int
    technician_minutes_today: int
    pipeline: HubAdminPipeline
    priority: HubPriorityCounts
    on_the_clock: list[HubAdminOnClockEntry] = []
    exceptions: HubAdminExceptions
    billing: HubAdminBilling

    model_config = {"from_attributes": True}
```

- [ ] **Step 7: Add `priority_high`/`priority_medium` to `HubGraphsResponse`**

In `HubGraphsResponse` (after line 347, `statuses: list[HubGraphStatus] = []`):

```python
class HubGraphsResponse(BaseModel):
    generated_at: datetime
    weeks: int
    statuses: list[HubGraphStatus] = []
    priority_high: HubGraphDistribution
    priority_medium: HubGraphDistribution
    communities: list[HubGraphDistribution] = []
    service_types: list[HubGraphDistribution] = []
    duration: HubGraphDuration

    model_config = {"from_attributes": True}
```

- [ ] **Step 8: Pass `priority` through in `get_hub`**

`get_hub_crew`, `get_hub_admin`, and `get_hub_graphs` already call `Response.model_validate(hub_service.xxx_hub(...))` directly and need no change — the new schema fields pick up the matching dataclass attributes automatically. Only `get_hub` builds its response field-by-field. In `backend/app/routers/hub.py`, add `priority=payload.priority,` to the `HubResponse(...)` construction (around line 68), alongside `counts=payload.counts,`.

- [ ] **Step 9: Run every test left failing since Tasks 2-5**

Run (from `backend/`):
```bash
venv/Scripts/python.exe -m pytest tests/test_hub_service.py -v -k serialises
venv/Scripts/python.exe -m pytest tests/test_hub_router.py -v -k test_graphs_route_serializes_the_two_priority_distributions
```
Expected: all pass now.

- [ ] **Step 10: Run the whole hub test surface plus the role-gate suite**

Run (from `backend/`):
```bash
venv/Scripts/python.exe -m pytest tests/test_hub_service.py tests/test_hub_router.py tests/test_route_role_gates.py tests/test_hub_graphs_domain.py -v
```
Expected: everything passes. `test_route_role_gates.py` should be unaffected — no route's minimum role changed, only response bodies grew new fields.

- [ ] **Step 11: Run the full backend suite**

Run (from `backend/`):
```bash
venv/Scripts/python.exe -m pytest tests/ -q
```
Expected: full suite passes.

- [ ] **Step 12: Commit**

```bash
git add backend/app/schemas/hub.py backend/app/routers/hub.py backend/tests/test_hub_router.py
git commit -m "feat(hub): wire priority counts and distributions onto the hub API responses"
```

---

### Task 7: Priorities card — frontend

**Files:**
- Create: `backend/static/views/hubPriorities.js`
- Modify: `backend/static/views/hubTechnician.js` (`mountHubDashboard`, lines 154-171)
- Modify: `backend/static/views/userHub.js` (render/refresh wiring, safety timer, socket subscription)
- Modify: `backend/static/styles.css` (one small rule)

No JS test harness exists in this repo (per the dropdown-normalization plan's own Global Constraints, confirmed still true) — this task has no automated test step. It ends with a manual-check handoff instead, same as every other frontend-only task in this codebase's plans.

**Interfaces:**
- Consumes: the `priority` field now present on the `/hub`, `/hub/crew`, `/hub/admin` JSON responses (`{assigned, unassigned}}`, `unassigned` possibly `null`).
- Produces: `mountHubPriorities(container, { role, personal, crew, admin }) -> void`, exported from `hubPriorities.js`.

- [ ] **Step 1: Create the view module**

Create `backend/static/views/hubPriorities.js`:

```js
// View: the Priorities card at the top of the User Hub Dashboard tab.
//
// Layer: views. Renders inside the Dashboard tab body, above the personal
// counts tiles hubTechnician.js draws. Every role gets one card, but its
// shape differs: a Technician sees one number (assigned to them); a
// Supervisor or Admin+ viewer sees two (assigned within their scope,
// unassigned within their scope). Consumes whichever of the personal/crew/
// admin payloads userHub.js has already fetched; makes no requests of its
// own.

import { escapeHtml } from "../format.js";
import { roleAtLeast } from "../roles.js";

function tileHtml(label, value, sub) {
  return `
    <section class="hub-tile">
      <p class="hub-tile-label">${escapeHtml(label)}</p>
      <p class="hub-tile-value">${escapeHtml(String(value))}</p>
      ${sub ? `<p class="hub-tile-sub">${escapeHtml(sub)}</p>` : ""}
    </section>`;
}

// Supervisor and Admin+ share this two-tile shape; only the source payload
// and the "your crew" / "company-wide" wording differ.
function scopedHtml(priority, scopeLabel) {
  return `
    <div class="hub-tile-grid">
      ${tileHtml(`High priority — ${scopeLabel}`, priority.assigned, "")}
      ${tileHtml("High priority — unassigned", priority.unassigned, priority.unassigned ? "needs a technician" : "")}
    </div>`;
}

export function mountHubPriorities(container, { role, personal, crew, admin } = {}) {
  if (!container) return;
  const isAdminPlus = roleAtLeast(role, "techfm_oa");
  const isSupervisor = role === "supervisor";

  let body;
  if (isAdminPlus) {
    // Company-wide (admin_hub), not the viewer's own led set -- an
    // Admin/Owner/TechFM OA may also be routed as a supervisor on some work
    // orders, but the card's promise for this role tier is company-wide.
    if (!admin) {
      container.innerHTML = "";
      return;
    }
    body = scopedHtml(admin, "company-wide");
  } else if (isSupervisor) {
    if (!crew) {
      container.innerHTML = "";
      return;
    }
    body = scopedHtml(crew, "your crew");
  } else {
    if (!personal) {
      container.innerHTML = "";
      return;
    }
    body = `<div class="hub-tile-grid">${tileHtml("High priority — assigned to you", personal.assigned, "")}</div>`;
  }

  container.innerHTML = `<section class="hub-priorities"><p class="hub-tile-label">Priorities</p>${body}</section>`;
}
```

- [ ] **Step 2: Add the mount point to the Dashboard tab**

In `backend/static/views/hubTechnician.js`, change `mountHubDashboard` (lines 154-171) to place the new mount first:

```js
export function mountHubDashboard(container, payload) {
  const isAdminPlus = roleAtLeast(payload.user.role, "techfm_oa");
  container.innerHTML =
    `<div id="hub-priorities-mount"></div>` +
    countsHtml(payload.counts) +
    (isAdminPlus ? "" : timeTodayHtml(payload)) +
    (isAdminPlus ? "" : toolsOutHtml(payload.tools_out)) +
    // Present unconditionally so userHub.js never has to special-case
    // whether these elements exist. #hub-admin-mount is only ever
    // populated for techfm_oa+ viewers (spec: the admin time summary);
    // #hub-crew-mount is populated when the viewer is a routed supervisor
    // (D16), any role.
    `<div id="hub-admin-mount"></div>` +
    `<div id="hub-crew-mount"></div>`;
  container.querySelectorAll(".hub-timeline-block").forEach((block) => {
    block.style.left = `${block.dataset.left}%`;
    block.style.width = `${block.dataset.width}%`;
  });
}
```

(Only the first line of the template concatenation changed — everything else in the function body is unchanged.)

- [ ] **Step 3: Wire rendering into `userHub.js`**

In `backend/static/views/userHub.js`, add the import (alongside the existing view imports, line 16):

```js
import { mountHubDashboard, mountHubWorkOrders } from "./hubTechnician.js";
import { mountHubPriorities } from "./hubPriorities.js";
```

Add a mount getter next to `crewMount`/`adminMount` (after line 93):

```js
function priorityMount() {
  return tabPanels.dashboard.querySelector("#hub-priorities-mount");
}

function renderPriorities() {
  if (!latestPayload) return;
  const mount = priorityMount();
  if (!mount) return;
  mountHubPriorities(mount, {
    role: latestPayload.user.role,
    personal: latestPayload.priority,
    crew: latestCrewPayload?.priority,
    admin: latestAdminPayload?.priority,
  });
}
```

Call it everywhere `renderCrew()`/`renderAdmin()` are already called, so it always repaints with whichever payloads are freshest:

- In `renderActiveTab()`'s dashboard branch (around line 131-134), add `renderPriorities();` after `mountHubDashboard(...)`:

```js
  if (activeTab === "dashboard") {
    mountHubDashboard(tabPanels.dashboard, latestPayload);
    renderPriorities();
    renderCrew();
    renderAdmin();
  }
```

- At the end of `renderCrew()` (after line 121, inside the `if (!crewBoardShouldRender(...))` early-return branch too, so a viewer who loses crew visibility still gets a correct — Technician-shaped — card):

```js
function renderCrew() {
  if (!latestCrewPayload) return;
  const mount = crewMount();
  if (!mount) return;
  if (!crewBoardShouldRender(latestCrewPayload)) {
    mount.innerHTML = "";
    renderPriorities();
    return;
  }
  mountHubCrew(mount, latestCrewPayload, { isAdminPlus: viewerCanSeeAdminTiles() });
  renderPriorities();
}
```

- At the end of `renderAdmin()` (after line 127):

```js
function renderAdmin() {
  if (!latestAdminPayload) return;
  const mount = adminMount();
  if (mount) mountHubAdminSummary(mount, latestAdminPayload);
  renderPriorities();
}
```

- [ ] **Step 4: Widen the safety timer to run for every role**

Currently `startCrewSafetyRefresh` is only ever started for `supervisor+` (`loadUserHub`'s `if (canViewSupervisorTabs)` branch, line 360-365, and the `visibilitychange` handler, line 405-407). A plain Technician has no periodic refresh today; the Priorities card needs one so it can stay live without a full page reload. Add a `refreshPersonal` function and start the timer unconditionally.

Add near `refreshCrew`/`refreshAdmin` (after `refreshAdmin`, around line 283):

```js
// Mirrors refreshCrew/refreshAdmin -- background-only, keeps the last good
// numbers on failure. Every role gets this: a plain Technician has no other
// periodic refresh, and the Priorities card is the one thing on their
// Dashboard that needs to stay live without a manual reload.
async function refreshPersonal({ background = false } = {}) {
  try {
    const payload = await apiGetHub();
    latestPayload = payload;
    if (activeTab === "dashboard") mountHubDashboard(tabPanels.dashboard, latestPayload);
    renderPriorities();
    renderCrew();
    renderAdmin();
  } catch (err) {
    if (background) return;
  }
}
```

Rename the timer functions' role in the flow — keep `startCrewSafetyRefresh`/`stopCrewSafetyRefresh`/`CREW_SAFETY_REFRESH_MS` named as-is (a rename is a larger diff than this task needs and every call site already reads clearly with a short comment), but change what the interval body does (lines 292-300):

```js
function startCrewSafetyRefresh() {
  stopCrewSafetyRefresh();
  crewSafetyTimer = setInterval(() => {
    if (document.hidden) return;
    void refreshPersonal({ background: true });
    if (roleAtLeast(latestPayload?.user.role, "supervisor")) void refreshCrew({ background: true });
    if (viewerCanSeeAdminTiles()) void refreshAdmin({ background: true });
    if (activeTab === "graphs" && viewerCanSeeAdminTiles()) void loadGraphs({ background: true });
  }, CREW_SAFETY_REFRESH_MS);
}
```

Change `loadUserHub`'s timer-start block (lines 360-365) to start unconditionally:

```js
  if (canViewSupervisorTabs) {
    await refreshCrew();
  }
  startCrewSafetyRefresh();

  if (canViewAdminTiles) {
    await refreshAdmin();
  }
```

Change the `visibilitychange` handler (lines 397-408) to restart the timer for every role, not just supervisor+:

```js
document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    stopHubClockTicking();
    stopCrewSafetyRefresh();
    return;
  }
  if (!document.getElementById("user-hub-page").classList.contains("active")) return;
  startHubClockTicking();
  if (latestPayload) startCrewSafetyRefresh();
});
```

- [ ] **Step 5: Widen the `work_order.status.changed` handler to every role**

Currently (lines 390-395) this event only triggers a Graphs refresh, gated on `viewerCanSeeAdminTiles()`. A status/priority/assignment change on any work order can move any role's Priorities numbers, so widen it:

```js
subscribe(WORK_ORDER_STATUS_CHANGED_EVENT, ({ activePage, reason }) => {
  if (activePage !== HUB_PAGE) return;
  void refreshPersonal({ background: true });
  if (roleAtLeast(latestPayload?.user.role, "supervisor")) void refreshCrew({ background: true });
  if (viewerCanSeeAdminTiles()) {
    void refreshAdmin({ background: true });
    if (activeTab === "graphs" || reason === "reconnect") {
      void loadGraphs({ background: true });
    }
  }
});
```

- [ ] **Step 6: Reset priority state on user change**

In `loadUserHub`, `latestCrewPayload`/`latestAdminPayload` are already reset to `null` on a user change or role downgrade (lines 325-341) — since `renderPriorities()` reads those same variables, no extra reset is needed. Confirm this by reading the surrounding block once more before moving on; no code change in this step.

- [ ] **Step 7: Add the one CSS rule**

In `backend/static/styles.css`, add immediately after the `.hub-tile-grid` rule (after line ~1847, wherever that block ends):

```css
/* The Priorities card at the top of the Dashboard tab. Reuses .hub-tile-grid
   and .hub-tile wholesale (hubPriorities.js), so the only rule this needs is
   spacing before the counts grid below it. */
.hub-priorities {
    margin-bottom: var(--space-6);
}
```

- [ ] **Step 8: `node --check` every changed file**

Run (from the repo root):
```bash
node --check backend/static/views/hubPriorities.js
node --check backend/static/views/hubTechnician.js
node --check backend/static/views/userHub.js
```
Expected: no output (syntax OK) from all three. If `node` is not on PATH, skip this step and rely on the manual browser check instead — do not treat its absence as a blocker.

- [ ] **Step 9: Run the full backend suite once more**

Static JS changes don't run under pytest, but `test_route_role_gates.py` and any source-parity tests elsewhere in the suite should still be re-run as a safety net:

Run (from `backend/`):
```bash
venv/Scripts/python.exe -m pytest tests/ -q
```
Expected: full suite passes, unchanged from Task 6's count.

- [ ] **Step 10: Commit**

```bash
git add backend/static/views/hubPriorities.js backend/static/views/hubTechnician.js backend/static/views/userHub.js backend/static/styles.css
git commit -m "feat(hub): add the live Priorities card to every role's Dashboard tab"
```

- [ ] **Step 11: Manual check (hand off, do not start the server yourself)**

Hand off with: on the User Hub Dashboard tab —
1. **Technician**: the Priorities card shows one tile, "High priority — assigned to you," matching the count of their own High-bucketed (high/urgent/emergency) live work orders.
2. **Supervisor**: two tiles, "High priority — your crew" and "High priority — unassigned," scoped to work orders they lead.
3. **TechFM OA / Admin / Owner**: same two-tile shape, company-wide — change a work order's priority or assignment in another browser tab and confirm the numbers update within the 60-second safety window without a manual reload, and confirm they update immediately after a `work_order.status.changed`-triggering action (status edit, archive, restore, assign) in the *same* browser.
4. Confirm the card appears above the existing "Assigned to me" / pipeline tiles, not below them.
5. Confirm nothing regressed in the counts tiles, crew board, or admin summary below it.

---

### Task 8: Graphs tab — High/Medium priority pies

**Files:**
- Modify: `backend/static/views/hubGraphs.js`

No automated test (same JS-harness limitation as Task 7); ends with a manual-check handoff.

- [ ] **Step 1: Add the two cards above "Status by community"**

In `backend/static/views/hubGraphs.js`, in `mountHubGraphs` (the template literal starting at line 86), insert a new section between the header and the "Status by community" `<section>`:

```js
export function mountHubGraphs(container, payload, { showAllServiceTypes, onToggleServiceTypes, onWeekChange } = {}) {
  const services = showAllServiceTypes ? payload.service_types : payload.service_types.slice(0, 6);
  const serviceToggle = payload.service_types.length > 6
    ? `<button type="button" class="secondary-btn hub-graphs-service-toggle">${showAllServiceTypes ? "Show fewer service types" : `Show all ${payload.service_types.length} service types`}</button>`
    : "";
  const updated = new Date(payload.generated_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  container.innerHTML = `<section class="hub-graphs"><header class="hub-graphs-header"><div><h2>Graphs</h2><p class="hint">Live circulating work orders. Updated ${escapeHtml(updated)}.</p></div><label class="hub-graphs-range">Range <select class="hub-graphs-weeks" aria-label="Duration graph range"><option value="12" ${payload.weeks === 12 ? "selected" : ""}>12 weeks</option><option value="26" ${payload.weeks === 26 ? "selected" : ""}>26 weeks</option><option value="52" ${payload.weeks === 52 ? "selected" : ""}>52 weeks</option></select></label></header><section><h2>Status by priority</h2><div class="hub-graph-grid">${distributionCard(payload.priority_high, payload.statuses)}${distributionCard(payload.priority_medium, payload.statuses)}</div></section><section><h2>Status by community</h2><p class="hint">A work order that names multiple communities appears in each matching community chart; do not add community totals together.</p><div class="hub-graph-grid">${payload.communities.map((row) => distributionCard(row, payload.statuses)).join("")}</div></section><section><h2>Status by service type</h2><div class="hub-graph-grid">${services.map((row) => distributionCard(row, payload.statuses)).join("")}</div>${serviceToggle}</section><section class="hub-duration-section"><h2>Work-order age and close-out time</h2><p class="hint"><span class="hub-duration-key hub-duration-key-age"></span>Average circulating age at each week end <span class="hub-duration-key hub-duration-key-close"></span>Average time from creation to Closed for work orders closed that week.</p>${durationSvg(payload.duration.buckets)}${durationTable(payload.duration.buckets)}</section></section>`;
  container.querySelector(".hub-graphs-service-toggle")?.addEventListener("click", onToggleServiceTypes);
  container.querySelector(".hub-graphs-weeks")?.addEventListener("change", (event) => onWeekChange?.(Number(event.target.value)));
}
```

(Only the `container.innerHTML =` line changed — a new `<section><h2>Status by priority</h2>...` inserted right after the `</header>`, before the existing "Status by community" section. Everything else in the function is byte-for-byte unchanged.)

`distributionCard` already handles a zero-total distribution (`"No circulating work orders"`, from `donutSvg`, lines 22-24) — no change needed there for a priority bucket with no live matches.

- [ ] **Step 2: `node --check`**

Run (from the repo root):
```bash
node --check backend/static/views/hubGraphs.js
```
Expected: no output. If `node` is not on PATH, skip and rely on the manual check.

- [ ] **Step 3: Commit**

```bash
git add backend/static/views/hubGraphs.js
git commit -m "feat(hub): add High/Medium priority status donuts above the community charts"
```

- [ ] **Step 4: Manual check (hand off, do not start the server yourself)**

Hand off with: as TechFM OA/Admin/Owner, open the Graphs tab and confirm —
1. Two new cards, "High priority" and "Medium priority," appear first, above "Status by community."
2. Each is the same 7-status donut/legend format as the community cards, with an exact-count legend and a center total.
3. A priority bucket with zero live work orders renders "No circulating work orders," not a misleading full ring.
4. Changing the week-range preset does not affect these two cards (they're a live snapshot, not part of the duration series) — confirm they stay stable across a preset change.
5. The cards are keyboard/screen-reader accessible the same way the existing community cards already are (this is inherited from `distributionCard`/`donutSvg`, not new markup, so a regression here would mean something else broke).

---

## Verification Before Handoff

Run from `backend/`:

```bash
venv/Scripts/python.exe -m pytest tests/ -q
```

Then hand the branch to the owner for the manual checks listed at the end of Tasks 7 and 8 — the owner validates UI manually and prefers the preview server not be started automatically.

**Do not merge to `main` without asking.** Merging deploys to production.
