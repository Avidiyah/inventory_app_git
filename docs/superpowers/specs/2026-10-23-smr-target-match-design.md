# SMR27 target match — design

Date: 2026-10-23. Status: draft for approval. Extends
`2026-10-23-smr-audit-workflow-design.md` (the SMR import, page, Skilled
Technician labor and export all exist; this adds the number to aim at).

## Intent

The client's own reconciliation sheet, `SMR27 Work Order Breakdown & Labor
Hours`, states per work order the labor hours and material dollars they
expect to be charged ($428,152.94 in total). The client knows we
under-charged. The job on the SMR page is to bring every order up to that
sheet. Today the editor shows what an order carries and the tile shows the
change since import; neither shows how far the order still is from the
client's number. This adds a per-order **target** from the Breakdown sheet
and shows target / current / remaining wherever an Admin re-charges.

## Goals / non-goals / anti-goals

| Goals | Non-goals | Anti-goals |
|---|---|---|
| Import hours, labor $, material $ per order from the Breakdown sheet | Parsing the main sheet's free-text "1.5 SL hours, 1/2 bag mud" prose | Touching the frozen baseline or the Edited derivation |
| Editor shows target, current, remaining, matched state while editing | Creating orders from the Breakdown sheet | A match rule that calls an under-charged order matched |
| Tile and top bar show remaining and a Matched count / filter | Auto-adding labor or material lines to hit the target | Target rows attaching to non-SMR orders |
| Export carries target and gap columns | Any change to live Work Orders surfaces | |

## The Breakdown sheet (input contract)

| Fact | Value |
|---|---|
| Headers read | `WO#`, `Hours`, `Labor $`, `Total Material Cost`, `Total L&M`; `Unit#`, `Closed Date`, `Labor Type` and the HRS columns ride along in `source_row` |
| Rows | 690 with a WO#, plus one footer row with blank WO# and grand totals (skipped) |
| Hours | 0.5-hour steps; 13 rows at 0 |
| Labor $ | `$62.50 × Hours` on all but 3 rows; imported as given, never recomputed |
| Money | `$1,656.25` style: strip `$` and `,`; blank = 0 |
| Duplicates | 7 WO#s appear twice: **last row wins** (user) |
| Unknown WO#s | 22 are not SMR orders: **skipped and counted**, never created (user) |
| Coverage | 27 SMR orders have no row: they carry no target and never count as matched or short |
| Encoding | UTF-8, optional BOM, optional `sep=,` line (same preflight as the SMR import) |

## Decisions (as made)

| # | Decision | Owner |
|---|---|---|
| 1 | Source is the Breakdown sheet; targets attach only to orders already carrying `smr_imported_at`. | user |
| 2 | Duplicate WO#: last row wins. | user |
| 3 | Match = hours **and** material each within a band, **undershoot only**: overshoot is matched. Hours band 0.5 h; material band $10. | user |
| 4 | Visible in the editor, on the SMR tile and bar, and as gap columns in the export. | user |
| 5 | Current hours for the match are **billed** minutes, real + skilled, since that is what the client is charged. | Claude |
| 5a | The sheet's Total Material Cost is the receipt figure **with the 15% mark-up applied**, so current material for the match is `materials_total × 1.15` (the `+15%` number the card already prints), not the base total the tiles and export print elsewhere. | user |
| 6 | Re-importing targets overwrites them (they are the client's number, not an audit record); the baseline is untouched. | Claude |
| 7 | Labor $ and Total L&M from the sheet are stored and exported but play no part in the match rule; hours drive labor. | Claude |

## Data

One nullable column on `work_orders`, one Alembic migration, no backfill:

| Column | Type | Content |
|---|---|---|
| `smr_target` | JSONB | `{ "imported_at", "hours", "labor_total", "materials_total", "total", "source_row": {<every Breakdown column verbatim>} }`; numbers as strings (Decimal-safe), same convention as `smr_baseline` |

Why JSONB again: one write per order, read whole, never queried by field.

## Domain (`domain/work_orders_smr.py`)

Pure functions, no DB:

- `parse_target_row(row) -> dict | None`: `None` for a blank WO#; otherwise
  `{number, hours: Decimal, labor_total, materials_total, total, source_row}`.
  Money parser strips `$`, `,`, whitespace. Rejects a non-numeric cell with
  `WorkOrderStateError` naming the WO# and column.
- `TARGET_HOURS_BAND = Decimal("0.5")`, `TARGET_MATERIAL_BAND = Decimal("10")`.
- `target_gap(target, snapshot_totals) -> dict`: for hours and material,
  `current`, `target`, `gap = current − target` (signed, negative = short),
  `remaining = max(0, −gap)`; plus `matched` =
  `remaining_hours ≤ 0.5 and remaining_material ≤ 10`. Hours current =
  `(real_billed_minutes + skilled_billed_minutes) / 60`; material current =
  `materials_total × receipt.MARKUP_RATE` (`domain/receipt.py`, the same
  `Decimal("1.15")` the receipt and the card's `+15%` span already use).
  Returns `None` when the order has no target.

## Import (`POST /work-orders/smr/import-targets`, Owner)

Same shape as `import_smr`: `read_capped`, UTF-8 / `sep=,` / header
preflight (`WO#`, `Hours`, `Total Material Cost` required exactly once), all
rows parsed before any write, one commit.

Per row: blank WO# → skipped. Number not an SMR order (`find_by_number` is
`None` or `smr_imported_at` is `None`) → `unknown`, number collected. Else
`smr_target` is written (overwrite). Later duplicates simply overwrite
earlier ones, which is "last row wins" for free.

Result: `total, targeted, skipped, unknown, unknown_numbers` (first 50).

UI: a second Owner-only button **SMR Labor Import** beside **SMR Import** in
the NetFacilities card, same file picker pattern, its own `tips.js` entry.
Message on success: `Targets set on N orders · M unknown WO#s skipped`.

## Responses

`WorkOrderDetail` (editor) gains `smr_target: Optional[SmrTargetOut]`:

```
SmrTargetOut { hours, labor_total, materials_total, total,
               current_hours, current_materials_total,
               gap_hours, gap_materials_total,
               remaining_hours, remaining_materials_total, matched }
```

Cost fields follow the existing redaction: `None` below TechFM OA, same as
`materials_total`. `SmrTile` gains the same `target: Optional[SmrTargetOut]`.
`SmrCounts` gains `matched`, `short`, `no_target` (short = has target, not
matched). `SmrTilesResponse` gains `remaining: {hours, materials_total}`
summed over the population.

## Editor (`workOrderCardHtml.js` / `workOrderPresenters.js`)

Only when `detail.smr` and `detail.smr_target` is set. One presenter,
`targetSummaryHtml(detail)`, rendered twice: under `laborSummaryHtml` in the
Labor section and under the materials total in the Materials section, each
showing its own number:

```
Client sheet: 2.0 h   ·   Charged: 1.5 h   ·   Remaining: 0.5 h   ✓ Within 0.5 h
Client sheet: $67.16  ·   Charged (+15%): $0.00   ·   Remaining: $67.16  Short by $67.16
```

The material line's `Charged` is the marked-up figure (D5a), the same
number the `+15%:` span above it shows, so the two never disagree.

The card re-renders after every add / update / remove already, so the line
tracks edits with no new wiring. A `wo-target--matched` / `wo-target--short`
class ladder colours the state text (CSP: no inline styles). Plain words,
no legend (self-explanatory UI memory).

## SMR page

| Element | Change |
|---|---|
| Bar | adds `N MATCHED` · `N SHORT` · `N NO TARGET` · `REMAINING 123.5 H` · `REMAINING $4,567.89` |
| Filters | **Short** button added after Untouched; order: Untouched · Short · Edited · Archived · Matched · All |
| Tile | third line becomes the remaining-to-target when a target exists: `0.5 H · $67.16 TO GO` or `MATCHED`; the existing delta stays. No target → `NO TARGET` |
| Default view | stays Untouched |

`matches(tile, "short")` = target present and not matched; `"matched"` =
target present and matched. Both client-side like the existing four.

## Export

Orders sheet appends, after the DELTA triples and before the trail:
`TARGET HOURS`, `TARGET LABOR $`, `TARGET MATERIAL $`, `TARGET TOTAL`,
`GAP HOURS`, `GAP MATERIAL $`, `MATCHED`, `TARGET IMPORTED AT`. Gaps are
signed current − target (negative = still short), numbers not strings; the
material gap uses the marked-up current (D5a), and a `MATERIALS +15% AFTER`
column is added beside it so the subtraction is visible in the sheet. Blank
when the order has no target. Every Breakdown `source_row` column also
rides along verbatim, prefixed `BREAKDOWN `, after the main sheet's columns.

## Constraints

- No new dependencies, no new tables. Files under 500 lines; `smr.js` is at
  165 and `workOrderCardHtml.js` at 574 (already over; put the presenter in
  `workOrderPresenters.js`, 328).
- Targeted tests only before push: target-row parsing (money, blanks, last
  row wins), unknown WO# skipped not created, Owner gate, `target_gap` on
  short / within-band / overshoot / no-target, detail and tile carry the
  target, export columns, `staticImports` guard stays green.
- Deploy is production: ask before pushing main.

## Builder-check calls (Claude's, overridable)

- Hours compare on **billed** minutes (D5). Actual minutes would show a
  50-minute entry as short of a 1.0 h target the client is in fact charged.
- An order with real-technician hours above the target and zero skilled hours
  is matched on hours; nothing asks the Admin to remove labor.
- `unknown_numbers` is capped at 50 in the response; the full count is always
  returned.
- The Breakdown `Closed Date` (mixed `05/21/26`, `0602/26`) is stored verbatim
  and never parsed.

## Left to the builder

- Exact copy of the two editor lines and the tile's third line.
- Whether `SmrTargetOut` lives in `schemas/work_orders_smr.py` and is imported
  into `schemas/work_orders.py`, or the reverse (avoid a cycle).
- Alembic revision id; one line in `docs/endpoint-map.md` for the new route.
