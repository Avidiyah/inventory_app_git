# SMR27 paper stage — design

Date: 2026-11-06. Status: draft, builder-checked inline, awaiting the user's approval.
Extends `2026-11-04-smr-paper-import-design.md` (lines, readings, blocks, Hours tab) and
replaces the status model of `2026-10-23-smr-audit-workflow-design.md` on the SMR page.

## Intent

The SMR page still describes an order the way NetFacilities does: a lifecycle Status
dropdown (Created … In-Progress … Completed) and an Edited / Untouched outline. Neither
says where the order's **paper** stands, which is the only question the reconciliation
asks now. Nothing is "in progress"; every order sits in a physical pile, and the pile is
its status.

The piles (`paper_stacks.py`, the Stack Check page) are: a dated folder per invoice week
(Before Week 1, Week 1–7), an undated pile sorted by NetFacilities close week, and the
unreviewed remainder. This design makes the app say the same thing: every SMR order is
at one **stage** of a four-step chain, sits in one **week bucket**, and can be filtered
by either, or both.

## Goals / non-goals / anti-goals

- **Goals.** Status on the page is derived from the paper record. The chain is visible
  without a legend. Green means exactly one thing: a person said this order is ready for
  invoice. Not-reviewed orders are the default view, since they are the next pile to work.
- **Non-goals.** No change to lines, readings, blocks, the Hours tab or the export's
  Labor sheets. No change to the Work Orders page or NetFacilities status anywhere else.
  No automatic promotion to Ready.
- **Anti-goals.** An order reaching green by any rule other than the button. A stage that
  needs the Breakdown target or the block to compute. Color without a word beside it.

## Decisions (user, 2026-11-06)

| # | Decision |
|---|---|
| 1 | The chain is **Not reviewed → Paper reviewed, undated → Paper reviewed, dated → Ready for invoice**. Not reviewed comes first and is the default filter. |
| 2 | A paper-reviewed order joins its weekly bucket if dated, else the undated bucket. |
| 3 | **Ready for invoice** is pressed by a person, never derived, and only an order in a dated bucket offers the button. |
| 4 | A **Belfor-only** pile cuts across the week buckets, dated and undated alike: orders whose hours are all Belfor employees. |
| 5 | The paper-review lines are the only labor entries shown on an SMR order; the NetFacilities record stays as the read-only "before" figure the 2026-11-04 design already gives it. |
| 6 | Green is reserved for Ready for invoice. Today no order is green. |
| 7 | Any line with a week places the order, charged or excluded alike: the paper is in that folder. |
| 8 | Before W1 and After W7 are dated buckets like Week 1–7 and offer the Ready button. |
| 9 | Ready for invoice / Not ready are Admin and Owner, the same gate as the line editor. |

## Stage: the rule

Derived per order from readings and lines (removed lines aside), in this order:

| Stage | Rule | Label on the tile |
|---|---|---|
| `ready` | `smr_ready_at` set **and** the order is dated (below) | Ready for invoice |
| `dated` | any line carries a week (dated, or a placement basis with its week) | Reviewed · dated |
| `undated` | at least one reading, no line with a week | Reviewed · undated |
| `not_reviewed` | no readings | Not reviewed |

A `ready` stamp on an order that later loses every dated line is kept but not shown: the
tile falls back to `undated` and the card says "Ready stamp held until a line is dated"
(my call; it avoids silently deleting a person's decision when a date is corrected).

The old `edited` flag and `smr_paper_checked_at` play no part in the stage. Both stay in
the API and export; the tile stops showing them.

## Week bucket

- `weeks` on the tile is already the sorted list of line week labels (`Before W1`,
  `Week 1`–`Week 7`, `After W7`), `Undated` last or alone. Unchanged.
- An undated order (stage `undated` or `not_reviewed`) also carries `closed_week`: the
  label of `week_of(work_order.completed_at)`, blank when there is no close date. The
  tile shows it as the undated bubble's text: **Undated · closed Week 3**. This is the
  undated pile's own sort key, so the screen and the pile agree.
- `belfor_only`: true when the order has at least one non-removed line and every one is
  vendor `Belfor`. Admin lines never reach an order, so they cannot break it.

## Filters (page)

Three chip rows replace the one row and the Status dropdown. Each row is single-select
with an **All** chip; the rows combine (AND). The other filter fields (priority, Team
Lead, technician, community, scheduled date, search boxes, sort) stay.

| Row | Chips | Default |
|---|---|---|
| Stage | Not reviewed · Reviewed, undated · Reviewed, dated · Ready for invoice · All | Not reviewed |
| Pile | Before W1 · Week 1 … Week 7 · After W7 · Undated · Belfor only · All | All |
| Flags | Short · Matched · Block pending · Archived · All | All |

Pile chips match an order whose `weeks` contains the label; `Undated` matches
`weeks` containing `Undated`; `Belfor only` matches `belfor_only`. An order spanning two
weeks appears under both. Dropped chips: Untouched, Edited, Paper checked, Checked still
short, Has lines (Has lines ≡ not `not_reviewed`). The saved-chip memory in
`smrFilters.js` becomes three keys, one per row.

The Status `<select>` leaves `pages/smr.html`, `smrFilters.js` and the server query
params; `test_smr_tiles.py` loses its status case.

## Tile

```
[Week 2] [Week 3]                      [Reviewed · dated]   <- weeks left, stage pill right
23281234                                                   <- number
Centennial 631 · Green Choice                              <- where · vendor assignee
+$2,640.00                                                 <- delta
+42.0 h · v2 pasted                                        <- third line, unchanged
184 min · 6 lines              [Belfor]                    <- meta; Belfor tag when belfor_only
```

Outline and pill color by stage, always with the pill's words:

| Stage | Outline / pill fill | Token |
|---|---|---|
| Not reviewed | red | `#B91C1C` keycap (today's untouched) |
| Reviewed · undated | amber | `--status-dispense` fill, `--status-dispense-text` outline |
| Reviewed · dated | neutral | `--panel-border` outline, `--gray-500` pill (today's archived gray) |
| Ready for invoice | green | `#15803D` keycap (today's edited) |

The Undated bubble keeps its dashed style and gains the closed-week text. The `Paper ✓`
badge and the Edited / Untouched classes go. Archived keeps its dashed, dimmed treatment
on top of the stage color. Amber on tiles is a deliberate second exception to the
"status accents are badge-only" rule, recorded in `docs/design-system.md` in the same
commit: the SMR page's outlines already carry red/green status.

## Bar

Stage counts lead: `N not reviewed · N undated · N dated · N ready · N Belfor only`,
then the existing `charged h · excluded h · blocks not pasted · remaining · Δ labor ·
Δ material · Δ total · imported`. Dropped cells: edited, untouched, matched, short, no
target, paper checked, checked still short, with lines (Short and Matched remain as
chips; their counts are the result count when the chip is on).

## Card (SMR orders)

In the Paper corrections section, under the totals line, a **Ready for invoice** row:

- Stage `dated`, not ready: button **Ready for invoice** (`secondary-btn`, Admin+).
  Pressing it stamps the order and reloads the card; no confirm dialog (reversible).
- Ready: text `Ready for invoice · 11/08/26 by JM` with a **Not ready** button beside it.
- Stage `undated` or `not_reviewed`: the row reads `Date a line to mark ready` (muted), no
  button. Dating a line in the editor reveals the button on the reload.

The NetFacilities Labor section on an SMR order with readings renders collapsed and
read-only under its existing "NetFacilities Record Before Correction" heading (decision
5); on an SMR order with no readings it is unchanged.

## Data and API

- `work_orders` gains `smr_ready_at` (timestamptz, null) and `smr_ready_by_id` (FK users,
  SET NULL), the `smr_paper_checked_*` pattern; one Alembic migration.
- `POST /work-orders/smr/{id}/ready` body `{ready: bool}`, Admin+, beside `paper-check`.
  `ready: true` on an order whose stage is not `dated` → 409 "Date a line first". Returns
  the tile. Stamping is idempotent; clearing nulls both columns (no history row: the
  stamp itself is the who/when, the same as the paper check — my call).
- `SmrTile` gains `stage`, `closed_week: Optional[str]`, `belfor_only: bool`,
  `ready: Optional[{at, by_name}]`. `SmrCounts` gains the five stage counts; the eight
  dropped bar cells leave the schema.
- `WorkOrderDetail` gains `smr_stage` and `smr_ready` (same shape) for the card.
- Export Orders sheet appends `STAGE`, `READY AT`, `READY BY`, `BELFOR ONLY`.
- Tile `status` (NetFacilities) stays in the payload for the export; the `status` query
  param is removed.

## Tests

- `test_smr_tiles.py`: stage for each rule (no readings; reading with no dated line;
  dated line; placement-basis line with a week; ready on dated; ready stamp held on an
  order that loses its date); `closed_week`; `belfor_only` true / false / no lines;
  ready endpoint 409 on undated, stamp and clear, Admin gate.
- `smr.test.js`: three rows combine; defaults; dropped chips absent; tile markup carries
  the stage label text and the closed-week bubble; the bar leads with stage counts.
- Served-source test for the removed Status select (`staticImports`-style guard not
  needed: markup only).

## Left to the builder

Chip row markup and spacing; the exact amber keycap shadow values; whether the stage
label on the card is a pill or plain text; the migration id; splitting `smr.js` if the
three rows push it past 500 lines (the filter rows belong in `smrFilters.js`).

## Deviations

(log here, dated, as the build departs from the above)
