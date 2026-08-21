# User Hub P4 — Admin Time Summary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **This repo's CLAUDE.md forbids using the Agent tool for this project unless
> explicitly told otherwise.** Do not dispatch subagents to execute these
> tasks — use `superpowers:executing-plans` (inline, in this session) instead
> of `superpowers:subagent-driven-development`, regardless of which the user
> picks at the execution-choice prompt, unless they explicitly override this
> note.

**Goal:** Give TechFM OA+ viewers of the User Hub a company-wide "Supervisor
Time" / "Technician Time" summary for today, and drop three tiles that don't
make sense for that role tier (personal Time Today, Tools out, and the
crew board's "Crew on the clock" headcount).

**Architecture:** A new `GET /hub/admin` endpoint (already reserved at
`techfm_oa+` in the router's own docstring, previously unimplemented) sums
today's tracked minutes for every active Supervisor and every active
Technician company-wide, bucketed by account role. The frontend renders this
as two new tiles in a new `hubAdmin.js` view, wired into the existing
Dashboard tab shell (`userHub.js`) with the same fetch/refresh lifecycle the
crew board already uses. Two existing view files get small role-conditional
edits to drop the three named tiles for `techfm_oa+` viewers only —
Technician and Supervisor viewers see no change.

**Tech Stack:** FastAPI + SQLAlchemy (backend), vanilla JS view modules
(frontend), pytest with a `db` fixture (backend tests only — no frontend
test harness exists in this repo).

**Spec:** This plan was scoped directly in conversation (bounded slice of
the pre-existing `docs/superpowers/specs/2026-08-20-user-hub-design.md` §5.4
/ §12 P4 phase) rather than written to its own spec file — the design was
fully nailed down and approved section-by-section in chat before this plan
was written. Read `docs/superpowers/specs/2026-08-20-user-hub-design.md`
§5.4 and §9 for the surrounding P4 context (this plan implements a narrower
slice than that section's full mockup: no pipeline, exceptions, or billing
tiles here — those are separate future work).

## Global Constraints

- **Bucketing is by account role, not by what work was clocked on.** A
  Supervisor's own hands-on hours count in Supervisor Time; a TechFM
  OA/Admin/Owner's hours (if any) count in neither bucket — their own time
  is already visible in their personal clock widget above the tabs.
- **Only active accounts count.** `User.archived_at IS NULL` filters both
  buckets.
- **The global sweep runs unscoped** (`work_orders_service.sweep_stale_sessions(db, now=now)`,
  no `technician_id`) before summing — this is the call site the router's
  own docstring already reserves for `GET /hub/admin`.
- **Reuse `labor_summary.crew_day_summaries`** for both buckets rather than
  writing new aggregation SQL — it already does exactly "N `day_summary`
  lookups, keyed by id, sharing one `now`."
- **Do not touch** the personal counts tile (`Assigned to me` / `In
  progress` / `Ready to complete`), `Work orders I lead`, or `Crew time
  today` — none of these were named for removal.
- **No new realtime event.** Reuse the existing `labor.session.changed`
  subscription (audience `supervisor+`, which already includes
  `techfm_oa+`) and the existing 60s crew safety-refresh timer.
- **No new CSS.** Reuse `.hub-tile`, `.hub-tile-grid`, `.hub-tile-label`,
  `.hub-tile-value` — all already styled.

---

## Task 1: Backend — `admin_hub()` service function

**Files:**
- Modify: `backend/app/services/hub.py` (add `HubAdminPayload` dataclass and
  `admin_hub()` function after `crew_hub()`, i.e. after line 466; add
  `from app.domain import roles` to the import block, after the existing
  `from app.domain import labor_day` line)
- Test: `backend/tests/test_hub_service.py` (append after the crew_hub test
  block, i.e. after line 539)

**Interfaces:**
- Consumes: `labor_summary.crew_day_summaries(db, ids, day, *, now)` →
  `dict[uuid.UUID, DaySummary]` (existing, `backend/app/services/labor_summary.py:252`).
  `work_orders_service.sweep_stale_sessions(db, *, technician_id=None, now=None)`
  (existing, `backend/app/services/work_orders.py:2268` — unscoped when
  `technician_id` is omitted).
- Produces: `hub_service.HubAdminPayload(server_now, supervisor_minutes_today,
  technician_minutes_today)` and `hub_service.admin_hub(db, user, *, now=None) -> HubAdminPayload`,
  consumed by Task 2's router handler.

- [x] **Step 1: Write the failing tests**

Add to `backend/tests/test_hub_service.py`, after `test_the_crew_payload_serialises_into_the_response_schema`
(after line 539):

```python
# --- admin_hub (P4 slice 1: the company-wide time summary) -----------------


def test_admin_hub_sums_supervisors_and_technicians_separately(db):
    # Bucketed by account role, not by what work was clocked on: a
    # supervisor doing hands-on work still lands in the supervisor bucket.
    creator = _seed_user(db, roles.ROLE_SUPERVISOR)
    supervisor_a = _seed_user(db, roles.ROLE_SUPERVISOR, first_name="Jose", last_name="Rivera")
    supervisor_b = _seed_user(db, roles.ROLE_SUPERVISOR, first_name="Dana", last_name="Ortiz")
    tech = _seed_user(db, roles.ROLE_TECHNICIAN, first_name="Marisol", last_name="Chen")
    wo_a = _seed_work_order(db, created_by=creator, assigned_to=supervisor_a, status=wo.STATUS_IN_PROGRESS)
    wo_b = _seed_work_order(db, created_by=creator, assigned_to=supervisor_b, status=wo.STATUS_IN_PROGRESS)
    wo_c = _seed_work_order(db, created_by=creator, assigned_to=tech, status=wo.STATUS_IN_PROGRESS)
    _seed_session(db, wo_a, supervisor_a, started_at=NOW - timedelta(hours=1), ended_at=NOW)
    _seed_session(db, wo_b, supervisor_b, started_at=NOW - timedelta(hours=2), ended_at=NOW)
    _seed_session(db, wo_c, tech, started_at=NOW - timedelta(minutes=30), ended_at=NOW)

    payload = hub_service.admin_hub(db, creator, now=NOW)

    assert payload.supervisor_minutes_today == 180  # 60 + 120
    assert payload.technician_minutes_today == 30


def test_admin_hub_excludes_techfm_oa_admin_and_owner_from_both_buckets(db):
    creator = _seed_user(db, roles.ROLE_SUPERVISOR)
    oa = _seed_user(db, roles.ROLE_TECHFM_OA, first_name="Pat", last_name="Nguyen")
    admin = _seed_user(db, roles.ROLE_ADMIN, first_name="Lee", last_name="Park")
    owner = _seed_user(db, roles.ROLE_OWNER, first_name="Sam", last_name="Boyd")
    for person in (oa, admin, owner):
        work_order = _seed_work_order(
            db, created_by=creator, assigned_to=person, status=wo.STATUS_IN_PROGRESS
        )
        _seed_session(db, work_order, person, started_at=NOW - timedelta(hours=1), ended_at=NOW)

    payload = hub_service.admin_hub(db, creator, now=NOW)

    assert payload.supervisor_minutes_today == 0
    assert payload.technician_minutes_today == 0


def test_admin_hub_excludes_archived_users(db):
    creator = _seed_user(db, roles.ROLE_SUPERVISOR)
    departed = _seed_user(db, roles.ROLE_SUPERVISOR, first_name="Former", last_name="Employee")
    work_order = _seed_work_order(
        db, created_by=creator, assigned_to=departed, status=wo.STATUS_IN_PROGRESS
    )
    _seed_session(db, work_order, departed, started_at=NOW - timedelta(hours=1), ended_at=NOW)
    departed.archived_at = datetime.now(timezone.utc)
    db.flush()

    payload = hub_service.admin_hub(db, creator, now=NOW)

    assert payload.supervisor_minutes_today == 0


def test_admin_hub_sweeps_a_forgotten_clock_before_summing(db):
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    tech = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _seed_work_order(
        db, created_by=supervisor, assigned_to=tech, status=wo.STATUS_IN_PROGRESS
    )
    started = datetime.now(timezone.utc) - timedelta(hours=20)
    session = WorkOrderLaborSession(
        id=uuid.uuid4(), work_order_id=work_order.id, technician_id=tech.id,
        started_at=started,
    )
    db.add(session)
    db.flush()

    payload = hub_service.admin_hub(db, supervisor)

    db.refresh(session)
    assert session.ended_at == started + timedelta(minutes=wo.LABOR_SESSION_MAX_MINUTES)
    assert payload.technician_minutes_today == wo.LABOR_SESSION_MAX_MINUTES


def test_the_admin_payload_serialises_into_the_response_schema(db):
    from app.routers.hub import get_hub_admin

    oa = _seed_user(db, roles.ROLE_TECHFM_OA)
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR, first_name="Jose", last_name="Rivera")
    work_order = _seed_work_order(
        db, created_by=oa, assigned_to=supervisor, status=wo.STATUS_IN_PROGRESS
    )
    wos.start_labor_session(db, work_order.id, user=supervisor)

    body = get_hub_admin(user=oa, db=db).model_dump()

    assert body["supervisor_minutes_today"] >= 0
    assert "technician_minutes_today" in body
    assert "server_now" in body
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_hub_service.py -k admin_hub -v`
Expected: FAIL — `AttributeError: module 'app.services.hub' has no attribute 'admin_hub'`
(the schema-serialization test will additionally fail on the `get_hub_admin`
import; that import is satisfied by Task 2, so it's expected to keep failing
until Task 2 lands — leave it red for now and continue).

- [x] **Step 3: Implement `admin_hub()`**

In `backend/app/services/hub.py`, add the import — after the existing line
`from app.domain import labor_day`:

```python
from app.domain import roles
```

Then add, after `crew_hub()` (after line 466, before the
`# --- the timesheet payload (P3b) -------------------------------------------`
section marker):

```python
# --- the admin payload (P4 slice 1: company-wide time summary) -------------


@dataclass(frozen=True)
class HubAdminPayload:
    """`GET /hub/admin`'s whole contract: today's tracked minutes, summed
    by account role across the whole company.

    Bucketed by account role, not by what work was clocked on -- a
    Supervisor's own hands-on hours count as Supervisor Time; a TechFM
    OA/Admin/Owner's hours (if any) land in neither bucket, since their own
    time is already the personal clock widget above the tabs.
    """

    server_now: datetime
    supervisor_minutes_today: int
    technician_minutes_today: int


def admin_hub(db: Session, user: User, *, now: Optional[datetime] = None) -> HubAdminPayload:
    """The `GET /hub/admin` payload: how much the company tracked today,
    split into Supervisor Time and Technician Time.

    **Not side-effect-free**, deliberately the widest sweep in the module:
    unscoped (no `technician_id`), so every over-cap running session in the
    company is closed before anything is summed. This is the call site the
    router module's own docstring already reserves for the global sweep
    (spec §3.5), and it is safe under concurrent callers for the same
    reason `crew_hub`'s per-member sweep is -- `sweep_stale_sessions` locks
    each work order `FOR UPDATE` before touching its sessions.
    """
    now = now or datetime.now(timezone.utc)
    day = labor_day.central_date_of(now)

    work_orders_service.sweep_stale_sessions(db, now=now)

    supervisors = (
        db.query(User)
        .filter(User.role == roles.ROLE_SUPERVISOR, User.archived_at.is_(None))
        .all()
    )
    technicians = (
        db.query(User)
        .filter(User.role == roles.ROLE_TECHNICIAN, User.archived_at.is_(None))
        .all()
    )

    supervisor_summaries = labor_summary.crew_day_summaries(
        db, [u.id for u in supervisors], day, now=now
    )
    technician_summaries = labor_summary.crew_day_summaries(
        db, [u.id for u in technicians], day, now=now
    )

    return HubAdminPayload(
        server_now=now,
        supervisor_minutes_today=sum(s.total_minutes for s in supervisor_summaries.values()),
        technician_minutes_today=sum(s.total_minutes for s in technician_summaries.values()),
    )
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_hub_service.py -k admin_hub -v`
Expected: the first four tests PASS. `test_the_admin_payload_serialises_into_the_response_schema`
still FAILs (no `get_hub_admin` yet) — that's expected until Task 2.

- [x] **Step 5: Commit**

```bash
git add backend/app/services/hub.py backend/tests/test_hub_service.py
git commit -m "feat(user-hub): add the admin_hub company-wide time summary"
```

---

## Task 2: Backend — `HubAdminResponse` schema + `GET /hub/admin` route

**Files:**
- Modify: `backend/app/schemas/hub.py` (add `HubAdminResponse` after
  `HubCrewResponse`, i.e. after line 219)
- Modify: `backend/app/routers/hub.py` (add the import and the new route
  after `get_hub_crew`, i.e. after line 98; update the module docstring's
  route table to drop "-- later phase")
- Test: `backend/tests/test_hub_service.py` (the schema-serialization test
  from Task 1 now passes)
- Test: `backend/tests/test_route_role_gates.py` (append after
  `test_the_crew_board_requires_supervisor`, i.e. after line 538)

**Interfaces:**
- Consumes: `hub_service.HubAdminPayload` and `hub_service.admin_hub()`
  from Task 1.
- Produces: `HubAdminResponse` (pydantic model, `from_attributes`) and the
  `GET /hub/admin` route handler `get_hub_admin`, consumed by Task 3's
  `apiGetHubAdmin()`.

- [x] **Step 1: Write the failing test**

Add to `backend/tests/test_route_role_gates.py`, after
`test_the_crew_board_requires_supervisor` (after line 538):

```python
def test_the_admin_summary_requires_techfm_oa():
    # `GET /hub/admin` is techfm_oa+ (router module docstring) -- a
    # supervisor gets 403, a TechFM OA gets 200.
    assert _min_role_for(hub_router, "get_hub_admin") == roles.ROLE_TECHFM_OA
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_route_role_gates.py -k admin_summary -v`
Expected: FAIL — `AssertionError: route 'get_hub_admin' not found on app.routers.hub`

Also run the schema test held over from Task 1:
Run: `cd backend && python -m pytest tests/test_hub_service.py -k admin_payload_serialises -v`
Expected: FAIL — `ImportError: cannot import name 'get_hub_admin'`

- [x] **Step 3: Add the schema**

In `backend/app/schemas/hub.py`, add after `HubCrewResponse` (after line 219,
before the `# --- GET /hub/timesheets (P3b) ---------------------------------------------`
marker):

```python
# --- GET /hub/admin (P4 slice 1) --------------------------------------------


class HubAdminResponse(BaseModel):
    """`GET /hub/admin`. Bucketed by account role, not by what work was
    clocked on -- a TechFM OA/Admin/Owner's own hours (if any) land in
    neither bucket; their own time is already the personal clock widget."""

    server_now: datetime
    supervisor_minutes_today: int
    technician_minutes_today: int

    model_config = {"from_attributes": True}
```

- [x] **Step 4: Add the route**

In `backend/app/routers/hub.py`, update the import line:

```python
from app.schemas.hub import HubAdminResponse, HubClock, HubCrewResponse, HubResponse, HubTimesheetResponse
```

Update the module docstring's route table (the block starting `- \`GET /hub\`
any authenticated`), changing:

```
- `GET /hub/admin`       techfm_oa+         -- later phase
```

to:

```
- `GET /hub/admin`       techfm_oa+         -- the company-wide time summary
```

Then add the route after `get_hub_crew` (after line 98):

```python
@router.get("/admin", response_model=HubAdminResponse)
def get_hub_admin(
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    db: Session = Depends(get_db),
):
    """The company-wide time summary: today's tracked minutes for every
    active Supervisor and every active Technician, summed separately.

    One declarative gate, same pattern as `get_hub_crew` -- `auth_deps.py`
    stays the only place a role 403 is raised.
    """
    return HubAdminResponse.model_validate(hub_service.admin_hub(db, user))
```

- [x] **Step 5: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_route_role_gates.py -k admin_summary -v`
Expected: PASS

Run: `cd backend && python -m pytest tests/test_hub_service.py -v`
Expected: all PASS, including `test_the_admin_payload_serialises_into_the_response_schema`

Run the full backend suite to confirm nothing else broke:
Run: `cd backend && python -m pytest -v`
Expected: PASS

- [x] **Step 6: Commit**

```bash
git add backend/app/schemas/hub.py backend/app/routers/hub.py backend/tests/test_route_role_gates.py
git commit -m "feat(user-hub): add GET /hub/admin"
```

---

## Task 3: Frontend — `apiGetHubAdmin()` + `hubAdmin.js` view

**Files:**
- Modify: `backend/static/api.js` (add `apiGetHubAdmin` after
  `apiGetHubCrew`, i.e. after line 490)
- Create: `backend/static/views/hubAdmin.js`

**Interfaces:**
- Consumes: nothing new from earlier tasks except the wire shape of
  `GET /hub/admin`'s JSON body: `{server_now, supervisor_minutes_today,
  technician_minutes_today}` (Task 2).
- Produces: `apiGetHubAdmin()` (async, resolves to that JSON body) and
  `mountHubAdminSummary(container, payload)` (exported from
  `hubAdmin.js`), both consumed by Task 4's `userHub.js` wiring.

This task has no automated test — this repo has no frontend test harness
(confirmed in the existing spec's Testing section). Verify manually at the
end of Task 4, once the module is actually wired into a page.

- [x] **Step 1: Add `apiGetHubAdmin()`**

In `backend/static/api.js`, add after `apiGetHubCrew` (after line 490):

```javascript
export async function apiGetHubAdmin() {
  return liveGet("/hub/admin");
}
```

- [x] **Step 2: Create `hubAdmin.js`**

Create `backend/static/views/hubAdmin.js`:

```javascript
// View: the Admin+ hub's company-wide time summary.
//
// Layer: views. Renders inside the Dashboard tab body, above the crew
// board mount point `hubTechnician.js` already draws. Consumes exactly the
// `GET /hub/admin` payload `userHub.js` fetches for techfm_oa+ viewers;
// makes no requests of its own.

import { escapeHtml } from "../format.js";

function formatHm(totalMinutes) {
  const minutes = Math.max(0, Math.round(totalMinutes));
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (!h) return `${m} m`;
  return `${h} h ${m} m`;
}

function tileHtml(label, value) {
  return `
    <section class="hub-tile">
      <p class="hub-tile-label">${escapeHtml(label)}</p>
      <p class="hub-tile-value">${escapeHtml(value)}</p>
    </section>`;
}

export function mountHubAdminSummary(container, payload) {
  container.innerHTML = `
    <div class="hub-tile-grid">
      ${tileHtml("Supervisor Time", formatHm(payload.supervisor_minutes_today))}
      ${tileHtml("Technician Time", formatHm(payload.technician_minutes_today))}
    </div>`;
}
```

- [x] **Step 3: Commit**

```bash
git add backend/static/api.js backend/static/views/hubAdmin.js
git commit -m "feat(user-hub): add the admin time-summary view module"
```

---

## Task 4: Frontend — wire the summary in, drop the three tiles

**Files:**
- Modify: `backend/static/views/hubTechnician.js` (`mountHubDashboard`,
  lines 153-167)
- Modify: `backend/static/views/hubSupervisor.js` (`rollUpsHtml` and
  `mountHubCrew`, lines 35-50 and 137-139)
- Modify: `backend/static/views/userHub.js` (imports, module state,
  `renderCrew`/`renderActiveTab`, `refreshCrew`, `startCrewSafetyRefresh`,
  the realtime subscription, and `loadUserHub`)

**Interfaces:**
- Consumes: `apiGetHubAdmin`, `mountHubAdminSummary` (Task 3); `roleAtLeast`
  (existing, `backend/static/roles.js`).
- Produces: the finished feature — no further tasks depend on this one.

This task has no automated test (no frontend harness). Step 6 is a manual
verification checklist instead of a pytest run.

- [x] **Step 1: Make `mountHubDashboard` role-conditional**

In `backend/static/views/hubTechnician.js`, add the import:

```javascript
import { roleAtLeast } from "../roles.js";
```

Replace `mountHubDashboard` (lines 153-167):

```javascript
export function mountHubDashboard(container, payload) {
  const isAdminPlus = roleAtLeast(payload.user.role, "techfm_oa");
  container.innerHTML =
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

- [x] **Step 2: Make the crew rollup tiles role-conditional**

In `backend/static/views/hubSupervisor.js`, replace `rollUpsHtml` (lines
35-50):

```javascript
function rollUpsHtml(payload, { isAdminPlus = false } = {}) {
  const tiles = [
    tileHtml(
      "Work orders I lead",
      payload.led.total,
      payload.led.in_progress ? `${payload.led.in_progress} in progress` : ""
    ),
  ];
  // "Crew on the clock" is dropped for techfm_oa+ viewers -- the new
  // company-wide Supervisor Time / Technician Time tiles (hubAdmin.js)
  // supersede it for that role tier.
  if (!isAdminPlus) {
    tiles.push(tileHtml("Crew on the clock", `${payload.crew_on_clock} of ${payload.crew_total}`, ""));
  }
  tiles.push(
    tileHtml(
      "Crew time today",
      formatHm(payload.crew_minutes_today),
      payload.crew_on_clock ? "ticking" : ""
    )
  );
  return `<div class="hub-tile-grid">${tiles.join("")}</div>`;
}
```

Replace `mountHubCrew` (lines 137-139):

```javascript
export function mountHubCrew(container, payload, { isAdminPlus = false } = {}) {
  container.innerHTML = rollUpsHtml(payload, { isAdminPlus }) + attentionHtml(payload.attention) + crewHtml(payload);
}
```

- [x] **Step 3: Wire the fetch/render/refresh lifecycle in `userHub.js`**

In `backend/static/views/userHub.js`, update the imports:

```javascript
import { apiGetHub, apiGetHubAdmin, apiGetHubCrew, apiGetHubTimesheets } from "../api.js";
```

```javascript
import { mountHubAdminSummary } from "./hubAdmin.js";
```
(add this line next to the existing `import { mountHubCrew } from "./hubSupervisor.js";`)

Add new module state next to the existing crew state (`latestCrewPayload`,
`crewRequestId`, `crewSafetyTimer`):

```javascript
let latestAdminPayload = null;
let adminRequestId = 0;
```

Add an `adminMount()` helper next to `crewMount()`:

```javascript
function adminMount() {
  return tabPanels.dashboard.querySelector("#hub-admin-mount");
}
```

Add a small role helper (used from several places below) next to
`crewMount()`/`adminMount()`:

```javascript
function canViewAdminTiles() {
  return Boolean(latestPayload) && roleAtLeast(latestPayload.user.role, "techfm_oa");
}
```

Update `renderCrew` to pass the flag through, and add `renderAdmin` next to
it:

```javascript
function renderCrew() {
  if (!latestCrewPayload) return;
  const mount = crewMount();
  if (mount) mountHubCrew(mount, latestCrewPayload, { isAdminPlus: canViewAdminTiles() });
}

function renderAdmin() {
  if (!latestAdminPayload) return;
  const mount = adminMount();
  if (mount) mountHubAdminSummary(mount, latestAdminPayload);
}
```

Update `renderActiveTab`'s dashboard branch to also call `renderAdmin()`:

```javascript
function renderActiveTab() {
  if (activeTab === "dashboard") {
    mountHubDashboard(tabPanels.dashboard, latestPayload);
    renderCrew();
    renderAdmin();
  } else if (activeTab === "timesheets") {
```

(leave the rest of the function unchanged)

Add `refreshAdmin`, mirroring `refreshCrew`, right after `refreshCrew`'s
definition:

```javascript
async function refreshAdmin({ background = false } = {}) {
  const mount = adminMount();
  if (!mount) return;
  const requestId = ++adminRequestId;
  try {
    const payload = await apiGetHubAdmin();
    if (requestId !== adminRequestId) return;
    latestAdminPayload = payload;
    mountHubAdminSummary(mount, payload);
  } catch (err) {
    if (requestId !== adminRequestId) return;
    if (background) return;
    mount.innerHTML = `<p class="error">${friendlyError(err, "Could not load the company summary.")}</p>`;
  }
}
```

Update `startCrewSafetyRefresh`'s interval body to also cover the admin
summary:

```javascript
function startCrewSafetyRefresh() {
  stopCrewSafetyRefresh();
  crewSafetyTimer = setInterval(() => {
    if (document.hidden) return;
    void refreshCrew({ background: true });
    if (canViewAdminTiles()) void refreshAdmin({ background: true });
  }, CREW_SAFETY_REFRESH_MS);
}
```

Update the `labor.session.changed` subscription to also refresh the admin
summary:

```javascript
subscribe(LABOR_SESSION_CHANGED_EVENT, ({ activePage }) => {
  if (activePage !== HUB_PAGE) return;
  void refreshCrew({ background: true });
  if (canViewAdminTiles()) void refreshAdmin({ background: true });
});
```

Update `loadUserHub()`: after the existing
`const canViewSupervisorTabs = roleAtLeast(payload.user.role, "supervisor");`
line, add:

```javascript
  const canViewAdminTiles = roleAtLeast(payload.user.role, "techfm_oa");
```

After the existing reset block (`if (userChanged || !canViewSupervisorTabs) { ... }`),
add a matching reset for the admin state:

```javascript
  if (userChanged || !canViewAdminTiles) {
    latestAdminPayload = null;
    adminRequestId += 1;
  }
```

Finally, after the existing:

```javascript
  if (canViewSupervisorTabs) {
    await refreshCrew();
    startCrewSafetyRefresh();
  } else {
    stopCrewSafetyRefresh();
  }
```

add:

```javascript
  if (canViewAdminTiles) {
    await refreshAdmin();
  }
```

(Note: this creates one local variable `canViewAdminTiles` inside
`loadUserHub` that shadows the module-level function `canViewAdminTiles()`
defined earlier — rename the module-level helper to `viewerCanSeeAdminTiles()`
to avoid the collision. Apply that rename everywhere the helper is called:
`renderCrew`, `startCrewSafetyRefresh`, and the `labor.session.changed`
subscription.)

- [x] **Step 4: Fix the naming collision from the note above**

Rename the module-level helper function from `canViewAdminTiles` to
`viewerCanSeeAdminTiles` at its definition and at all three call sites
(`renderCrew`, `startCrewSafetyRefresh`, the `subscribe(...)` callback), so
it no longer collides with the local `const canViewAdminTiles` inside
`loadUserHub`.

- [x] **Step 5: Run the backend test suite once more to confirm no regressions**

Run: `cd backend && python -m pytest -v`
Expected: PASS (this task touches no backend files, but confirms Tasks 1-2
are still green before manual frontend verification)

- [ ] **Step 6: Manual verification**

Start the app per the existing runbook (do not auto-run this — check with
the user first, per this repo's standing preference for manual validation).
Then, for each of three accounts (a Technician, a Supervisor, and a TechFM
OA/Admin/Owner):

- Log in and open the User Hub's Dashboard tab.
- **Technician / Supervisor:** confirm the page looks exactly as before —
  Time Today, Tools out, and (for the Supervisor, if they lead a crew)
  "Crew on the clock" are all still present.
- **TechFM OA/Admin/Owner:** confirm Time Today, Tools out are gone; confirm
  two new tiles — "Supervisor Time" and "Technician Time" — appear with
  today's company-wide totals; if this viewer is a routed supervisor on a
  live work order, confirm the crew board still renders below with "Crew on
  the clock" absent but "Work orders I lead" and "Crew time today" present.
- Start a labor session as a Technician in one browser tab while a TechFM
  OA/Admin/Owner has the hub open in another; confirm the Technician Time
  tile updates within 60 seconds (safety refresh) without a manual reload.

- [x] **Step 7: Commit**

```bash
git add backend/static/views/hubTechnician.js backend/static/views/hubSupervisor.js backend/static/views/userHub.js
git commit -m "feat(user-hub): wire the admin time summary into the Dashboard tab"
```

---

## Plan Self-Review Notes

- **Spec coverage:** all three named removals (Clocked-in/"Crew on the
  clock", Time Today, Tools out) and the new split (Supervisor Time /
  Technician Time, company-wide, by account role) are covered — Task 4
  Steps 1-2 for the removals, Tasks 1-3 for the new summary.
- **Type consistency:** `HubAdminPayload`/`HubAdminResponse` field names
  (`supervisor_minutes_today`, `technician_minutes_today`, `server_now`)
  are identical across the service dataclass (Task 1), the schema (Task 2),
  and the frontend's `payload.supervisor_minutes_today` /
  `payload.technician_minutes_today` reads (Task 3) — checked end to end.
- **Known wrinkle flagged inline:** the `canViewAdminTiles` naming collision
  in Task 4 Step 3 is called out explicitly with its own fix-up step (Step
  4) rather than silently avoided, since the plan is written function-by-function
  and the collision only becomes visible once both pieces exist side by side.
