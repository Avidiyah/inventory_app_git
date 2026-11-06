# SMR weekly hours chart — design (2026-11-06)

Status: draft, awaiting go-ahead. Budget ≤ 1,800 words.

## Goal

A live chart at the top of the SMR work-orders tab, above the search, that
reproduces the weekly reports' picture from app data: per Mon–Sun week, three
bars — **Original** (NetFacilities charge before any audit), **Added** (paper
hours charged in the app), **Missing** (vendor hours invoiced but not yet on
an order) — each stacked by vendor.

## Series definitions

| Bar | Source | Week | Vendor |
|---|---|---|---|
| Original | each SMR order's `smr_baseline` labor hours (the frozen NetFacilities figure; D1) | `closed_week` (sheet COMPLETION DATE) | baseline `ASSIGNED TO`, mapped to a `VENDORS` name; unmapped → Unknown |
| Added | `smr_labor_lines` with `status = charged` (what S15 already sums) | `line.week` | `line.vendor` |
| Missing | `invoiced − placed` per vendor per week, floored at 0, where `placed` = Added for that vendor/week | invoice week | invoice vendor |

Orders without a close date count in a trailing "Undated" bucket for Original,
as the Hours tab does for lines without a week. Excluded lines never enter
the chart; the pile of undated paper is the Hours tab's business.

## New data: vendor invoices

The app holds no invoiced hours. One table, one upload, no edit UI.

`smr_vendor_invoices`: `id`, `vendor` (one of `VENDORS`), `week` (Monday
date), `hours` (Decimal), `source` (invoice number / file, free text),
`uploaded_at`, `uploaded_by_id`. Unique on `(vendor, week, source)`.

Upload: `POST /work-orders/smr/invoices` (Owner), CSV with columns
`vendor,date,hours,source`. Dates land in the Mon–Sun week containing them;
rows for a given `source` replace that source's earlier rows (rerun-safe,
same rule as the targets import). The CSV is produced from the
reconciliation folder's `SMR27 Timesheets.xlsx` invoice lines; the Owner
keeps it with the other load CSVs.

## Endpoint

`GET /work-orders/smr/weekly-hours` (Admin+, same gate as S15). Returns

```
{ weeks: ["2026-05-25", ...],            // Mondays, ascending, "" = undated
  vendors: ["Green Choice", ...],         // only vendors that appear
  cells: [{week, vendor, original, added, invoiced, missing}] }
```

One service function, pure aggregation over the three reads above. No
caching; the population is a few thousand rows.

## Chart

Dependency-free inline SVG in a new `smrWeeklyHours.js` (hubGraphs.js's
`niceStep` / axis pattern reused; no chart library). One group per week,
three stacked bars, vendor colours fixed in one map so a vendor keeps its
colour across every bar and the legend. Hover tooltip names vendor + hours
(existing `tooltip.js`). Legend lists vendors; axis labels are the week
labels the Hours tab already prints. Figures under the chart in a small
table (week × bar totals) so the numbers are readable without the picture,
per the self-explanatory-UI rule. CSP: no inline `style=`; colours via
classes.

Placement: a collapsible panel above the search row on the SMR tab, open by
default, state remembered in localStorage like the chip rows. Admin+ only;
below Admin the panel is absent.

## Not in scope

- Editing invoices in the app (re-upload the CSV).
- Money. Hours only.
- Per-worker breakdown (Hours tab).
- Charts on the Hub or report workbook.

## Tests

- Service: one order with baseline 10 h closed 06/10, one charged line 4 h
  GC week 06/08, invoice GC 06/08 30 h → cell original 10 / added 4 /
  invoiced 30 / missing 26; a second invoice source adds, a re-upload of the
  same source replaces; undated close → "" week.
- Route: Owner upload 200, Admin 403; bad vendor / date 400 names the row.
- Vitest: module renders one `<g>` per week and a legend row per vendor from
  a fixture payload.
