# User Hub - Admin Graphs Tab Implementation Plan

**Status:** Proposed after documentation and code review. No application code is
changed by this plan.

**Reviewed baseline:** `main` at `fea464d` on 2026-08-21.

**Goal:** Add a TechFM OA+ `Graphs` tab to the User Hub that gives a live,
company-wide view of work-order status by community and service type, plus a
time-series comparison of circulating work-order age and closed work-order cycle
time. Keep the experience useful to people with limited analytical training.

## Review findings

1. **The target is the User Hub, not the Users table.** The current hub is
   `backend/static/pages/user-hub.html`, orchestrated by
   `backend/static/views/userHub.js`. It already has Dashboard, Timesheets, and
   Work Orders tabs. The separate `saved-users` page is account management and
   should not receive analytics.
2. **Admin means the existing Admin-hub role tier.** The hub design sends
   TechFM OA, Admin, and Owner through the same rank-gated design. The Graphs tab
   should therefore be visible and callable at `techfm_oa+`, consistent with
   `GET /hub/admin`, rather than only for the literal `admin` role.
3. **Most source data already exists.** `work_orders` has `status`, `community`,
   `location`, `service_type`, `created_at`, `completed_at`, and `archived_at`.
   Closed is represented by `archived_at`, not a stored status. Seven live
   statuses exist: Created, Assigned, In-Progress, On-Hold, Ready to Complete,
   Completed, and Review.
4. **The current Admin dashboard is a useful precedent, not the graph API.**
   `GET /hub/admin` already returns a company-wide six-stage pipeline, a
   14-day completion sparkline, and `avg_days_to_complete`. It deliberately
   excludes On-Hold from the pipeline and measures `created_at -> completed_at`.
   The requested status pies must include On-Hold so each pie sums to all live
   work, and the requested close-out metric must use `archived_at`, so neither
   existing value should be relabeled or stretched to fit.
5. **Community is membership-based.** The Work Orders filters recognize five
   stable choices (Scholars, Centennial, Commons, Young Hall, Academics) from
   both structured community and raw location text. A work order can match more
   than one named community; Academics is the fallback when none of the named
   terms match. The graphs must reuse this vocabulary and behavior.
6. **The live transport is already suitable.** `work_order.status.changed` is
   an invalidation envelope; REST remains the source of truth. Status edits,
   archive, restore, and tracking transitions already emit it. CSV import and
   bulk legacy archive do not currently emit a matching membership invalidation
   and must be added for a genuinely live aggregate.
7. **Historical close data has a known limit.** Restore clears `archived_at`.
   The current schema cannot reconstruct a prior close/restore interval after
   that restore. The first release can accurately describe current live rows and
   currently archived rows, but it must not claim audit-grade historical
   closure data for restored work orders.
8. **The durable docs lag the code.** `docs/open-work.md` still calls User Hub P4
   "next," `docs/current-state.md` cites an 85-operation baseline, and
   `docs/endpoint-map.md` omits `GET /hub/admin`; the running OpenAPI schema has
   93 HTTP operations. Documentation synchronization is part of this plan.

## Decisions this request changes

- Amend User Hub decision D9 from three Admin tabs to four:
  **Dashboard - Timesheets - Work Orders - Graphs**. Lower roles keep their
  current tab visibility.
- Amend the hub/design-system chart rule to allow one narrow categorical-color
  exception: work-order status charts may reuse the exact seven colors already
  used by Work Order cards. Every slice also has a direct text legend containing
  status, count, and percentage; color is never the only encoding.
- Keep the Graphs tab a fixed, guided report. A general-purpose custom graph
  builder is explicitly out of scope.

## Product behavior

### Tab and loading

- Add `Graphs` after Work Orders in the User Hub tab strip.
- Show it only to TechFM OA, Admin, and Owner.
- Fetch graph data lazily on first activation, then refresh on each later
  activation.
- Keep the last successful charts visible during a background refresh. Show an
  inline retry on the first-load failure; do not blank usable charts when a live
  refresh fails.
- Display `Updated <time>` so users know how fresh a live snapshot is.

### Community status charts

- Render one donut-style pie per stable community, in the same order as the
  Work Orders community filter.
- Denominator: every circulating work order matching that community, where
  `archived_at IS NULL`.
- Slices: all seven live statuses, in lifecycle order, omitting zero-count
  slices from the drawing but retaining the stable legend order.
- Center label: total circulating work orders for that community.
- Legend row: `Status - count - percentage` with one-decimal percentages.
- A zero-total community renders `No circulating work orders`, not an empty or
  misleading 100% ring.
- Include a short note that a location mentioning multiple communities appears
  in each matching chart, so community totals should not be added together.

### Service-type status charts

- Normalize service types by trimming and grouping case-insensitively; render
  null/blank as `Unspecified` rather than dropping those work orders.
- Render one donut per normalized service type with the same seven-status order,
  colors, center total, and exact legend as community charts.
- Order service types by live total descending, then label ascending for stable
  ties.
- Show the first six cards initially and a plain `Show all N service types`
  control when more exist. This keeps the page readable while still making
  every service type available, as requested.

### Age versus close-out trend

- Render a two-series line chart titled `Work-order age and close-out time`.
- Default to 12 weekly buckets, Monday-Sunday in `America/Chicago`, including
  the current partial week. Offer only three presets: 12, 26, and 52 weeks.
  These are guided choices, not arbitrary graph construction.
- Series 1, `Average circulating age`: at each bucket end (or `now` for the
  current bucket), average the age of work orders that were circulating at
  that point: `snapshot_time - created_at`.
- Series 2, `Average time to close`: for work orders whose `archived_at` falls
  inside that bucket, average `archived_at - created_at`.
- A bucket with no sample returns `null` and draws a gap; it never reports zero
  days. Tooltips include the average and sample count (`n`).
- Place a compact accessible data table under the chart, collapsed visually but
  available to keyboard and screen-reader users.
- Label this metric distinctly from the existing `Avg time to complete`, which
  uses `completed_at` and remains on the Dashboard.

## Proposed API contract

Add a separate lazy endpoint rather than making every Dashboard load pay for
the graph payload:

`GET /hub/graphs?weeks=12` - `techfm_oa+`

`weeks` accepts exactly `12`, `26`, or `52`; invalid values return 422. The
response shape should be equivalent to:

```text
{
  generated_at,
  weeks,
  statuses: [{ key, label }],
  communities: [
    { key, label, total, counts: { created, assigned, in_progress,
                                  on_hold, ready_to_complete, completed,
                                  review } }
  ],
  service_types: [
    { key, label, total, counts: { ...all seven statuses... } }
  ],
  duration: {
    range: { start, end },
    buckets: [
      { start, end, partial,
        circulating_avg_age_days, circulating_count,
        closed_avg_days, closed_count }
    ]
  }
}
```

Return counts and denominators as the authoritative data. The view computes the
display percentage from those integers so the chart and legend cannot disagree.

## Architecture

### Backend

- Add pure helpers in `backend/app/domain/hub.py` or
  `backend/app/domain/work_orders.py` for weekly bucket boundaries, stable
  status ordering, community memberships, and service-type normalization.
  Keep SQLAlchemy out of domain code.
- Add graph payload dataclasses and aggregation in
  `backend/app/services/hub.py`. Use narrow projections rather than hydrating
  work-order relationships. The status distributions should require one scan of
  live work-order columns; the trend should use timestamp-only projections.
- Add Pydantic response models in `backend/app/schemas/hub.py`.
- Add `GET /hub/graphs` in `backend/app/routers/hub.py` with one declarative
  `require_min_role(ROLE_TECHFM_OA)` gate.
- Do not run the labor-session sweep for this endpoint. None of its values
  depend on running-session freshness.
- Measure the query on representative data before adding indexes. The current
  model indexes status but not `archived_at`, `community`, `service_type`, or
  completion/closure timestamps; add a migration only when `EXPLAIN` or route
  timing shows it is warranted, consistent with the repo's measured-scale
  policy.

### Realtime

- Reuse `work_order.status.changed`; do not put chart data on the WebSocket.
- After successful CSV import and bulk legacy archive, emit one null-id status
  invalidation because list/chart membership may have changed.
- On the active Graphs tab, any status invalidation or reconnect triggers one
  background `GET /hub/graphs` refresh.
- Extend the User Hub's existing 60-second visible-page safety refresh to the
  active Graphs tab rather than creating a second timer. Stop it when the page
  or browser tab is hidden.
- Extend the exact emitter-set tests and update
  `docs/notification-events.md` in the same implementation commit.

### Frontend and chart rendering

- Add `backend/static/views/hubGraphs.js` to own rendering, chart lifecycle,
  preset changes, retry state, and teardown.
- Extend `backend/static/views/userHub.js` with the role-gated tab, lazy request,
  stale-response request id, live subscription, and refresh lifecycle.
- Add `apiGetHubGraphs({ weeks })` to `backend/static/api.js`.
- Add the tab button/panel to `backend/static/pages/user-hub.html` and responsive
  card-grid/chart styles to `backend/static/styles.css`.
- Use a locally vendored, pinned chart renderer with its license committed under
  `backend/static/vendor/`, following the existing ZXing pattern. Load it before
  `main.js`; do not add a CDN or relax CSP. Verify the chosen release before
  vendoring it.
- Promote the seven existing Work Order card accent colors to named CSS custom
  properties and have both cards and charts consume those properties. Update
  `docs/design-system.md` to document the exception.
- Destroy chart instances before repainting to prevent leaked canvases/listeners
  across live refreshes and range changes.
- Provide an adjacent semantic legend/table for every canvas. Tooltips are an
  enhancement, not the only path to exact values; touch and keyboard users must
  receive the same information.

## Implementation tasks

### Task 1 - Reconcile the feature contract

**Modify:**

- `docs/superpowers/specs/2026-08-20-user-hub-design.md`
- `docs/design-system.md`

Record the four-tab Admin decision, TechFM OA+ visibility, live/closed metric
definitions, categorical status-color exception, restored-work-order limitation,
and custom-builder exclusion before writing application code.

### Task 2 - Add and test pure aggregation rules

**Modify:**

- `backend/app/domain/hub.py`
- `backend/app/domain/work_orders.py` only if community/status vocabulary belongs
  there rather than in the hub module

**Test:**

- `backend/tests/test_hub_flags.py` or a focused new
  `backend/tests/test_hub_graphs_domain.py`
- `backend/tests/test_work_orders_domain.py` for community-filter parity when
  shared vocabulary changes

Cover all seven status keys, multi-community membership, Commons aliases,
Academics fallback, blank service type, case/whitespace normalization, Central
weekly boundaries, current partial week, and DST boundaries.

### Task 3 - Add the graph service and response contract

**Modify:**

- `backend/app/services/hub.py`
- `backend/app/schemas/hub.py`
- `backend/app/routers/hub.py`

**Test:**

- `backend/tests/test_hub_service.py`
- `backend/tests/test_hub_router.py`
- `backend/tests/test_route_role_gates.py`

Use before/after deltas because the repository's DB fixture shares the local
PostgreSQL database. Prove company-wide scope, archived exclusion from pies,
On-Hold inclusion, every community/service-type bucket, close-out semantics,
null empty samples, stable order, range validation, serialization, and the
TechFM OA gate.

### Task 4 - Complete live invalidation coverage

**Modify:**

- `backend/app/routers/work_orders.py`
- `backend/app/domain/realtime.py` comments if the membership description is
  still restore-specific
- `docs/notification-events.md`

**Test:**

- `backend/tests/test_realtime_emit.py`
- relevant import/archive route tests

Prove import and bulk legacy archive each emit exactly one null-id
`work_order.status.changed` envelope after the durable write, and that failure
to hand off the best-effort envelope cannot fail the write.

### Task 5 - Build the role-gated Graphs tab

**Modify:**

- `backend/static/pages/user-hub.html`
- `backend/static/views/userHub.js`
- `backend/static/views/hubGraphs.js` (new)
- `backend/static/api.js`
- `backend/static/styles.css`
- `backend/static/shell-tail.html` if a vendored renderer is loaded globally
- `backend/static/vendor/<pinned-chart-file>` and its license

Implement lazy loading, request-order guards, range presets, chart destruction,
responsive small multiples, exact legends, accessible tables, empty/error
states, live invalidation, reconnect recovery, and the one shared safety timer.
Do not expose the tab or start its request below TechFM OA.

### Task 6 - Verify and document the shipped state

**Automated checks:**

- Focused domain/service/router/realtime tests above.
- `node --check` for every changed non-vendor JavaScript file.
- Full backend pytest suite when the focused checks pass.
- `git diff --check`.
- Recount OpenAPI operations and update the documented baseline.

**Manual checks:**

- TechFM OA, Admin, and Owner see Graphs; Supervisor and Technician do not.
- Two-browser test: status edit, archive, restore, import, and bulk archive in
  one browser refresh the active Graphs tab in the other.
- Changing weeks cannot let a slower old response overwrite the newer choice.
- Phone-width layout, touch tooltips, long service-type labels, six-plus service
  types, all-zero community, and one-work-order 100% pie.
- Keyboard tab order, screen-reader names, exact-value legends/tables, and
  color-not-alone verification.
- Blocked WebSocket still catches up through tab activation and the 60-second
  REST safety refresh.

**Documentation:**

- Update `docs/current-state.md` with the final route, schema, UI, realtime,
  test, dependency, and operation-count facts.
- Update `docs/endpoint-map.md` with a new Hub row and Database-to-View flow.
- Update `docs/open-work.md` so P4 is no longer described as next and record
  Graphs as shipped only after it is shipped.
- Sync the final repository docs into
  `4. Notes/Repository-Docs/inventory-app-git` through the Obsidian workflow.

## Acceptance criteria

- Every stable community and every normalized service type has a status donut
  based on all and only live work orders.
- Each nonempty pie's displayed counts equal its total and its displayed
  percentages round from the same counts; all seven statuses are supported.
- The duration chart distinguishes live age from time to Closed and never calls
  the latter `time to complete`.
- Graphs update from REST after relevant live invalidations without receiving
  row data over the socket.
- The Graphs endpoint and tab are unavailable below TechFM OA.
- Exact values remain readable without color, hover, or a mouse.
- No CDN, CSP relaxation, scheduler, analytical database, or custom query
  language is introduced.

## Recommended follow-on graphs

Ordered by usefulness for this app and by how little interpretation they need:

1. **Created versus Closed per week, with net backlog change.** This is the best
   next graph: it answers whether work is arriving faster than it is being
   cleared and uses the same timestamps and weekly buckets as the duration
   chart.
2. **Live aging buckets by community** (`0-2`, `3-7`, `8-14`, `15+` days). An
   average can hide a few very old jobs; simple stacked counts show the backlog
   that needs attention. Reuse community membership and exact labels.
3. **Ready-to-Complete and Review queue age.** Two compact aging distributions
   reveal supervisor/admin bottlenecks more directly than a total queue count.
4. **Status dwell time by stage.** Valuable, but defer until the app records a
   durable lifecycle-event history; the current row stores only current status
   and cannot reconstruct time spent in each stage.

Do not add an SLA-compliance graph yet. `schedule_date` is permissive raw vendor
text and the model has no SLA target/deadline, so such a chart would invent a
business rule the data does not contain.

## Custom graph tool recommendation

Do not build a general custom graph tool in this phase. It would require a query
grammar, field-level authorization, validation, saved definitions, empty/invalid
state handling, and user training, while still allowing misleading combinations.
For this audience, the safer future option is a **guided question picker** with
three or four vetted questions (status mix, intake versus closure, aging,
bottleneck), fixed dimensions, and the same 12/26/52-week presets. That captures
most of the value without turning users into report designers.

## Explicit non-goals

- No generic drag-and-drop/custom query builder.
- No arbitrary SQL, formulas, or user-authored calculated fields.
- No nightly snapshot job, scheduler, warehouse, or read replica.
- No claim that restored work orders have complete historical close records.
- No changes to Work Order lifecycle rules, billing rules, or lower-role data
  visibility.
