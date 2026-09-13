# Weekly Closed Work Order Report — frozen weeks

Status: designed 2026-09-13, decisions settled in chat ·
**supersedes** `2026-08-30-work-order-daily-report-design.md`,
`2026-08-30-hub-report-xlsx-export-design.md`, and
`2026-08-30-hub-report-xlsx-redesign-design.md` in full. Decisions here
are **W-numbers**.

The Admin Report tab and `GET /hub/report/export` stop being a daily
digest and become a **weekly record of closed work orders**: any Monday
to Sunday week, selectable at any time; completed weeks frozen on first
request and served from the stored copy thereafter; one workbook of
six-column lists, one tab per service type, community blocks inside.

---

## 1. Purpose

Three requirements, one feature.

1. **Any week, any time.** Today the report is week-to-date up to the
   download instant, with no way to ask for a past week.
2. **A frozen record.** Every Monday the previous week is complete. Its
   numbers must not drift afterwards. Today a restore erases a close
   retroactively because there is no status history.
3. **Trimmed content.** The reader needs six columns per closed work
   order, split by service type and community. The KPI strip, pies,
   community chart sheets, Work Orders sheet, and re-importable Data
   sheet are noise for this reader and are deleted.

---

## 2. Decisions

| # | Decision |
|---|---|
| W1 | **A week is Monday 00:00 Central through the next Monday 00:00 Central, half-open** — 11:59:59 PM Sunday inclusive. `labor_day.week_bounds_containing` already names the Monday; `day_bounds` converts both ends to UTC. |
| W2 | **A week is `in_progress` until its end instant and `completed` after.** No 6 AM grace: a request at 00:00:01 Monday sees last week completed. The current week is computed live on every request and never stored. |
| W3 | **Population: work orders with `archived_at` inside the window.** Nothing else — no open backlog, no intake. Closed is `archived_at`, the app's only close marker. |
| W4 | **Frozen record = the JSON response.** A completed week is stored as the serialized `HubReportResponse`, so the stored bytes *are* the API payload, and the workbook renders from the same object the screen does. Storing the workbook bytes instead would pin past weeks to today's styling. |
| W5 | **Lazy freeze.** A completed week that is not stored is computed, inserted with `ON CONFLICT DO NOTHING`, re-read, and served. No scheduler: the Render web service sleeps when idle, so an in-process timer cannot be trusted. A cron ping is a later addition if drift is ever observed; it needs no design change. |
| W6 | **Weeks before launch follow W5.** They freeze on first request from current state. `frozen_at` is printed on screen and in the workbook, so a late freeze is visible rather than hidden. No back-fill. |
| W7 | **`week` query parameter on both routes**, `YYYY-MM-DD`, must be a Monday and not after the current week's Monday; otherwise 422. Absent means the current week. The UI only ever sends Mondays; the rule is an API contract, not a convenience. |
| W8 | **One tab per service type, alphabetical by label.** Tabs are `normalize_service_type` labels (blank → `Unspecified`). Alphabetical rather than largest-first so a weekly reader finds the same tab in the same place every week. |
| W9 | **Community blocks inside a tab, fixed `ALL_COMMUNITY_FILTERS` order, primary community only.** A row lands under `community_memberships(...)[0]`, so a work order appears exactly once per workbook. This is the E14 rule for figures that must sum, applied to a list. |
| W10 | **Six columns, raw vendor text.** `WORK ORDER`, `ASSIGNED TO` (`vendor_assignee`), `LOCATION`, `SERVICE TYPE` (raw), `SCHEDULE DATE` (raw string), `PRIORITY` (raw). No normalisation, no timestamps, no money. Rows sort by work-order number within a block. |
| W11 | **The screen mirrors the file.** Same payload, same grouping. The Closing and New sections are deleted from the page along with the pies from the file. One payload, two renderers. |
| W12 | **Admin floor unchanged.** Both routes stay the app's only Admin-floored routes; `test_route_role_gates.py` keeps its exemption verbatim. |
| W13 | **Schema-versioned records, no re-freeze.** The row carries `schema_version = 1`. A future shape change must keep reading version 1; it never rewrites stored weeks. There is no admin "re-freeze" action — a frozen week is the record. |

### Decisions deliberately not taken

- No list-weeks endpoint. The picker is prev/next arrows plus a "This
  week" button; every Monday is a valid target.
- No day sub-windows, no "today" counts. The unit is the week.
- No CSV route, no `?format=`. The Excel download is the export.
- No re-import path. `report_csv` and the `Data` sheet go; the
  operational work-order export is untouched and remains the
  re-importable file.
- No charts of any kind.

---

## 3. Payload

`HubReportResponse` (rewritten):

| Field | Type | Notes |
|---|---|---|
| `week_start` | date | the Monday |
| `week_end` | date | the Sunday, for labelling |
| `status` | `"in_progress" \| "completed"` | W2 |
| `generated_at` | datetime | when this payload was computed |
| `frozen_at` | datetime? | set on stored records; null while in progress |
| `count` | int | `len(rows)` — no cap, the window is the bound |
| `rows` | list[`HubReportRow`] | closed rows, in workbook order: service type label, primary community, number |

`HubReportRow`: `work_order_id`, `number`, `assigned_to`, `location`,
`service_type` (raw), `service_type_label` (normalised, the tab name),
`community` (primary, key), `schedule_date`, `priority`, `archived_at`.

`work_order_id` and `archived_at` serve the screen's row click-through
and its Closed timestamp; they are not workbook columns.

---

## 4. Storage

Table `work_order_report_weeks`, one Alembic migration:

| Column | Type | Notes |
|---|---|---|
| `week_start` | date, PK | the Monday |
| `frozen_at` | timestamptz, not null | server `now()` at insert |
| `schema_version` | int, not null | 1 |
| `payload` | jsonb, not null | `HubReportResponse.model_dump_json` |

A dev copy of ~700 rows serializes to well under 200 KB; a week's
closes are a fraction of that.

---

## 5. Service shape

```
app/services/work_order_report.py            # rewritten, < 250 lines
  weekly_report(db, *, week_start, now) -> HubReportResponse   # live compute
  report_for_week(db, *, week_start, now) -> HubReportResponse # W2/W5 dispatch
  resolve_week(week: date | None, now) -> date                 # W7 validation
  _closed_rows(db, start, end) -> list[HubReportRow]

app/services/work_order_report_xlsx.py       # rewritten, < 200 lines
  report_xlsx(payload) -> bytes
  report_xlsx_filename(payload) -> str        # wo-report_{week_start}.xlsx
  _service_type_sheet(sheet, payload, label, rows)

app/services/_xlsx_theme.py                  # kept; chart helpers deleted
app/models/work_order_report_week.py         # new ORM model
app/schemas/hub.py                           # HubReportResponse / HubReportRow rewritten
app/routers/hub.py                           # both routes take `week`

deleted: work_order_report_buckets.py, work_order_report_xlsx_charts.py
         and their tests
```

`report_for_week`: if `week_start` is the current week's Monday, return
`weekly_report(...)` with `status="in_progress"`. Otherwise `SELECT` the
row; on miss, compute with `status="completed"`, insert
`ON CONFLICT DO NOTHING`, re-`SELECT`, and return the stored payload
with `frozen_at` filled from the row. The route never sees the
difference.

`_closed_rows` reuses the existing eager-load shape (`supervisor`,
`technicians` are no longer needed; only the columns W10 names).

---

## 6. Workbook

House style from `_xlsx_theme.py` stands: Aptos Narrow, gridlines off,
title block in rows 1–3, brand-red title, landscape print. No frozen
panes and no `print_title_rows`: a tab holds several blocks, each with
its own header.

Sheet order: one tab per service type label, alphabetical (W8). Tab
names are sanitised for Excel (31 chars, no `: \ / ? * [ ]`) and
de-duplicated with a numeric suffix if sanitising collides. Tab colour
`MUTED`.

Each sheet:

```
A1  Maintenance                                     [18 semibold red]
A2  Closed 2026-09-07 – 2026-09-13 · 41 work orders  [subtitle]
A3  Completed · frozen 2026-09-14 00:12 Central      [subtitle]
    (or: In progress · generated 2026-09-13 15:40 Central)

A5  Scholars                                        [section heading]
A6  WORK ORDER | ASSIGNED TO | LOCATION | SERVICE TYPE | SCHEDULE DATE | PRIORITY
A7  … rows …
    (blank row)
    Centennial                                      [section heading]
    header row, rows …
```

Widths: 14 / 22 / 34 / 18 / 14 / 10. Only communities with rows on
that tab get a block. Each block's header row is styled `HEADER`; no
Excel Table objects (one tab holds several blocks, and a Table cannot
span a heading row).

An empty week produces a single sheet named `Report` carrying the title
block and the line `No work orders closed this week.`

Filename: `wo-report_{week_start}.xlsx` — the Monday, so the file is
named for the period it covers (D14 convention).

---

## 7. Screen

`static/views/hubReport.js` rewritten; `userHub.js` keeps ownership of
the tab and the fetch.

```
[◀]  Week of Sep 7 – Sep 13, 2026  [▶]   [This week]
     Completed · frozen Sep 14, 12:12 AM      (or: In progress · generated …)
     41 closed work orders                     Download Excel

Maintenance (18)
  Community | Number | Assigned to | Location | Schedule date | Priority | Closed
  …
Window Repair (9)
  …
```

- Arrows move one Monday; `▶` is disabled on the current week.
- `Download Excel` is a plain `<a href="/hub/report/export?week=…">`.
- Each row's number keeps the R11 click-through: closed rows route to
  the exact-number search, which offers the restore prompt.
- Empty week: `No work orders closed this week.`
- Re-entering the tab re-fetches the *selected* week, not the current
  one; a fresh session defaults to the current week.
- `Closed` is `archived_at` rendered in Central, the one timestamp the
  page shows.

`apiGetHubReport(weekStart)` gains the parameter.

---

## 8. Testing

Backend (`tests/test_work_order_report.py`,
`tests/test_work_order_report_xlsx.py`, `tests/test_hub_router.py`):

- `resolve_week`: `None` → this Monday; a Monday ≤ this Monday accepted;
  a Tuesday and a future Monday raise the 422 domain error.
- Window edges: a row archived Sunday 23:59:59 Central is in; Monday
  00:00:00 is in the next week; a row restored (`archived_at` cleared)
  is absent from a live week.
- Freeze: first request for a past week inserts one row; a restore after
  the freeze does not change the second request's payload; the current
  week never inserts; `frozen_at` is null in progress and set when
  completed.
- Race: two concurrent first requests leave one row (`ON CONFLICT`).
- Grouping: rows ordered by label, community order, number; a
  two-community row appears once under its first community; blank
  service type lands on `Unspecified`.
- Workbook: sheet names are the alphabetical labels; a sheet's blocks are
  the communities present in fixed order; header cells are the six W10
  headers; cells are the raw vendor strings; empty week gives the single
  `Report` sheet; filename is the Monday.
- Route: `?week=` on both routes, 422 cases, attachment headers, and the
  role-gate exemption unchanged.

Frontend (`tests/frontend/views/hubReport.test.js`, `userHub.test.js`):
week label, badge text for both statuses, arrows and their disabled
state, download href carrying the week, service-type sections and
counts, row click-through, empty state, retry.

---

## 9. Docs to update in the same change

`docs/current-state.md` (feature row), `docs/endpoint-map.md` (H6/H7 and
`HubReportResponse`), `docs/open-work.md`: delete
`N-REPORT-CLOSING-PAGINATION` (no cap exists), narrow
`N-WO-STATUS-EVENTS` (frozen weeks now satisfy the reconcile trigger for
this report), keep `N-REPORT-EXPORT-AUDIT`.
