# Low Stock Recency Tabs and In-Card Editing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Low Stock page splits its queue into three mutually exclusive recency tabs — dispensed in the last 24 hours, 2–7 days, and older-or-never — and every card expands in place to edit the item's core fields, its additional barcodes, and to correct the on-hand count without leaving the page.

**Architecture:** One new response field (`last_dispensed_at`, a second grouped aggregate over the same non-voided `dispense` rows the 7-day figure already counts) is the whole backend change; no new routes exist, because `PATCH /items/{id}`, `PATCH /items/{id}/barcodes`, `PATCH /items/{id}/low-stock-threshold` and `POST /transactions/adjust` all already permit every role that can see this page. On the frontend the page fetches once and buckets client-side, and each card grows a nested `<details>` body whose save path reuses a newly extracted, DOM-free item-save helper shared with the Saved Items editor.

**Tech Stack:** FastAPI 0.136.3, SQLAlchemy 2.x, Pydantic 2.13, PostgreSQL, pytest, vanilla ES modules (no build step, no framework).

**Spec:** `docs/superpowers/specs/2026-09-01-low-stock-alerts-design.md` (the parent feature). This increment adds no new spec; the decisions it settles are recorded in Global Constraints below.

## Global Constraints

- **No new endpoints and no new migration.** Every write this feature performs already exists and is already gated at TechFM OA or below it.
- **`last_dispensed_at` uses the same transaction rule as the 7-day figure**: `transaction_type == 'dispense'`, `voided_at IS NULL`, **no** `affects_stock` filter (retroactive work-order backfills count), corrections/adjusts excluded. The only difference is that it has **no time window** — an item last dispensed 90 days ago still reports a timestamp.
- **Tabs are mutually exclusive.** `day` = age < 24h. `week` = 24h ≤ age < 7d. `stale` = age ≥ 7d **or** never dispensed (`null`). The counts in the three tab labels sum to the total.
- **Bucketing is client-side** from the ISO timestamp. `created_at` is `DateTime(timezone=True)`, so the JSON carries an offset and `Date.parse` is safe.
- **Headroom order is preserved inside every tab.** The server's ordering (`quantity - low_stock_threshold` ascending, then name) is never re-sorted on the client.
- **Rows are always rebuilt from the server after any write.** A correction or a threshold edit can remove the row it was made on; a card patched in place would be lying. This is the existing rule in `views/lowStock.js` and it still holds.
- **The threshold input stays outside the `<details>`.** A click anywhere inside a `<summary>` toggles the element, so an input placed there fights the user. The card stays a `<div>`; only the new editor body is a `<details>`.
- **No inline `style=` attributes in any HTML or JS string.** CSP silently drops them. Use CSS classes.
- **No nested `<button>` elements.** HTML hoists an inner button out into a sibling and silently breaks flex rows.
- **All backend-supplied text goes through `escapeHtml`** before reaching `innerHTML`.
- **No client-side price gating.** The page is TechFM OA+ only, so `_item_response` never redacts `price` / `product_link` for anyone who can load it.
- **Commit message trailers:** do NOT add `Co-Authored-By`. This repo's `.claude/settings.json` sets no `attribution.commit`.
- **Do not push to `origin`.** Pushing `main` deploys to production. Commit locally only; the user decides when to push.

---

## File Structure

**Created:**

| Path | Responsibility |
| --- | --- |
| `backend/static/itemSave.js` | Foundation. The one item-save sequence (barcode-change confirm → additional barcodes PATCH → core PATCH, all under `confirmArchivedReuse`). No DOM, no selectors. |
| `backend/static/views/lowStockCard.js` | The expanded card body: markup for the core-field editor, the additional-barcode rows, and the correction form, plus the delegated handlers that save them. Keeps `lowStock.js` under budget. |

**Modified:**

| Path | Change |
| --- | --- |
| `backend/app/services/items.py:563-605` | `list_low_stock` returns a third element per row: the last non-voided dispense timestamp. |
| `backend/app/schemas/items.py:98-108` | `LowStockItemResponse` gains `last_dispensed_at`. |
| `backend/app/routers/items.py:60-71,146-149` | `_low_stock_response` takes and forwards the timestamp. |
| `backend/static/views/itemEditor.js:125-192` | Save handler delegates to `itemSave.js`. Behaviour unchanged. |
| `backend/static/pages/low-stock.html` | Tab bar markup. |
| `backend/static/views/lowStock.js` | One fetch, three buckets, tab wiring, card renders the nested editor body. |
| `backend/static/main.js` | Side-effect import of `views/lowStockCard.js`. |
| `backend/static/styles.css` | Tab bar, expanded body, correction form. |
| `backend/tests/test_items_low_stock.py` | `last_dispensed_at` coverage. |
| `backend/tests/test_low_stock_shell.py` | Tab markup is assembled into the shell. |
| `docs/current-state.md`, `docs/endpoint-map.md` | The new field and the page's new shape. |

## Running the tests

From `backend/`, with the venv active:

```bash
cd backend
./venv/Scripts/python.exe -m pytest tests/ -q
```

DB-backed tests need the local Postgres on port 8801 (`DATABASE_URL` is already in `backend/.env`). Pure tests run without it. **Never truncate or rewrite `.env`** — read it and append if it must change at all.

One pre-existing failure is environmental, not yours: `test_cascade_deletes_with_user` fails against a dev database holding real cloud-session rows. Ignore it.

The SPA has no JS test harness. Frontend tasks are verified by the user in the browser at `http://localhost:8124` (hard-reload — a stale service-worker cache renders a blank page). Do not start the preview server yourself.

---

### Task 1: `last_dispensed_at` on the low-stock response

**Files:**
- Modify: `backend/app/services/items.py:563-605`
- Modify: `backend/app/schemas/items.py:98-108`
- Modify: `backend/app/routers/items.py:60-71`, `backend/app/routers/items.py:146-149`
- Test: `backend/tests/test_items_low_stock.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `items_service.list_low_stock(db) -> list[tuple[Item, Decimal, Optional[datetime]]]`; `LowStockItemResponse.last_dispensed_at: Optional[datetime]`; `_low_stock_response(item: Item, role: str, dispensed: Decimal, last_dispensed_at: Optional[datetime]) -> LowStockItemResponse`. Task 3 reads the JSON field `last_dispensed_at` (ISO 8601 string, or `null`).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_items_low_stock.py` (the `_seed_item`, `_dispense` and `_low_stock_rows` helpers already exist in that file):

```python
def test_last_dispensed_reports_the_newest_dispense(db):
    item = _seed_item(db, quantity="2", threshold=6)
    _dispense(db, item, hours_ago=50)
    _dispense(db, item, hours_ago=3)

    row = next(r for r in _low_stock_rows(db).json() if r["id"] == str(item.id))
    stamp = datetime.fromisoformat(row["last_dispensed_at"])
    age_hours = (datetime.now(timezone.utc) - stamp).total_seconds() / 3600
    assert 2.5 < age_hours < 3.5


def test_last_dispensed_is_not_windowed(db):
    """The 7-day *usage* figure is windowed; the recency stamp is not.
    An item last touched two months ago still has to land in the
    older-or-never tab rather than looking like it never moved."""
    item = _seed_item(db, quantity="2", threshold=6)
    _dispense(db, item, hours_ago=1500)

    row = next(r for r in _low_stock_rows(db).json() if r["id"] == str(item.id))
    assert row["last_dispensed_at"] is not None
    assert Decimal(row["dispensed_last_7_days"]) == Decimal("0")


def test_last_dispensed_ignores_voided_rows(db):
    item = _seed_item(db, quantity="2", threshold=6)
    _dispense(db, item, hours_ago=1, voided=True)

    row = next(r for r in _low_stock_rows(db).json() if r["id"] == str(item.id))
    assert row["last_dispensed_at"] is None


def test_last_dispensed_ignores_corrections(db):
    item = _seed_item(db, quantity="2", threshold=6)
    _dispense(db, item, quantity="-8", hours_ago=1, transaction_type="adjust")

    row = next(r for r in _low_stock_rows(db).json() if r["id"] == str(item.id))
    assert row["last_dispensed_at"] is None


def test_last_dispensed_counts_retroactive_backfills(db):
    """Same rule as the 7-day figure: stock consumed off-app and logged
    on paper is real usage, so it sets the recency stamp too."""
    item = _seed_item(db, quantity="2", threshold=6)
    _dispense(db, item, hours_ago=2, affects_stock=False)

    row = next(r for r in _low_stock_rows(db).json() if r["id"] == str(item.id))
    assert row["last_dispensed_at"] is not None


def test_a_never_dispensed_item_reports_no_timestamp(db):
    item = _seed_item(db, quantity="1", threshold=6)
    row = next(r for r in _low_stock_rows(db).json() if r["id"] == str(item.id))
    assert row["last_dispensed_at"] is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/Scripts/python.exe -m pytest tests/test_items_low_stock.py -q -k last_dispensed`
Expected: FAIL with `KeyError: 'last_dispensed_at'`.

- [ ] **Step 3: Add the aggregate in the service**

In `backend/app/services/items.py`, replace the tail of `list_low_stock` (the `since = ...` block through the final `return`) with:

```python
    item_ids = [item.id for item in items]
    dispenses = (
        db.query(Transaction.item_id)
        .filter(Transaction.item_id.in_(item_ids))
        .filter(Transaction.transaction_type == "dispense")
        .filter(Transaction.voided_at.is_(None))
        .group_by(Transaction.item_id)
    )

    since = datetime.now(timezone.utc) - LOW_STOCK_USAGE_WINDOW
    totals = dict(
        dispenses.with_entities(
            Transaction.item_id, func.sum(Transaction.quantity)
        )
        .filter(Transaction.created_at >= since)
        .all()
    )
    # Unwindowed on purpose: the tab an item belongs to is a question about
    # how long ago it last moved, which a 7-day window cannot answer -- every
    # item older than the window would collapse into "never dispensed".
    last_seen = dict(
        dispenses.with_entities(
            Transaction.item_id, func.max(Transaction.created_at)
        ).all()
    )
    return [
        (item, totals.get(item.id) or Decimal(0), last_seen.get(item.id))
        for item in items
    ]
```

Update the signature and docstring:

```python
def list_low_stock(db: Session) -> list[tuple[Item, Decimal, Optional[datetime]]]:
```

and append this paragraph to the existing docstring:

```
    The third element is *when* the item last moved, over all time rather
    than inside the usage window, because the page groups rows by recency
    (last 24 hours / 2-7 days / older or never) and a windowed maximum
    would make every older item indistinguishable from one that has never
    been dispensed at all. `None` means exactly that: never.
```

- [ ] **Step 4: Widen the schema**

In `backend/app/schemas/items.py`, extend `LowStockItemResponse`:

```python
class LowStockItemResponse(ItemResponse):
    """An item on the Low Stock page.

    Its own schema rather than more fields on `ItemResponse`: the two
    aggregates cost a grouped query each, and every other item route
    would pay for numbers none of them display. `low_stock_threshold`
    stays on the parent because it is a plain column that any item view
    may want.

    `last_dispensed_at` is `None` for an item that has never been
    dispensed, which the page reads as its oldest recency bucket rather
    than as missing data.
    """

    dispensed_last_7_days: Decimal
    last_dispensed_at: Optional[datetime] = None
```

- [ ] **Step 5: Forward it through the router**

In `backend/app/routers/items.py`, replace `_low_stock_response` and the list comprehension in `list_low_stock`:

```python
def _low_stock_response(
    item: Item,
    role: str,
    dispensed: Decimal,
    last_dispensed_at: Optional[datetime],
) -> LowStockItemResponse:
    """`_item_response` plus the 7-day figure and the recency stamp.

    Reuses the base serializer rather than re-deriving it so the
    price/product-link redaction cannot drift between the two -- a second
    hand-written copy is exactly how a Supervisor ends up seeing a price
    on one page and not another.
    """
    base = _item_response(item, role)
    return LowStockItemResponse(
        **base.model_dump(),
        dispensed_last_7_days=dispensed,
        last_dispensed_at=last_dispensed_at,
    )
```

```python
    return [
        _low_stock_response(item, user.role, dispensed, last_dispensed_at)
        for item, dispensed, last_dispensed_at in items_service.list_low_stock(db)
    ]
```

Confirm `datetime` is imported in `routers/items.py`; add `from datetime import datetime` to its import block if it is not.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `./venv/Scripts/python.exe -m pytest tests/test_items_low_stock.py -q`
Expected: PASS, all tests in the file including the pre-existing 7-day-usage ones.

- [ ] **Step 7: Run the full backend suite**

Run: `./venv/Scripts/python.exe -m pytest tests/ -q`
Expected: PASS except the known environmental `test_cascade_deletes_with_user`.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/items.py backend/app/schemas/items.py backend/app/routers/items.py backend/tests/test_items_low_stock.py
git commit -m "feat(items): report when each low-stock item last moved"
```

---

### Task 2: Extract the shared item-save sequence

**Files:**
- Create: `backend/static/itemSave.js`
- Modify: `backend/static/views/itemEditor.js:125-192`

**Interfaces:**
- Consumes: `apiUpdateItem`, `apiUpdateBarcodes` (`static/api.js`); `confirmDialog`, `confirmArchivedReuse` (`static/dom.js`).
- Produces: `saveItemCore(itemId, fields, {originalBarcode, originalBarcodes, barcodes}) -> Promise<void>` and the constant `BARCODE_CHANGE_WARNING`. Task 4 calls `saveItemCore` with the identical contract.

No test step: this layer has no JS harness, and the task is a behaviour-preserving extraction. It is verified by the user re-saving an item on Saved Items (Step 4).

- [ ] **Step 1: Write the helper**

Create `backend/static/itemSave.js`:

```js
// Foundation: the one item-save sequence.
//
// Layer: foundation (beside `api.js` / `dom.js`, below the views). Two
// editors now write the same item -- the Saved Items panel
// (`views/itemEditor.js`) and the Low Stock card (`views/lowStockCard.js`)
// -- and the order of operations here is load-bearing in three ways that a
// second hand-written copy would eventually get wrong:
//
//   1. The additional barcodes PATCH goes FIRST, so a duplicate-code 400
//      surfaces before the core fields are touched.
//   2. Both writes ride ONE `confirmArchivedReuse`, so a collision with an
//      archived item prompts once and retries the whole (idempotent)
//      sequence with `override_archived`.
//   3. A changed primary barcode warns first, because scanner labels in
//      the field still pointing at the old code stop resolving.
//
// No DOM access and no selectors: callers own their own markup and pass
// plain values.

import { apiUpdateItem, apiUpdateBarcodes } from "./api.js";
import { confirmArchivedReuse, confirmDialog } from "./dom.js";

export const BARCODE_CHANGE_WARNING =
  "Changing this barcode breaks any scanner labels still pointing at this row. Continue?";

// `fields` is `{barcode, name, location, price, product_link}` -- `price` a
// number or null, `product_link` a string or null. `barcodes` is the full
// desired list of *additional* codes; it is only PATCHed when it differs
// from `originalBarcodes`, so an unchanged list costs no request.
//
// Throws `{cancelled: true}` if the user declines the barcode-change warning
// or the archived-reuse prompt, matching `confirmArchivedReuse`'s contract so
// callers can clear their status line instead of showing an error.
export async function saveItemCore(
  itemId,
  fields,
  { originalBarcode, originalBarcodes = [], barcodes = [] } = {}
) {
  if (fields.barcode !== originalBarcode) {
    const ok = await confirmDialog(BARCODE_CHANGE_WARNING);
    if (!ok) throw { cancelled: true };
  }

  const barcodesChanged =
    JSON.stringify(barcodes) !== JSON.stringify(originalBarcodes);

  await confirmArchivedReuse(async (override) => {
    if (barcodesChanged) {
      await apiUpdateBarcodes(itemId, barcodes, override);
    }
    await apiUpdateItem(itemId, { ...fields, override_archived: override });
  });
}
```

- [ ] **Step 2: Point the Saved Items editor at it**

In `backend/static/views/itemEditor.js`, replace the import of `apiUpdateItem` / `apiUpdateBarcodes` with the helper, and drop `confirmArchivedReuse` / `confirmDialog` from the `dom.js` import (keep `setMessage`):

```js
import { getEditingItemId, setEditingItemId } from "../state.js";
import { escapeHtml, friendlyError } from "../format.js";
import { setMessage } from "../dom.js";
import { saveItemCore } from "../itemSave.js";
```

Then replace the body of the save handler from the `if (barcode !== originalBarcode) {` block through the end of the `try` block's write section with a single call. The handler's validation, messaging, and close-on-success behaviour are unchanged:

```js
  try {
    await saveItemCore(
      editingId,
      {
        barcode,
        name,
        location,
        price: price ? parseFloat(price) : null,
        product_link: productLink ? productLink : null,
      },
      { originalBarcode, originalBarcodes, barcodes: codes }
    );
    originalBarcodes = [...codes];
    setMessage(itemEditorMessage, "Item saved.", "success");
    if (onSavedCallback) await onSavedCallback();
    setTimeout(closeItemEditor, 1000);
  } catch (err) {
    if (err && err.cancelled) {
      setMessage(itemEditorMessage, "", "");
      return;
    }
    setMessage(itemEditorMessage, friendlyError(err, "Could not save the changes. Try again."), "error");
  }
```

Also fold the three "why this order" comments that lived above the old inline sequence into `itemSave.js` (they are already reproduced in its header) rather than leaving them behind on a call site that no longer performs the writes.

- [ ] **Step 3: Verify nothing else in the file still needs the dropped imports**

Run: `grep -n "apiUpdateItem\|apiUpdateBarcodes\|confirmArchivedReuse\|confirmDialog" backend/static/views/itemEditor.js`
Expected: no matches.

- [ ] **Step 4: Manual verification (user)**

On Saved Items: edit an item's name only and save; edit its primary barcode and confirm the warning appears; add and remove an additional barcode and save. All three must behave exactly as before.

- [ ] **Step 5: Commit**

```bash
git add backend/static/itemSave.js backend/static/views/itemEditor.js
git commit -m "refactor(items): extract the shared item-save sequence"
```

---

### Task 3: Recency tabs on the Low Stock page

**Files:**
- Modify: `backend/static/pages/low-stock.html`
- Modify: `backend/static/views/lowStock.js`
- Test: `backend/tests/test_low_stock_shell.py`

**Interfaces:**
- Consumes: `last_dispensed_at` from Task 1.
- Produces: `#low-stock-tabs` with three `.sub-nav-btn[data-bucket]` buttons (`day` / `week` / `stale`); a rendered `.low-stock-card[data-id]` per row. Task 4 appends its body markup inside those cards and delegates off `#low-stock-list`.

- [ ] **Step 1: Write the failing shell test**

Append to `backend/tests/test_low_stock_shell.py`:

```python
def test_the_recency_tabs_are_assembled_into_the_shell():
    """Three mutually exclusive buckets. A missing button is invisible in
    the browser -- the page just renders one bucket and hides the rest of
    the queue with no error."""
    assembled = b"".join((STATIC_DIR / part).read_bytes() for part in SHELL_PARTS)
    assert b'id="low-stock-tabs"' in assembled
    for bucket in (b"day", b"week", b"stale"):
        assert b'data-bucket="%s"' % bucket in assembled
```

- [ ] **Step 2: Run it to verify it fails**

Run: `./venv/Scripts/python.exe -m pytest tests/test_low_stock_shell.py -q`
Expected: FAIL — `assert b'id="low-stock-tabs"' in assembled`.

- [ ] **Step 3: Add the tab bar markup**

In `backend/static/pages/low-stock.html`, insert between the `.filter-row` div and `#low-stock-list`:

```html
            <!-- Recency buckets, mutually exclusive: an item appears under
                 exactly one, and the three counts sum to the queue. These
                 carry `data-bucket`, not `data-feature`, because they filter
                 one list rather than swapping `.feature-panel`s -- the
                 `initSubNav` convention does not apply here. -->
            <nav class="sub-nav low-stock-tabs" id="low-stock-tabs" aria-label="Sort low stock by how recently it moved">
                <button type="button" class="sub-nav-btn active" data-bucket="day">Last 24h</button>
                <button type="button" class="sub-nav-btn" data-bucket="week">2-7 days</button>
                <button type="button" class="sub-nav-btn" data-bucket="stale">Older or never</button>
            </nav>
```

Extend the page's `.hint` paragraph with one sentence:

```
               Tabs group the queue by how recently each item was
               dispensed, so what is both low and moving reaches you first.
```

- [ ] **Step 4: Bucket and render in the view**

In `backend/static/views/lowStock.js`, add below the existing constants:

```js
const tabsEl = document.getElementById("low-stock-tabs");

const DAY_MS = 24 * 60 * 60 * 1000;
const WEEK_MS = 7 * DAY_MS;

// Labels live here rather than in the markup so the count can be appended
// without the view having to parse the text already on the button.
const BUCKETS = [
  { key: "day", label: "Last 24h" },
  { key: "week", label: "2-7 days" },
  { key: "stale", label: "Older or never" },
];

const EMPTY_TEXT = {
  day: "Nothing low was dispensed in the last 24 hours.",
  week: "Nothing low was dispensed in the last week.",
  stale: "Everything low has moved within the last week.",
};

// The whole queue, held so a tab switch is a filter rather than a fetch.
let allRows = [];
let activeBucket = "day";
```

Add the bucketing rule, written as a pure function so the boundary is stated once:

```js
// Which tab a row belongs to. Boundaries are exclusive on purpose: an item
// dispensed an hour ago is in `day` and NOT also in `week`, so the three
// counts sum to the queue and no card is read twice. A missing or
// unparseable timestamp means "never dispensed", which is the oldest
// bucket -- not a hidden row.
function bucketOf(row, now) {
  if (!row.last_dispensed_at) return "stale";
  const at = Date.parse(row.last_dispensed_at);
  if (Number.isNaN(at)) return "stale";
  const age = now - at;
  if (age < DAY_MS) return "day";
  if (age < WEEK_MS) return "week";
  return "stale";
}

function bucketRows(rows) {
  const now = Date.now();
  const grouped = { day: [], week: [], stale: [] };
  // Server order (headroom ascending) is preserved: rows are appended in
  // the order they arrived and never re-sorted.
  for (const row of rows) grouped[bucketOf(row, now)].push(row);
  return grouped;
}
```

Replace `render` with a bucket-aware version, and add the tab painter:

```js
function paintTabs(grouped) {
  if (!tabsEl) return;
  for (const { key, label } of BUCKETS) {
    const btn = tabsEl.querySelector(`.sub-nav-btn[data-bucket="${key}"]`);
    if (!btn) continue;
    btn.textContent = `${label} (${grouped[key].length})`;
    btn.classList.toggle("active", key === activeBucket);
  }
}

function render() {
  const grouped = bucketRows(allRows);

  // Never strand the user on an empty tab: keep the one they chose while it
  // still holds rows, otherwise fall to the first that does. This covers
  // both the initial load and a background reload that emptied the tab
  // under them.
  if (!grouped[activeBucket].length) {
    const firstFilled = BUCKETS.find(b => grouped[b.key].length);
    if (firstFilled) activeBucket = firstFilled.key;
  }
  paintTabs(grouped);

  const open = openCardIds();
  listEl.replaceChildren();

  if (!allRows.length) {
    setMessage(messageEl, "Nothing is below its threshold.", "success");
    return;
  }

  const rows = grouped[activeBucket];
  if (!rows.length) {
    setMessage(messageEl, EMPTY_TEXT[activeBucket], "success");
    return;
  }

  const fragment = document.createDocumentFragment();
  for (const row of rows) fragment.append(buildCard(row));
  listEl.append(fragment);
  restoreOpenCards(open);
  setMessage(messageEl, "", "");
}
```

Add the open-card memory (the editor body Task 4 installs must survive a background reload mid-edit):

```js
// A background reload rebuilds every card, which would slam shut an editor
// the user is typing in. Remember which ones were open by item id and
// reopen them after the rebuild.
function openCardIds() {
  return new Set(
    Array.from(listEl.querySelectorAll("details.low-stock-more[open]"))
      .map(el => el.dataset.id)
  );
}

function restoreOpenCards(ids) {
  if (!ids.size) return;
  for (const el of listEl.querySelectorAll("details.low-stock-more")) {
    if (ids.has(el.dataset.id)) el.open = true;
  }
}
```

Update `loadLowStock` to store rather than render directly:

```js
    const rows = await apiListLowStock();
    if (sequence !== loadSequence) return;
    allRows = rows;
    render();
```

and clear the cache on the error path, above the existing `listEl.replaceChildren()`:

```js
    allRows = [];
```

Wire the tab bar:

```js
if (tabsEl) {
  tabsEl.addEventListener("click", (event) => {
    const btn = event.target.closest(".sub-nav-btn");
    if (!btn || !btn.dataset.bucket || btn.dataset.bucket === activeBucket) return;
    activeBucket = btn.dataset.bucket;
    // Filter, do not refetch: the queue in hand is the same queue.
    render();
  });
}
```

Finally, add the nested editor body to `buildCard` — replace the `low-stock-row-message` line at the end of its template with:

```js
    `<p class="low-stock-row-message" aria-live="polite"></p>` +
    cardBodyHtml(row);
```

and import it at the top of the file:

```js
import { cardBodyHtml } from "./lowStockCard.js";
```

(`cardBodyHtml` lands in Task 4. Implement Task 3 and Task 4 back to back; the page does not render between them.)

- [ ] **Step 5: Run the shell test to verify it passes**

Run: `./venv/Scripts/python.exe -m pytest tests/test_low_stock_shell.py -q`
Expected: PASS.

- [ ] **Step 6: Commit (after Task 4 — see its Step 6)**

Tasks 3 and 4 land in one commit because `lowStock.js` imports `lowStockCard.js`; committing Task 3 alone leaves the page broken on an unresolved module.

---

### Task 4: The expandable in-card editor

**Files:**
- Create: `backend/static/views/lowStockCard.js`
- Modify: `backend/static/main.js:33`

**Interfaces:**
- Consumes: `saveItemCore` (Task 2); `apiCreateCorrection`, `apiListLowStock` shape (`last_dispensed_at`, `barcodes`, `price`, `product_link`) from Task 1; `#low-stock-list` and `.low-stock-card[data-id]` from Task 3.
- Produces: `cardBodyHtml(row) -> string` (imported by `lowStock.js`) and a module side effect that delegates every editor action off `#low-stock-list`.

- [ ] **Step 1: Write the module**

Create `backend/static/views/lowStockCard.js`:

```js
// View: the expanded body of a Low Stock card.
//
// Layer: views. Sibling of `lowStock.js`, which owns the list, the tabs and
// the threshold control; this module owns everything behind the card's
// "Edit item" disclosure -- the core fields, the additional barcodes, and
// the count correction.
//
// It is a `<details>` INSIDE the card rather than the card itself being one:
// a click anywhere in a `<summary>` toggles the element, which would fight
// the threshold input that has to stay one click away in the card header.
//
// Every handler is delegated off `#low-stock-list`, so cards rebuilt by a
// reload need no rewiring. After any successful save the page reloads in
// the background rather than patching the card, because a correction or a
// threshold change can remove the row it was made on -- the same rule
// `lowStock.js` already follows.

import { apiCreateCorrection } from "../api.js";
import { setMessage } from "../dom.js";
import { escapeHtml, friendlyError } from "../format.js";
import { saveItemCore } from "../itemSave.js";
import { loadLowStock } from "./lowStock.js";

const listEl = document.getElementById("low-stock-list");

function barcodeRowHtml(code) {
  return (
    `<div class="ls-barcode-row">` +
      `<input type="text" class="ls-alt-barcode" placeholder="Additional barcode" ` +
        `aria-label="Additional barcode" value="${escapeHtml(code)}">` +
      `<button type="button" class="note-remove-btn" data-action="remove-barcode" ` +
        `title="Remove" aria-label="Remove barcode">&times;</button>` +
    `</div>`
  );
}

// The card's disclosure body. Built as a string (like the card itself) and
// injected once; the inputs are read back out of the DOM on save, so no
// draft state is held in JS.
export function cardBodyHtml(row) {
  const codes = Array.isArray(row.barcodes) ? row.barcodes : [];
  return (
    `<details class="low-stock-more" data-id="${escapeHtml(row.id)}">` +
      `<summary class="low-stock-more-summary">Edit item</summary>` +

      `<div class="low-stock-edit">` +
        `<label class="ls-field"><span>Name</span>` +
          `<input type="text" class="ls-name" value="${escapeHtml(row.name)}"></label>` +
        `<label class="ls-field"><span>Barcode</span>` +
          `<input type="text" class="ls-barcode" value="${escapeHtml(row.barcode)}"></label>` +
        `<label class="ls-field"><span>Location</span>` +
          `<input type="text" class="ls-location" value="${escapeHtml(row.location)}"></label>` +
        `<label class="ls-field"><span>Price</span>` +
          `<input type="number" step="0.01" min="0" inputmode="decimal" class="ls-price" ` +
            `value="${escapeHtml(row.price ?? "")}"></label>` +
        `<label class="ls-field ls-field-wide"><span>Product link</span>` +
          `<input type="url" class="ls-product-link" ` +
            `value="${escapeHtml(row.product_link ?? "")}"></label>` +

        `<div class="ls-field ls-field-wide">` +
          `<span>Additional barcodes</span>` +
          `<div class="ls-barcode-rows">${codes.map(barcodeRowHtml).join("")}</div>` +
          `<button type="button" class="secondary-btn" data-action="add-barcode">Add barcode</button>` +
        `</div>` +

        `<div class="ls-actions">` +
          `<button type="button" data-action="save-item">Save item</button>` +
        `</div>` +
      `</div>` +

      `<div class="low-stock-correction">` +
        `<h4>Correct the count</h4>` +
        `<p class="hint">Recording an absolute recount. The app writes the ` +
          `difference as an audited correction, so the reason is required.</p>` +
        `<label class="ls-field"><span>New count</span>` +
          `<input type="number" min="0" step="1" inputmode="numeric" class="ls-correct-qty" ` +
            `value="${escapeHtml(String(Number(row.quantity)))}"></label>` +
        `<label class="ls-field ls-field-wide"><span>Reason</span>` +
          `<input type="text" class="ls-correct-reason" placeholder="Why the count changed"></label>` +
        `<div class="ls-actions">` +
          `<button type="button" data-action="save-correction">Save correction</button>` +
        `</div>` +
      `</div>` +

      `<p class="low-stock-edit-message" aria-live="polite"></p>` +
    `</details>`
  );
}

function collectAltBarcodes(body, messageEl) {
  const codes = [];
  const seen = new Set();
  for (const input of body.querySelectorAll(".ls-alt-barcode")) {
    const code = input.value.trim();
    if (!code) continue;
    if (seen.has(code)) {
      setMessage(messageEl, `The barcode "${code}" is listed twice. Remove the duplicate.`, "error");
      return null;
    }
    seen.add(code);
    codes.push(code);
  }
  return codes;
}

async function saveItem(body, card) {
  const messageEl = body.querySelector(".low-stock-edit-message");
  setMessage(messageEl, "", "");

  const barcode = body.querySelector(".ls-barcode").value.trim();
  const name = body.querySelector(".ls-name").value.trim();
  const location = body.querySelector(".ls-location").value.trim();
  const price = body.querySelector(".ls-price").value.trim();
  const productLink = body.querySelector(".ls-product-link").value.trim();

  if (!barcode || !name || !location) {
    setMessage(messageEl, "Barcode, name, and location are required.", "error");
    return;
  }

  const codes = collectAltBarcodes(body, messageEl);
  if (codes === null) return;

  try {
    await saveItemCore(
      card.dataset.id,
      {
        barcode,
        name,
        location,
        price: price ? parseFloat(price) : null,
        product_link: productLink ? productLink : null,
      },
      {
        originalBarcode: card.dataset.barcode,
        originalBarcodes: JSON.parse(card.dataset.barcodes || "[]"),
        barcodes: codes,
      }
    );
    setMessage(messageEl, "Item saved.", "success");
    loadLowStock({ background: true });
  } catch (err) {
    if (err && err.cancelled) {
      setMessage(messageEl, "", "");
      return;
    }
    setMessage(messageEl, friendlyError(err, "Could not save the changes. Try again."), "error");
  }
}

async function saveCorrection(body, card) {
  const messageEl = body.querySelector(".low-stock-edit-message");
  setMessage(messageEl, "", "");

  const raw = body.querySelector(".ls-correct-qty").value;
  const newQuantity = Number(raw);
  if (raw === "" || !Number.isFinite(newQuantity)) {
    setMessage(messageEl, "Enter a valid new count.", "error");
    return;
  }
  if (newQuantity < 0) {
    setMessage(messageEl, "Enter a count of zero or more.", "error");
    return;
  }
  const reason = body.querySelector(".ls-correct-reason").value.trim();
  if (!reason) {
    setMessage(messageEl, "Enter a reason for the correction.", "error");
    return;
  }

  try {
    await apiCreateCorrection({ itemId: card.dataset.id, newQuantity, reason });
    // A correction that clears the threshold removes this card entirely, so
    // say what happened before the reload takes the message with it.
    setMessage(messageEl, "Count corrected.", "success");
    loadLowStock({ background: true });
  } catch (err) {
    setMessage(messageEl, friendlyError(err, "Could not save the correction. Try again."), "error");
  }
}

if (listEl) {
  listEl.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-action]");
    if (!btn || !listEl.contains(btn)) return;
    const body = btn.closest(".low-stock-more");
    const card = btn.closest(".low-stock-card");
    if (!body || !card) return;

    const action = btn.dataset.action;
    if (action === "add-barcode") {
      body.querySelector(".ls-barcode-rows").insertAdjacentHTML("beforeend", barcodeRowHtml(""));
    } else if (action === "remove-barcode") {
      btn.closest(".ls-barcode-row").remove();
    } else if (action === "save-item") {
      saveItem(body, card);
    } else if (action === "save-correction") {
      saveCorrection(body, card);
    }
  });
}
```

- [ ] **Step 2: Carry the originals on the card**

`saveItemCore` needs the values the row arrived with, and the card is the only thing that survives a re-render. In `backend/static/views/lowStock.js::buildCard`, beside the existing `card.dataset.id = row.id;`, add:

```js
  // The pre-edit values, so a save can tell a changed barcode from an
  // untouched one without holding draft state in a module variable.
  card.dataset.barcode = row.barcode;
  card.dataset.barcodes = JSON.stringify(row.barcodes || []);
```

- [ ] **Step 3: Register the module**

In `backend/static/main.js`, add below the existing `import "./views/lowStock.js";`:

```js
import "./views/lowStockCard.js";
```

- [ ] **Step 4: Check for the import cycle**

`lowStockCard.js` imports `loadLowStock` from `lowStock.js`, which imports `cardBodyHtml` from `lowStockCard.js`. ES modules resolve this fine because neither call happens at module-evaluation time, but confirm the ordering: `lowStock.js` must call `cardBodyHtml` only inside `buildCard` (invoked on load), and `lowStockCard.js` must call `loadLowStock` only inside a handler.

Run: `grep -n "cardBodyHtml\|loadLowStock" backend/static/views/lowStock.js backend/static/views/lowStockCard.js`
Expected: every call site sits inside a function body, none at top level.

- [ ] **Step 5: Manual verification (user)**

Hard-reload `http://localhost:8124`, open Low Stock, and check:
1. Three tabs with counts that sum to the full queue; switching is instant and does not refetch.
2. An item dispensed today appears under **Last 24h** and nowhere else.
3. "Edit item" expands; changing the name and saving updates the card after the reload.
4. Adding an additional barcode and saving persists it (reopen the card).
5. A correction that raises the count above the threshold removes the card from the page.
6. The threshold input in the card header still saves on blur and on Enter.

- [ ] **Step 6: Commit Tasks 3 and 4 together**

```bash
git add backend/static/pages/low-stock.html backend/static/views/lowStock.js backend/static/views/lowStockCard.js backend/static/main.js backend/tests/test_low_stock_shell.py
git commit -m "feat(ui): recency tabs and in-card editing on Low Stock"
```

---

### Task 5: Styles

**Files:**
- Modify: `backend/static/styles.css` (the `--- Low Stock page ---` block, currently lines 1561-1632)

**Interfaces:**
- Consumes: the class names emitted by Tasks 3 and 4.
- Produces: nothing other modules read.

- [ ] **Step 1: Extend the Low Stock block**

Append after `.low-stock-row-message:empty`:

```css
/* The recency tabs reuse `.sub-nav` chrome; only the spacing differs,
   because they sit inside a section rather than at the top of a page. */
.low-stock-tabs {
    margin-bottom: var(--space-3);
}

/* The disclosure that holds the editor. Ruled off from the card's
   threshold row so the two read as separate decisions. */
.low-stock-more {
    margin-top: var(--space-3);
    padding-top: var(--space-3);
    border-top: 1px solid var(--panel-rule);
}

.low-stock-more-summary {
    cursor: pointer;
    font-size: var(--fs-sm);
    font-weight: var(--fw-semibold);
}

.low-stock-edit,
.low-stock-correction {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: var(--space-2);
    margin-top: var(--space-3);
}

.low-stock-correction {
    padding-top: var(--space-3);
    border-top: 1px solid var(--panel-rule);
}

.low-stock-correction h4 {
    grid-column: 1 / -1;
    margin: 0;
}

.low-stock-correction .hint {
    grid-column: 1 / -1;
    margin: 0;
}

.ls-field {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    font-size: var(--fs-sm);
}

.ls-field-wide {
    grid-column: 1 / -1;
}

.ls-barcode-rows {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
}

.ls-barcode-row {
    display: flex;
    align-items: center;
    gap: var(--space-2);
}

.ls-barcode-row input {
    flex: 1;
}

.ls-actions {
    grid-column: 1 / -1;
    display: flex;
    justify-content: flex-end;
}

.low-stock-edit-message:empty {
    display: none;
}
```

- [ ] **Step 2: Confirm no inline styles were introduced**

Run: `grep -n "style=" backend/static/views/lowStockCard.js backend/static/views/lowStock.js backend/static/pages/low-stock.html`
Expected: no matches. CSP silently drops inline styles, so a match here is a bug that shows as an unstyled control rather than an error.

- [ ] **Step 3: Manual verification (user)**

The expanded body reads as a form on a phone-width screen (fields stack, buttons stay reachable), and the card grid does not shift when one card opens.

- [ ] **Step 4: Commit**

```bash
git add backend/static/styles.css
git commit -m "style(ui): Low Stock tabs and in-card editor"
```

---

### Task 6: Documentation

**Files:**
- Modify: `docs/current-state.md`, `docs/endpoint-map.md`

**Interfaces:**
- Consumes: everything above.
- Produces: nothing.

Living docs are current-truth only — state what is true now, delete nothing that is still true, and add no how-we-got-here narrative. Word budgets: `current-state.md` 16,500, `endpoint-map.md` 11,000.

- [ ] **Step 1: Update `endpoint-map.md`**

Find the `GET /items/low-stock` row and extend its response description to name both aggregates: `dispensed_last_7_days` (windowed sum) and `last_dispensed_at` (unwindowed max, `null` if never dispensed). Do not add a row — no endpoint was added.

- [ ] **Step 2: Update `current-state.md`**

In the Low Stock page's description, replace the existing sentence about the flat list with the page's current shape, in the file's established clipped-bullet form:

```
Three mutually exclusive recency tabs (last 24h / 2-7 days / older or
never), bucketed client-side from `last_dispensed_at`; one fetch serves
all three. Each card expands to edit core fields, additional barcodes,
and to correct the count (`POST /transactions/adjust`); the threshold
control stays in the card header. Any save reloads the queue rather
than patching the card.
```

If this update pushes the file past its budget, delete something stale in the same edit.

- [ ] **Step 3: Verify the vault mirror is left alone**

The `docs/` → Obsidian mirror is generated automatically at turn end by `scripts/sync-obsidian.ps1` (Stop hook). Do **not** run it or edit the vault copy by hand.

- [ ] **Step 4: Commit**

```bash
git add docs/current-state.md docs/endpoint-map.md
git commit -m "docs: Low Stock recency tabs and in-card editing"
```

---

## Self-Review

**Spec coverage.** Both requests from the brief are covered: recency tabs (Tasks 1, 3) and expand-to-edit including count correction (Tasks 2, 4). The user's two explicit decisions — full core-field editing inline, and mutually exclusive buckets — are implemented in Task 4 Step 1 and Task 3 Step 4 respectively, and restated in Global Constraints.

**Placeholders.** None. Every code step carries the actual code; every test step carries the actual assertions and the command to run.

**Type consistency.** `list_low_stock` returns a 3-tuple in Task 1 and is unpacked as a 3-tuple in the same task's router change. `cardBodyHtml(row)` is defined in Task 4 and imported in Task 3 (the two land in one commit, noted at Task 3 Step 6). `saveItemCore(itemId, fields, {originalBarcode, originalBarcodes, barcodes})` is defined in Task 2 and called with that exact shape by both `itemEditor.js` (Task 2) and `lowStockCard.js` (Task 4). The bucket keys `day` / `week` / `stale` are identical across the markup, `BUCKETS`, `EMPTY_TEXT`, `bucketOf`, and the shell test.

**Known gap, deliberate.** There is no automated coverage of the bucketing rule — the SPA has no JS test harness, and adding one is out of scope here. `bucketOf` is written as a pure function so a future harness can reach it; until then Task 4 Step 5 items 1–2 are the verification.
