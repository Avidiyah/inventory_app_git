# SMR27 paper check — design

Date: 2026-10-27. Status: approved decisions, awaiting go-ahead. Extends
`2026-10-23-smr-target-match-design.md` (targets, Short / Matched, the
editor's target lines all exist; this adds "I checked this order against
its paper").

## Intent

The paper work orders are now in hand. An order that is Short gets its
labor and material keyed from the paper in the normal editor. Today nothing
records that the paper was checked: an order whose paper doesn't cover the
client's number stays Short forever and looks exactly like one nobody has
looked at. This adds a per-order **paper checked** mark, separate from
Edited (billables changed), Matched (at target) and Archived (finished).

The two working lists it unlocks:

| List | Meaning |
|---|---|
| Short, not checked | the stack still to key from paper |
| Short, checked | paper keyed and the order is still below target: raise with the client |

## Goals / non-goals / anti-goals

| Goals | Non-goals | Anti-goals |
|---|---|---|
| Set / clear the mark from the editor, one click | Bulk check from the SMR page | The mark changing Edited, Matched, baseline or archive state |
| Mark visible on the tile, counted in the bar, filterable | Any per-line "from paper" tagging | A confirm dialog (undo over guardrails: clearing the mark is the undo) |
| Export carries who and when | Storing a scan of the paper | The mark leaking onto non-SMR orders |

## Decisions

| # | Decision | Owner |
|---|---|---|
| 1 | A per-order mark with timestamp and who set it, toggled on and off. | user (option A) |
| 2 | **Any signed-in role** sets or clears it (all hands). | user |
| 3 | Short keeps its meaning; a separate **Checked, still short** filter is added. | user |
| 4 | Clearing the mark wipes the who/when; no history kept (git-style audit not needed for a working flag). | Claude |
| 5 | The mark never auto-clears when lines change after checking. Re-keying after a check is normal. | Claude |

## Data

Two nullable columns on `work_orders`, one Alembic migration, no backfill:

| Column | Type | Content |
|---|---|---|
| `smr_paper_checked_at` | timestamptz | set when marked, NULL when cleared |
| `smr_paper_checked_by_id` | FK `users.id`, `ON DELETE SET NULL` | who marked it |

Plain columns, not JSONB: two fields, and the user FK must null out on user
delete (cascade test `test_cascade_deletes_with_user` stays green).

## API

`PUT /work-orders/smr/{work_order_id}/paper-check`, body `{ "checked": bool }`
→ `SmrPaperCheckOut { checked_at, checked_by_name }`.

- 404 when the order doesn't exist; 422 when it has no `smr_imported_at`.
- Idempotent: `checked: true` on a checked order keeps the original who/when.
- Any signed-in role (D2). One line in `docs/endpoint-map.md` (S5).

`WorkOrderDetail` gains `smr_paper_check: Optional[SmrPaperCheckOut]`.
`SmrTile` gains the same. `SmrCounts` gains `paper_checked` and
`short_checked` (has a target, not matched, checked).

## Editor

Only when `detail.smr`. One button in the Materials section, under the
target materials line (`targetMaterialsHtml`), since that is where the
last paper line gets keyed:

| State | Button | Line beside it |
|---|---|---|
| unchecked | **Mark paper checked** | — |
| checked | **Clear paper check** | `Paper checked by J. Smith · Oct 27, 2:14 PM` |

Click → PUT → card re-renders through the existing detail refresh. Presenter
`paperCheckHtml(detail)` in `workOrderPresenters.js` (374 lines); click
wiring beside the card's existing SMR handlers. No inline styles (CSP).

## SMR page

| Element | Change |
|---|---|
| Bar | adds `N PAPER CHECKED` · `N CHECKED, STILL SHORT` |
| Filters | adds **Checked, still short** and **Paper checked** after Short; Short unchanged |
| Tile | a `PAPER ✓` badge on checked tiles (`smr-tile--checked` class) |
| Default view | stays Untouched |

Client-side filtering like the existing six: `matches(tile, "checked")` =
`Boolean(tile.paper_check)`; `"short_checked"` = short and checked.

## Export

Orders sheet appends after `TARGET IMPORTED AT`: `PAPER CHECKED`
(Yes / blank), `PAPER CHECKED AT`, `PAPER CHECKED BY`.

## Constraints

- No new dependencies, no new tables. Files under 500 lines (`smr.js` 188,
  `work_orders_smr.py` service 338, router 120).
- Targeted tests only: toggle on / off / idempotent, 422 on non-SMR, role
  gate, user delete nulls the FK, tile + detail carry the mark, counts,
  export columns, Vitest for the presenter and the new filter,
  `staticImports` guard green.
- Deploy is production: ask before pushing main.

## Left to the builder

- Exact button copy and badge styling within `docs/design-system.md`.
- Alembic revision id.
