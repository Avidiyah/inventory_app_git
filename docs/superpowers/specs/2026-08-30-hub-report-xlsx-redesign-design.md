# Hub Report Excel Export — redesign

Status: reviewed 2026-08-30, open decisions resolved (E14–E16, §8) ·
supersedes the chart and layout half of
`2026-08-30-hub-report-xlsx-export-design.md` (X6, X7, X11 and §4.2);
that spec's X1–X5, X8–X10 still hold.

`GET /hub/report/export` keeps serving one `.xlsx` from one payload, but
the workbook is rebuilt: a designed **Report** overview, one **chart
sheet per community** carrying a four-slice status pie over a grid of
service-type small multiples, a readable **Work Orders** sheet whose
third column is Notes, and the re-importable **Data** sheet demoted to
last. The four slices are the lifecycle collapsed to the four states an
Admin actually acts on.

Parent specs: `2026-08-30-work-order-daily-report-design.md` (R-numbers),
`2026-08-30-hub-report-xlsx-export-design.md` (X-numbers),
`2026-08-30-hub-graphs-community-drilldown-design.md` (the Graphs tree
this borrows its shape from). New decisions here are **E-numbers**.

---

## 1. Purpose

Two complaints, one file.

**It looks gross.** The current workbook is openpyxl's defaults with bold
headers bolted on: Calibri 11 everywhere, gridlines behind everything,
27 unsized columns, money rendered as text so Excel flags every cell with
a green error triangle, and four charts stacked in column E at whatever
size openpyxl felt like. Nothing about it says a person designed it.

**The charts answer the wrong question.** Bar charts of raw section
counts tell an Admin what the *report* contains. What the Admin wants —
and already has on screen, in the Graphs tab — is *where the work
stands, per community, split by trade*. This spec moves that view into
the file and collapses seven statuses to the four the weekly
conversation is actually about.

---

## 2. The four slices

Every pie in the workbook — the company pie, each community pie, each
service-type small multiple — is the same four-bucket distribution over
the same population, in the same order, in the same colors. Only the row
set narrows. That is what makes the small multiples comparable at a
glance, and it is the single most important property of this design.

| # | Slice label | Statuses folded in | Why |
|---|---|---|---|
| 1 | **Accepted** | `created` | The user's own word for it. A work order exists and has been taken on; nobody is on it yet. |
| 2 | **In progress** | `assigned`, `in_progress`, `on_hold` | The three "someone owns this, it isn't finished" states. On-hold is not a separate conversation at weekly cadence. |
| 3 | **Ready to close** | `ready_to_complete`, `completed`, `review` | Everything waiting on paperwork rather than on a technician. This is the closing pipeline the old Summary sheet charted separately. |
| 4 | **Closed** | archived within the report week | The week's output. |

The order is lifecycle order, left to right in every legend and clockwise
from 12 o'clock in every pie (`firstSliceAng = 0`). Never alphabetical,
never largest-first — a small multiple grid whose slice order shifts per
card cannot be read.

### 2.1 The population, stated plainly

Slices 1–3 are a **snapshot of live (non-archived) work orders right
now**. Slice 4 is a **window**: rows archived inside the report's own
week (`week.start` 00:00 Central through `generated_at`).

That mix is deliberate (E1) and it is the only honest weekly pie: "here
is everything on our plate, and here is what we took off it this week."
The alternative — a cohort pie over work orders *created* this week —
answers a question nobody asked and reports a near-empty Closed slice
every Monday. Both the chart sheets and the overview carry the subtitle:

> Live work orders as of {generated} Central, plus work orders closed
> {week.start}–{week.end}. A work order named in two communities is
> counted in both; community totals do not sum to the company total.

The multi-community caveat is the Graphs tab's own, carried over
verbatim — `community_memberships()` is membership, not a tag.

---

## 3. Decisions

| # | Decision |
|---|---|
| E1 | **One population for the whole workbook: live rows + rows closed this week.** Every pie, every table, and the Work Orders sheet count the same set. A workbook whose charts and rows disagree about what "this report" means is worse than no charts. |
| E2 | **Four buckets, fixed order, fixed colors, everywhere.** §2. The bucket map is one table in code (`REPORT_BUCKETS`), consumed by the aggregator and both renderers, so a fifth status added to the domain fails loudly at one place instead of silently vanishing from a pie. |
| E3 | **A new aggregate on `DailyReport`: `distribution`.** Community × service type × bucket counts, computed in `work_order_report.py` from a columns-only query (`status, community, location, service_type` over live rows) plus the existing `closed_week.rows`. No eager loads, no cap — it is four integers per group. Mirrors `services/hub.py::graphs_hub`, which already proves the query shape at company scale. |
| E4 | **The Work Orders sheet carries the full E1 population, uncapped.** The on-screen `closing` list keeps its cap (R3/§7); the *file* does not. The parent spec's own reasoning for leaving `closed_*` and `new_*` uncapped applies with more force here: a downloadable record that silently omits rows while looking complete is a record-keeping problem, not a performance one. It reuses `_base_query`'s eager loads, exactly as the sections do. |
| E5 | **Notes is column C.** After `WORK ORDER` and `LOCATION`, before every other column, per the request. It is the widest column in the workbook (60 chars, wrapped, top-aligned) because it is the only free-text column and the reason the sheet exists. |
| E6 | **One sheet per community, plus an overview.** `Report`, then `Scholars`, `Centennial`, `Commons`, `Young Hall`, `Academics` (the fixed `ALL_COMMUNITY_FILTERS` order), then `Work Orders`, then `Data`. Nine visible sheets. A single scrolling chart sheet holding five communities' worth of small multiples is ~180 rows of charts — unnavigable, and every screenshot of it is a crop. |
| E7 | **Chart source cells live on one hidden `Chart Data` sheet**, a flat machine-written block per chart. Keeps the designed sheets free of stray numbers. Every chart also sets `visible_cells_only = False` (openpyxl's `plotVisOnly`), belt-and-braces against Excel refusing to plot a range it considers hidden. |
| E8 | **Service-type small multiples: top 8 by total, plus an `Other` roll-up.** A 3×3 grid. The cap is a layout constraint and it is stated on the sheet (`"Other" combines N further service types`) — never a silent truncation. Exact numbers for *every* service type are in the sheet's bottom table, so the cap costs no information. |
| E9 | **Every pie has an adjacent exact-value table.** `docs/design-system.md` makes the Graphs tab the app's sole categorical-color exception on the condition that color is never the only way to read a value. That condition travels with the charts into Excel: the community pie gets a four-row count/percent block beside it; the small multiples share one Excel Table at the bottom of the sheet. |
| E10 | **`Data` stays byte-identical and moves last, with a gray tab.** X5's re-import round-trip is untouched — same header, same section order, same money-as-text cells, still pinned cell-for-cell against `report_csv`. It is a machine sheet; it stops being the first thing after the charts. |
| E11 | **The old Summary sheet is replaced, not extended.** Activity and dollars-by-community move onto `Report`. "Closing pipeline" is deleted as a chart — it *is* the Ready-to-close slice now, and its three-status split lives in a number block. "Closed this week by service type" is deleted — superseded by the per-community service-type grid. |
| E12 | **Styling is a module: `services/_xlsx_theme.py`.** Fonts, fills, number formats, column widths, chart geometry, and the bucket palette as named constants and small helpers (`title`, `section`, `kpi`, `pie_of`, `table_of`). `work_order_report_xlsx.py` becomes sheet composition only. Neither module reaches 500 lines; today's single module would. |
| E13 | **`report_xlsx` stays a pure function of `DailyReport`** (X3, unchanged). The new aggregate is computed in `daily_report`, not in the renderer. No queries and no clock below the service layer. |
| E14 | **Community, wherever the workbook names one, is `community_memberships(community, location)` — never the raw `community` column.** That column is NULL on every NetFacilities-imported row (697 of 697 in the 2026-08-30 dev copy); only the create form and mass staging set it. The app's canonical community is the membership parse of the location text — what the Graphs tab, the Work Orders filter, and the community sheets already count. Two derived forms: the **membership list** (`; `-joined) for the `Work Orders` sheet's COMMUNITIES column, and the **primary community** — the first membership in `ALL_COMMUNITY_FILTERS` order, Academics fallback — wherever a figure must sum, i.e. dollars. Every row has exactly one primary, so money is never counted twice; the rare two-community row (3 of 697 in the dev copy) is attributed to its first and the sheet says so in a footnote. |
| E15 | **The service-type small multiples carry no legend.** All nine cards share the same four slices, colors, and order (E2), so nine identical legends are noise, and a four-entry bottom legend on a 7.5 × 6 cm card costs about a quarter of its height. The community status pie above them is the shared key; the detail table below carries the numbers, so E9 holds. |
| E16 | **The page pays for the workbook's population, and that is accepted.** `GET /hub/report` and `GET /hub/report/export` share one `daily_report`, which now always fetches every live row (E4) and computes `distribution` (E3). That is the price of one payload that cannot disagree with itself, and it is the same order of cost as the existing capped `closing` fetch. The one-time visual check (§7) times `daily_report` on the developer database; an `include_rows` switch is the fallback if it proves materially slow on production-shaped data, and it is not added speculatively. |

### Decisions deliberately not taken

- **No new route, no `?format=`, no second button.** X1 holds.
- **The JSON `HubReportResponse` does not carry `distribution` yet.** The
  Report *tab* shows no pies, so there is nothing for the file to
  disagree with. Exposing it is a one-line schema addition the day the
  page wants them.
- **No merged cells anywhere.** Merges break sort, filter, and
  copy-paste. Titles that need to span use `centerContinuous`.
- **No conditional formatting, no sparklines, no slicers, no macros.**
  openpyxl writes the first two; none of the four survive a save-as-CSV,
  and none add a number the tables don't already carry.
- **No doughnut charts.** The request said pie, and a doughnut's hole
  buys nothing without a center total, which the KPI block provides.
- **No per-community *dollars*.** Money stays one chart on `Report`; the
  community sheets are about work, not billing.

---

## 4. The workbook

### 4.0 House style

The whole point of E12. Applied to every sheet:

| Element | Spec |
|---|---|
| Body font | Aptos Narrow 10, falling back to Calibri (Excel's own default chain; naming the family explicitly stops the file inheriting a random workbook theme) |
| Sheet title | 18 semibold, brand red `#C8102E` |
| Subtitle / caveat line | 9 italic, `#5A5C60` |
| Section heading | 11 bold `#1C1D20`, with a 1pt bottom rule in `#D8D9DB` |
| Table header row | 10 bold white on `#1C1D20`, frozen, autofilter on |
| Gridlines | **off** on every sheet except `Data` (`sheet_view.showGridLines = False`) — the tables carry their own rules |
| Zebra | Excel Table style `TableStyleLight1`, banded rows; never manual fills |
| Counts | `#,##0` |
| Money | `$#,##0.00` — real `Decimal` values, so no green error triangles (`Data` is the one exception, X5) |
| Percent | `0.0%` over real fractions, not pre-formatted strings |
| Dates | `yyyy-mm-dd hh:mm` |
| Rows 1–4 | title block; `freeze_panes` below it on every sheet |
| Tab colors | `Report` brand red; the five communities `#5A5C60`; `Work Orders` `#1C1D20`; `Data` `#B7B9BC` |
| Print | landscape, `fitToWidth = 1`, header row repeated (`print_title_rows`), 0.5" margins |

**The bucket palette** (E2), traceable to the `--wo-status-*` tokens the
Graphs tab already uses, darkened where the token was tuned for a dark
canvas and would wash out on white paper:

| Slice | Hex | From |
|---|---|---|
| Accepted | `#9CA3AF` | `--wo-status-created` `#D1D5DB`, darkened |
| In progress | `#D97706` | `--wo-status-in-progress` `#FACC15`, darkened |
| Ready to close | `#6D28D9` | `--wo-status-ready-to-complete`, as-is |
| Closed | `#15803D` | `--wo-status-review`, as-is |

Brand red is **not** a slice. It is the title color and the KPI rule —
the brand, not a category. Slice fills are set per `DataPoint`, in bucket
order, on every chart, so Accepted is the same gray in all fifty-odd
pies.

### 4.1 `Report`

```
A1  Weekly Work Order Report                        [18 semibold red]
A2  Fri, Aug 30, 2026 · week of 2026-08-24 – 2026-08-30 (week to date)
A3  Generated 2026-08-30 16:42 Central
A4  Live work orders as of now, plus work orders closed this week. …
──────────────────────────────────────────────────────────────────────
A6   KPI strip: five tiles, label above value, brand-red rule under each
       Open work orders │ Accepted │ In progress │ Ready to close │ Closed this week
A10  Company status            [pie, 4 slices]   ← counts+% block at A11:C15
A26  Activity                  [column chart]    ← Closed/New × Today/Week
A42  Dollars closed this week  [stacked column]  ← labor + materials by primary community (E14)
A58  By community              [table] community │ 4 bucket columns │ total
```

The KPI tiles restate the deleted pipeline chart's numbers: Ready to
close is one tile, and its three-status split (`ready_to_complete`,
`completed`, `review`) is a footnote row under the by-community table.
The `closed_today.auto_closed_count` / `closed_week` NetFacilities note
(R10) sits under the Activity chart in the page's own phrasing,
unchanged.

Activity and dollars keep the existing brand-red/neutral two-series
treatment; they are not bucket charts and must not borrow the bucket
palette.

Dollars are attributed by **primary community** (E14): each closed row
lands under its first membership, so the block is at most five rows,
never double counts, and never shows a `(no community)` line. A one-line
footnote under the block says so — `Dollars count a work order under its
first community.` Because the block is bounded, the by-community table
sits at a fixed row 58.

### 4.2 A community sheet (× 5)

```
A1  Scholars                                        [18 semibold red]
A2  Weekly status · 142 work orders
A3  Live … plus closed this week. A work order named in two
    communities is counted in both. …
──────────────────────────────────────────────────────────────────────
A5   Status                    [pie, 16 × 10 cm, legend right,
                                data labels = percentage]
     E5:G9  exact-value block: bucket │ count │ percent  (E9)
A22  By service type           [section heading]
A23  "Other" combines 6 further service types.        (E8, when it bites)
     3 × 3 grid of pies, 7.5 × 6 cm, no legend (E15), no data labels,
     each titled with its service type and total; the status pie above
     is the shared key:
       B24  E24  H24
       B37  E37  H37
       B50  E50  H50
A64  Service type detail       [Excel Table, every service type:
                                Service type │ Accepted │ In progress │
                                Ready to close │ Closed │ Total,
                                sorted by Total desc then label]
```

Column widths are fixed so the grid lines up: A = 22, B–J = 11 uniform,
K onward default. Charts anchor on B/E/H, thirteen rows apart — a 6 cm
pie is ≈ 12 rows, leaving one row of air.

A community with no work orders renders the sheet with an empty-state
line (`No live or recently closed work orders in this community.`) in
place of the charts. It never renders a chart of zeros — a pie with no
area is a rendering bug, not a data point.

### 4.3 `Work Orders`

The readable row sheet. One row per work order — **deduped**, unlike
`Data`, where a row appears under both `closed_today` and `closed_week`.
Population is E1/E4. Sorted: Closed first (most recent close first),
then Ready to close, In progress, Accepted, each by work-order number.

An Excel Table (`TableStyleLight1`, banded, autofilter) with row 5 as its
header, frozen at `D6` so Number / Location / Notes stay visible while
scrolling right.

| # | Column | Width | Notes |
|---|---|---|---|
| A | WORK ORDER | 14 | text; leading zeros preserved |
| B | LOCATION | 34 | |
| C | **NOTES** | 60 | wrapped, top-aligned, row height auto-capped at 4 lines |
| D | BUCKET | 14 | the four-slice label — the column the Admin filters on |
| E | STATUS | 16 | the underlying status, human-labeled |
| F | COMMUNITIES | 22 | `community_memberships` labels, `; `-joined (E14) — the same set the community sheets count, so a row that appears on two sheets says so here |
| G | SERVICE TYPE | 18 | |
| H | PRIORITY | 12 | raw vendor text |
| I | BUILDING | 10 | |
| J | UNIT | 10 | |
| K | SUPERVISOR | 18 | |
| L | TECHNICIANS | 24 | `; `-joined |
| M | MATERIAL LINES | 12 | `#,##0` |
| N | MATERIALS TOTAL | 14 | `$#,##0.00`, numeric |
| O | LABOR MINUTES | 12 | `#,##0` |
| P | LABOR TOTAL | 14 | `$#,##0.00`, numeric |
| Q | TOTAL | 14 | `$#,##0.00`, numeric |
| R | CREATED AT | 18 | UTC, per `export_row`'s seam (§5) |
| S | COMPLETED AT | 18 | |
| T | CLOSED AT | 18 | `archived_at` |
| U | SECTIONS | 20 | which report sections this row appeared in, `; `-joined — the `Data` sheet's `SECTION` filter folded into one deduped row |

Money here is numeric `Decimal`, not `export_row`'s strings: this sheet
is for reading and pivoting, and it is not the re-import path. That is
the whole reason it can be nice.

### 4.4 `Data` and `Chart Data`

`Data`: unchanged from X5 / §4.1 of the parent spec, moved last, gray
tab, gridlines left on. It is the machine sheet.

`Chart Data`: `sheet_state = "hidden"`. One labeled block per chart in a
fixed order (company, then per community: the pie block, the nine
small-multiple blocks, the full service-type table). Blocks are addressed
by cursor, each preceded by a one-cell name so a human who unhides the
sheet can find what a chart reads.

---

## 5. What does not change

- The route, its Admin-only floor, and the plain-`<a>` download (X1).
- The filename `wo-report_{day}.xlsx` — named for the period covered,
  not the moment of export (D14).
- `report_csv` / `report_filename`, still the executable contract the
  `Data` sheet is tested against and still one route-flip from being
  restorable (X10).
- The UTC-vs-Central timestamp seam: `export_row` writes UTC while the
  sections are Central calendar windows, so a row closed at 8 PM Central
  on the 30th reads the 31st in `CREATED AT` / `CLOSED AT`. The covered
  period is in the filename and the title block. Do not "fix" this by
  reformatting the shared export.
- The Graphs tab itself. This spec borrows its shape; it changes no pixel
  of it.

---

## 6. Implementation shape

```
app/services/work_order_report.py
  + REPORT_BUCKETS: tuple[Bucket, ...]        # key, label, statuses
  + bucket_of(status) -> str
  + communities_of(row) -> tuple[str, ...]    # membership labels (E14)
  + primary_community(row) -> str             # first membership (E14)
  + @dataclass ReportDistribution             # company + per community
  + @dataclass CommunityDistribution          # counts, service_types
  + _distribution(db, *, week_start_at, now)  # columns-only live query
  + _report_rows(db, ...)                     # E4 population, deduped
  ~ DailyReport                               # + distribution, + all_rows

app/services/_xlsx_theme.py                   # NEW (E12)
  palette, fonts, fills, formats, widths, chart geometry,
  title() / section() / kpi() / pie_of() / table_of() / empty_state()

app/services/work_order_report_xlsx.py        # rewritten
  report_xlsx(payload) -> bytes
  _report_sheet / _community_sheet / _work_orders_sheet
  _data_sheet (unchanged) / _chart_data_sheet
```

Order of work: buckets and the aggregate first (testable without a
workbook), then the theme module, then sheets one at a time — `Work
Orders` before the chart sheets, because it is the half of the request
that carries information rather than shape.

---

## 7. Testing

The parent spec's constraint stands: **openpyxl cannot read back charts
it wrote**, so charts are asserted at the zip level and their visual
shape is a one-time manual check.

- `bucket_of` covers all seven `ALL_STATUSES` and raises on an unknown
  status — the E2 loud-failure property.
- `_distribution` over a fixture: a multi-community row counted in both
  communities; a blank service type in `Unspecified`; a row closed this
  week in `Closed` and absent from the live buckets; a row closed *last*
  week in neither.
- Each community's four bucket counts sum to its total; community totals
  deliberately do **not** sum to the company total (asserted, so a future
  "fix" trips a test).
- `Data` still equals `report_csv` cell-for-cell (X5's existing test,
  retargeted at the sheet's new position).
- `Work Orders` has `NOTES` in column C, no duplicate work-order numbers,
  and a row count equal to the E1 population.
- Sheet names and order are exactly the nine of E6; `Chart Data` is
  hidden; `Data` is last.
- `zipfile` over the saved bytes: `xl/charts/chart*.xml` count equals
  3 (Report) + 5 × (1 + up to 9), and every chart part contains
  `plotVisOnly val="0"`.
- An empty database produces a valid workbook: five empty-state community
  sheets, no zero-area pies, no exception.
- `communities_of` / `primary_community` (E14): a row naming two
  communities lists both in `ALL_COMMUNITY_FILTERS` order and is primary
  to the first; a row naming none is Academics, never empty; the dollars
  block counts a two-community row exactly once and never writes a
  `(no community)` line.
- Zip-level: the number of chart parts carrying a `<legend>` equals the
  charts that are not grid cards — three on `Report` plus one status pie
  per non-empty community (E15).
- The one-time visual check renders two workbooks: one from the developer
  database and one from a synthetic showcase payload that exercises every
  slice, the `Other` roll-up, a two-community row, and an empty community.
  The dev copy has no archived rows, so on its own it never shows a Closed
  slice or a non-zero Dollars chart.

---

## 8. Resolved question

**The label for slice 2 is "In progress"** — confirmed 2026-08-30. The
request grouped Assigned / In-Progress / On-Hold without naming the group;
*In progress* is the phrase the group means and reads naturally in the KPI
strip. It collides with the `in_progress` status label only on the `Work
Orders` sheet, where BUCKET (D) and STATUS (E) sit side by side under their
own headers. *Active* was the runner-up (one word, ops-native) and was
passed over because it reads as a synonym for the "Open work orders" KPI;
*Working* and *Underway* were not close. The label is one string in
`REPORT_BUCKETS`.
