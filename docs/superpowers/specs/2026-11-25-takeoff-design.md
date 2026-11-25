# Takeoff — predicted material per work order

Status: approved for planning · 2026-11-25 (preview: `2026-11-25-takeoff-preview.html`)

## Intent

Big projects (e.g. WMR service types) need material bought before
the work starts. Mass Stage was built for that and is not needed; it is
retired in a separate project. Takeoff replaces it: admins and Team Leads
predict the material for one work order at a time from the catalogue, the
office sees the combined need per service type on one page, records what was
purchased, and technicians turn predictions into real dispenses with one tap.

"Takeoff" is the trade term for estimating material; picked over "Stage" so
nobody reads it as physically putting material in a unit.

## Goals

- Predict material per work order, catalogue-driven, entered like Add Item.
- One overview page: what each service type needs, what it costs, what is on
  the shelf, what is on the way, and how much more to order.
- One-tap dispense from a takeoff line on the work order.
- A work-order card that works on a phone: pinned task + location and a
  top icon bar (see Work-order top bar).

## Non-goals

- Templates per service type (each order is predicted on its own).
- Purchase orders, vendors, receiving paperwork.
- Retiring Mass Stage (own project).
- Retiring SMR-specific code (own project; Takeoff adds no SMR branches — every service type is standard).

## Anti-goals

- Predictions must never change stock, billing, invoices or materials
  totals. They live in their own tables, never in `work_order_items`.
- No SMR special cases in anything new.

## Approaches considered

| Approach | Verdict |
|---|---|
| **Own tables for takeoff lines and purchases; overview computed on read** | **Picked.** Matches "bought 100 for a need of 80" and "arrival clears it" exactly. |
| Ordered quantity stored on each takeoff line | Dropped: assumes you buy exactly what is needed. |
| "Predicted" flag on `work_order_items` | Dropped: those lines feed billing. |
| Reuse Mass Stage tables | Dropped: keyed by community/building with a load lifecycle, not by work order. |

## Data

New Alembic migration, two tables.

**`work_order_takeoff_lines`**
- `id`, `work_order_id` (FK, cascade on delete), `item_id` (FK, restrict),
  `quantity` (Numeric, remaining, > 0), `created_by_id`, `created_at`,
  `updated_at`.
- `UNIQUE(work_order_id, item_id)`: adding an item already on the order adds
  to its quantity (same aggregate rule as `attach_dispense_line`).
- A line reaching zero is deleted.

**`takeoff_purchases`**
- `id`, `item_id` (FK, restrict), `service_type_key` + `service_type_label`
  (from `domain.work_orders.normalize_service_type`), `quantity_on_the_way`
  (Numeric, > 0), `created_by_id`, `created_at`, `updated_at`.
- `UNIQUE(item_id, service_type_key)`: one on-the-way figure per row of the
  page. Ticking adds to it; editing sets it; 0 deletes it. `created_at` is set
  on insert only and orders the arrival count-down.

## Work-order card (Takeoff section, under More)

```
Takeoff · 3
 Toilet       1 left of 4       [Dispense]
 Supply line  4 left of 4       [Dispense]
 + Takeoff item   (Team Lead+)
```

- **Takeoff** is its own section (`id="wo-sec-takeoff"`), reached from the top
  bar's More menu as "Takeoff · N" (N = lines left). Listed in More for every
  order a Team Lead+ views, and for anyone when the order has lines.
- **+ Takeoff item**: same catalogue search + quantity UI as Add Item
  (`ms-item-search` chooser); writes a takeoff line, moves no stock. Roles:
  Team Lead (`supervisor`) and up.
- Each line can be edited (quantity) or removed by Team Lead+.
- **Dispense**: opens the quantity pre-filled with the remaining amount,
  editable. Submitting runs the existing Add Item dispense (same endpoint
  logic, entry mode, crew rules, short-stock recount request) and, in the same
  DB transaction, reduces the takeoff line by the dispensed quantity (deleted
  at zero; dispensing more than remains just zeroes it). Who may tap it: the
  same people who may add material to that order today.
- Completed orders keep their takeoff block, read-only.
- The card's existing live-update path must refresh the block when another
  session changes it.

## Takeoff page (new, admin)

Nav entry "Takeoff". Roles: Owner, Admin, TechFM OA (same gate as Admin
Review).

```
WMR
 Item         Need   Price   Total    Stock  On the way  Ordered
 Toilet        110   $120   $13,200     12      100      ☐ Order 10 more
   ↳ WO 1042 ×4 · WO 1043 ×4 · …
 Supply line    40   $8     $320        60        —      ☑ Covered
Plumbing
 …
```

Grouped by service type (normalized; blank → "Unspecified"), then one row per
item. Each row shows:

| Column | Source |
|---|---|
| Need | Sum of takeoff line quantities on that type's work orders **not Completed** (archived orders also excluded) |
| Price | `Item.price` now |
| Total | Need × Price |
| Stock | `Item.quantity` |
| On the way | Sum of `takeoff_purchases` for that item and service type |
| Item link | The item's `product_link` (vendor buying page, as on the Low Stock card); plain text when blank |
| Ordered | Checkbox + shortfall text |
| Work orders | Expandable list of order numbers × quantity, each opening the card |

**Shortfall** is computed per item across all service types so shared stock
is not counted twice:
`shortfall = max(0, total need for item − stock − total on the way for item)`.
Every row of that item shows the same shortfall.

**Ordered checkbox**
- Checked ("Covered") when the item's shortfall is 0 and at least one
  purchase or enough stock exists; unchecked with "Order N more" otherwise.
- Ticking it asks "How many did you order?" (pre-filled with N, editable, can
  exceed N) and adds it to that row's `takeoff_purchases` figure.
- A later takeoff addition that pushes need past stock + on the way unchecks
  it automatically, because it is computed on read.
- The On-the-way number can be edited or cleared from the row (a cancelled or
  wrong purchase).

## Arrival clears purchases

In `services.transactions.apply_transaction`, when `transaction_type ==
"stock"`, reduce that item's `takeoff_purchases` by the stocked quantity,
oldest `created_at` first, across service types, deleting rows that reach
zero. Any surplus stocked quantity is ignored. Same DB transaction and the
item row lock already taken there.

- A partial delivery (50 of 100) leaves 50 on the way.
- An unrelated restock of the same item also counts purchases down. Accepted.
- Corrections (`adjust`), voids, and line-removal stock restores do **not**
  touch purchases.

## API

- `POST /work-orders/{id}/takeoff`, `PATCH|DELETE /work-orders/{id}/takeoff/{line_id}` (Team Lead+).
- Dispense: `POST /work-orders/{id}/items` gains optional `takeoff_line_id`.
- `GET /takeoff/` overview; `PUT /takeoff/purchases` sets one row's on-the-way figure (OA+).
- `WorkOrderDetail` gains `takeoff: list[TakeoffLineOut]`.

## Work-order top bar

Every service type gets the same card (no SMR branches in new code).

```
Replace toilet, running constantly        ← task (description), pinned
Scholars · Bldg 4 · Unit 212   ● In progress  WO 1042
[Materials] [Labor] [Notes] [Photos] [More ▾]   ← icon + word + count
```

- **Pinned header** (`.wo-pin`, sticky under the app header while the card
  page scrolls): task, location, status chips + WO number, then the icon bar.
  On the card page the old summary row is hidden; the pin replaces it.
- **Icon bar:** Materials · N, Labor · h, Notes, Photos · N, More. Inline SVG
  icons (CSP: no icon fonts) above the word; the count under it. Labor stays
  hidden for viewers who cannot see it today (bar shows four).
- **More menu:** Details; Takeoff · N; Invoice (only on orders that have one,
  until the SMR removal project deletes it); then the old ⋯ contents (admin
  tools, Edit details). One More on the card.
- **Default section** on open: Materials (Notes when unread prior-work notes
  gate the card, as today). Details is a section like any other.

## Constraints

- New routes must be added to the memprobe route catalogue; the
  change-sensitive tests list (card tab / detail field / new route / page
  loader) applies.
- CSP: no inline styles; class ladder.
- No horizontal scroll: on phones each overview row reflows to a stacked card
  (item, need × price = total, stock / on the way, checkbox).
- `workOrder*.js` line cap: new card code goes in its own modules
  (`workOrderTakeoff.js`, `workOrderTopBar.js`); new page in `views/takeoff.js`.
- Self-explanatory UI: column labels as words, "Order 10 more" rather than a
  bare number.

## Calls made by the designer (check these)

- Team Lead+ adds takeoff lines; OA+ sees the Takeoff page.
- Voiding a takeoff-born dispense does not restore the takeoff line.
- Archived orders are excluded from Need like Completed ones.
- Purchases remember the service type they were entered on (for the On the
  way column) but shortfall pools by item.
- No tutorial in this project; add one to the tutorials backlog.
- The card opens on Materials; the old ⋯ menu folds into More.
- Tick adds to the row's on-the-way figure; editing replaces it.

## Left to the builder

Migration ids, endpoint paths and payload names, module split, test layout,
exact copy.
