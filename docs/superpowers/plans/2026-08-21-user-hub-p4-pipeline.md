# User Hub P4 — Work Order Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **This repo's CLAUDE.md forbids using the Agent tool for this project unless
> explicitly told otherwise.** Do not dispatch subagents to execute these
> tasks — use `superpowers:executing-plans` (inline, in this session) instead
> of `superpowers:subagent-driven-development`, regardless of which the user
> picks at the execution-choice prompt, unless they explicitly override this
> note.

**Goal:** Give TechFM OA+ viewers of the User Hub a "Work Order Pipeline" row
on the Admin Dashboard tab — six company-wide, unscoped status counts
(Created, Assigned, In-Progress, Ready to complete, Completed, Review) —
where clicking any count opens the standalone Work Orders page pre-filtered
to that status.

**Architecture:** `GET /hub/admin` (shipped in the prior P4 slice) gains a
new `pipeline` field on its existing payload/response. The service computes
it with one grouped `COUNT` query over `WorkOrder.status`, filtered to live
(non-archived) rows only — no session sweep involved, since this reads work
order status, not labor sessions. The frontend adds a second tile row to the
existing `hubAdmin.js` mount, each tile a real `<button>` (this hub's first
*interactive* tile) that sets the standalone Work Orders page's status filter
and switches to it, reusing that page's own existing filter/fetch machinery
rather than building a new one.

**Tech Stack:** FastAPI + SQLAlchemy (backend), vanilla JS view modules
(frontend), pytest with a `db` fixture (backend tests only — no frontend
test harness exists in this repo).

**Spec:** `docs/superpowers/specs/2026-08-20-user-hub-design.md` §5.4 (the
mockup, lines 615–620 and 635–638) and §7 (the `GET /hub/admin` contract,
lines 824–835). This plan implements one tile group of that section's full
mockup — the pipeline row only. "On the clock now" (per-person live list),
Exceptions, and Billing are separate future slices; the two aggregate tiles
already shipped (`Supervisor Time` / `Technician Time`) were P4 slice 1
(`docs/superpowers/plans/2026-08-21-user-hub-p4-admin-time-summary.md`,
committed on `main` as of `78c2595`/`811c558`/`275cebe`/`cb34c17`). This is
P4 slice 2.

## Global Constraints

- **Company-wide, unscoped, live rows only.** Every count filters
  `WorkOrder.archived_at IS NULL` and has no other scope — no per-technician,
  per-supervisor, or per-creator filter. This matches `admin_hub()`'s
  existing precedent (it already runs the widest sweep in the module).
- **No session sweep needed for this field.** Pipeline counts read
  `WorkOrder.status` directly; they do not depend on labor-session
  freshness. `admin_hub()`'s existing `work_orders_service.sweep_stale_sessions(db, now=now)`
  call (already present for the minutes fields) is left exactly where it is
  — nothing in this plan calls it again or moves it.
- **Six columns, not seven.** The pipeline excludes `on_hold` — the spec's
  mockup (§5.4) shows exactly six stages (Created, Assigned, In-Progress,
  Ready to complete, Completed, Review). An on-hold work order is a temporal
  pause on In-Progress, not a pipeline stage of its own, and simply does not
  appear in this row (it still counts everywhere else in the app).
- **Shared dev database, not an isolated test DB.** The `db` fixture (see
  `backend/tests/conftest.py`) joins a savepoint on the real local Postgres
  database, not a fresh one — confirmed the hard way in P4 slice 1, where
  absolute-count assertions on `admin_hub()` were flaky against pre-existing
  manual-QA rows. Every new test in this plan asserts on a **before/after
  delta**, not an absolute count, from the first line written — no lesson to
  relearn here.
- **Click target is the standalone Work Orders page, not the hub's own
  "Work Orders" tab.** `backend/static/pages/work-orders.html`'s own comment
  confirms it is already server-scoped `admin/owner -> all` (and `techfm_oa`
  passes the same `require_min_role` gate elsewhere in that router), so it
  is already the unscoped, company-wide list the pipeline row needs — no new
  endpoint or scope change required. The Hub's *own* embedded "Work Orders"
  tab (§5.4's Tab 3, "embedded card list, unscoped") is a separate, still-open
  piece of P4 and out of scope here.
- **This task adds one new CSS class, deliberately.** P4 slice 1's "no new
  CSS" constraint held because every tile in that slice was static. This
  slice's pipeline tiles are the hub's first *clickable* tiles, and the
  existing `.hub-tile`/`section` styling (global `section { ... }` rule,
  `backend/static/styles.css:478`) has no button-shaped equivalent — a
  `<button>` does not inherit it. `.hub-tile-pipeline-item` (added in Task 4)
  reproduces that same look on a real `<button>` element, plus a hover state.
  No other new CSS.
- **Reuse the existing status vocabulary and labels verbatim.** The six
  status values (`created`, `assigned`, `in_progress`, `ready_to_complete`,
  `completed`, `review`) and their human labels ("Created", "Assigned",
  "In-Progress", "Ready to Complete", "Completed", "Review") already exist as
  the `<option>`s in `backend/static/pages/work-orders.html:20-27` — this
  plan does not invent new copy, it matches that page's own filter dropdown
  exactly so the tile's label and the page it opens always agree.

---

## Task 1: Backend — pipeline counts in `admin_hub()`

**Files:**
- Modify: `backend/app/services/hub.py` (add `AdminPipelineCounts` dataclass
  and a `_pipeline_counts()` helper before `admin_hub()`, i.e. before line
  489; add a `pipeline` field to `HubAdminPayload`, i.e. after line 486; add
  the field to `admin_hub()`'s return statement, i.e. inside lines 524-528)
- Test: `backend/tests/test_hub_service.py` (append after
  `test_admin_hub_sweeps_a_forgotten_clock_before_summing`, i.e. after line
  629, before `test_the_admin_payload_serialises_into_the_response_schema`
  at line 632; also extend that existing test)

**Interfaces:**
- Consumes: nothing new — reads `WorkOrder.status` and `WorkOrder.archived_at`
  directly, both already imported (`from app.models import User, WorkOrder, ...`
  at `backend/app/services/hub.py:30`; `from sqlalchemy import func, or_` at
  line 22).
- Produces: `hub_service.AdminPipelineCounts(created, assigned, in_progress,
  ready_to_complete, completed, review)` and a `pipeline` field on
  `hub_service.HubAdminPayload`, consumed by Task 2's schema.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_hub_service.py`, after
`test_admin_hub_sweeps_a_forgotten_clock_before_summing` (after line 629):

```python
def test_admin_hub_pipeline_counts_are_company_wide_and_unscoped(db):
    # The shared dev database already has live rows in it (see this plan's
    # Global Constraints), so assert on the delta this test's own fixtures
    # caused, not on an absolute total.
    creator = _seed_user(db, roles.ROLE_SUPERVISOR)
    stranger = _seed_user(db, roles.ROLE_SUPERVISOR, first_name="Dana", last_name="Ortiz")
    baseline = hub_service.admin_hub(db, creator).pipeline

    _seed_work_order(db, created_by=creator, status=wo.STATUS_CREATED)
    _seed_work_order(db, created_by=creator, status=wo.STATUS_ASSIGNED)
    _seed_work_order(db, created_by=creator, status=wo.STATUS_IN_PROGRESS)
    _seed_work_order(db, created_by=creator, status=wo.STATUS_READY_TO_COMPLETE)
    _seed_work_order(db, created_by=creator, status=wo.STATUS_COMPLETED)
    _seed_work_order(db, created_by=creator, status=wo.STATUS_REVIEW)
    # A stranger's work order still counts -- the pipeline is company-wide,
    # not scoped to the caller the way `GET /hub`'s own counts are.
    _seed_work_order(db, created_by=stranger, status=wo.STATUS_CREATED)

    pipeline = hub_service.admin_hub(db, creator).pipeline

    assert pipeline.created - baseline.created == 2
    assert pipeline.assigned - baseline.assigned == 1
    assert pipeline.in_progress - baseline.in_progress == 1
    assert pipeline.ready_to_complete - baseline.ready_to_complete == 1
    assert pipeline.completed - baseline.completed == 1
    assert pipeline.review - baseline.review == 1


def test_admin_hub_pipeline_excludes_on_hold_and_archived(db):
    creator = _seed_user(db, roles.ROLE_SUPERVISOR)
    baseline = hub_service.admin_hub(db, creator).pipeline

    _seed_work_order(db, created_by=creator, status=wo.STATUS_ON_HOLD)
    archived = _seed_work_order(db, created_by=creator, status=wo.STATUS_IN_PROGRESS)
    archived.archived_at = datetime.now(timezone.utc)
    db.flush()

    pipeline = hub_service.admin_hub(db, creator).pipeline

    # Six columns, not seven (Global Constraints) -- on_hold has nowhere to
    # land, and the archived row is excluded everywhere.
    assert pipeline.created == baseline.created
    assert pipeline.assigned == baseline.assigned
    assert pipeline.in_progress == baseline.in_progress
    assert pipeline.ready_to_complete == baseline.ready_to_complete
    assert pipeline.completed == baseline.completed
    assert pipeline.review == baseline.review
```

Also extend the existing schema-serialization test in the same file (lines
632-646) to cover the new field — replace:

```python
    assert body["supervisor_minutes_today"] >= 0
    assert "technician_minutes_today" in body
    assert "server_now" in body
```

with:

```python
    assert body["supervisor_minutes_today"] >= 0
    assert "technician_minutes_today" in body
    assert "server_now" in body
    assert "pipeline" in body
    assert "in_progress" in body["pipeline"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_hub_service.py -k pipeline -v`
Expected: FAIL — `AttributeError: 'HubAdminPayload' object has no attribute 'pipeline'`
(the schema-serialization test's new assertion will additionally fail with
`KeyError: 'pipeline'` until Task 2 lands — expected, continue).

- [ ] **Step 3: Implement `AdminPipelineCounts` and `_pipeline_counts()`**

In `backend/app/services/hub.py`, add before `HubAdminPayload` (before line
473):

```python
@dataclass(frozen=True)
class AdminPipelineCounts:
    """Company-wide, unscoped work-order status counts -- the "Work Order
    Pipeline" row (spec §5.4). Six columns, not seven: `on_hold` is a
    temporal pause on `in_progress`, not a pipeline stage of its own, and
    has no column here."""

    created: int
    assigned: int
    in_progress: int
    ready_to_complete: int
    completed: int
    review: int


def _pipeline_counts(db: Session) -> AdminPipelineCounts:
    rows = (
        db.query(WorkOrder.status, func.count(WorkOrder.id))
        .filter(WorkOrder.archived_at.is_(None))
        .group_by(WorkOrder.status)
        .all()
    )
    counts = dict(rows)
    return AdminPipelineCounts(
        created=counts.get(wo.STATUS_CREATED, 0),
        assigned=counts.get(wo.STATUS_ASSIGNED, 0),
        in_progress=counts.get(wo.STATUS_IN_PROGRESS, 0),
        ready_to_complete=counts.get(wo.STATUS_READY_TO_COMPLETE, 0),
        completed=counts.get(wo.STATUS_COMPLETED, 0),
        review=counts.get(wo.STATUS_REVIEW, 0),
    )
```

Add the `pipeline` field to `HubAdminPayload` (after line 486,
`technician_minutes_today: int`):

```python
    pipeline: AdminPipelineCounts
```

Update `admin_hub()`'s return statement (lines 524-528) to:

```python
    return HubAdminPayload(
        server_now=now,
        supervisor_minutes_today=sum(s.total_minutes for s in supervisor_summaries.values()),
        technician_minutes_today=sum(s.total_minutes for s in technician_summaries.values()),
        pipeline=_pipeline_counts(db),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_hub_service.py -k pipeline -v`
Expected: the two new tests PASS.
`test_the_admin_payload_serialises_into_the_response_schema` still FAILs on
`assert "pipeline" in body` — expected until Task 2.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/hub.py backend/tests/test_hub_service.py
git commit -m "feat(user-hub): add pipeline counts to admin_hub"
```

---

## Task 2: Backend — `HubAdminPipeline` schema field

**Files:**
- Modify: `backend/app/schemas/hub.py` (add `HubAdminPipeline` before
  `HubAdminResponse`, i.e. before line 225; add a `pipeline` field to
  `HubAdminResponse`, i.e. after line 232)

**Interfaces:**
- Consumes: `hub_service.AdminPipelineCounts` from Task 1.
- Produces: `HubAdminPipeline` (pydantic model, `from_attributes`) and the
  `pipeline` field on `HubAdminResponse`, consumed by Task 4's frontend.

No route change is needed: `backend/app/routers/hub.py`'s `get_hub_admin`
already does the whole translation with
`HubAdminResponse.model_validate(hub_service.admin_hub(db, user))`
(`backend/app/routers/hub.py:112`) — pydantic's `from_attributes` reads the
new nested dataclass field the same way `HubCrewResponse.led` already reads
`HubCrewPayload.led` (a `LedCounts` dataclass) today.

- [ ] **Step 1: Run the held-over test to confirm it still fails on schema, not service**

Run: `cd backend && python -m pytest tests/test_hub_service.py -k admin_payload_serialises -v`
Expected: FAIL — `KeyError: 'pipeline'` (Task 1 already made `pipeline` a
real attribute on the dataclass; the response model just doesn't declare it
yet).

- [ ] **Step 2: Add the schema**

In `backend/app/schemas/hub.py`, add before `HubAdminResponse` (before line
225):

```python
class HubAdminPipeline(BaseModel):
    """Company-wide, unscoped work-order status counts -- six columns, not
    seven (`on_hold` has no column; see the service dataclass's docstring)."""

    created: int
    assigned: int
    in_progress: int
    ready_to_complete: int
    completed: int
    review: int

    model_config = {"from_attributes": True}


```

Add the `pipeline` field to `HubAdminResponse` (after line 232,
`technician_minutes_today: int`):

```python
    pipeline: HubAdminPipeline
```

- [ ] **Step 3: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_hub_service.py -k admin -v`
Expected: all PASS, including `test_the_admin_payload_serialises_into_the_response_schema`.

Run the full backend suite to confirm nothing else broke:
Run: `cd backend && python -m pytest -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/app/schemas/hub.py
git commit -m "feat(user-hub): add pipeline field to HubAdminResponse"
```

---

## Task 3: Frontend — `openWorkOrdersFilteredByStatus()` in `workOrders.js`

**Files:**
- Modify: `backend/static/views/workOrders.js` (add the export after
  `focusWorkOrderNumber`, i.e. after line 1321)

**Interfaces:**
- Consumes: the module-private `statusFilter` DOM reference
  (`backend/static/views/workOrders.js:73`), `resetFilterControls()`
  (line 290), and the module-private `showAll` flag (line 125) — all
  already exist in this file.
- Produces: `openWorkOrdersFilteredByStatus(status)`, consumed by Task 4's
  click handler in `hubAdmin.js`.

This task adds no new fetch call. `showPage("work-orders")`
(`backend/static/views/nav.js:222-223`) already calls
`loadWorkOrders({ refreshReferenceData: true })` on every entry to the
page, and that call reads the filter dropdowns' live DOM values through
`currentFilters()` (line 274-284) — so setting the dropdown's value before
calling `showPage` is sufficient; calling `loadWorkOrders()` a second time
here would just double the fetch.

This task has no automated test — this repo has no frontend test harness
(confirmed in the prior P4 slice's plan). Verify manually at the end of
Task 4, once the click handler is wired in.

- [ ] **Step 1: Add `openWorkOrdersFilteredByStatus()`**

In `backend/static/views/workOrders.js`, add after `focusWorkOrderNumber`
(after line 1321):

```javascript
// Called from the Admin Dashboard's pipeline tiles (hubAdmin.js). Sets the
// status filter and clears every other one, so the tile always lands on
// exactly that status's full company-wide list -- never a stale filter left
// over from the last time someone visited this page. Does not itself fetch:
// `showPage("work-orders")` (nav.js) already calls `loadWorkOrders` on every
// page entry, and that reads these dropdowns' live values.
export function openWorkOrdersFilteredByStatus(status) {
  resetFilterControls();
  if (statusFilter) statusFilter.value = status;
  showAll = false;
}
```

- [ ] **Step 2: Commit**

```bash
git add backend/static/views/workOrders.js
git commit -m "feat(user-hub): add openWorkOrdersFilteredByStatus"
```

---

## Task 4: Frontend — the pipeline row in `hubAdmin.js`

**Files:**
- Modify: `backend/static/views/hubAdmin.js` (add pipeline rendering and a
  delegated click handler to `mountHubAdminSummary`)
- Modify: `backend/static/styles.css` (add `.hub-tile-pipeline-item`, after
  `.hub-tile-count`, i.e. after line 1816)

**Interfaces:**
- Consumes: `openWorkOrdersFilteredByStatus` (Task 3, from
  `./workOrders.js`), `showPage` (existing, from `./nav.js` — same import
  `hubTechnician.js` already uses), the wire shape of `GET /hub/admin`'s new
  `pipeline` object (Task 2): `{created, assigned, in_progress,
  ready_to_complete, completed, review}`.
- Produces: the finished pipeline row — no further tasks depend on this one.

This task has no automated test (no frontend harness). Step 4 is a manual
verification checklist instead of a pytest run.

- [ ] **Step 1: Add the pipeline row markup**

Read the current `backend/static/views/hubAdmin.js` first — it is a small
file (33 lines as of the prior slice) — then replace its full contents with:

```javascript
// View: the Admin+ hub's company-wide time summary and work order pipeline.
//
// Layer: views. Renders inside the Dashboard tab body, above the crew
// board mount point `hubTechnician.js` already draws. Consumes exactly the
// `GET /hub/admin` payload `userHub.js` fetches for techfm_oa+ viewers;
// makes no requests of its own.

import { escapeHtml } from "../format.js";
import { showPage } from "./nav.js";
import { openWorkOrdersFilteredByStatus } from "./workOrders.js";

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

// Order and labels match `backend/static/pages/work-orders.html`'s own
// status filter `<option>`s verbatim (Global Constraints) -- the tile's
// label and the page it opens must always agree.
const PIPELINE_STAGES = [
  ["created", "Created"],
  ["assigned", "Assigned"],
  ["in_progress", "In-Progress"],
  ["ready_to_complete", "Ready to Complete"],
  ["completed", "Completed"],
  ["review", "Review"],
];

function pipelineTileHtml(status, label, count) {
  // Ready to complete carries the attention flag (spec §5.4): it is the one
  // status where the work is done and the supervisor is the bottleneck.
  const flag =
    status === "ready_to_complete" && count > 0
      ? ` <span class="hub-attention-icon" aria-hidden="true">⚠</span>`
      : "";
  return `
    <button type="button" class="hub-tile hub-tile-pipeline-item" data-status="${escapeHtml(status)}">
      <p class="hub-tile-label">${escapeHtml(label)}${flag}</p>
      <p class="hub-tile-value">${escapeHtml(String(count))}</p>
    </button>`;
}

function pipelineHtml(pipeline) {
  const tiles = PIPELINE_STAGES.map(([status, label]) =>
    pipelineTileHtml(status, label, pipeline[status])
  ).join("");
  return `<div class="hub-tile-grid">${tiles}</div>`;
}

export function mountHubAdminSummary(container, payload) {
  container.innerHTML = `
    <div class="hub-tile-grid">
      ${tileHtml("Supervisor Time", formatHm(payload.supervisor_minutes_today))}
      ${tileHtml("Technician Time", formatHm(payload.technician_minutes_today))}
    </div>
    ${pipelineHtml(payload.pipeline)}`;

  // Bound once per container element, guarded by a dataset flag -- this
  // function re-runs on every live refresh (initial load, the
  // `labor.session.changed` socket event, the 60s safety timer) against the
  // *same* container node whenever the Dashboard tab hasn't been rebuilt in
  // between, so binding unconditionally here would stack up duplicate
  // listeners over a session. The container is only ever replaced wholesale
  // by `hubTechnician.js`'s `mountHubDashboard`, which drops the flag along
  // with the old node.
  if (!container.dataset.pipelineBound) {
    container.dataset.pipelineBound = "true";
    container.addEventListener("click", (event) => {
      const tile = event.target.closest("[data-status]");
      if (!tile) return;
      openWorkOrdersFilteredByStatus(tile.dataset.status);
      showPage("work-orders");
    });
  }
}
```

- [ ] **Step 2: Add the CSS**

In `backend/static/styles.css`, add after `.hub-tile-count` (after line
1816):

```css
/* The hub's first clickable tile (P4 pipeline row). A real <button> does
   not inherit the global `section { ... }` card look every other `.hub-tile`
   gets for free, so this reproduces it explicitly, plus a hover state. */
.hub-tile-pipeline-item {
    background-color: var(--panel-bg);
    backdrop-filter: blur(var(--glass-blur));
    -webkit-backdrop-filter: blur(var(--glass-blur));
    border: 1px solid var(--panel-border);
    color: var(--text-panel);
    border-radius: var(--radius-md);
    padding: var(--space-6);
    margin-bottom: 0;
    text-align: left;
    font: inherit;
    cursor: pointer;
}

.hub-tile-pipeline-item:hover {
    border-color: var(--color-primary);
}
```

- [ ] **Step 3: Run the backend test suite once more to confirm no regressions**

Run: `cd backend && python -m pytest -v`
Expected: PASS (this task touches no backend files, but confirms Tasks 1-2
are still green before manual frontend verification)

- [ ] **Step 4: Manual verification**

Start the app per the existing runbook (do not auto-run this — check with
the user first, per this repo's standing preference for manual validation).
Log in as a TechFM OA/Admin/Owner account and open the User Hub's Dashboard
tab:

- Confirm a new "Work Order Pipeline" row of six tiles appears below the
  Supervisor Time / Technician Time tiles, labeled Created / Assigned /
  In-Progress / Ready to Complete / Completed / Review, each showing a count.
- If the Ready to Complete count is greater than zero, confirm the ⚠ icon
  appears next to its label.
- Click a tile with a non-zero count (e.g. In-Progress). Confirm the page
  switches to Work Orders, the Status filter dropdown shows that status
  selected, every other filter is cleared, and the list shows only work
  orders in that status.
- Click a different tile (e.g. Completed). Confirm the filter switches
  cleanly to the new status with no stale rows from the previous filter.
- Confirm a Technician or Supervisor viewer's Dashboard is unaffected (no
  pipeline row, no `#hub-admin-mount` content at all — unchanged from the
  prior P4 slice).
- Leave the tab open and idle for over 60 seconds (or trigger a
  `labor.session.changed` event by starting/stopping a labor session
  elsewhere); confirm the pipeline counts refresh live and clicking a tile
  still works afterward (proves the click handler survived the re-render
  without double-firing or going silent).

- [ ] **Step 5: Commit**

```bash
git add backend/static/views/hubAdmin.js backend/static/styles.css
git commit -m "feat(user-hub): add the work order pipeline row to the admin hub"
```

---

## Plan Self-Review Notes

- **Spec coverage:** the pipeline row's six counts (§5.4 lines 615-620),
  its company-wide/unscoped nature, the Ready-to-complete attention flag
  (§5.4 line 639-640), and the "each count links to the Work Orders page
  pre-filtered" behavior (§5.4 line 638) are all covered — Task 1 for the
  counts, Task 4 Step 1 for the flag and the click wiring, Task 3 for the
  filter mechanism the click relies on. The pipeline funnel-vs-row framing
  ("a row of counts, not a funnel chart," §5.4 line 635-637) needed no task
  of its own — a `<button>` grid is already not a funnel chart.
- **Type consistency:** `AdminPipelineCounts`/`HubAdminPipeline` field names
  (`created`, `assigned`, `in_progress`, `ready_to_complete`, `completed`,
  `review`) are identical across the service dataclass (Task 1), the schema
  (Task 2), and the frontend's `payload.pipeline[status]` reads keyed by the
  same six strings (Task 4) — checked end to end.
- **Known wrinkle flagged inline:** the click handler's one-time-binding
  guard (Task 4 Step 1) is explained in its own code comment rather than
  left implicit, since `mountHubAdminSummary` genuinely is called repeatedly
  against the same container across live refreshes (established by the
  prior P4 slice's own live-service wiring) — a naive unconditional
  `addEventListener` here would silently stack duplicate handlers over a
  session, firing navigation N times per click by the Nth refresh.
- **Explicit non-goals restated from Global Constraints:** the "On the clock
  now" per-person list, Exceptions, Billing, and the Hub's own unscoped
  "Work Orders" tab (§5.4 Tab 3) are not touched by this plan — each is
  its own future slice.
