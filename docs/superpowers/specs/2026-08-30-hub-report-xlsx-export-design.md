# Hub Report Excel Export — design

Status: approved for implementation · 2026-08-30 · not yet implemented

The Report tab's `Download CSV` becomes `Download Excel`: the same
`GET /hub/report/export` route serves an `.xlsx` workbook whose `Data`
sheet is the SECTION-prefixed CSV cell-for-cell, plus a `Summary` sheet
holding the report's headline numbers and four charts. Everything renders
from the one existing `DailyReport` payload — no new queries, no new
windows, no change to what the report means.

Parent spec: `2026-08-30-work-order-daily-report-design.md` (the report
itself; R-numbers referenced below are its decisions).

---

## 1. Purpose

The daily report's CSV answers "what happened" only after the Admin builds
pivot tables by hand. The Excel export ships the workbook already charted:
open the file, see the day — activity, pipeline, service-type mix, and
where the week's money went — with the raw rows one sheet away.

---

## 2. Decisions

| # | Decision |
|---|---|
| X1 | **Excel replaces CSV, same route.** `GET /hub/report/export` serves xlsx; the URL, the Admin-only floor, and the plain-`<a>` download mechanism are unchanged. No second button, no `?format=` switch — the user chose *instead*, and restoring CSV later is one route-flip (X10). |
| X2 | **No template file; the workbook is built in code.** See §3 — openpyxl discards charts from any workbook it loads and re-saves, so a hand-made template's charts would silently vanish from every download. The "template" is a renderer module that builds the identical workbook every time: deterministic, diffable, no binary in git. |
| X3 | **`report_xlsx` is a pure function of the `DailyReport` payload.** No queries, no clock — the payload's third renderer beside the JSON route and `report_csv`, under the parent spec's R9: screen and file cannot disagree, cap included. |
| X4 | **New module `services/work_order_report_xlsx.py`.** `work_order_report.py` is at 324 lines; a four-chart builder would break the 500-line rule. The new module owns the xlsx render and nothing else. |
| X5 | **The `Data` sheet is the CSV, verbatim.** Same header row (`SECTION` + the 26 `EXPORT_HEADERS`), same section order, same `export_cells` values — money strings like `"7.50"` included. Save-as-CSV from Excel still round-trips through `parse_import_row`. Pinned by a test that compares the sheet to `report_csv` output cell-for-cell. |
| X6 | **The `Summary` sheet carries labeled cell blocks plus four charts.** xlsx charts must reference real cells, so each chart's source data is written as a small readable block; the blocks double as the numbers-at-a-glance view. |
| X7 | **Charts read the Summary blocks, never the Data sheet.** The Data sheet's money cells stay text (X5); the blocks hold real numerics with `#,##0.00` formats. |
| X8 | **Block numbers come from the payload's own counts, never row tallies.** Same rule the page follows: `closing` can be capped, and a tally over rendered rows would under-report. The pipeline block zero-fills absent `by_status` keys so the chart always shows all three lifecycle categories. |
| X9 | **openpyxl, pinned exact, runtime.** Pure Python (only dep `et_xmlfile`): no native libraries, no CI or Docker changes. `requirements-dev.txt` inherits it via `-r requirements.txt`. |
| X10 | **`report_csv` and `report_filename` stay.** `report_csv` becomes the executable contract the Data sheet is tested against; the pair keeps the CSV renderer one route-flip from restorable. Neither is served by any route after this change. |
| X11 | **The dollars chart is by community, stacked labor + materials.** Chosen over a bare labor/materials split and over a by-supervisor view: one chart shows where the week's money went *and* its split. |

### Decisions deliberately not taken

- **No numeric coercion of the Data sheet's money columns.** Excel shows
  its "number stored as text" hint on them; that is the price of X5's
  cell-for-cell CSV fidelity, and the charts are immune (X7).
- **No styling beyond bold headers, money formats, and brand series
  colors** (red primary, neutral secondary, per `docs/design-system.md`).
  No themes, no logos, no conditional formatting.
- **No chart read-back verification through openpyxl.** The same
  limitation behind X2 makes loaded charts invisible to it; presence is
  asserted at the zip level (§7) and shape by one-time visual check.

---

## 3. The constraint that shapes this design

**openpyxl does not preserve charts across a load/save cycle.** The
intuitive build — commit a hand-made `.xlsx` with charts pointed at an
empty data sheet, fill the sheet at runtime — produces a workbook whose
charts are gone, silently, in every download. There is no error to catch;
the feature simply never works. Every other mainstream option loses too:
xlsxwriter cannot read templates at all, and driving real Excel is a
Windows-COM dependency a Linux deploy cannot run.

So the template is code (X2), and charts are created programmatically —
which openpyxl does fully support. Consequences: charts also cannot be
*read* by openpyxl-based tests (§7 tests presence via `zipfile`), and any
future change to chart cosmetics is a code change, not a spreadsheet edit.

---

## 4. The workbook

Sheet order: `Summary`, `Data` — Excel opens on Summary.

### 4.1 `Data`

- Row 1, bold, frozen (`freeze_panes="A2"`): columns A–AA —
  `SECTION, WORK ORDER, LOCATION, OUTPUT TO, ASSIGNED TO, SERVICE TYPE,
  SCHEDULE DATE, SYMPTOM/TASK, STATUS, TECHNICIANS, SUPERVISOR, COMMUNITY,
  BUILDING, UNIT, ENTRY MODE, MATERIAL LINES, MATERIALS TOTAL,
  LABOR MINUTES, BILLED LABOR MINUTES, LABOR TOTAL, TOTAL, NOTES,
  CREATED AT, UPDATED AT, COMPLETED AT, ARCHIVED AT`.
- Body: exactly `report_csv`'s iteration —
  `for key in SECTION_ORDER: for row in section.rows: [key, *row.export_cells]`.
  Cells are `export_row`'s values as-is: strings stay strings, the three
  genuine ints (`MATERIAL LINES`, `LABOR MINUTES`, `BILLED LABOR MINUTES`)
  stay ints.
- All five sections are written, so a row still appears under both
  `closed_today` and `closed_week` — the CSV's filter-on-SECTION property.

### 4.2 `Summary`

Blocks live in columns A–C, stacked top-to-bottom. The first two have
fixed addresses; blocks 3 and 4 are variable-length, so the module lays
blocks out with a row cursor and builds each chart's `Reference` from the
block's actual extent. Each chart anchors in column E at its block's
starting row; the cursor advances by `max(block height, 15) + 2` rows so
nothing overlaps.

**Header (rows 1–4):** `Daily Report`; the covered day; `Week of <start>
– <end> · week to date`; `Generated <stamp>` rendered in Central — the
zone the page renders (`labor_day`'s zone if exported, else
`ZoneInfo("America/Chicago")`).

**Block 1 — Activity (rows 7–9) → clustered bar.** Matrix: rows
`Closed` / `New`, columns `Today` / `Week to date`, values the four
section counts. When either closed section has `auto_closed_count > 0`, a
footnote cell notes it in the page's own "(n in NetFacilities)" phrasing.

**Block 2 — Closing pipeline (rows ~12–15) → bar.** Label row with
`closing.count`, then one row per status in lifecycle order — `Ready to
complete`, `Completed`, `Review` — values from `by_status`, zero-filled
(X8). If `closing.truncated`, a note cell mirrors the page's "counts are
complete, rows are capped" warning; the Data sheet holds only the capped
rows, same as the CSV today.

**Block 3 — Closed this week by service type (variable) → bar.** Header
`Service type | Closed`; one row per distinct `service_type` across
`closed_week.rows`, counted, sorted count-desc then name; `None` →
`(no service type)`. Empty week → single `(none) | 0` row so the chart
renders instead of erroring.

**Block 4 — Closed this week dollars by community (variable) → stacked
column.** Header `Community | Labor $ | Materials $`; one row per
distinct `community`, summing the rows' `labor_total` /
`materials_total` Decimals (openpyxl writes `Decimal` natively), sorted
by combined total desc then name; `None` → `(no community)`; empty week
→ `(none) | 0 | 0`. Chart: series Labor and Materials,
`grouping="stacked"`, `overlap=100`. Money cells `#,##0.00`.

---

## 5. Changes by file

**New — `backend/app/services/work_order_report_xlsx.py`** (~300 lines).
Public surface:

```python
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

def report_xlsx(payload: DailyReport) -> bytes: ...
def report_xlsx_filename(payload: DailyReport) -> str:
    # f"wo-report_{payload.day.isoformat()}.xlsx" — named for the day it
    # covers, the timesheet convention (user-hub-design.md D14)
```

Private helpers, one per block or chart: `_data_sheet`, `_summary_sheet`,
`_headline_block`, `_pipeline_block`, `_service_type_block`,
`_community_money_block`, their chart builders, and pure aggregators
`_service_type_counts(rows)` / `_community_money(rows)`.

**`backend/app/routers/hub.py` — `export_hub_report()`.** Route path,
floor, and compose-from-`daily_report` shape unchanged; only the render
swaps:

```python
payload = work_order_report.daily_report(db, now=datetime.now(timezone.utc))
filename = work_order_report_xlsx.report_xlsx_filename(payload)
return Response(
    content=work_order_report_xlsx.report_xlsx(payload),
    media_type=work_order_report_xlsx.XLSX_MEDIA_TYPE,
    headers={"Content-Disposition": f'attachment; filename="{filename}"'},
)
```

**`backend/static/views/hubReport.js`.** The header link's text:
`Download CSV` → `Download Excel`; comment updated. Same
`<a class="secondary-btn" href="/hub/report/export">` — no JS behavior
change, no `api.js` change.

**`backend/requirements.txt`.** `openpyxl==<version verified at install>`
with a rationale comment in the file's convention.

**`docs/endpoint-map.md`, row H7.** Renderer column becomes
`work_order_report.daily_report` + `work_order_report_xlsx.report_xlsx`.
(The Obsidian mirror updates itself.)

## 6. What deliberately does not change

- `daily_report`, the section queries, windows, and the closing cap.
- `report_csv` / `report_filename` (X10).
- `export_row` — the 26-cell contract shared with the operational export.
- `GET /hub/report` (JSON), all role gates, and the Work Orders page's own
  CSV import/export — the re-import path everyone actually uses lives
  there, not here.

---

## 7. Testing

**Modified — `tests/test_hub_router.py`.**
`test_report_export_is_an_attachment_csv` becomes
`test_report_export_is_an_attachment_xlsx`: 200; content-type is
`XLSX_MEDIA_TYPE`; disposition carries `attachment`, `wo-report_`, and
`.xlsx`; `openpyxl.load_workbook(BytesIO(content))` yields sheets
`["Summary", "Data"]` with Data row 1 equal to
`("SECTION",) + EXPORT_HEADERS`. The parametrized 403 gate test is
untouched — same path, same floor.

**New — `tests/test_work_order_report_xlsx.py`.** The renderer's purity
(X3) means the file needs no `db` fixture: it hand-builds frozen
`DailyReport` / `ReportRow` dataclasses with tiny local builders, which
sidesteps the dev-Postgres fencing the report tests need.

1. `test_data_sheet_matches_report_csv` — the load-bearing pin: Data
   cells, normalized (`None` → `""`, numbers stringified as csv does),
   equal `csv.reader(report_csv(payload))` row-for-row.
2. `test_headline_block_matches_the_payload_counts` — Block 1's four
   cells equal the four section counts.
3. `test_pipeline_block_zero_fills_by_status` — three lifecycle-ordered
   rows; an absent status reads 0; the total cell equals `closing.count`
   even when rows are capped.
4. `test_service_type_and_community_blocks_aggregate_closed_week` —
   known rows produce the expected sorted block rows, `None` bucketed.
5. `test_empty_report_renders_placeholders` — an all-empty payload
   builds; variable blocks show their `(none)` rows.
6. `test_workbook_contains_four_charts` — via `zipfile` over the bytes,
   `xl/charts/chart*.xml` count == 4 (§3 explains why not openpyxl).
7. `test_filename_is_the_covered_day` — `wo-report_2026-08-25.xlsx`.

---

## 8. Implementation order

1. **Dependency first:** install openpyxl into the backend venv, confirm
   import and version, pin in `requirements.txt`. Nothing else starts
   until this is real.
2. **Renderer, test-first:** write `test_work_order_report_xlsx.py`
   (red — module doesn't exist), implement §4/§5's module until green.
3. **Router, test-first:** rewrite the hub-router export test to expect
   xlsx (red against the CSV route), then flip `export_hub_report()`.
4. **Frontend label + `docs/endpoint-map.md` H7.**
5. **Full suite** (`python -m pytest -q` in `backend/`). The known
   environmental `test_cascade_deletes_with_user` failure on the dev DB
   is pre-existing and reported as such, not absorbed.
6. **Manual validation by the user** — Report tab → Download Excel →
   two sheets, four charts, numbers matching the screen. No preview
   server is auto-started.
7. **Commit to `main`** (after fetch/status check). **No push without an
   explicit go-ahead — push deploys.**

## 9. Risks and accepted trade-offs

- **New supply-chain surface:** openpyxl is the standard, widely-audited
  choice; pure Python; pinned exact like everything else in the file.
- **Charts are write-only** (§3): zip-level test plus a one-time visual
  check in real Excel is the verification story.
- **Money-as-text on the Data sheet** (X5): cosmetic Excel hints; charts
  immune (X7).
- **No one-click CSV:** save-as from Excel covers re-import; one line to
  add a second button later if it stings.
- **`closing` cap:** the Data sheet inherits the CSV's capped rows; the
  Summary's counts stay complete — today's posture, now with a warning
  cell.
