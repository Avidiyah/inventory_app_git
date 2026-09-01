# Low Stock Alerts — design

An item whose on-hand count falls to or below a per-item threshold raises a
Web Push notification to every TechFM OA and above, and appears on a new
Low Stock page in the Review nav group where that threshold can be retuned.

## 1. Decisions

Settled in brainstorming; recorded so they are not re-argued.

| Question | Decision |
| --- | --- |
| When does a push fire | Edge only: the item was **not** low before the write and **is** low after |
| Threshold storage | `items.low_stock_threshold`, `INTEGER NOT NULL`, existing rows backfilled to `6` |
| Threshold range | Whole numbers, minimum 1. No mute value — every item alerts at some level |
| Trigger sites | Scan/dispense, correction/adjust (incl. void), Mass Stage load, work-order item lines |
| Push audience | TechFM OA and above, **including the actor** |
| Push text | Names the item: `"<name> is down to <n>."` One push per item; no batching |
| Threshold raised past current stock | Pushes, exactly like a stock drop |
| Item created/restored already low | Appears in the list, sends nothing |
| Page audience | TechFM OA+ for both viewing and editing |
| Page contents | Only items currently at or below their own threshold |
| Page freshness | Live, over the existing realtime socket |
| 7-day usage | Every non-voided `dispense` row in the last 168 hours, retroactive included; renders `0` when none |

**Consequence worth stating once:** because a threshold raise counts as a
crossing, the whole rule is one pure comparison over `(quantity, threshold)`
before and after a write. There is no armed-state column, no cooldown
timestamp, and no scheduler. The threshold column is the only new state.

## 2. Data

One column on `items`:

```
low_stock_threshold  INTEGER  NOT NULL  DEFAULT 6  CHECK (low_stock_threshold >= 1)
```

Alembic migration: add with `server_default="6"` so existing rows backfill in
the same statement. The `server_default` stays on the column — it is what
makes `create_item` default correctly without the service naming the number.
`6` is written once, in the migration and as the model default; nothing else
in the codebase may hardcode it.

`quantity` is `Numeric` and the threshold is an integer. The comparison
`quantity <= threshold` is valid across the two, and an integer threshold is
what the input field can validate simply. This is a deliberate asymmetry, not
an oversight: a decimal threshold buys nothing a whole number does not.

## 3. The rule (pure domain)

New module `app/domain/low_stock.py`. No SQLAlchemy, no FastAPI.

```python
def is_low(quantity, threshold) -> bool
def crossed_into_low(*, quantity_before, threshold_before,
                        quantity_after,  threshold_after) -> bool
def membership_changed(...) -> bool
```

`crossed_into_low` is `not is_low(before) and is_low(after)` — the push
predicate. `membership_changed` is `is_low(before) != is_low(after)` — the
realtime-invalidation predicate, which fires in both directions so an item
restocked back above its threshold disappears from open Low Stock pages.

Taking both a before and an after *threshold* is what makes the
threshold-raise case fall out of the same function rather than needing a
second code path.

## 4. The trigger (approach B — chokepoint)

New module `app/services/low_stock.py`. Three stock-writing services gain
**one line** at each of their six `item.quantity` mutation points:

| Service | Line today |
| --- | --- |
| `services/transactions.py` | `create_transaction` (~:83), `create_correction` (~:340), and the void/reverse path |
| `services/mass_staging.py` | ~:471 |
| `services/work_orders.py` | ~:3265 (line edit auto-correct), ~:3335 (return-unused, re-arm only) |

Each site calls `low_stock.record(item, quantity_before=...)` immediately
after the mutation, while the row is still locked and the session is alive.
`record` evaluates the pure predicates and appends a **plain-value** snapshot
— `(item_id, name, quantity_after, crossed)` — to a request-scoped buffer.
Nothing lazy is retained, which is what keeps rule 4 of
`adding-a-notification-trigger.md` satisfied downstream.

**Why one line at each site rather than an ORM hook:** a `before_flush`
listener would catch every write for free, but it runs inside flush where
`BackgroundTasks` is unreachable, and it would make the trigger invisible to
anyone reading the routers. The explicit call keeps the rule greppable and
lets a test assert that all six mutation points call it.

### Request-scoped buffer

The buffer is a `ContextVar` holding a **mutable list**, mutated in place —
the same pattern and the same reason as `logging_config.request_context`. A
`set()` from inside a service running in the threadpool would be invisible to
the handler; an in-place `append` is not. A tiny dependency
(`Depends(low_stock_scope)`) installs a fresh list per request on the three
routers that need it (`transactions`, `mass_stages`, `work_orders`), so nothing leaks between requests or between tests.

Services must never call `set()`. That constraint is a docstring in the
module and an assertion in its unit test.

### Dispatch

The router drains the buffer once, after the durable write has committed and
beside the existing realtime emit:

```python
low_stock_service.notify_low_stock(db, background, actor_id=user.id)
```

For each crossed entry it resolves `push.user_ids_for_min_role(db, ROLE_TECHFM_OA)`
during the request and schedules one `_deliver` task per item. For each entry
whose membership changed in either direction it emits the realtime envelope
(§6). Both halves go through the existing `_notify` swallow so a rule bug
costs a notification, never the save.

`routers/transactions.py` has no `BackgroundTasks` parameter today; it gains
one as a plain (non-defaulted) parameter on the affected handlers, per the
trigger doc's warning about silent no-op deployments.

## 5. The notification

`app/domain/notifications.py` gains:

```python
EVENT_ITEM_LOW_STOCK = "item.low_stock"
LOW_STOCK_AUDIENCE_MIN_ROLE = roles.ROLE_TECHFM_OA

_MESSAGES[EVENT_ITEM_LOW_STOCK] = ("Low stock", "{name} is down to {quantity}.")
```

`build_message` gains `name` and `quantity` keyword arguments alongside
`number` and `count`. `quantity` is pre-formatted by
`domain.receipt.format_quantity` so a `Numeric` renders as `5`, not `5.000`.

**Widening `build_message` is the argued change.** The module docstring names
the current signature as the line to defend, so the spec answers it rather
than quietly editing it: the rule protects *customer and job* detail on a lock
screen — names, addresses, descriptions, prices. An item name is a
catalogue/manufacturer string that discloses nothing about a customer, a site,
or a person, and without it the notification is unactionable (nobody reads
barcodes off a lock screen). The docstring is updated to state the widened
line — **catalogue identifiers, counts, and quantities yes; customer, job, and
price detail no** — so the next person inherits a rule, not an exception.

**Actor suppression is deliberately bypassed.** `recipients_for_low_stock`
calls `select_recipients(candidates, actor_id=None)` with a docstring saying
why: this is a state alarm about the stockroom, not a report of somebody's
action, and the person holding the empty box is the most useful person to
tell. This inversion goes in the registry, next to the existing
`build_netfacilities_chain_message` inversion.

## 6. Realtime

`app/domain/realtime.py` gains:

```python
EVENT_ITEM_LOW_STOCK_CHANGED = "item.low_stock.changed"
_AUDIENCE_MIN_ROLE[EVENT_ITEM_LOW_STOCK_CHANGED] = roles.ROLE_TECHFM_OA
```

Envelope carries `id = item_id`, or `None` for a collection change. Emitted
whenever low-stock membership may have changed: a crossing in either
direction, a threshold edit, item creation, archive, and restore. The last
three are not stock movements and do not go through the buffer — their routes
emit directly.

Client: `views/lowStock.js` subscribes exactly as `adminReview.js` does —
refresh only when the Low Stock page is the active page, plus on reconnect
recovery, since `nav.js` already reloads the page on entry.

## 7. API

Two routes on the existing items router, both `require_min_role(ROLE_TECHFM_OA)`:

| Route | Behaviour |
| --- | --- |
| `GET /items/low-stock` | Live (non-archived) items where `quantity <= low_stock_threshold`, ordered lowest-first by remaining headroom. Returns the full `ItemResponse` plus `low_stock_threshold` and `dispensed_last_7_days`. |
| `PATCH /items/{item_id}/low-stock-threshold` | Body `{ "low_stock_threshold": int }`, validated `>= 1`. Reads quantity and threshold under `FOR UPDATE`, writes, then runs the same crossing predicate — a raise past current stock pushes; a lower that clears the condition emits realtime only. |

### 7-day dispensed total

`dispensed_last_7_days` is computed only by the low-stock list endpoint — it
is not added to `ItemResponse` generally, because every other item route would
then pay for an aggregate nobody reads. The list response is therefore its own
schema, `LowStockItemResponse`, extending `ItemResponse` with that one extra
field.

Definition, in `services/items.py`:

```sql
SUM(quantity) WHERE transaction_type = 'dispense'
                AND voided_at IS NULL
                AND created_at >= now() - interval '7 days'
GROUP BY item_id
```

No `affects_stock` filter: a retroactive work-order backfill is already stored
as a `dispense` row with `affects_stock = false`, so including retroactive
usage means simply *not* filtering on that column. Corrections and adjusts are
excluded on purpose — a recount write-off is not consumption, and letting it
count would make a mis-stocked item look fast-moving.

**One aggregate query, not one per row.** The endpoint runs the group-by
once, keyed by `item_id`, over exactly the low items it is returning, and
zip-joins the totals in Python. An item with no rows in the window is absent
from the result and renders `0` — the absence is resolved in the service, not
by a `LEFT JOIN`, so an item that has never been dispensed is not a special
case anywhere.

Window is a rolling 168 hours from request time (`now() - interval '7 days'`),
so no timezone or day-boundary logic is involved.

**Route ordering matters:** `GET /items/{barcode}` already exists and would
swallow `/items/low-stock`. The literal path must be registered first. A test
pins this.

`low_stock_threshold` is added to `ItemResponse` for every role — it is an
operational number, not cost-sensitive, so it is not routed through the
`price`/`product_link` redaction in `_item_response`.

## 8. Page

New `low-stock` page in the **Review** nav group, beside User Requests and
Admin Review.

- `static/pages/low-stock.html` — one section, one list, no sub-nav.
- `static/views/lowStock.js` — loads on page entry via `nav.js`, renders one
  card per low item: name, barcode, location, current quantity, and — in the
  card's action column — the 7-day dispensed figure sitting beside the edit-
  threshold control, so "how fast is this moving" and "when should it warn me"
  are read and acted on in one place. The figure is labelled (`7-day used:
  12`), never a bare number, and is read-only.
- `nav.js`: `PAGE_ACCESS["low-stock"] = ["owner", "admin", "techfm_oa"]`, a
  nav button in the review group, and a `showPage` branch calling `loadLowStock()`.

Empty state reads as a positive result ("Nothing is below its threshold"), not
an error. Per-row save shows inline success/failure on that row only; a failed
save reverts the input to the stored value.

Styling follows `docs/design-system.md`. Quantity is a status accent
(badge-only, per the palette rule), never a colored panel. No inline `style=`
attributes anywhere — CSP silently drops them; use the class ladder for string
builders and CSSOM for module-owned nodes.

## 9. Testing

| Layer | File | Asserts |
| --- | --- | --- |
| Rule | `tests/test_low_stock_domain.py` | `is_low` boundary at exactly the threshold; crossing true only on the false→true edge; threshold-raise crossing; both-direction membership change |
| Buffer | `tests/test_low_stock_service.py` | records plain values only; no `set()`; empty buffer schedules nothing; buffer is per-request |
| Notification | `tests/test_notifications_domain.py` | audience is TechFM OA+; **actor is included**; message text; `build_message` still raises for a template missing a field |
| Trigger sites | `tests/test_low_stock_triggers.py` | each of the six mutation points fires once on a crossing and stays silent when already low; a restock re-arms |
| Routes | `tests/test_items_low_stock.py` | list contents and ordering; role gate at TechFM OA; `/items/low-stock` is not shadowed by `/items/{barcode}`; threshold `0` and blank rejected; threshold raise pushes; item created low is listed but silent |
| 7-day usage | `tests/test_items_low_stock.py` | a dispense inside the window counts and one at 169 hours does not; a voided dispense is excluded; a retroactive (`affects_stock = false`) dispense **is** included; a downward correction is **not**; an item with no dispenses returns `0`; the totals come from one query regardless of row count |
| Realtime | existing realtime tests | new event's audience floor |

Nothing in the suite sends a real push — assert on recipients and on a task
having been scheduled. The transport has its own tests.

**Manual, before merge** (CI cannot prove delivery): on a phone with the app
installed to the Home Screen, dispense an item down past its threshold from a
*different* account, confirm the notification arrives with the app closed —
then repeat from the same account and confirm it arrives there too, since the
actor is deliberately in the audience.

## 10. Docs to update in the same commit

- `docs/notification-events.md` — the new push row, and the actor-inclusion
  inversion in the exceptions section.
- `docs/endpoint-map.md` — the two new routes.
- `docs/current-state.md` — the new page and the `items` column.
- `docs/adding-a-notification-trigger.md` — the widened `build_message` line.

## 11. Out of scope

Digests, cooldowns, mute, a global default threshold, low-stock alerts for
`tools` (a separate table with its own quantity), reorder quantities, and
supplier/purchase-order integration. Any of these is a later spec.

The 7-day figure is **display only**. It does not suggest a threshold, does
not sort the list, and does not feed the alerting rule — reading it and
deciding the number stays the human's job in this version.
