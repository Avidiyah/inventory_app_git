# Work Order Daily Report — design

Status: approved for planning · 2026-08-30 (expanded the same day after
spec review; review-settled points are marked *review*)

An Admin-only daily digest on the User Hub: what closed, what is on its way
to closing, and what arrived. Rendered on the page and downloadable as one
CSV, both built from a single payload so they can never disagree.

---

## 1. Purpose

An Admin opens the hub each morning and needs three answers without
building a filter by hand:

- **Closed** — how much work finished, today and week-to-date.
- **Closing** — what is sitting in the last stretch of the pipeline.
- **New** — what came in, today and week-to-date.

Today the only way to get any of this is the Work Orders page's own filters
plus `GET /work-orders/export`, which is viewer-scoped, TechFM OA+, and has
no notion of a time window. This report is that missing surface.

---

## 2. Decisions

| # | Decision |
|---|---|
| R1 | **Two nested windows: Today and This Week.** Both are Central calendar periods. Today is one Central day; This Week is the Monday–Sunday week containing today, evaluated **week-to-date** (Monday 00:00 Central through `now`). This Week *includes* Today — on Monday both read the same number; on Tuesday the week is Monday+Tuesday. |
| R2 | **Closed means `archived_at`.** Closed is represented by `archived_at`, per `WorkOrder`'s own model contract. `completed_at` is not used for this section; it belongs to the existing dashboard's time-to-complete metric. |
| R3 | **Closing is a snapshot, not an event.** The section lists every **live** work order currently in `ready_to_complete`, `completed`, or `review`. It deliberately does not claim "entered a closing status since yesterday" — see §3. |
| R4 | **New means `created_at`.** Same two windows as Closed. |
| R5 | **Admin+ only, company-wide.** Route floor is `ROLE_ADMIN`; rows are every work order in the system, not the viewer's routed set. |
| R6 | **A new lazy "Report" tab** on the User Hub, hidden for every role below Admin, fetched on first open — the pattern Graphs and Timesheets already use. |
| R7 | **One CSV, `SECTION`-prefixed.** A single file whose rows are the existing 26-column `EXPORT_HEADERS` row preceded by a `SECTION` cell. |
| R8 | **Endpoint pair, new service module.** `GET /hub/report` (JSON) and `GET /hub/report/export` (CSV), mirroring the timesheets pair. Logic lives in a new `services/work_order_report.py`. |
| R9 | **The CSV is a pure function of the JSON payload.** Both endpoints compose the same payload; the exporter only renders it. Screen and file cannot drift. |
| R10 | *review* **Closes no person made here are included and marked.** A close by the NetFacilities reconcile sweep, or an archived `legacy` row, stays in `closed_*` and in the counts, with a badge on the page and a sub-count in the header. The CSV rows and `SECTION` keys are unchanged. Not excluded, not a separate section: a close is a close, but the Admin must be able to tell 6 finished jobs from 14 tickets NetFacilities closed. |
| R11 | *review* **A closed row's click lands on the exact-number search.** The Work Orders page hides archived rows, so a closed row routes there with its number in the search box, which triggers the shipped "Work Order has been closed. Restore?" prompt. A live row opens its card page. |
| R12 | *review* **Operational columns on the page.** Number · Status · Community / Location · Service type · Supervisor · Technicians · the section's timestamp. Money stays in the CSV. |

### Decisions deliberately *not* taken

- **No persisted "last report" watermark.** "Since the previous report" was
  considered and rejected in favour of R1's calendar windows: a watermark
  needs a new table, and it breaks the moment a report is regenerated or a
  second Admin runs one. Calendar windows are stateless and reproducible.
- **No scheduling, email, or push delivery.** This app has no scheduler and
  no mailer — `lifespan.py` starts only realtime dispatch and the
  NetFacilities coordinator. "Daily" describes the windows and the habit,
  not an automated send. Auto-delivery is a separate project (§10).
- **No new status-transition timestamps.** See §3.

---

## 3. The constraint that shapes this design

**There is no status-history table.** A work order carries exactly four
timestamps: `created_at`, `updated_at`, `completed_at`, `archived_at`.
Three consequences, all of which the design accepts rather than works
around:

1. **Closing cannot be a delta.** Nothing records when a work order entered
   `ready_to_complete` or `review`. Asking "what moved into closing since
   yesterday" is unanswerable from the current schema, so R3 makes the
   section an honest snapshot of current state. The count answers "how big
   is the closing queue right now", which is the operationally useful
   question anyway.

2. **A restore erases a close.** `restore_work_order` clears `archived_at`,
   so a work order closed Monday and restored Wednesday disappears from
   Monday's numbers retroactively. `graphs_hub` already carries this exact
   caveat ("does not claim audit-grade historical close data") and this
   report inherits it. **The report is a live view, not an archival record.**
   Two runs of the same window on different days may legitimately differ.
   This is stated on the page, not buried here. The reconcile sweep's
   reopen-on-reappearance is one more way a close can vanish.

3. **`created_at` is import time, not vendor time.** Work orders are
   import-only. "New today" means "first imported into this system today,"
   which with the NetFacilities capture chain is close to but not identical
   with when the vendor raised the ticket. Acceptable for a daily digest;
   noted so nobody later reads the number as vendor intake.

If any of these become a real problem in use, the fix is a
`work_order_status_events` table — logged as a follow-on in §10, not built
here.

---

## 4. Sections

Five row sets, from three concepts × the two nested windows (Closing has no
window — it is current state).

| Section key | Meaning | Predicate |
|---|---|---|
| `closed_today` | Closed during today's Central day | `archived_at` within `day_bounds(today)` |
| `closed_week` | Closed Monday 00:00 Central → now | `archived_at` within `[week_start_at, now]` |
| `closing` | Live and in a closing status | `archived_at IS NULL AND status IN (ready_to_complete, completed, review)` |
| `new_today` | Created during today's Central day | `created_at` within `day_bounds(today)` |
| `new_week` | Created Monday 00:00 Central → now | `created_at` within `[week_start_at, now]` |

**Nesting (R1).** `closed_today ⊆ closed_week` and `new_today ⊆ new_week`.
A work order closed this morning appears in **both** sections, and therefore
in the CSV **twice**, under two different `SECTION` values. This is
intended: the file is a faithful serialisation of what the page shows, and
`SECTION` is what a spreadsheet filters on. Anyone wanting a deduplicated
week takes `SECTION = closed_week` alone.

**Archived rows in Closing.** None — `closing` filters `archived_at IS NULL`.
A closed work order is in `closed_*`, never in `closing`.

**Overlap between Closed and New.** A work order created and closed on the
same day appears in both `new_today` and `closed_today`. Correct, and worth
seeing.

**Who closed it (R10).** Every row carries two booleans the page turns into
badges: `auto_closed` (`auto_closed_batch_id IS NOT NULL`, the reconcile
sweep's provenance column) and `legacy` (`WorkOrder.legacy`). Each
`closed_*` section also carries `auto_closed_count`, computed server-side
over the same predicate. Ordering dependency: the column comes from the
reconcile migration (`2026-08-30-netfacilities-reconcile-design.md`); if
this report is built first, `auto_closed` is a constant `false` and
`auto_closed_count` is `0` until that migration lands. The contract does
not change either way.

**Sort order** (a call made on review, not a user decision — override
freely): `closed_*` by `archived_at` descending, which floats today's rows
above the rest of the week on its own; `new_*` by `created_at` descending;
`closing` by status in lifecycle order (`ready_to_complete`, `completed`,
`review`) then `created_at` ascending, so the longest-waiting row in each
stage is first. The CSV writes rows in the same order.

### Window arithmetic

All of it comes from `domain/labor_day.py`, already used by timesheets:

```
today       = labor_day.central_date_of(now)
day_start, day_end   = labor_day.day_bounds(today)
week_start, _        = labor_day.week_bounds_containing(today)
week_start_at, _     = labor_day.day_bounds(week_start)
```

Today's upper bound is `day_end` rather than `now`; the week's is `now`.
The difference is immaterial (nothing is stamped in the future) and using
`day_end` keeps the day a clean half-open Central day. DST is `zoneinfo`'s
problem — `day_bounds` already handles 23- and 25-hour days.

---

## 5. API

### `GET /hub/report`

Gate: `require_min_role(roles.ROLE_ADMIN)`. No query parameters — the
windows are derived from server time, which is the whole point of a daily
report. Returns `HubReportResponse`.

```
{
  "generated_at": "2026-08-30T14:02:11Z",
  "day": "2026-08-30",
  "week": { "start": "2026-08-24", "end": "2026-08-30" },
  "sections": {
    "closed_today": { "count": 20, "auto_closed_count": 14, "rows": [...] },
    "closed_week":  { "count": 31, "auto_closed_count": 14, "rows": [...] },
    "closing":      { "count": 9,
                      "by_status": { "ready_to_complete": 4, "completed": 3, "review": 2 },
                      "truncated": false, "rows": [...] },
    "new_today":    { "count": 4,  "rows": [...] },
    "new_week":     { "count": 21, "rows": [...] }
  }
}
```

Three section models, not one with optional fields: `HubReportClosedSection`
(`count`, `auto_closed_count`, `rows`), `HubReportClosingSection` (`count`,
`by_status`, `truncated`, `rows`), `HubReportNewSection` (`count`, `rows`).
`by_status` is a separate count query, not a tally over `rows`, so the
sub-counts stay right when `closing` is truncated (§7).

`week.end` is the Sunday of the current week (the calendar week's end, for
labelling); the *data* stops at `generated_at`. The page renders "Week of
Aug 24 – Aug 30" from this pair and week-to-date numbers from the counts.

**Row shape** (`HubReportRow`). The report's own display projection, not
the 26-column CSV row:

| Field | Note |
|---|---|
| `work_order_id`, `number` | `number` is the identity users read |
| `status` | the row's `status` column as it stands. Archiving does not rewrite it, so a closed row still reads `completed` or `review` — the badge must not be mistaken for "still open" |
| `community`, `location`, `building_number`, `unit_number` | placement |
| `service_type`, `priority` | |
| `supervisor_name` | `null` when unrouted |
| `technician_names` | list from `work_order.technicians`; may be empty |
| `materials_total`, `labor_minutes`, `labor_total`, `total` | reuses `wo.effective_billable` / `wo.labor_charge`, so the money matches the export and Admin Review exactly |
| `created_at`, `completed_at`, `archived_at` | UTC instants; the client formats in Central |
| `auto_closed`, `legacy` | R10 badges |

Rendering money and minutes server-side from the same domain helpers is the
existing rule (`services/work_orders.py:1331` and the export docstring) —
the report must not become a fourth place that computes a total.

### `GET /hub/report/export`

Same gate, same derivation, no parameters. Returns `text/csv; charset=utf-8`
with `Content-Disposition: attachment`.

**Filename:** `wo-report_YYYY-MM-DD.csv`, where the date is the Central
report day. Named for the period it covers — the timesheet convention
(`docs/.../user-hub-design.md` §D14) — not the export moment, which is the
work-order export's convention. This report *is* the day, so the day is
the name.

**Body:** a header row of `("SECTION",) + wo.EXPORT_HEADERS`, then, for each
section in the fixed order `closed_today, closed_week, closing, new_today,
new_week`, one row per work order in the section's sort order: the section
key followed by `services.work_orders.export_row(work_order)` verbatim.

Reusing `_export_row` (promoted to a public `export_row`, since it now has
a second caller) is load-bearing: it keeps report rows byte-identical to
the full export's, which means the file still round-trips through
`POST /work-orders/import` — the importer reads its seven headers by name
and ignores every column after them, including a column *before* them.
`\r\n` line endings and the `csv` module's quoting, as everywhere else.
The R10 badges are page-only: adding a column to `export_row` would change
the operational export's shape for every consumer.

**Timestamp seam — document it.** `export_row` writes UTC via
`_csv_timestamp`, but the sections are Central calendar periods. A work
order closed at 8:00 PM Central on the 30th sits in `closed_today` for the
30th while its `ARCHIVED AT` cell reads `2026-08-31 01:00`. This is not a
bug and must not be "fixed" by rewriting the export's timestamp format —
that format is shared with the operational export and its consumers. The
CSV carries the covered day in its filename; the page carries it in the
heading.

---

## 6. Auth

`ROLE_ADMIN` is a floor no other route in this app uses, on purpose:
`tests/test_route_role_gates.py::test_no_route_gate_is_left_at_the_admin_floor`
asserts the set of Admin-floored routes is empty, precisely so a route
written at that floor out of habit is caught. That test anticipates this
case in its own comment:

> If a genuinely Admin-only route is ever added, add its endpoint name to
> the expected set here, deliberately and with a reason.

So the test changes from `assert offenders == set()` to an expected set of
`{"get_hub_report", "export_hub_report"}` with a comment naming this spec.

**Consequence, accepted deliberately:** TechFM OA does **not** see this
report, despite holding the rest of the admin toolkit — the admin hub
tiles, the Graphs tab, and the work-order CSV export. This is the one place
the TechFM OA / Admin line is drawn at Admin. If that proves wrong in use,
lowering the floor to `techfm_oa` is a one-line change plus removing the
test exemption; nothing else in the design depends on it.

---

## 7. Row ceilings

Four of the five sections are bounded by construction — a week of work
orders. `closing` is not: it is every live work order in three statuses,
which grows with any pipeline backlog.

`closing` therefore passes through `services._list_cap` at `MAX_LIST_ROWS`,
the standard ceiling, and its section carries `truncated: true` when the
ceiling bites (the cap also emits `event=list.truncated`, which is the
signal that this section needs real pagination). The page shows a plain
notice when truncated; the CSV, being a render of the same payload, is
truncated identically. **The two must never diverge**, which is why the cap
lives in the payload builder and not in either renderer. `count` and
`by_status` are always the true totals, cap or no cap.

The time-windowed sections take no cap. This mirrors the work-order
export's considered exemption — a report that silently omits closures while
looking complete is a record-keeping problem, not a performance one — and
here the window itself is the bound.

---

## 8. Files

| File | Change |
|---|---|
| `backend/app/services/work_order_report.py` | **New.** Payload dataclasses, `daily_report(db, *, now)`, `report_csv(payload)`. The whole feature's logic. |
| `backend/app/services/work_orders.py` | Promote `_export_row` → `export_row` (public); no behaviour change. |
| `backend/app/schemas/hub.py` | Add `HubReportRow`, the three section models, `HubReportWeek`, `HubReportSections`, `HubReportResponse`. |
| `backend/app/routers/hub.py` | Add the two handlers. Thin, like the rest of the file. |
| `backend/static/api.js` | Add `apiGetHubReport()`; the CSV is a plain link/`window.location`, as the timesheet export is. |
| `backend/static/pages/user-hub.html` | Fifth tab button + panel (`hub-tab-report`, `hub-tabpanel-report`), after Graphs, `hidden` by default. |
| `backend/static/views/userHub.js` | `viewerIsAdmin()` (`roleAtLeast(role, "admin")`); reveal the tab; lazy-fetch on first open; skeleton while loading; reset the cached payload alongside the admin state in `loadUserHub`, and fall back to the dashboard if a non-Admin's `activeTab` is `report`. |
| `backend/static/views/hubReport.js` | **New.** Renders the five sections. |
| `backend/static/views/workOrders.js` | **New export** `openWorkOrdersByNumberSearch(number)` (R11, §9). |
| `backend/static/styles.css` (or the hub partial) | Section/table styles; no inline `style=` attributes — CSP drops them. |
| `docs/endpoint-map.md`, `docs/current-state.md` | Document the two routes and the report. |

New service module rather than growing `services/hub.py` (1306 lines) or
`services/work_orders.py` (2973) — both already far past the 500-line rule
in `CLAUDE.md`, and neither is the right home for a surface that reads from
work orders but answers to the hub.

---

## 9. UI

A single lazy tab body, `hubReport.js`, mounted into `#hub-tabpanel-report`.

```
Daily Report                          Thu, Aug 30 2026   [ Download CSV ]
Week of Aug 24 – Aug 30 · week to date

┌ Closed ─────────────────────────────────────────────────────────────┐
│   Today  20 (14 in NetFacilities)    This week  31 (14 in NetFacilities)
│   [table of closed_week rows, today's marked]                       │
└─────────────────────────────────────────────────────────────────────┘
┌ Closing ────────────────────────────────────────────────────────────┐
│   In the pipeline  9      ready to complete 4 · completed 3 · review 2│
│   [table of closing rows]                                           │
└─────────────────────────────────────────────────────────────────────┘
┌ New ────────────────────────────────────────────────────────────────┐
│   Today  4            This week  21                                 │
│   [table of new_week rows, today's marked]                          │
└─────────────────────────────────────────────────────────────────────┘
```

**Nested windows render as one table, not two.** Closed and New each show
the week's rows with today's rows marked (a "Today" badge; the server's
sort already puts them first), rather than repeating six rows in a second
table. The two counts sit above as a total and its subset — the same
"total plus subsets, not disjoint buckets" idiom `HubCounts` already
establishes. The CSV still writes both sections, because a spreadsheet
filters on a column where a page uses a badge.

**Header sub-counts (R10).** The parenthetical `(14 in NetFacilities)`
appears after a Closed count only when its `auto_closed_count` is
non-zero. Closing's `ready to complete 4 · completed 3 · review 2` comes
from `by_status`, never from counting rows.

**Columns (R12).** Number · Status · Community / Location · Service type ·
Supervisor · Technicians · timestamp. The timestamp column is `Closed`
(`archived_at`) in the Closed section and `Created` (`created_at`) in the
Closing and New sections — for Closing it reads as the row's age, which is
what an Admin looking at a queue wants. Central time, formatted by the
client. Location composes `community`, `building_number`, `unit_number`,
`location` the way the Work Orders card already does. Tables sit in the
existing `.hub-timesheet-table-wrap` so a narrow screen scrolls the table,
not the page.

**Badges.** Status follows the existing badge-only status-accent rule from
the design system; red stays the primary brand colour and is not used to
mean "bad". Additional badges, all neutral: `Today` (row is in the
`*_today` subset), `Closed in NetFacilities` (`auto_closed`), `Legacy`
(`legacy`).

**Row click (R11).** Every row is a real `<button>` inside its first cell
(number), so it is keyboard-reachable; no nested buttons. The handler
branches on `archived_at`:

- **Live row** (`archived_at === null`) — Closing rows, and New rows still
  open: `focusWorkOrderNumber(number)` then `showPage("work-orders")`,
  which opens the work order's card page by number.
- **Closed row** — `openWorkOrdersByNumberSearch(number)` then
  `showPage("work-orders")`. The new export in `workOrders.js` resets the
  filter controls, puts the number in the search box, and arms a one-shot
  `pendingArchivedCheck` that the next `loadWorkOrders` (the one
  `showPage` triggers) consumes as `checkArchivedSearch: true` — the same
  one-shot idiom `pendingSoloNumber` already uses. That runs the shipped
  `offerRestoreForExactArchivedSearch`, so the Admin lands on the "Work
  Order has been closed. Restore?" prompt. Choosing *Close* leaves them on
  the empty search with the number filled in; *Clear filters* is one click
  away. No new UI.

**Empty states** are per-section and plainly worded ("Nothing closed yet
today."), not an empty table.

**The live-view caveat (§3.2)** appears once, as a footnote under the
Closed section: restoring a closed work order — by hand, by the auto-close
undo, or by a NetFacilities reappearance — removes it from these numbers.

**Refresh.** Fetched on first open and re-fetched on tab re-entry, matching
Graphs. No polling — a daily report does not need a live socket, and
`generated_at` is rendered so the viewer knows how stale it is.

---

## 10. Out of scope

Named so they are decisions, not omissions:

- **Scheduled/emailed/pushed delivery.** Needs a scheduler and a transport
  this app does not have. Revisit only if reading the tab each morning
  proves insufficient.
- **`work_order_status_events`.** The fix for §3.1 and §3.2 both. Log in
  `docs/open-work.md` as the upgrade path for turning Closing into a real
  delta and Closed into an audit-grade history.
- **Export audit logging.** `docs/open-work.md` (DEC, 2026-08-23) commits
  every CSV/report export to record actor, type, row count, and timestamp
  into a log sink that is not yet built. This report's export is a member of
  that set and must be wired in when the sink lands; it does not block this
  work. Add it to the sink's checklist rather than inventing a private log
  here.
- **Filters** (supervisor, community, service type). The report is
  deliberately parameterless. If narrowing is wanted, the Work Orders page's
  export already does it.
- **Date navigation** (previous days/weeks). The windows are always
  current. Historical navigation would immediately hit §3.2's restore
  problem and should wait for the events table.
- **A `SECTION`-style column for the R10 badges in the CSV.** `export_row`
  is shared with the operational export; the badges stay on the page.

---

## 11. Testing

**Domain/service (no HTTP), `tests/test_work_order_report.py`:**

- Window derivation with a frozen `now`: Monday shows equal Today and Week
  counts; Tuesday's week covers Monday+Tuesday; Sunday's week is the full
  Monday–Sunday. Explicitly pins the user's own example (6 closed Monday,
  6 of 12 on Tuesday).
- A DST spring-forward and fall-back week produce correct bounds.
- A work order closed at 23:30 Central lands in that Central day, not the
  next UTC one.
- Nesting: a row closed today appears in both `closed_today` and
  `closed_week`.
- `closing` includes exactly the three statuses, excludes archived rows,
  and excludes live rows in earlier statuses.
- Created-and-closed-same-day appears in both `new_today` and
  `closed_today`.
- `closing` truncation sets `truncated`, caps rows at `MAX_LIST_ROWS`, and
  leaves `count` and `by_status` at the true totals.
- Sort: `closed_*` newest close first; `closing` in lifecycle order then
  oldest first.
- R10: a row with `auto_closed_batch_id` set reports `auto_closed = true`
  and is counted in `auto_closed_count`; a `legacy` archived row reports
  `legacy = true`; a hand-archived row reports both `false`.
- Money and minutes match `export_row`'s values for the same work order —
  the guard against a fourth totals implementation.

**CSV, same file:**

- Header is `("SECTION",) + EXPORT_HEADERS`; sections appear in the fixed
  order and rows in each section's sort order.
- A row's 26 cells are identical to `export_row`'s output for that work
  order (the round-trip guarantee).
- The emitted CSV, with its `SECTION` column present, still parses through
  `parse_import_row` and yields the right `number` — pinning that a leading
  extra column does not break re-import.
- `\r\n` endings; a row whose `NOTES` carry embedded commas and newlines
  quotes correctly.
- Filename is `wo-report_<central-date>.csv`.

**Routes, `tests/test_route_role_gates.py`:**

- Both handlers gate at `ROLE_ADMIN`; the expected-offenders set is updated
  with a comment pointing at this spec.
- A `techfm_oa` caller gets 403 from both — the explicit pin for §6's
  accepted consequence.

**HTTP, via `TestClient`** (not direct handler calls — `int`-`Literal`
query params are not involved here, but the suite's convention holds):
happy path shape including the three section models, the CSV's
content-type and disposition header.

**Frontend:** manual validation on the running app — the JS has no test
harness. Check both click branches of R11 and the header parenthetical.

---

## 12. Build order

1. `services/work_order_report.py` + its tests — the whole payload,
   provable without HTTP or UI.
2. `export_row` promotion + the CSV renderer + round-trip tests.
3. Schemas + the two routes + the role-gate test change.
4. `openWorkOrdersByNumberSearch`, the tab shell, `hubReport.js`, styles.
5. Docs (`endpoint-map.md`, `current-state.md`, `open-work.md` follow-ons).

Steps 1–3 are shippable and verifiable with no UI at all.
