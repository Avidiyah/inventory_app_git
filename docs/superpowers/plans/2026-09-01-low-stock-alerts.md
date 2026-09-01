# Low Stock Alerts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An item whose on-hand count falls to or below a per-item threshold sends a Web Push notification to every TechFM OA and above, and appears on a new Low Stock page in the Review nav group where the threshold can be retuned and 7-day usage read.

**Architecture:** One new integer column on `items`. A pure predicate module decides "was not low, is now low" from a before/after pair of `(quantity, threshold)`. Eight stock-mutation points in three services each call a one-line recorder that appends a plain-value snapshot to a request-scoped buffer; three routers drain that buffer once per request and dispatch pushes plus realtime invalidations. Two new item routes back a new SPA page.

**Tech Stack:** FastAPI 0.136.3, SQLAlchemy 2.x, Alembic, Pydantic 2.13, PostgreSQL, pytest, vanilla ES modules (no build step, no framework).

**Spec:** `docs/superpowers/specs/2026-09-01-low-stock-alerts-design.md`

## Global Constraints

- **Threshold default is `6`, minimum is `1`.** Written in exactly two places — the Alembic migration's `server_default` and `domain/low_stock.DEFAULT_LOW_STOCK_THRESHOLD`. No other file may contain the literal.
- **Push is edge-triggered.** A push fires only when `is_low` was `False` before the write and `True` after. Never on a write that leaves an already-low item low.
- **The actor is NOT suppressed.** Every low-stock push goes to every non-archived user at `ROLE_TECHFM_OA` or above, including whoever caused the crossing. This inverts `select_recipients`' normal behaviour and must be explicit in code and docstring.
- **Push audience floor is `roles.ROLE_TECHFM_OA`.** Never `ROLE_ADMIN`.
- **Delivery is best-effort.** Nothing in this feature may raise into a request that already committed a durable write. `flush_low_stock` swallows and logs.
- **Decide inside the request, deliver outside it.** Every value a background task needs is captured as a plain `str` / `int` / `uuid` while the session is alive. No ORM object, no lazy relationship, ever reaches a background task.
- **Recording happens immediately BEFORE `db.commit()`** in each service, while the ORM object is still loaded. Draining happens in the router only on the success path, so an exception between the two discards the buffer with the request context.
- **7-day usage counts `transaction_type == 'dispense'` with `voided_at IS NULL` and `created_at >= now() - 7 days`.** No `affects_stock` filter — retroactive rows are included deliberately. Corrections/adjusts are excluded.
- **No inline `style=` attributes in any HTML or JS string.** CSP silently drops them. Use CSS classes.
- **No nested `<button>` elements.** HTML hoists an inner button out into a sibling and silently breaks flex rows.
- **Plain `int` for the threshold query/body field.** Never `Literal[...]` — int `Literal` params 422 on every real request in this pinned FastAPI/Pydantic pair.
- **Commit message trailers:** do NOT add `Co-Authored-By`. This repo's `.claude/settings.json` sets no `attribution.commit`.
- **Do not push to `origin`.** Pushing `main` deploys to production. Commit locally only; the user decides when to push.

## File Structure

**Created:**

| Path | Responsibility |
| --- | --- |
| `backend/alembic/versions/a1c3e5b7d9f0_add_item_low_stock_threshold.py` | The column and its backfill |
| `backend/app/domain/low_stock.py` | Pure predicates: `is_low`, `crossed_into_low`, `membership_changed`, the two constants |
| `backend/app/services/low_stock.py` | Request-scoped crossing buffer. Imports nothing from `app.services` — this is what keeps `work_orders → low_stock` cycle-free |
| `backend/app/routers/_low_stock.py` | `flush_low_stock` (drain + push + emit, swallowing) and `emit_low_stock_changed` |
| `backend/static/pages/low-stock.html` | Page fragment |
| `backend/static/views/lowStock.js` | Page behaviour |
| `backend/tests/test_low_stock_domain.py` | Predicate tests (pure) |
| `backend/tests/test_low_stock_buffer.py` | Buffer tests (pure) |
| `backend/tests/test_low_stock_triggers.py` | All eight mutation points (DB) |
| `backend/tests/test_items_low_stock.py` | Both routes over real HTTP (DB) |
| `backend/tests/test_low_stock_shell.py` | Page fragment / nav plumbing (pure) |

**Modified:** `backend/app/models.py`, `backend/app/domain/notifications.py`, `backend/app/domain/realtime.py`, `backend/app/services/notifications.py`, `backend/app/services/transactions.py`, `backend/app/services/mass_staging.py`, `backend/app/services/work_orders.py`, `backend/app/services/items.py`, `backend/app/routers/items.py`, `backend/app/routers/transactions.py`, `backend/app/routers/mass_stages.py`, `backend/app/routers/work_orders.py`, `backend/app/schemas/items.py`, `backend/app/main.py`, `backend/static/api.js`, `backend/static/main.js`, `backend/static/views/nav.js`, `backend/static/shell-head.html`, `backend/static/styles.css`, `backend/tests/test_notifications_domain.py`, `backend/tests/test_realtime_domain.py`, and four docs.

## Running the tests

From `backend/`, with the venv active:

```bash
cd backend
./venv/Scripts/python.exe -m pytest tests/ -q
```

DB-backed tests need the local Postgres on port 8801 (`DATABASE_URL` is already in `backend/.env`). Pure tests run without it. **Never truncate or rewrite `.env`.**

One pre-existing failure is environmental, not yours: `test_cascade_deletes_with_user` fails against a dev database holding real cloud-session rows. Ignore it.

---

### Task 1: The threshold column

**Files:**
- Create: `backend/alembic/versions/a1c3e5b7d9f0_add_item_low_stock_threshold.py`
- Modify: `backend/app/models.py:111` (add the column after `quantity`)
- Modify: `backend/app/schemas/items.py:82` (add the field to `ItemResponse`)
- Test: `backend/tests/test_items_low_stock.py` (created here, one test)

**Interfaces:**
- Consumes: nothing.
- Produces: `Item.low_stock_threshold` (int, NOT NULL, default 6); `ItemResponse.low_stock_threshold: int`.

- [x] **Step 1: Write the failing test**

Create `backend/tests/test_items_low_stock.py`:

```python
"""The Low Stock column, list route, and threshold route.

Route tests drive real HTTP through `TestClient` rather than calling the
handler function directly: a direct call never exercises FastAPI's
path/query parsing, which is where this repo has been bitten before
(FastAPI 0.136 / Pydantic 2.13 and int `Literal` params).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
from decimal import Decimal

from app.domain import low_stock as low_stock_policy
from app.models import Item


def _seed_item(db, *, quantity="10", threshold=None):
    item = Item(
        barcode=f"BC-{uuid.uuid4().hex[:10]}",
        name=f"Widget {uuid.uuid4().hex[:6]}",
        quantity=Decimal(quantity),
        location="Bay 1",
    )
    if threshold is not None:
        item.low_stock_threshold = threshold
    db.add(item)
    db.flush()
    return item


def test_new_items_default_to_the_shared_threshold(db):
    item = _seed_item(db)
    db.commit()
    db.refresh(item)
    assert item.low_stock_threshold == low_stock_policy.DEFAULT_LOW_STOCK_THRESHOLD
```

- [x] **Step 2: Run it and watch it fail**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_items_low_stock.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.domain.low_stock'`.

- [x] **Step 3: Add the constants module (minimum needed now)**

Create `backend/app/domain/low_stock.py` with only the constants for the moment; Task 2 fills in the predicates:

```python
"""Low-stock policy: is an item low, and did this write make it low.

Layer: pure domain (no SQLAlchemy, no FastAPI, no models). Every
function takes numbers and returns a bool, which is what makes the one
interesting rule -- the *edge*, not the state -- testable without a
database.

The whole feature rests on a single idea: a push fires when an item was
not low before a write and is low after it. Because a threshold edit is
also a write with a before and an after, raising a threshold past the
current count is the same event as dispensing down past a fixed one, and
falls out of the same comparison rather than needing a second code path.
That is why there is no armed-state column anywhere in this feature.
"""

from decimal import Decimal

# The threshold every item starts at. Written here and in the Alembic
# migration's `server_default`, and nowhere else -- a third copy is how
# the database and the application drift apart.
DEFAULT_LOW_STOCK_THRESHOLD = 6

# Thresholds are whole numbers of at least one. There is deliberately no
# "0 = never alert" mute: stock cannot go below zero, so a zero threshold
# would be an invisible off-switch rather than a threshold.
MIN_LOW_STOCK_THRESHOLD = 1
```

- [x] **Step 4: Add the model column**

In `backend/app/models.py`, immediately after the `quantity` column in `class Item` (line 111):

```python
    quantity = Column(Numeric, nullable=False, default=0)
    # The count at or below which this item raises a low-stock push and
    # appears on the Low Stock page. Whole numbers >= 1 (see
    # `domain.low_stock`); every item has one, so there is no "unmonitored"
    # state to handle at the eight stock-mutation sites.
    low_stock_threshold = Column(
        Integer, nullable=False, default=DEFAULT_LOW_STOCK_THRESHOLD, server_default="6"
    )
```

Add `Integer` to the existing `from sqlalchemy import (...)` import list at the top of `models.py`, and add near the other app imports:

```python
from app.domain.low_stock import DEFAULT_LOW_STOCK_THRESHOLD
```

- [x] **Step 5: Write the migration**

Create `backend/alembic/versions/a1c3e5b7d9f0_add_item_low_stock_threshold.py`:

```python
"""add low_stock_threshold to items

Revision ID: a1c3e5b7d9f0
Revises: b3d5f7a9c1e2
Create Date: 2026-09-01 12:00:00.000000

Introduces per-item low-stock alerting. An item whose on-hand count falls
to or below this number raises a push to TechFM OA and above and appears
on the Low Stock page.

`server_default="6"` does double duty: it backfills every existing row in
the same statement (so the column can be NOT NULL immediately) and it is
what makes an INSERT that omits the column land on the shared default.
The CHECK pins the floor of 1 -- a zero threshold would be an invisible
mute, since stock cannot go below zero.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1c3e5b7d9f0"
down_revision: Union[str, Sequence[str], None] = "b3d5f7a9c1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "items",
        sa.Column(
            "low_stock_threshold",
            sa.Integer(),
            nullable=False,
            server_default="6",
        ),
    )
    op.create_check_constraint(
        "ck_items_low_stock_threshold_positive",
        "items",
        "low_stock_threshold >= 1",
    )


def downgrade() -> None:
    op.drop_constraint("ck_items_low_stock_threshold_positive", "items", type_="check")
    op.drop_column("items", "low_stock_threshold")
```

- [x] **Step 6: Add the response field**

In `backend/app/schemas/items.py`, in `ItemResponse`, immediately after `quantity: Decimal` (line 82):

```python
    quantity: Decimal
    # Operational, not cost-sensitive: unlike `price` / `product_link` this
    # is NOT redacted in `routers/items._item_response`, so every role sees
    # it wherever an item is returned.
    low_stock_threshold: int
```

- [x] **Step 7: Run the migration**

Run: `cd backend && ./venv/Scripts/python.exe -m alembic upgrade head`
Expected: `Running upgrade b3d5f7a9c1e2 -> a1c3e5b7d9f0, add low_stock_threshold to items`.

- [x] **Step 8: Run the tests**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_items_low_stock.py tests/test_item_price_gating.py -q`
Expected: PASS. `test_item_price_gating.py` builds a `SimpleNamespace` item, so add `low_stock_threshold=6` to its `_fake_item()` if it fails on the missing attribute.

> **Deviation (2026-09-01):** `tests/test_item_barcodes.py` has its own separate
> `_fake_item()` (not the one in `test_item_price_gating.py`) that also builds
> a `SimpleNamespace` fed to `ItemResponse.model_validate`. It needed the same
> one-line `low_stock_threshold=6` fix, found via the full-suite run in Step 9
> rather than the plan's two-file Step 8 command. Anyone adding another field
> to `ItemResponse` later should grep for `_fake_item` repo-wide, not just in
> `test_item_price_gating.py`.

- [x] **Step 9: Full suite**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/ -q`
Expected: PASS except the known environmental `test_cascade_deletes_with_user`.

> Ran 2026-09-01: 1584 passed (excluding `test_cascade_deletes_with_user`).
> One other failure appeared on the first full-suite run,
> `test_netfacilities_cloud_auth.py::test_enrichment_giving_up_leaves_the_import_standing`;
> it passed in isolation both before and after this task's changes, so it is a
> pre-existing timing-flaky test, not a regression from this work.

- [x] **Step 10: Commit**

```bash
git add backend/alembic/versions/a1c3e5b7d9f0_add_item_low_stock_threshold.py backend/app/models.py backend/app/domain/low_stock.py backend/app/schemas/items.py backend/tests/test_items_low_stock.py backend/tests/test_item_price_gating.py backend/tests/test_item_barcodes.py
git commit -m "feat(items): add per-item low_stock_threshold column"
```

Committed as `6fd036b`.

---

### Task 2: The predicates

**Files:**
- Modify: `backend/app/domain/low_stock.py`
- Test: `backend/tests/test_low_stock_domain.py`

**Interfaces:**
- Consumes: `DEFAULT_LOW_STOCK_THRESHOLD`, `MIN_LOW_STOCK_THRESHOLD` from Task 1.
- Produces:
  - `is_low(quantity: Decimal, threshold: int) -> bool`
  - `crossed_into_low(*, quantity_before, threshold_before, quantity_after, threshold_after) -> bool`
  - `membership_changed(*, quantity_before, threshold_before, quantity_after, threshold_after) -> bool`

- [x] **Step 1: Write the failing tests**

Create `backend/tests/test_low_stock_domain.py`:

```python
"""The low-stock edge rule.

The state ("is it low") is trivial; the *edge* ("did this write make it
low") is the whole feature, and it is what stops a fast-moving item
pushing on every dispense while it sits below its threshold.

Because a threshold edit is a write with a before and an after, the same
function decides both a stock drop and a threshold raise. Each is pinned
here so a later refactor cannot quietly split them apart again.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decimal import Decimal

from app.domain import low_stock


def test_at_the_threshold_is_low():
    """`<=`, not `<`. Six with a threshold of six is the alerting case
    the whole feature was asked for."""
    assert low_stock.is_low(Decimal("6"), 6) is True


def test_above_the_threshold_is_not_low():
    assert low_stock.is_low(Decimal("7"), 6) is False


def test_a_negative_count_is_low():
    """Scan / Stock deliberately allows a dispense to drive the recorded
    count below zero and raises a recount request. That item is as low as
    an item can be."""
    assert low_stock.is_low(Decimal("-2"), 6) is True


def test_a_decimal_count_compares_against_a_whole_threshold():
    assert low_stock.is_low(Decimal("2.5"), 6) is True
    assert low_stock.is_low(Decimal("6.5"), 6) is False


def test_a_dispense_that_crosses_the_threshold_fires():
    assert low_stock.crossed_into_low(
        quantity_before=Decimal("7"), threshold_before=6,
        quantity_after=Decimal("6"), threshold_after=6,
    ) is True


def test_a_dispense_that_leaves_an_already_low_item_low_is_silent():
    """The noise case. Without this the crew gets a push per dispense for
    the rest of the item's life below its threshold."""
    assert low_stock.crossed_into_low(
        quantity_before=Decimal("5"), threshold_before=6,
        quantity_after=Decimal("4"), threshold_after=6,
    ) is False


def test_a_restock_back_above_the_threshold_does_not_fire():
    assert low_stock.crossed_into_low(
        quantity_before=Decimal("2"), threshold_before=6,
        quantity_after=Decimal("9"), threshold_after=6,
    ) is False


def test_raising_the_threshold_past_the_current_count_fires():
    """The retune case: nothing moved, but the item is newly low."""
    assert low_stock.crossed_into_low(
        quantity_before=Decimal("10"), threshold_before=6,
        quantity_after=Decimal("10"), threshold_after=20,
    ) is True


def test_lowering_the_threshold_below_the_current_count_does_not_fire():
    assert low_stock.crossed_into_low(
        quantity_before=Decimal("10"), threshold_before=20,
        quantity_after=Decimal("10"), threshold_after=6,
    ) is False


def test_membership_changes_in_both_directions():
    """The realtime predicate is wider than the push predicate: an item
    leaving the list must invalidate an open Low Stock page too."""
    assert low_stock.membership_changed(
        quantity_before=Decimal("2"), threshold_before=6,
        quantity_after=Decimal("9"), threshold_after=6,
    ) is True
    assert low_stock.membership_changed(
        quantity_before=Decimal("9"), threshold_before=6,
        quantity_after=Decimal("2"), threshold_after=6,
    ) is True


def test_membership_is_unchanged_when_a_low_item_stays_low():
    assert low_stock.membership_changed(
        quantity_before=Decimal("5"), threshold_before=6,
        quantity_after=Decimal("4"), threshold_after=6,
    ) is False
```

- [x] **Step 2: Run them and watch them fail**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_low_stock_domain.py -q`
Expected: FAIL — `AttributeError: module 'app.domain.low_stock' has no attribute 'is_low'`.

- [x] **Step 3: Implement**

Append to `backend/app/domain/low_stock.py`:

```python
def is_low(quantity: Decimal, threshold: int) -> bool:
    """Whether `quantity` is at or below `threshold`.

    `<=`, not `<`: "six or fewer" is the alert that was asked for, so an
    item sitting exactly on its threshold is already low. A negative
    count (Scan / Stock records real usage past the recorded balance) is
    low for the same reason.
    """
    return Decimal(quantity) <= Decimal(threshold)


def crossed_into_low(
    *,
    quantity_before: Decimal,
    threshold_before: int,
    quantity_after: Decimal,
    threshold_after: int,
) -> bool:
    """Whether this write is the moment the item BECAME low.

    The push predicate, and the reason there is no armed-state column: an
    item that was already low stays silent because the before-state is
    already `True`, and it re-arms by being restocked, with nothing
    persisted in between.

    Taking a before *and* after threshold is what folds the retune case
    in. Raising a threshold from 6 to 20 over a count of 10 is the same
    false-to-true edge as dispensing from 10 to 5 against a fixed 6, so
    both callers -- the stock services and the threshold route -- ask the
    same question.
    """
    return not is_low(quantity_before, threshold_before) and is_low(
        quantity_after, threshold_after
    )


def membership_changed(
    *,
    quantity_before: Decimal,
    threshold_before: int,
    quantity_after: Decimal,
    threshold_after: int,
) -> bool:
    """Whether the item entered OR left the low-stock set.

    Deliberately wider than `crossed_into_low`: the Low Stock page has to
    drop a row when an item is restocked back above its threshold, and a
    push-shaped predicate would leave that row on screen until the next
    page activation.
    """
    return is_low(quantity_before, threshold_before) != is_low(
        quantity_after, threshold_after
    )
```

- [x] **Step 4: Run the tests**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_low_stock_domain.py -q`
Expected: PASS (11 tests).

- [x] **Step 5: Commit**

```bash
git add backend/app/domain/low_stock.py backend/tests/test_low_stock_domain.py
git commit -m "feat(low-stock): pure edge-crossing predicates"
```

Committed as `f9923dd`.

---

### Task 3: The request-scoped crossing buffer

**Files:**
- Create: `backend/app/services/low_stock.py`
- Test: `backend/tests/test_low_stock_buffer.py`

**Interfaces:**
- Consumes: `app.domain.low_stock` (Task 2), `app.domain.receipt.format_quantity`.
- Produces:
  - `class Crossing` — frozen dataclass with `item_id: uuid.UUID`, `name: str`, `quantity: str`, `pushes: bool`
  - `record(item, *, quantity_before, threshold_before=None) -> None`
  - `drain() -> list[Crossing]`
  - `MAX_BUFFERED_CROSSINGS = 500`

`item` is any object exposing `.id`, `.name`, `.quantity`, `.low_stock_threshold` — the ORM `Item` in production, a `SimpleNamespace` in tests. The module imports no ORM model and nothing from `app.services`; that is what keeps `services.work_orders → services.low_stock` free of an import cycle.

- [x] **Step 1: Write the failing tests**

Create `backend/tests/test_low_stock_buffer.py`:

```python
"""The request-scoped crossing buffer.

Two things are worth pinning: that what gets buffered is plain values
(anything lazy would raise `DetachedInstanceError` in the background task
that eventually reads it), and that the buffer is per-context, so one
request's crossings can never be delivered on another's response.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import contextvars
import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services import low_stock


@pytest.fixture(autouse=True)
def _clean_buffer():
    """Drain before and after so a leaked entry fails its own test rather
    than the next one."""
    low_stock.drain()
    yield
    low_stock.drain()


def _item(quantity="5", threshold=6, name="Blue Tape"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        name=name,
        quantity=Decimal(quantity),
        low_stock_threshold=threshold,
    )


def test_a_crossing_is_buffered_with_pushes_true():
    item = _item(quantity="5")
    low_stock.record(item, quantity_before=Decimal("7"))
    crossings = low_stock.drain()
    assert len(crossings) == 1
    assert crossings[0].pushes is True
    assert crossings[0].name == "Blue Tape"
    assert crossings[0].item_id == item.id


def test_an_already_low_item_buffers_nothing():
    """Membership did not change, so there is neither a push to send nor a
    page to invalidate. This is the noise case the whole edge rule exists
    for."""
    item = _item(quantity="4")
    low_stock.record(item, quantity_before=Decimal("5"))
    assert low_stock.drain() == []


def test_leaving_the_low_set_is_buffered_with_pushes_false():
    item = _item(quantity="9")
    low_stock.record(item, quantity_before=Decimal("2"))
    crossings = low_stock.drain()
    assert len(crossings) == 1
    assert crossings[0].pushes is False


def test_a_write_that_changes_nothing_relevant_buffers_nothing():
    item = _item(quantity="9")
    low_stock.record(item, quantity_before=Decimal("10"))
    assert low_stock.drain() == []


def test_quantity_is_buffered_as_a_display_string():
    """`Decimal("5.000")` on a lock screen reads as a bug. The background
    task receives text, already formatted, because it cannot format
    anything itself without the session."""
    item = _item(quantity="5.000")
    low_stock.record(item, quantity_before=Decimal("7"))
    assert low_stock.drain()[0].quantity == "5"


def test_a_threshold_raise_crosses_without_stock_moving():
    item = _item(quantity="10", threshold=20)
    low_stock.record(item, quantity_before=Decimal("10"), threshold_before=6)
    crossings = low_stock.drain()
    assert len(crossings) == 1
    assert crossings[0].pushes is True


def test_draining_empties_the_buffer():
    low_stock.record(_item(quantity="5"), quantity_before=Decimal("7"))
    assert len(low_stock.drain()) == 1
    assert low_stock.drain() == []


def test_the_buffer_does_not_leak_between_contexts():
    """A copied context is what each request (and each threadpool call
    into a sync handler) actually runs in. Recording inside one must be
    invisible outside it."""
    def _record_in_here():
        low_stock.record(_item(quantity="5"), quantity_before=Decimal("7"))
        return len(low_stock.drain())

    assert contextvars.copy_context().run(_record_in_here) == 1
    assert low_stock.drain() == []


def test_the_buffer_is_bounded():
    """A non-HTTP caller (a script, a job) never drains. The cap stops an
    unbounded list rather than pretending that case cannot happen."""
    for _ in range(low_stock.MAX_BUFFERED_CROSSINGS + 10):
        low_stock.record(_item(quantity="5"), quantity_before=Decimal("7"))
    assert len(low_stock.drain()) == low_stock.MAX_BUFFERED_CROSSINGS
```

- [x] **Step 2: Run them and watch them fail**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_low_stock_buffer.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.low_stock'`.

- [x] **Step 3: Implement**

Create `backend/app/services/low_stock.py`:

```python
"""The request-scoped buffer of low-stock crossings.

Layer: services, but deliberately the thinnest one in the app. This
module imports **nothing from `app.services`** and no ORM model. Three
services will import it (`transactions`, `mass_staging`, `work_orders`)
and one of those is imported by `services.notifications`; a service
import in the other direction would close that ring into a cycle.

**Why a buffer at all.** Stock moves in the middle of services that are
several frames below the router, some of them inside loops. Threading a
return value up through `load_item`'s allocation loop and
`work_orders`' line editing would touch far more code than the feature
is worth, and would still leave the next stock-writing service free to
forget. A buffer lets each mutation point say one true thing about the
item in front of it and lets exactly one place -- the router -- decide
what to do about it.

**Why a ContextVar, and why it is safe.** Each request runs in its own
copied context: an async handler in its task's context, a sync handler in
a fresh `copy_context()` per threadpool call. So a `set()` here is
visible for the rest of that request and invisible to every other, with
no explicit teardown. The buffer is only ever read back inside the same
handler invocation that filled it, which is the one direction context
copying guarantees.

**The invariant the call sites rely on:** `record` is called immediately
*before* the service's `db.commit()`, while the ORM object is loaded and
its values are cheap to read; `drain` is called by the router only after
the handler's success path. A service that raises between the two never
reaches the drain, and its buffered entry dies with the request context.
"""

import logging
import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from app.domain import low_stock as policy
from app.domain.receipt import format_quantity

logger = logging.getLogger(__name__)

# A ceiling, not a budget. Every HTTP path drains, so this only bites a
# non-request caller (a script, an import job) that mutates stock in a
# loop and never drains -- there, an unbounded list is a slow leak and a
# dropped notification is not.
MAX_BUFFERED_CROSSINGS = 500


@dataclass(frozen=True)
class Crossing:
    """One item's low-stock membership change, as plain values.

    Everything a background task will need is already a `str` / `int` /
    `uuid` here. Keeping an ORM object instead is the single easiest way
    to break notifications, and it breaks them only in a real deployment:
    the request's session is closed before background tasks run, so a
    lazy attribute touched there raises `DetachedInstanceError` that no
    synchronous test would ever see.

    `pushes` is the narrow, edge-only question; membership merely
    *changing* is the wider one and is why an item leaving the low set is
    buffered at all.
    """

    item_id: uuid.UUID
    name: str
    quantity: str
    pushes: bool


_buffer: ContextVar[Optional[list]] = ContextVar("low_stock_buffer", default=None)


def record(item, *, quantity_before: Decimal, threshold_before: Optional[int] = None) -> None:
    """Note that `item` may have entered or left the low-stock set.

    Call immediately before the service's `db.commit()`, with
    `quantity_before` captured before the mutation. `threshold_before`
    defaults to the item's current threshold, which is correct for every
    stock write -- only the threshold route supplies it, and only because
    that route is the one write where the threshold itself moved.

    Buffers nothing when membership did not change, so the common case
    (a dispense that leaves a healthy item healthy) costs two
    comparisons and no allocation.
    """
    threshold_after = int(item.low_stock_threshold)
    if threshold_before is None:
        threshold_before = threshold_after

    quantity_after = Decimal(item.quantity)
    if not policy.membership_changed(
        quantity_before=quantity_before,
        threshold_before=threshold_before,
        quantity_after=quantity_after,
        threshold_after=threshold_after,
    ):
        return

    entries = _buffer.get()
    if entries is None:
        entries = []
        _buffer.set(entries)
    if len(entries) >= MAX_BUFFERED_CROSSINGS:
        logger.warning(
            "low-stock buffer full at %s entries; dropping further crossings",
            MAX_BUFFERED_CROSSINGS,
        )
        return

    entries.append(
        Crossing(
            item_id=item.id,
            name=item.name,
            quantity=format_quantity(quantity_after),
            pushes=policy.crossed_into_low(
                quantity_before=quantity_before,
                threshold_before=threshold_before,
                quantity_after=quantity_after,
                threshold_after=threshold_after,
            ),
        )
    )


def drain() -> list:
    """Take everything buffered so far and empty the buffer.

    Total by contract: called on paths that have already committed, and
    called again by tests for cleanup. Returning a new list (rather than
    the buffered one) means a caller holding the result cannot be
    surprised by a later `record`.
    """
    entries = _buffer.get()
    if not entries:
        return []
    taken = list(entries)
    entries.clear()
    return taken
```

- [x] **Step 4: Run the tests**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_low_stock_buffer.py -q`
Expected: PASS (9 tests).

- [x] **Step 5: Commit**

```bash
git add backend/app/services/low_stock.py backend/tests/test_low_stock_buffer.py
git commit -m "feat(low-stock): request-scoped crossing buffer"
```

Committed as `56063ca`.

---

## Session hand-off

**Done through Task 4 (commit `a2e2935`).** Next session: start at **Task 5:
The realtime event** below. Task 4 deviated once from the plan: a
pre-existing event partition in `test_notifications_domain.py` needed a
fourth bucket (`_LOW_STOCK_EVENTS`) for the new event — see the deviation
note under Task 4 Step 7. `app.domain.notifications` now exposes
`EVENT_ITEM_LOW_STOCK`, `LOW_STOCK_AUDIENCE_MIN_ROLE`,
`recipients_for_low_stock`, and a `build_message` widened with `name` /
`quantity` params; `EVENT_ITEM_LOW_STOCK` is registered in `ALL_EVENTS`.
Full suite: 1611 passed.

---

### Task 4: The notification rule and its text

**Files:**
- Modify: `backend/app/domain/notifications.py` (module docstring, event constants, `ALL_EVENTS`, `_MESSAGES`, new `recipients_for_low_stock`, `build_message` signature)
- Test: `backend/tests/test_notifications_domain.py` (append)

**Interfaces:**
- Consumes: `roles.ROLE_TECHFM_OA`.
- Produces:
  - `EVENT_ITEM_LOW_STOCK = "item.low_stock"`
  - `LOW_STOCK_AUDIENCE_MIN_ROLE = roles.ROLE_TECHFM_OA`
  - `recipients_for_low_stock(*, recipient_ids: Sequence[uuid.UUID]) -> list[uuid.UUID]`
  - `build_message(event_type, *, number=None, count=None, name=None, quantity=None) -> tuple[str, str]`

- [x] **Step 1: Write the failing tests**

Append to `backend/tests/test_notifications_domain.py`:

```python
# --- low stock ----------------------------------------------------------


def test_low_stock_names_the_item_and_its_count():
    title, body = notif.build_message(
        notif.EVENT_ITEM_LOW_STOCK, name="3M Blue Tape", quantity="5"
    )
    assert title == "Low stock"
    assert body == "3M Blue Tape is down to 5."


def test_low_stock_text_still_refuses_a_missing_field():
    """The guard that keeps a buzz with no words from ever shipping."""
    with pytest.raises(ValueError):
        notif.build_message(notif.EVENT_ITEM_LOW_STOCK, name="3M Blue Tape")


def test_widening_the_builder_did_not_break_the_work_order_events():
    title, body = notif.build_message(
        notif.EVENT_WORK_ORDER_ASSIGNED, number="WO-1234"
    )
    assert body == "You were assigned to WO-1234."


def test_low_stock_keeps_the_actor():
    """Deliberately inverts the rule every other event follows. A low
    stockroom is a state alarm, not a report of somebody's action, and
    the person who just took the last of it is the most useful person to
    tell."""
    actor = uuid.uuid4()
    other = uuid.uuid4()
    assert notif.recipients_for_low_stock(recipient_ids=[actor, other]) == [
        actor,
        other,
    ]


def test_low_stock_still_dedupes_and_drops_none():
    first = uuid.uuid4()
    assert notif.recipients_for_low_stock(
        recipient_ids=[first, None, first]
    ) == [first]


def test_low_stock_audience_floor_is_techfm_oa():
    """A route written at the Admin floor out of habit would silently lock
    TechFM OA out of a capability they are meant to have."""
    assert notif.LOW_STOCK_AUDIENCE_MIN_ROLE == roles.ROLE_TECHFM_OA


def test_low_stock_is_registered():
    assert notif.EVENT_ITEM_LOW_STOCK in notif.ALL_EVENTS
```

Check the file's existing imports; add any of `pytest`, `uuid`, `roles` that are missing.

- [x] **Step 2: Run them and watch them fail**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_notifications_domain.py -q`
Expected: FAIL — `AttributeError: module 'app.domain.notifications' has no attribute 'EVENT_ITEM_LOW_STOCK'`.

- [x] **Step 3: Widen the module's stated rule**

In `backend/app/domain/notifications.py`, replace the third and fourth paragraphs of the module docstring (the two beginning "**Notification text renders on a locked phone.**" and "The line is **identifiers and counts yes...**") with:

```
**Notification text renders on a locked phone.** Nothing built here may
contain a customer name, an address, a job description, note text, or a
price. A work-order *number* is deliberately allowed: it is an opaque
identifier rather than a detail, it is what makes the notification
actionable, and it is already visible to anyone holding the phone.

The line is **catalogue identifiers, counts, and quantities yes; customer,
job, and price detail no.** `build_message` accepts a `number`, a `count`,
an item `name`, and a `quantity`, and widening it past those is the change
to argue about, not the strings.

`count` was added for the bulk import event: "40 work orders have been
assigned to you" names no work order, no customer, and no job -- a tally
of your own queue discloses nothing to somebody holding the phone that
the badge on the app icon would not.

`name` was added for the low-stock event, and it is the one entry that
looks like a widening rather than an addition. It is not: the rule
protects *customer and job* detail, and an item name is a
catalogue/manufacturer string ("3M Blue Tape") that identifies no person,
site, or job. Without it the notification is unactionable -- nobody reads
a barcode off a lock screen -- so the choice was a useful notification or
none at all. A *price* remains forbidden on the same item.
```

- [x] **Step 4: Add the event, audience, and text**

After `EVENT_NETFACILITIES_IMPORT_FAILED`:

```python
EVENT_ITEM_LOW_STOCK = "item.low_stock"
```

Add `EVENT_ITEM_LOW_STOCK,` to the `ALL_EVENTS` tuple.

After `UNROUTED_HOLD_AUDIENCE_MIN_ROLE`:

```python
# Who hears that the stockroom is running out. TechFM OA and above -- the
# same rank that works the Low Stock page and can retune a threshold, so
# every recipient of the alert can also act on it. A third constant rather
# than a reuse of either above: "who watches the review queue" and "who
# covers an unowned job" are different questions from "who reorders", and
# must be able to diverge without one silently dragging another.
LOW_STOCK_AUDIENCE_MIN_ROLE = roles.ROLE_TECHFM_OA
```

Add to `_MESSAGES`:

```python
    EVENT_ITEM_LOW_STOCK: (
        "Low stock",
        "{name} is down to {quantity}.",
    ),
```

- [x] **Step 5: Add the recipient rule**

After `recipients_for_hold`:

```python
def recipients_for_low_stock(
    *,
    recipient_ids: Sequence[uuid.UUID],
) -> list[uuid.UUID]:
    """An item fell to or below its threshold -- tell everyone who can act.

    **This rule deliberately does NOT suppress the actor**, and it is the
    only stock-side rule that does not. Every other event reports
    somebody's action to somebody else, where telling the actor what they
    just did is noise. This one is a state alarm about the stockroom: the
    person who just dispensed the last of an item is standing in front of
    the empty shelf and is the single most useful person to tell.

    Expressed by passing `actor_id=None` rather than by skipping
    `select_recipients`, so the dedup and the `None`-dropping still apply
    -- the audience is resolved from a role and can contain neither, but
    a future caller composing this list from several sources gets both
    for free.
    """
    return select_recipients(recipient_ids, actor_id=None)
```

- [x] **Step 6: Widen `build_message`**

Replace the signature and the `supplied` dict in `build_message`:

```python
def build_message(
    event_type: str,
    *,
    number: Optional[str] = None,
    count: Optional[int] = None,
    name: Optional[str] = None,
    quantity: Optional[str] = None,
) -> tuple[str, str]:
```

and

```python
    supplied = {
        key: value
        for key, value in (
            ("number", number),
            ("count", count),
            ("name", name),
            ("quantity", quantity),
        )
        if value is not None
    }
```

Leave the two `raise ValueError` branches exactly as they are — the second is what makes `test_low_stock_text_still_refuses_a_missing_field` pass.

- [x] **Step 7: Run the tests**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_notifications_domain.py -q`
Expected: PASS.

> **Deviation (2026-09-01):** `test_notifications_domain.py` has a pre-existing
> `_NUMBER_EVENTS` / `_COUNT_EVENTS` / `_CHAIN_EVENTS` partition (built from
> `notif.ALL_EVENTS`) that the plan's Step 1 diff did not touch. Adding
> `EVENT_ITEM_LOW_STOCK` to `ALL_EVENTS` put it in `_NUMBER_EVENTS` by default,
> which parametrizes `build_message` with only `number=` and fails since the
> low-stock template needs `name`/`quantity`. Added a fourth partition,
> `_LOW_STOCK_EVENTS = (notif.EVENT_ITEM_LOW_STOCK,)`, excluded it from
> `_NUMBER_EVENTS`, and widened the completeness test to
> `test_every_event_is_either_a_number_a_count_a_chain_or_a_low_stock_event`.
> Same class of gap as Task 1's `_fake_item` deviation — a fixed enumeration
> in an existing test file didn't anticipate a new event. Anyone adding
> another event later should check this partition too.

- [x] **Step 8: Commit**

```bash
git add backend/app/domain/notifications.py backend/tests/test_notifications_domain.py
git commit -m "feat(notifications): low-stock event, audience, and item-naming text"
```

Committed as `a2e2935`. Full suite: 1611 passed.

---

### Task 5: The realtime event

**Files:**
- Modify: `backend/app/domain/realtime.py` (`__all__`, vocabulary, `_AUDIENCE_MIN_ROLE`)
- Test: `backend/tests/test_realtime_domain.py` (append)

**Interfaces:**
- Produces: `EVENT_ITEM_LOW_STOCK_CHANGED = "item.low_stock.changed"`, audience floor `ROLE_TECHFM_OA`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_realtime_domain.py`:

```python
def test_low_stock_events_reach_techfm_oa_and_above():
    for role in ("techfm_oa", "admin", "owner"):
        assert (
            realtime.audience_allows(realtime.EVENT_ITEM_LOW_STOCK_CHANGED, role)
            is True
        ), role


def test_low_stock_events_do_not_reach_lower_roles():
    """Noise, not security -- P2 keeps row data out of the envelope. The
    Low Stock page is TechFM OA+ only, so nobody below it can act on the
    invalidation."""
    for role in ("supervisor", "technician"):
        assert (
            realtime.audience_allows(realtime.EVENT_ITEM_LOW_STOCK_CHANGED, role)
            is False
        ), role
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_realtime_domain.py -q`
Expected: FAIL — `AttributeError: ... has no attribute 'EVENT_ITEM_LOW_STOCK_CHANGED'`.

- [ ] **Step 3: Implement**

In `backend/app/domain/realtime.py`, add `"EVENT_ITEM_LOW_STOCK_CHANGED",` to `__all__` (keep the list alphabetical), then after `EVENT_LABOR_SESSION_CHANGED`:

```python
# The Low Stock page's membership. Narrow in the same way the others are:
# it invalidates *which items are low*, not an item's contents, so a name
# or price edit is not in this vocabulary. Emitted whenever an item enters
# or leaves the set -- a crossing in either direction, a threshold edit,
# an item created below its threshold, or an item archived out of the list.
#
# `id` names one item; `None` is unused today and reserved for a command
# that could change several rows at once.
EVENT_ITEM_LOW_STOCK_CHANGED = "item.low_stock.changed"
```

and in `_AUDIENCE_MIN_ROLE`:

```python
    # The page is TechFM OA+ for both viewing and editing, and so is the
    # push, so the socket audience matches both rather than inventing a
    # third rank.
    EVENT_ITEM_LOW_STOCK_CHANGED: roles.ROLE_TECHFM_OA,
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_realtime_domain.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/domain/realtime.py backend/tests/test_realtime_domain.py
git commit -m "feat(realtime): item.low_stock.changed invalidation event"
```

---

### Task 6: Push dispatch and the router flush helper

**Files:**
- Modify: `backend/app/services/notifications.py` (add `notify_item_low_stock`)
- Create: `backend/app/routers/_low_stock.py`
- Test: `backend/tests/test_low_stock_triggers.py` (created here, dispatch tests only)

**Interfaces:**
- Consumes: `services.low_stock.Crossing` / `drain` (Task 3), `domain.notifications` (Task 4), `domain.realtime` (Task 5), `services.push.user_ids_for_min_role`.
- Produces:
  - `services.notifications.notify_item_low_stock(db, background, *, crossings) -> None`
  - `routers._low_stock.flush_low_stock(db, background) -> None`
  - `routers._low_stock.emit_low_stock_changed(item_id) -> None`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_low_stock_triggers.py`:

```python
"""Low-stock dispatch and the eight stock-mutation trigger points.

Nothing here sends a real push: the transport has its own coverage in
`test_push_subscriptions.py`, and re-proving it per trigger is what makes
triggers expensive to add. These assert on *who* would be told and on
*whether a task was scheduled at all*.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
from decimal import Decimal

import pytest
from fastapi import BackgroundTasks

from app.domain import realtime as realtime_policy
from app.models import Item, User
from app.services import auth as auth_service
from app.services import low_stock as low_stock_service
from app.services import notifications as notifications_service
from app.services import push as push_service


@pytest.fixture(autouse=True)
def _clean_buffer():
    low_stock_service.drain()
    yield
    low_stock_service.drain()


@pytest.fixture
def configured(monkeypatch):
    """Push enabled. With no private key the service declines to schedule
    anything, which is correct and would hide every assertion here."""
    monkeypatch.setattr(push_service, "VAPID_PRIVATE_KEY", "test-private-key")
    return True


def _seed_user(db, role):
    user = User(
        username=f"u-{uuid.uuid4().hex[:10]}",
        password_hash=auth_service.hash_password("hunter2"),
        role=role,
    )
    db.add(user)
    db.flush()
    return user


def _seed_item(db, *, quantity="10", threshold=6):
    item = Item(
        barcode=f"BC-{uuid.uuid4().hex[:10]}",
        name=f"Widget {uuid.uuid4().hex[:6]}",
        quantity=Decimal(quantity),
        location="Bay 1",
        low_stock_threshold=threshold,
    )
    db.add(item)
    db.flush()
    return item


def _scheduled(background):
    return [task.args for task in background.tasks]


def _crossing(*, pushes=True, name="Blue Tape", quantity="5"):
    return low_stock_service.Crossing(
        item_id=uuid.uuid4(), name=name, quantity=quantity, pushes=pushes
    )


# --- dispatch -----------------------------------------------------------


def test_a_crossing_is_pushed_to_techfm_oa_and_above(db, configured):
    techfm = _seed_user(db, "techfm_oa")
    admin = _seed_user(db, "admin")
    supervisor = _seed_user(db, "supervisor")
    background = BackgroundTasks()

    notifications_service.notify_item_low_stock(
        db, background, crossings=[_crossing()]
    )

    assert len(_scheduled(background)) == 1
    user_ids, title, body = _scheduled(background)[0]
    assert techfm.id in user_ids
    assert admin.id in user_ids
    assert supervisor.id not in user_ids
    assert title == "Low stock"
    assert body == "Blue Tape is down to 5."


def test_a_membership_change_that_is_not_a_crossing_pushes_nothing(db, configured):
    _seed_user(db, "admin")
    background = BackgroundTasks()

    notifications_service.notify_item_low_stock(
        db, background, crossings=[_crossing(pushes=False)]
    )

    assert _scheduled(background) == []


def test_several_crossings_schedule_one_push_each(db, configured):
    """No batching: a Mass Stage load that crosses three items sends
    three notifications, each naming its own item."""
    _seed_user(db, "admin")
    background = BackgroundTasks()

    notifications_service.notify_item_low_stock(
        db,
        background,
        crossings=[
            _crossing(name="Tape", quantity="2"),
            _crossing(name="Screws", quantity="1"),
            _crossing(name="Caulk", quantity="0"),
        ],
    )

    bodies = [body for _ids, _title, body in _scheduled(background)]
    assert bodies == [
        "Tape is down to 2.",
        "Screws is down to 1.",
        "Caulk is down to 0.",
    ]


def test_nothing_is_scheduled_when_nobody_holds_the_rank(db, configured):
    background = BackgroundTasks()
    notifications_service.notify_item_low_stock(
        db, background, crossings=[_crossing()]
    )
    # Any TechFM OA+ already in the dev database would be a legitimate
    # recipient, so assert on the audience rather than on emptiness.
    for user_ids, _title, _body in _scheduled(background):
        assert user_ids


# --- the flush helper ---------------------------------------------------


def test_flush_drains_pushes_and_invalidates(db, configured, monkeypatch):
    from app.routers import _low_stock

    envelopes = []
    monkeypatch.setattr(
        _low_stock.realtime_service, "emit", lambda envelope: envelopes.append(envelope)
    )
    _seed_user(db, "admin")
    item = _seed_item(db, quantity="5")
    low_stock_service.record(item, quantity_before=Decimal("7"))
    background = BackgroundTasks()

    _low_stock.flush_low_stock(db, background)

    assert len(_scheduled(background)) == 1
    assert len(envelopes) == 1
    assert envelopes[0]["type"] == realtime_policy.EVENT_ITEM_LOW_STOCK_CHANGED
    assert envelopes[0]["id"] == str(item.id)
    # Drained: a second flush on the same request repeats nothing.
    second = BackgroundTasks()
    _low_stock.flush_low_stock(db, second)
    assert _scheduled(second) == []


def test_flush_invalidates_even_when_the_item_left_the_low_set(db, configured, monkeypatch):
    """A restock has no push but must still drop the row from an open
    Low Stock page."""
    from app.routers import _low_stock

    envelopes = []
    monkeypatch.setattr(
        _low_stock.realtime_service, "emit", lambda envelope: envelopes.append(envelope)
    )
    _seed_user(db, "admin")
    item = _seed_item(db, quantity="9")
    low_stock_service.record(item, quantity_before=Decimal("2"))
    background = BackgroundTasks()

    _low_stock.flush_low_stock(db, background)

    assert _scheduled(background) == []
    assert len(envelopes) == 1


def test_flush_never_raises_into_a_committed_request(db, monkeypatch):
    """The durable write already happened. A bug in recipient resolution
    must cost a notification, not turn a successful save into a 500."""
    from app.routers import _low_stock

    def boom(*args, **kwargs):
        raise RuntimeError("resolution exploded")

    monkeypatch.setattr(_low_stock.notifications_service, "notify_item_low_stock", boom)
    item = _seed_item(db, quantity="5")
    low_stock_service.record(item, quantity_before=Decimal("7"))

    _low_stock.flush_low_stock(db, BackgroundTasks())  # must not raise
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_low_stock_triggers.py -q`
Expected: FAIL — `AttributeError: module 'app.services.notifications' has no attribute 'notify_item_low_stock'`.

- [ ] **Step 3: Add the dispatch function**

Append to `backend/app/services/notifications.py` (and add `from typing import Sequence` if it is not already imported — it is):

```python
def notify_item_low_stock(
    db: Session,
    background: BackgroundTasks,
    *,
    crossings: Sequence,
) -> None:
    """Requirement: an item fell to or below its threshold.

    One push per crossed item, never a digest -- a Mass Stage load that
    crosses eight items sends eight notifications, each naming its own
    item, because a generic "8 items are low" tells the recipient nothing
    they can act on without opening the app.

    `crossings` carries only plain values (see
    `services.low_stock.Crossing`), so this reads nothing lazy and the
    scheduled task carries nothing that could detach. The audience is
    resolved here, inside the request, for the same reason every other
    rule resolves here: the session is closed by the time the task runs.

    Entries whose `pushes` is False are membership changes that are not
    crossings -- an item restocked back above its threshold. They exist
    for the realtime invalidation and are silent on the phone.
    """
    pushed = [crossing for crossing in crossings if crossing.pushes]
    if not pushed:
        return

    recipients = policy.recipients_for_low_stock(
        recipient_ids=push_service.user_ids_for_min_role(
            db, policy.LOW_STOCK_AUDIENCE_MIN_ROLE
        ),
    )
    for crossing in pushed:
        title, body = policy.build_message(
            policy.EVENT_ITEM_LOW_STOCK,
            name=crossing.name,
            quantity=crossing.quantity,
        )
        _schedule(background, recipients, title, body)
```

- [ ] **Step 4: Add the router helper**

Create `backend/app/routers/_low_stock.py`:

```python
"""The one call every stock-writing route makes about low stock.

Layer: routers (shared helper), alongside `_errors.py` and `_uploads.py`.
It exists so the three routers that move stock -- transactions, mass
stages, work orders -- each add exactly one line instead of three, and so
the swallow-and-log contract is written once.

Why the drain lives here rather than in a service: emitting realtime
invalidations from the router is the convention this repo already follows
(`routers/work_orders.py::_emit_status_changed`), and pulling
`services.realtime` into a service that `services.notifications` imports
would close an import ring. The buffer module underneath
(`services.low_stock`) deliberately imports nothing from `app.services`
for the same reason.
"""

import logging
import uuid
from typing import Optional

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from app.domain import realtime as realtime_policy
from app.logging_config import current_request_id
from app.services import low_stock as low_stock_service
from app.services import notifications as notifications_service
from app.services import realtime as realtime_service

logger = logging.getLogger(__name__)


def emit_low_stock_changed(item_id: Optional[uuid.UUID]) -> None:
    """Invalidate the Low Stock page for one item.

    Best-effort by contract, exactly like the work-order emitters:
    ``emit`` is total and its boolean result is deliberately ignored so a
    full handoff can never fail a durable write.
    """
    realtime_service.emit(
        realtime_policy.build_envelope(
            event_type=realtime_policy.EVENT_ITEM_LOW_STOCK_CHANGED,
            entity_id=item_id,
            request_id=current_request_id(),
        )
    )


def flush_low_stock(db: Session, background: BackgroundTasks) -> None:
    """Drain this request's crossings, push the ones that crossed, and
    invalidate every item whose membership changed.

    Call once, on the success path, after the service returned -- the
    durable write has committed by then, which is what makes swallowing
    correct rather than lazy. A failure here costs a notification; raising
    would cost the user a save that actually succeeded.

    Draining on the failure path is neither needed nor wanted: the request
    context dies with the request, taking its buffer with it.
    """
    try:
        crossings = low_stock_service.drain()
        if not crossings:
            return
        notifications_service.notify_item_low_stock(db, background, crossings=crossings)
        for crossing in crossings:
            emit_low_stock_changed(crossing.item_id)
    except Exception:  # noqa: BLE001 - best-effort by contract
        logger.exception("low-stock notification failed")
```

- [ ] **Step 5: Run the tests**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_low_stock_triggers.py -q`
Expected: PASS (7 tests).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/notifications.py backend/app/routers/_low_stock.py backend/tests/test_low_stock_triggers.py
git commit -m "feat(low-stock): push dispatch and the shared router flush helper"
```

---

### Task 7: Wire the eight stock-mutation points

**Files:**
- Modify: `backend/app/services/transactions.py` (3 sites)
- Modify: `backend/app/services/mass_staging.py` (2 sites)
- Modify: `backend/app/services/work_orders.py` (3 sites)
- Test: `backend/tests/test_low_stock_triggers.py` (append)

**Interfaces:**
- Consumes: `services.low_stock.record` / `drain` (Task 3).
- Produces: nothing new — after this task, every write that moves `Item.quantity` buffers its crossing.

Line numbers below are from the pre-change files; find the quoted code rather than trusting the number.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_low_stock_triggers.py`:

```python
# --- the eight mutation points ------------------------------------------


def _crossings_after(fn):
    """Run a stock write and return what it buffered."""
    low_stock_service.drain()
    fn()
    return low_stock_service.drain()


def test_a_scan_dispense_that_crosses_is_recorded(db):
    from app.services import transactions as txn_service

    user = _seed_user(db, "supervisor")
    item = _seed_item(db, quantity="7", threshold=6)
    db.commit()

    crossings = _crossings_after(
        lambda: txn_service.apply_transaction(
            db,
            item_id=item.id,
            transaction_type="dispense",
            quantity=Decimal("2"),
            user_id=user.id,
            work_order_number=None,
        )
    )
    assert [c.pushes for c in crossings] == [True]
    assert crossings[0].quantity == "5"


def test_a_scan_dispense_on_an_already_low_item_is_silent(db):
    from app.services import transactions as txn_service

    user = _seed_user(db, "supervisor")
    item = _seed_item(db, quantity="5", threshold=6)
    db.commit()

    crossings = _crossings_after(
        lambda: txn_service.apply_transaction(
            db,
            item_id=item.id,
            transaction_type="dispense",
            quantity=Decimal("1"),
            user_id=user.id,
            work_order_number=None,
        )
    )
    assert crossings == []


def test_a_stock_in_that_re_arms_is_recorded_without_a_push(db):
    from app.services import transactions as txn_service

    user = _seed_user(db, "supervisor")
    item = _seed_item(db, quantity="2", threshold=6)
    db.commit()

    crossings = _crossings_after(
        lambda: txn_service.apply_transaction(
            db,
            item_id=item.id,
            transaction_type="stock",
            quantity=Decimal("20"),
            user_id=user.id,
            work_order_number=None,
        )
    )
    assert [c.pushes for c in crossings] == [False]


def test_a_correction_down_across_the_threshold_is_recorded(db):
    from app.services import transactions as txn_service

    user = _seed_user(db, "techfm_oa")
    item = _seed_item(db, quantity="30", threshold=6)
    db.commit()

    crossings = _crossings_after(
        lambda: txn_service.apply_correction(
            db,
            item_id=item.id,
            new_quantity=Decimal("3"),
            reason="Recount",
            user_id=user.id,
        )
    )
    assert [c.pushes for c in crossings] == [True]


def test_voiding_a_stock_in_back_across_the_threshold_is_recorded(db):
    """Undoing a restock lowers on-hand and can cross like any dispense."""
    from app.services import transactions as txn_service

    user = _seed_user(db, "supervisor")
    item = _seed_item(db, quantity="2", threshold=6)
    db.commit()
    txn = txn_service.apply_transaction(
        db,
        item_id=item.id,
        transaction_type="stock",
        quantity=Decimal("20"),
        user_id=user.id,
        work_order_number=None,
    )

    crossings = _crossings_after(
        lambda: txn_service.void_transaction(
            db, transaction_id=txn.id, user_id=user.id, user_role="supervisor"
        )
    )
    assert [c.pushes for c in crossings] == [True]


def _loading_stage(db, item, planned1=10, planned2=5):
    """A loading stage with `item` planned in two slots.

    Mirrors `_seed_loading_stage` in `test_mass_staging_load.py`. The
    duplication is deliberate: importing helpers across test modules
    couples two suites that should be free to change apart.
    """
    from app.services import work_orders as wo_service
    from app.services.mass_staging import (
        add_item,
        add_work_order_to_stage,
        create_stage,
        update_stage,
    )

    stage = create_stage(
        db,
        community="Scholars",
        building_name=f"B-{uuid.uuid4().hex[:6]}",
        created_by_id=None,
    )
    for planned in (planned1, planned2):
        number = f"WO-{uuid.uuid4().hex[:8]}"
        wo_service.get_or_create_work_order(db, number=number, created_by_id=None)
        slot = add_work_order_to_stage(db, stage.id, work_order_number=number)
        add_item(db, stage.id, slot.id, item_id=item.id, planned_quantity=Decimal(planned))
    update_stage(db, stage.id, status="loading")
    return stage


def test_a_mass_stage_load_that_crosses_records_exactly_one_crossing(db):
    """One item, several per-slot slices, ONE buffered crossing -- the
    recorder runs after the allocation loop, not inside it. Inside, a load
    filling six rooms would buzz six times for one event."""
    from app.services.mass_staging import load_item

    item = _seed_item(db, quantity="20", threshold=6)
    stage = _loading_stage(db, item)
    db.commit()

    crossings = _crossings_after(
        lambda: load_item(
            db, stage.id, item_id=item.id, quantity=Decimal("15"), user_id=None
        )
    )
    assert [c.pushes for c in crossings] == [True]
    assert crossings[0].quantity == "5"


def test_a_mass_stage_return_re_arms_without_pushing(db):
    from app.services.mass_staging import load_item, return_item

    item = _seed_item(db, quantity="20", threshold=6)
    stage = _loading_stage(db, item)
    db.commit()
    load_item(db, stage.id, item_id=item.id, quantity=Decimal("15"), user_id=None)

    crossings = _crossings_after(
        lambda: return_item(db, stage.id, item_id=item.id, quantity=Decimal("10"))
    )
    assert [c.pushes for c in crossings] == [False]


def test_a_work_order_material_line_that_crosses_is_recorded(db):
    from app.services import work_orders as wo_service

    user = _seed_user(db, "supervisor")
    item = _seed_item(db, quantity="7", threshold=6)
    number = f"WO-{uuid.uuid4().hex[:8]}"
    work_order = wo_service.get_or_create_work_order(
        db, number=number, created_by_id=user.id
    )
    db.commit()

    crossings = _crossings_after(
        lambda: wo_service.add_work_order_item(
            db, work_order.id, user=user, item_id=item.id, quantity=Decimal("2")
        )
    )
    assert [c.pushes for c in crossings] == [True]


def test_every_item_quantity_mutation_has_a_recorder():
    """The guard that stops the ninth stock-writing site from silently
    skipping the alert. Counts the mutation lines and the recorder calls
    in the three services that own them."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "app" / "services"
    mutations = 0
    records = 0
    for name in ("transactions.py", "mass_staging.py", "work_orders.py"):
        source = (root / name).read_text(encoding="utf-8")
        mutations += source.count("item.quantity = ")
        records += source.count("low_stock.record(")
    # Nine mutation lines across eight functions: `apply_transaction` has
    # two branches (the Scan / Stock shortage path and the strict path)
    # that share one recorder call.
    assert mutations == 9
    assert records == 8
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_low_stock_triggers.py -q`
Expected: FAIL — the recorder assertions fail (`assert 0 == 8`) and the trigger tests return `[]`.

- [ ] **Step 3: Wire `services/transactions.py`**

Add the import beside the other app imports:

```python
from app.services import low_stock
```

**Site 1 — `apply_transaction`.** `quantity_before` is already captured. Immediately before the `db.commit()` near the end of the function (the one followed by `db.refresh(new_txn)`), insert:

```python
    # Recorded before the commit, while the row is loaded, and drained by
    # the router only after this returns -- so a rollback below never
    # leaves a phantom crossing behind.
    low_stock.record(item, quantity_before=quantity_before)
    db.commit()
```

**Site 2 — `apply_correction`.** The function computes `delta = new_quantity - item.quantity`, so capture the before-value first. Change:

```python
    delta = new_quantity - item.quantity
    if delta == 0:
        raise NoChangeError("No change to apply.")

    item.quantity = apply_delta(item.quantity, "adjust", delta)
```

to:

```python
    quantity_before = item.quantity
    delta = new_quantity - quantity_before
    if delta == 0:
        raise NoChangeError("No change to apply.")

    item.quantity = apply_delta(quantity_before, "adjust", delta)
```

and immediately before this function's `db.commit()`:

```python
    low_stock.record(item, quantity_before=quantity_before)
    db.commit()
```

**Site 3 — `void_transaction`.** The item is bound only inside `if txn.affects_stock:`. Record at the end of that block, after the `try/except` that reverses the delta:

```python
        quantity_before = item.quantity
        try:
            item.quantity = reverse_delta(
                item.quantity, txn.transaction_type, txn.quantity
            )
        except NegativeQuantityError as exc:
            raise TransactionVoidError(
                "Cannot void this entry — it would make the on-hand count "
                "negative. Make a correction instead."
            ) from exc
        # Inside the branch on purpose: a stock-neutral retroactive row
        # never moved on-hand, so undoing it cannot change membership.
        low_stock.record(item, quantity_before=quantity_before)
```

- [ ] **Step 4: Wire `services/mass_staging.py`**

Add the import:

```python
from app.services import low_stock
```

**Site 4 — `load_item`.** Capture before the allocation loop and record once after it. Change:

```python
    try:
        for alloc in allocations:
```

to:

```python
    # One item, many per-slot slices: capture once outside the loop and
    # record once after it, so a load that fills six rooms is one crossing
    # rather than six.
    quantity_before = item.quantity
    try:
        for alloc in allocations:
```

and change the loop's tail:

```python
            si.loaded_quantity = si.loaded_quantity + alloc.quantity
        db.commit()
```

to:

```python
            si.loaded_quantity = si.loaded_quantity + alloc.quantity
        low_stock.record(item, quantity_before=quantity_before)
        db.commit()
```

**Site 5 — `return_item`.** Change the last two lines:

```python
    item.quantity = item.quantity + quantity
    db.commit()
```

to:

```python
    quantity_before = item.quantity
    item.quantity = quantity_before + quantity
    # Upward only, so this can re-arm and drop the row from an open Low
    # Stock page but can never push.
    low_stock.record(item, quantity_before=quantity_before)
    db.commit()
```

- [ ] **Step 5: Wire `services/work_orders.py`**

Add the import:

```python
from app.services import low_stock
```

**Site 6 — `add_work_order_item`.** `quantity_before` is already captured. Immediately before this function's `db.commit()`:

```python
    low_stock.record(item, quantity_before=quantity_before)
    db.commit()
```

**Site 7 — `update_work_order_item`.** Insert a capture before the stock branch and a recorder before the commit. Change:

```python
    stock_delta = line.quantity - quantity
    if stock_delta != 0 and wo.affects_stock(line.mode):
```

to:

```python
    quantity_before = item.quantity
    stock_delta = line.quantity - quantity
    if stock_delta != 0 and wo.affects_stock(line.mode):
```

and before this function's `db.commit()`:

```python
    # Unconditional: a retroactive line moves no stock, so the recorder
    # sees an unchanged quantity and buffers nothing. Guarding the call
    # would only duplicate that decision.
    low_stock.record(item, quantity_before=quantity_before)
    db.commit()
```

**Site 8 — `delete_work_order_item`.** Change:

```python
    if wo.affects_stock(line.mode):
        item.quantity = apply_delta(item.quantity, "stock", line.quantity)
```

to:

```python
    quantity_before = item.quantity
    if wo.affects_stock(line.mode):
        item.quantity = apply_delta(item.quantity, "stock", line.quantity)
```

and before this function's final `db.commit()`:

```python
    low_stock.record(item, quantity_before=quantity_before)
    db.commit()
```

- [ ] **Step 6: Run the tests**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_low_stock_triggers.py -q`
Expected: PASS.

- [ ] **Step 7: Run the stock suites for regressions**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_mass_staging_load.py tests/test_mass_staging.py tests/test_quantity_reverse.py tests/test_billing_validation.py tests/test_work_orders_router.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/transactions.py backend/app/services/mass_staging.py backend/app/services/work_orders.py backend/tests/test_low_stock_triggers.py
git commit -m "feat(low-stock): record crossings at all eight stock-mutation points"
```

---

### Task 8: Drain at the three routers

**Files:**
- Modify: `backend/app/routers/transactions.py` (3 handlers)
- Modify: `backend/app/routers/mass_stages.py` (2 handlers)
- Modify: `backend/app/routers/work_orders.py` (3 handlers)
- Test: `backend/tests/test_items_low_stock.py` (append)

**Interfaces:**
- Consumes: `routers._low_stock.flush_low_stock` (Task 6).
- Produces: end-to-end delivery — a real HTTP dispense now schedules a real push task.

`BackgroundTasks` must be a **plain parameter with no default**. A defaulted one keeps direct callers compiling and gives you a deployment where notifications silently never fire.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_items_low_stock.py`:

```python
import uuid as _uuid

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models import User
from app.services import auth as auth_service
from app.services import push as push_service


def _seed_user(db, role):
    user = User(
        username=f"u-{_uuid.uuid4().hex[:10]}",
        password_hash=auth_service.hash_password("hunter2"),
        role=role,
    )
    db.add(user)
    db.flush()
    return user


def _client(db):
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def test_a_dispense_over_real_http_schedules_a_low_stock_push(db, monkeypatch):
    """End to end through FastAPI: the handler must actually receive a
    `BackgroundTasks` and the drain must run on the success path."""
    monkeypatch.setattr(push_service, "VAPID_PRIVATE_KEY", "test-private-key")
    sent = []
    monkeypatch.setattr(
        push_service,
        "send_to_users",
        lambda session, ids, title, body: sent.append((title, body))
        or {"sent": 1, "dropped": 0, "failed": 0},
    )
    _seed_user(db, "admin")
    actor = _seed_user(db, "supervisor")
    item = _seed_item(db, quantity="7")
    db.commit()
    token = auth_service.create_session(db, actor)

    try:
        with _client(db) as client:
            client.cookies.set("session", token)
            response = client.post(
                "/transactions/",
                json={
                    "item_id": str(item.id),
                    "transaction_type": "dispense",
                    "quantity": "2",
                },
            )
    finally:
        del app.dependency_overrides[get_db]

    assert response.status_code == 201, response.text
    assert sent, "no low-stock push was delivered"
    assert sent[0][1] == f"{item.name} is down to 5."
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_items_low_stock.py -q`
Expected: FAIL — `assert sent, "no low-stock push was delivered"`.

- [ ] **Step 3: Wire `routers/transactions.py`**

Add to the imports:

```python
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
...
from app.routers._low_stock import flush_low_stock
```

In `create_transaction`, add the parameter and the flush:

```python
def create_transaction(
    payload: TransactionCreate,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
```

and change the `return` at the end of its `try` block to:

```python
        transaction = transactions_service.apply_transaction(
            db,
            item_id=payload.item_id,
            transaction_type=payload.transaction_type,
            quantity=payload.quantity,
            user_id=user.id,
            work_order_number=work_order_number,
            work_order_id=work_order_id,
        )
        flush_low_stock(db, background)
        return transaction
    except DomainError as exc:
        raise to_http(exc)
```

In `create_correction`, add `background: BackgroundTasks,` after `payload` and change its body to:

```python
    try:
        transaction = transactions_service.apply_correction(
            db,
            item_id=payload.item_id,
            new_quantity=payload.new_quantity,
            reason=payload.reason,
            user_id=user.id,
        )
        flush_low_stock(db, background)
        return transaction
    except DomainError as exc:
        raise to_http(exc)
```

In `void_transaction`, add `background: BackgroundTasks,` after `transaction_id` and add the flush after the service call:

```python
    try:
        transactions_service.void_transaction(
            db,
            transaction_id=transaction_id,
            user_id=user.id,
            user_role=user.role,
        )
        flush_low_stock(db, background)
    except DomainError as exc:
        raise to_http(exc)
```

- [ ] **Step 4: Wire `routers/mass_stages.py`**

Add `BackgroundTasks` to the `fastapi` import and `from app.routers._low_stock import flush_low_stock`.

`load_item`: add `background: BackgroundTasks,` after `payload` and insert `flush_low_stock(db, background)` immediately after the `ms_service.load_item(...)` call, before `stage = ms_service.get_stage(db, stage_id)`.

`return_item`: this handler has no `user` parameter and does not need one — the low-stock audience includes the actor, so nothing here resolves an actor id. Add `background: BackgroundTasks,` after `payload` and insert `flush_low_stock(db, background)` immediately after the `ms_service.return_item(...)` call.

- [ ] **Step 5: Wire `routers/work_orders.py`**

`BackgroundTasks` is already imported. Add `from app.routers._low_stock import flush_low_stock`.

In `add_work_order_item`, `update_work_order_item`, and `delete_work_order_item`, add `background: BackgroundTasks,` immediately after the last path/body parameter (before the `user: User = Depends(...)` default), and call `flush_low_stock(db, background)` immediately after the `wo_service.*` call inside each `try`.

For `add_work_order_item` and `update_work_order_item` the flush goes between the service call and the `return _line_detail(...)`:

```python
        line = wo_service.add_work_order_item(
            db, work_order_id, user=user, item_id=payload.item_id, quantity=payload.quantity
        )
        flush_low_stock(db, background)
        return _line_detail(line, include_price=_can_see_price(user))
```

- [ ] **Step 6: Run the tests**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_items_low_stock.py tests/test_low_stock_triggers.py -q`
Expected: PASS.

- [ ] **Step 7: Full suite**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/ -q`
Expected: PASS except the known environmental `test_cascade_deletes_with_user`. `test_route_role_gates.py` calls some handlers directly and will need a `BackgroundTasks()` argument passed where it now constructs a call — fix those call sites if they fail.

- [ ] **Step 8: Commit**

```bash
git add backend/app/routers/transactions.py backend/app/routers/mass_stages.py backend/app/routers/work_orders.py backend/tests/test_items_low_stock.py backend/tests/test_route_role_gates.py
git commit -m "feat(low-stock): drain and dispatch crossings at the stock-writing routes"
```

---

### Task 9: `GET /items/low-stock`

**Files:**
- Modify: `backend/app/services/items.py` (add `list_low_stock`)
- Modify: `backend/app/schemas/items.py` (add `LowStockItemResponse`)
- Modify: `backend/app/routers/items.py` (new route, registered **before** `get_item_by_barcode`)
- Test: `backend/tests/test_items_low_stock.py` (append)

**Interfaces:**
- Consumes: `Item.low_stock_threshold` (Task 1).
- Produces:
  - `items_service.list_low_stock(db) -> list[tuple[Item, Decimal]]`
  - `LowStockItemResponse(ItemResponse)` with `dispensed_last_7_days: Decimal`
  - `GET /items/low-stock` → `list[LowStockItemResponse]`, gate `ROLE_TECHFM_OA`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_items_low_stock.py`:

```python
from datetime import datetime, timedelta, timezone

from app.models import Transaction


def _dispense(db, item, *, quantity="3", hours_ago=1, voided=False, affects_stock=True,
              transaction_type="dispense"):
    txn = Transaction(
        item_id=item.id,
        user_id=None,
        transaction_type=transaction_type,
        quantity=Decimal(quantity),
        work_order_number=None,
        affects_stock=affects_stock,
        created_at=datetime.now(timezone.utc) - timedelta(hours=hours_ago),
        voided_at=datetime.now(timezone.utc) if voided else None,
    )
    db.add(txn)
    db.flush()
    return txn


def _low_stock_rows(db, role="admin"):
    user = _seed_user(db, role)
    db.commit()
    token = auth_service.create_session(db, user)
    try:
        with _client(db) as client:
            client.cookies.set("session", token)
            response = client.get("/items/low-stock")
    finally:
        del app.dependency_overrides[get_db]
    return response


def test_low_stock_lists_only_items_at_or_below_their_threshold(db):
    low = _seed_item(db, quantity="6", threshold=6)
    fast = _seed_item(db, quantity="15", threshold=20)
    healthy = _seed_item(db, quantity="7", threshold=6)

    response = _low_stock_rows(db)

    assert response.status_code == 200, response.text
    ids = {row["id"] for row in response.json()}
    assert str(low.id) in ids
    assert str(fast.id) in ids
    assert str(healthy.id) not in ids


def test_low_stock_excludes_archived_items(db):
    archived = _seed_item(db, quantity="1", threshold=6)
    archived.archived_at = datetime.now(timezone.utc)

    response = _low_stock_rows(db)

    assert str(archived.id) not in {row["id"] for row in response.json()}


def test_low_stock_is_not_shadowed_by_the_barcode_lookup(db):
    """`GET /items/{barcode}` would swallow the literal path if it were
    registered first, answering 404 for a route that exists."""
    _seed_item(db, quantity="1", threshold=6)
    response = _low_stock_rows(db)
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_low_stock_is_gated_at_techfm_oa(db):
    _seed_item(db, quantity="1", threshold=6)
    assert _low_stock_rows(db, role="supervisor").status_code == 403
    assert _low_stock_rows(db, role="techfm_oa").status_code == 200


def test_seven_day_usage_counts_a_recent_dispense(db):
    item = _seed_item(db, quantity="2", threshold=6)
    _dispense(db, item, quantity="3", hours_ago=1)
    _dispense(db, item, quantity="4", hours_ago=167)

    row = next(r for r in _low_stock_rows(db).json() if r["id"] == str(item.id))
    assert Decimal(row["dispensed_last_7_days"]) == Decimal("7")


def test_seven_day_usage_excludes_anything_older_than_the_window(db):
    item = _seed_item(db, quantity="2", threshold=6)
    _dispense(db, item, quantity="9", hours_ago=169)

    row = next(r for r in _low_stock_rows(db).json() if r["id"] == str(item.id))
    assert Decimal(row["dispensed_last_7_days"]) == Decimal("0")


def test_seven_day_usage_excludes_voided_rows(db):
    """A voided transaction is a mistake that was undone; counting it
    would overstate how fast the item moves."""
    item = _seed_item(db, quantity="2", threshold=6)
    _dispense(db, item, quantity="5", voided=True)

    row = next(r for r in _low_stock_rows(db).json() if r["id"] == str(item.id))
    assert Decimal(row["dispensed_last_7_days"]) == Decimal("0")


def test_seven_day_usage_includes_retroactive_dispenses(db):
    """Stock consumed off-app and backfilled on paper is still usage. It
    is stored as a `dispense` with `affects_stock=false`, so including it
    means simply not filtering on that column."""
    item = _seed_item(db, quantity="2", threshold=6)
    _dispense(db, item, quantity="6", affects_stock=False)

    row = next(r for r in _low_stock_rows(db).json() if r["id"] == str(item.id))
    assert Decimal(row["dispensed_last_7_days"]) == Decimal("6")


def test_seven_day_usage_excludes_corrections(db):
    """A recount write-off is not consumption. Counting it would make a
    mis-stocked item look fast-moving and invite the wrong threshold."""
    item = _seed_item(db, quantity="2", threshold=6)
    _dispense(db, item, quantity="-8", transaction_type="adjust")

    row = next(r for r in _low_stock_rows(db).json() if r["id"] == str(item.id))
    assert Decimal(row["dispensed_last_7_days"]) == Decimal("0")


def test_an_item_with_no_usage_reports_zero(db):
    item = _seed_item(db, quantity="1", threshold=6)
    row = next(r for r in _low_stock_rows(db).json() if r["id"] == str(item.id))
    assert Decimal(row["dispensed_last_7_days"]) == Decimal("0")


def test_low_stock_is_ordered_by_headroom(db):
    """Deepest below its own threshold first, so the item most likely to
    run out is the one nearest the top of the page."""
    barely = _seed_item(db, quantity="6", threshold=6)     # headroom 0
    deep = _seed_item(db, quantity="1", threshold=20)      # headroom -19

    ids = [row["id"] for row in _low_stock_rows(db).json()]
    assert ids.index(str(deep.id)) < ids.index(str(barely.id))
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_items_low_stock.py -q`
Expected: FAIL — 404 on `/items/low-stock`.

- [ ] **Step 3: Add the service query**

Append to `backend/app/services/items.py` (`func`, `and_`, `Transaction`, `Decimal` and `timedelta` are already imported except `timedelta` — add it to the `datetime` import line):

```python
# The usage window on the Low Stock page. Rolling hours rather than
# calendar days on purpose: a fixed offset needs no timezone or
# day-boundary logic, and the figure is read as "how fast is this
# moving", which does not become more true for being aligned to midnight.
LOW_STOCK_USAGE_WINDOW = timedelta(days=7)


def list_low_stock(db: Session) -> list[tuple[Item, Decimal]]:
    """Live items at or below their own threshold, with 7-day usage.

    Ordered by *headroom* (`quantity - low_stock_threshold`) ascending, so
    the item furthest below its own threshold leads the page rather than
    the item with the smallest absolute count. An item at 1 with a
    threshold of 20 is in more trouble than one at 6 with a threshold of
    6, and sorting on the raw count would say the opposite.

    Usage is a single grouped aggregate over exactly the items being
    returned, not a query per row. It counts every non-voided `dispense`
    inside the window and does **not** filter on `affects_stock`: a
    retroactive work-order backfill is stored as a `dispense` with
    `affects_stock=False`, so including real off-app consumption means
    not filtering there. Corrections and adjusts are excluded, because a
    recount write-off is not consumption and would make a mis-stocked
    item look fast-moving.

    Items with no rows in the window are simply absent from the aggregate
    and resolve to `Decimal(0)` here, so "never dispensed" is not a
    special case for any caller.
    """
    items = (
        db.query(Item)
        .filter(Item.archived_at.is_(None))
        .filter(Item.quantity <= Item.low_stock_threshold)
        .order_by((Item.quantity - Item.low_stock_threshold).asc(), Item.name.asc())
        .all()
    )
    if not items:
        return []

    since = datetime.now(timezone.utc) - LOW_STOCK_USAGE_WINDOW
    totals = dict(
        db.query(Transaction.item_id, func.sum(Transaction.quantity))
        .filter(Transaction.item_id.in_([item.id for item in items]))
        .filter(Transaction.transaction_type == "dispense")
        .filter(Transaction.voided_at.is_(None))
        .filter(Transaction.created_at >= since)
        .group_by(Transaction.item_id)
        .all()
    )
    return [(item, totals.get(item.id) or Decimal(0)) for item in items]
```

- [ ] **Step 4: Add the response schema**

Append to `backend/app/schemas/items.py`, after `ItemResponse`:

```python
class LowStockItemResponse(ItemResponse):
    """An item on the Low Stock page.

    Its own schema rather than two more fields on `ItemResponse`: the
    7-day aggregate costs a grouped query, and every other item route
    would pay for a number none of them display. `low_stock_threshold`
    stays on the parent because it is a plain column that any item view
    may want.
    """

    dispensed_last_7_days: Decimal
```

- [ ] **Step 5: Add the route**

In `backend/app/routers/items.py`, add `LowStockItemResponse` to the `app.schemas.items` import, then insert this route **between `list_items` and `get_item_by_barcode`**:

```python
@router.get(
    "/low-stock",
    response_model=list[LowStockItemResponse],
    dependencies=[Depends(require_min_role(roles.ROLE_TECHFM_OA))],
)
def list_low_stock(
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    db: Session = Depends(get_db),
):
    """Every live item at or below its own low-stock threshold, deepest
    below first, with the quantity dispensed in the last 7 days.

    TechFM OA+ -- the same rank that receives the low-stock push and can
    retune a threshold, so everyone who can see this can act on it.

    **This route MUST stay registered above `GET /items/{barcode}`.**
    That route's path parameter matches any single segment, so a
    later-registered literal is unreachable and answers 404 for a route
    that exists. Pinned by
    `test_low_stock_is_not_shadowed_by_the_barcode_lookup`.
    """
    return [
        _low_stock_response(item, user.role, dispensed)
        for item, dispensed in items_service.list_low_stock(db)
    ]
```

and add the serializer beside `_item_response`:

```python
def _low_stock_response(item: Item, role: str, dispensed: Decimal) -> LowStockItemResponse:
    """`_item_response` plus the 7-day figure.

    Reuses the base serializer rather than re-deriving it so the
    price/product-link redaction cannot drift between the two -- a second
    hand-written copy is exactly how a Supervisor ends up seeing a price
    on one page and not another.
    """
    base = _item_response(item, role)
    return LowStockItemResponse(
        **base.model_dump(), dispensed_last_7_days=dispensed
    )
```

Add `from decimal import Decimal` to the router's imports.

- [ ] **Step 6: Run the tests**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_items_low_stock.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/items.py backend/app/schemas/items.py backend/app/routers/items.py backend/tests/test_items_low_stock.py
git commit -m "feat(items): GET /items/low-stock with 7-day dispensed totals"
```

---

### Task 10: `PATCH /items/{item_id}/low-stock-threshold`

**Files:**
- Modify: `backend/app/services/items.py` (add `set_low_stock_threshold`)
- Modify: `backend/app/schemas/items.py` (add `LowStockThresholdUpdate`)
- Modify: `backend/app/routers/items.py` (new route)
- Test: `backend/tests/test_items_low_stock.py` (append)

**Interfaces:**
- Consumes: `low_stock.record` (Task 3), `flush_low_stock` (Task 6), `MIN_LOW_STOCK_THRESHOLD` (Task 1).
- Produces: `items_service.set_low_stock_threshold(db, item_id, *, threshold) -> Item`; `PATCH /items/{item_id}/low-stock-threshold` → `ItemResponse`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_items_low_stock.py`:

```python
def _set_threshold(db, item, value, *, role="admin"):
    user = _seed_user(db, role)
    db.commit()
    token = auth_service.create_session(db, user)
    try:
        with _client(db) as client:
            client.cookies.set("session", token)
            response = client.patch(
                f"/items/{item.id}/low-stock-threshold",
                json={"low_stock_threshold": value},
            )
    finally:
        del app.dependency_overrides[get_db]
    return response


def test_setting_a_threshold_persists_it(db):
    item = _seed_item(db, quantity="30", threshold=6)
    response = _set_threshold(db, item, 20)
    assert response.status_code == 200, response.text
    assert response.json()["low_stock_threshold"] == 20


def test_a_threshold_below_one_is_rejected(db):
    """No mute value: stock cannot go below zero, so a zero threshold
    would be an invisible off-switch rather than a threshold."""
    item = _seed_item(db, quantity="30", threshold=6)
    assert _set_threshold(db, item, 0).status_code == 422


def test_a_missing_threshold_is_rejected(db):
    item = _seed_item(db, quantity="30", threshold=6)
    user = _seed_user(db, "admin")
    db.commit()
    token = auth_service.create_session(db, user)
    try:
        with _client(db) as client:
            client.cookies.set("session", token)
            response = client.patch(
                f"/items/{item.id}/low-stock-threshold", json={}
            )
    finally:
        del app.dependency_overrides[get_db]
    assert response.status_code == 422


def test_the_threshold_route_is_gated_at_techfm_oa(db):
    item = _seed_item(db, quantity="30", threshold=6)
    assert _set_threshold(db, item, 10, role="supervisor").status_code == 403


def test_an_unknown_item_is_404(db):
    user = _seed_user(db, "admin")
    db.commit()
    token = auth_service.create_session(db, user)
    try:
        with _client(db) as client:
            client.cookies.set("session", token)
            response = client.patch(
                f"/items/{_uuid.uuid4()}/low-stock-threshold",
                json={"low_stock_threshold": 5},
            )
    finally:
        del app.dependency_overrides[get_db]
    assert response.status_code == 404


def test_raising_a_threshold_past_the_current_count_pushes(db, monkeypatch):
    """The retune case. Nothing moved, but the item is newly low, and the
    crew is told the same way a dispense would tell them."""
    monkeypatch.setattr(push_service, "VAPID_PRIVATE_KEY", "test-private-key")
    sent = []
    monkeypatch.setattr(
        push_service,
        "send_to_users",
        lambda session, ids, title, body: sent.append(body)
        or {"sent": 1, "dropped": 0, "failed": 0},
    )
    item = _seed_item(db, quantity="10", threshold=6)

    assert _set_threshold(db, item, 20).status_code == 200
    assert sent == [f"{item.name} is down to 10."]


def test_lowering_a_threshold_clear_of_the_count_pushes_nothing(db, monkeypatch):
    monkeypatch.setattr(push_service, "VAPID_PRIVATE_KEY", "test-private-key")
    sent = []
    monkeypatch.setattr(
        push_service,
        "send_to_users",
        lambda session, ids, title, body: sent.append(body)
        or {"sent": 1, "dropped": 0, "failed": 0},
    )
    item = _seed_item(db, quantity="10", threshold=20)

    assert _set_threshold(db, item, 6).status_code == 200
    assert sent == []


def test_raising_a_threshold_that_keeps_a_low_item_low_pushes_nothing(db, monkeypatch):
    monkeypatch.setattr(push_service, "VAPID_PRIVATE_KEY", "test-private-key")
    sent = []
    monkeypatch.setattr(
        push_service,
        "send_to_users",
        lambda session, ids, title, body: sent.append(body)
        or {"sent": 1, "dropped": 0, "failed": 0},
    )
    item = _seed_item(db, quantity="3", threshold=6)

    assert _set_threshold(db, item, 20).status_code == 200
    assert sent == []
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_items_low_stock.py -q`
Expected: FAIL — 405/404 on the PATCH.

- [ ] **Step 3: Add the payload schema**

Append to `backend/app/schemas/items.py`:

```python
class LowStockThresholdUpdate(BaseModel):
    """Payload for `PATCH /items/{id}/low-stock-threshold`.

    A plain `int`, deliberately not a constrained `Literal` or an enum:
    int `Literal` query/body params 422 on every real request under this
    repo's pinned FastAPI/Pydantic pair, and the floor is one comparison
    that reads better as a validator anyway.
    """

    low_stock_threshold: int

    @field_validator("low_stock_threshold")
    @classmethod
    def _at_least_the_minimum(cls, v):
        if v < MIN_LOW_STOCK_THRESHOLD:
            raise ValueError(
                f"Threshold must be at least {MIN_LOW_STOCK_THRESHOLD}."
            )
        return v
```

Add to the imports at the top of the file:

```python
from app.domain.low_stock import MIN_LOW_STOCK_THRESHOLD
```

- [ ] **Step 4: Add the service function**

Append to `backend/app/services/items.py`:

```python
def set_low_stock_threshold(db: Session, item_id: uuid.UUID, *, threshold: int) -> Item:
    """Set one item's low-stock threshold.

    Locked with `FOR UPDATE` for the same reason every stock write is: the
    crossing decision reads the quantity, and a dispense landing between
    the read and the write would make this route decide against a count
    that no longer exists.

    Records the before/after pair through the same buffer the stock
    services use, so a raise past the current count reaches the crew as
    the identical notification a dispense would have produced. The route
    drains it; nothing about the dispatch differs.
    """
    item = (
        db.query(Item)
        .filter(Item.id == item_id)
        .filter(Item.archived_at.is_(None))
        .with_for_update()
        .first()
    )
    if item is None:
        raise ItemNotFoundError("Item not found.")

    threshold_before = item.low_stock_threshold
    quantity_before = item.quantity
    item.low_stock_threshold = threshold
    low_stock.record(
        item, quantity_before=quantity_before, threshold_before=threshold_before
    )
    db.commit()
    db.refresh(item)
    return item
```

Add `from app.services import low_stock` to the imports of `services/items.py`.

- [ ] **Step 5: Add the route**

In `backend/app/routers/items.py`, add `LowStockThresholdUpdate` to the schema import and `from app.routers._low_stock import flush_low_stock`, then add the route immediately after `update_item_barcodes` (before the bare `PATCH /{item_id}`):

```python
@router.patch(
    "/{item_id}/low-stock-threshold",
    response_model=ItemResponse,
    dependencies=[Depends(require_min_role(roles.ROLE_TECHFM_OA))],
)
def update_low_stock_threshold(
    item_id: uuid.UUID,
    payload: LowStockThresholdUpdate,
    background: BackgroundTasks,
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    db: Session = Depends(get_db),
):
    """Retune when this item starts warning. TechFM OA+ only.

    Raising the threshold past the current count is a crossing and pushes
    exactly like a dispense would: the item is newly low, and which write
    made it low is not something the crew needs to distinguish. 404 if the
    item is unknown or archived; 422 below the minimum of 1.
    """
    try:
        item = items_service.set_low_stock_threshold(
            db, item_id, threshold=payload.low_stock_threshold
        )
        flush_low_stock(db, background)
        return _item_response(item, user.role)
    except DomainError as exc:
        raise to_http(exc)
```

Add `BackgroundTasks` to the `fastapi` import line in this router.

- [ ] **Step 6: Run the tests**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_items_low_stock.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/items.py backend/app/schemas/items.py backend/app/routers/items.py backend/tests/test_items_low_stock.py
git commit -m "feat(items): PATCH low-stock threshold, pushing on a raise past stock"
```

---

### Task 11: Invalidate on item create and archive

**Files:**
- Modify: `backend/app/routers/items.py` (`create_item`, `delete_item`)
- Test: `backend/tests/test_items_low_stock.py` (append)

**Interfaces:**
- Consumes: `routers._low_stock.emit_low_stock_changed` (Task 6).
- Produces: nothing new.

Creation and archival are not stock movements and do not go through the buffer, but both change which rows the page shows. **There is no un-archive path in this codebase** (`services/items._free_archived_holder` releases a barcode; it never revives an item), so the spec's "restore" case has nothing to wire — do not invent one.

An item created below its threshold appears in the list and sends **no** push: creation is a config act performed by someone looking at the screen, and there is no before-state to cross from.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_items_low_stock.py`:

```python
def test_creating_an_item_below_its_threshold_lists_it_without_pushing(db, monkeypatch):
    monkeypatch.setattr(push_service, "VAPID_PRIVATE_KEY", "test-private-key")
    sent = []
    monkeypatch.setattr(
        push_service,
        "send_to_users",
        lambda session, ids, title, body: sent.append(body)
        or {"sent": 1, "dropped": 0, "failed": 0},
    )
    envelopes = []
    from app.routers import _low_stock
    monkeypatch.setattr(
        _low_stock.realtime_service, "emit", lambda e: envelopes.append(e)
    )
    user = _seed_user(db, "admin")
    db.commit()
    token = auth_service.create_session(db, user)
    barcode = f"BC-{_uuid.uuid4().hex[:10]}"

    try:
        with _client(db) as client:
            client.cookies.set("session", token)
            created = client.post(
                "/items/",
                json={
                    "barcode": barcode,
                    "name": "Nearly Empty",
                    "location": "Bay 1",
                    "quantity": "2",
                },
            )
            listed = client.get("/items/low-stock")
    finally:
        del app.dependency_overrides[get_db]

    assert created.status_code == 201, created.text
    assert sent == []
    assert len(envelopes) == 1
    assert barcode in {row["barcode"] for row in listed.json()}


def test_archiving_a_low_item_invalidates_the_page(db, monkeypatch):
    envelopes = []
    from app.routers import _low_stock
    monkeypatch.setattr(
        _low_stock.realtime_service, "emit", lambda e: envelopes.append(e)
    )
    item = _seed_item(db, quantity="1", threshold=6)
    user = _seed_user(db, "admin")
    db.commit()
    token = auth_service.create_session(db, user)

    try:
        with _client(db) as client:
            client.cookies.set("session", token)
            response = client.delete(f"/items/{item.id}")
    finally:
        del app.dependency_overrides[get_db]

    assert response.status_code == 204
    assert len(envelopes) == 1
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_items_low_stock.py -q`
Expected: FAIL — `assert len(envelopes) == 1` fails with `0`; no invalidation is emitted yet.

- [ ] **Step 3: Implement**

In `backend/app/routers/items.py`, add:

```python
from app.routers._low_stock import emit_low_stock_changed
```

`emit_low_stock_changed` calls `realtime_service.emit` through its own module attribute, which is what the tests above patch. There is one emit path for this event and no second copy to drift.

In `create_item`, after the service call and before the return:

```python
        item = items_service.create_item(...)
        # An item can be born below its threshold. That is not a crossing
        # -- there is no before-state -- so it lists without pushing, but
        # the page still has to learn about the new row.
        emit_low_stock_changed(item.id)
        return _item_response(item, user.role)
```

In `delete_item`, after the service call:

```python
        items_service.delete_item(db, item_id)
        # Archiving removes the row from the list as surely as a restock
        # would.
        emit_low_stock_changed(item_id)
```

Note the argument: `delete_item` takes `item_id` as a path parameter and the service returns nothing, so the id comes from the parameter rather than from a row.

- [ ] **Step 4: Run the tests**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_items_low_stock.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/items.py backend/tests/test_items_low_stock.py
git commit -m "feat(items): invalidate the Low Stock page on item create and archive"
```

---

### Task 12: The Low Stock page

**Files:**
- Create: `backend/static/pages/low-stock.html`
- Create: `backend/static/views/lowStock.js`
- Modify: `backend/app/main.py:341-356` (`SHELL_PARTS`)
- Modify: `backend/static/shell-head.html:136-142` (the review nav group)
- Modify: `backend/static/views/nav.js` (import, `PAGE_ACCESS`, `showPage`)
- Modify: `backend/static/api.js`
- Modify: `backend/static/main.js`
- Modify: `backend/static/styles.css`
- Test: `backend/tests/test_low_stock_shell.py`

**Interfaces:**
- Consumes: `GET /items/low-stock` (Task 9), `PATCH /items/{id}/low-stock-threshold` (Task 10), `item.low_stock.changed` (Task 5).
- Produces: page id `low-stock-page`, nav key `low-stock`, `loadLowStock()`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_low_stock_shell.py`:

```python
"""The Low Stock page's plumbing.

The SPA has no JS test harness, so these pin the three hand-maintained
joins that fail silently: a fragment missing from `SHELL_PARTS` (the page
markup simply never reaches the browser), a page absent from `PAGE_ACCESS`
(its nav button is hidden for every role), and a nav button whose
`data-page` does not match a `.page` id (clicking it shows nothing).
"""

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import SHELL_PARTS, STATIC_DIR

NAV_JS = Path(__file__).resolve().parents[1] / "static" / "views" / "nav.js"
SHELL_HEAD = Path(__file__).resolve().parents[1] / "static" / "shell-head.html"


def test_every_shell_fragment_exists():
    missing = [part for part in SHELL_PARTS if not (STATIC_DIR / part).is_file()]
    assert missing == []


def test_the_low_stock_fragment_is_assembled_into_the_shell():
    assembled = b"".join((STATIC_DIR / part).read_bytes() for part in SHELL_PARTS)
    assert b'id="low-stock-page"' in assembled


def test_low_stock_is_reachable_by_techfm_oa_and_above():
    source = NAV_JS.read_text(encoding="utf-8")
    match = re.search(r'"low-stock":\s*\[(.*?)\]', source)
    assert match, "low-stock missing from PAGE_ACCESS"
    allowed = {role.strip().strip('"') for role in match.group(1).split(",") if role.strip()}
    assert allowed == {"owner", "admin", "techfm_oa"}


def test_the_nav_button_exists_and_targets_the_page():
    assert 'data-page="low-stock"' in SHELL_HEAD.read_text(encoding="utf-8")


def test_showpage_loads_the_low_stock_page():
    source = NAV_JS.read_text(encoding="utf-8")
    assert 'pageName === "low-stock"' in source
    assert "loadLowStock()" in source
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_low_stock_shell.py -q`
Expected: FAIL — the fragment assertion and the nav assertions.

- [ ] **Step 3: Create the page fragment**

Create `backend/static/pages/low-stock.html`:

```html
    <!-- =================== LOW STOCK PAGE =================== -->
    <!-- TechFM OA+ reorder queue. Lists every live item at or below its own
         threshold, deepest below first, with the quantity dispensed in the
         last 7 days beside the threshold control so "how fast is this
         moving" and "when should it warn me" are read together. Rows are
         invalidated live by `item.low_stock.changed`. -->
    <div class="page" id="low-stock-page">

        <section id="low-stock-section">
            <h2>Low Stock</h2>
            <p class="hint">Every item at or below its alert threshold. The
               7-day figure counts what was dispensed in the last week,
               including materials logged retroactively on a work order.
               Raise an item's threshold to be warned earlier; the change
               takes effect on the next count that crosses it.</p>

            <div class="filter-row low-stock-controls">
                <button id="low-stock-refresh" type="button" class="secondary-btn">Refresh</button>
            </div>

            <div id="low-stock-list" class="low-stock-grid"></div>
            <p id="low-stock-message" aria-live="polite"></p>
        </section>

    </div>
```

- [ ] **Step 4: Register the fragment**

In `backend/app/main.py`, add to `SHELL_PARTS` immediately after `"pages/user-requests.html",`:

```python
    "pages/low-stock.html",
```

- [ ] **Step 5: Add the nav button**

In `backend/static/shell-head.html`, inside `<div class="nav-group" data-nav-group="review">`, add as the first button in the group's menu (before User Requests):

```html
                    <button class="nav-btn" data-page="low-stock"><svg class="nav-ico" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M3 7l9-4 9 4v10l-9 4-9-4z"/><path d="M12 10v5"/><path d="M9.5 12.5L12 15l2.5-2.5"/></svg>Low Stock</button>
```

- [ ] **Step 6: Wire `nav.js`**

Add the import beside the others:

```javascript
import { loadLowStock } from "./lowStock.js";
```

Add to `PAGE_ACCESS`, immediately before the `"admin-review"` entry:

```javascript
  // The reorder queue. Same rank as the low-stock push audience, so
  // everyone who receives the alert can also retune the threshold that
  // produced it.
  "low-stock": ["owner", "admin", "techfm_oa"],
```

Add to `showPage`, in the `else if` chain beside `admin-review`:

```javascript
  } else if (pageName === "low-stock") {
    loadLowStock();
```

- [ ] **Step 7: Add the API wrappers**

Append to the `// --- Items ---` section of `backend/static/api.js`:

```javascript
export async function apiListLowStock() {
  return liveGet("/items/low-stock");
}

export async function apiSetLowStockThreshold(itemId, threshold) {
  return jsonRequest(`/items/${itemId}/low-stock-threshold`, "PATCH", {
    low_stock_threshold: threshold,
  });
}
```

- [ ] **Step 8: Write the view**

Create `backend/static/views/lowStock.js`:

```javascript
// View: the TechFM OA+ reorder queue.
//
// Layer: views. Lists every item at or below its own threshold, deepest
// below first, and lets that threshold be retuned in place. The 7-day
// dispensed figure sits in the same action column as the threshold
// control on purpose: the number that answers "how fast is this moving"
// and the control that answers "when should it warn me" are read
// together or not at all.
//
// Rows are rebuilt from the server on every load. Nothing is patched in
// place, because a threshold edit can remove the row it was made on
// (lowering a threshold below the current count clears the condition),
// and a list that quietly kept such a row would be lying.

import { apiListLowStock, apiSetLowStockThreshold } from "../api.js";
import { setMessage } from "../dom.js";
import { escapeHtml, friendlyError } from "../format.js";
import { subscribe } from "../realtime.js";

const LOW_STOCK_CHANGED_EVENT = "item.low_stock.changed";
const LOW_STOCK_PAGE = "low-stock";

const listEl = document.getElementById("low-stock-list");
const messageEl = document.getElementById("low-stock-message");
const refreshBtn = document.getElementById("low-stock-refresh");

// Guards against an out-of-order response overwriting a newer one: a
// realtime invalidation can land while a slower manual refresh is still
// in flight.
let loadSequence = 0;

function quantityText(value) {
  // Matches the backend's `domain.receipt.format_quantity`: 3.00 -> 3.
  return String(Number(value));
}

function buildCard(row) {
  const card = document.createElement("div");
  card.className = "low-stock-card";
  card.dataset.id = row.id;
  card.innerHTML =
    `<div class="low-stock-card-header">` +
      `<h3>${escapeHtml(row.name)}</h3>` +
      `<span class="low-stock-count">${escapeHtml(quantityText(row.quantity))} on hand</span>` +
    `</div>` +
    `<div class="low-stock-details">` +
      `<span>${escapeHtml(row.barcode)}</span>` +
      `<span>${escapeHtml(row.location)}</span>` +
    `</div>` +
    `<div class="low-stock-actions">` +
      `<span class="low-stock-usage">7-day used: ` +
        `${escapeHtml(quantityText(row.dispensed_last_7_days))}</span>` +
      `<label class="low-stock-threshold">` +
        `<span>Warn at</span>` +
        `<input type="number" min="1" step="1" inputmode="numeric" ` +
          `class="low-stock-threshold-input" ` +
          `value="${escapeHtml(String(row.low_stock_threshold))}" ` +
          `aria-label="Low stock threshold for ${escapeHtml(row.name)}">` +
      `</label>` +
    `</div>` +
    `<p class="low-stock-row-message" aria-live="polite"></p>`;
  return card;
}

function render(rows) {
  listEl.replaceChildren();
  if (!rows.length) {
    setMessage(messageEl, "Nothing is below its threshold.", "success");
    return;
  }
  const fragment = document.createDocumentFragment();
  for (const row of rows) fragment.append(buildCard(row));
  listEl.append(fragment);
  setMessage(messageEl, "", "");
}

export async function loadLowStock({ background = false } = {}) {
  if (!listEl) return;
  const sequence = ++loadSequence;
  if (!background) setMessage(messageEl, "Loading low stock...", "");
  try {
    const rows = await apiListLowStock();
    if (sequence !== loadSequence) return;
    render(rows);
  } catch (err) {
    if (sequence !== loadSequence) return;
    listEl.replaceChildren();
    setMessage(messageEl, friendlyError(err, "Could not load low stock."), "error");
  }
}

// Commit on blur and on Enter, not on every keystroke: a threshold typed
// as "20" passes through "2", which would fire a push for a crossing the
// operator never intended.
async function commitThreshold(input) {
  const card = input.closest(".low-stock-card");
  const rowMessage = card.querySelector(".low-stock-row-message");
  const previous = input.defaultValue;
  const value = Number(input.value);

  if (!Number.isInteger(value) || value < 1) {
    input.value = previous;
    setMessage(rowMessage, "Threshold must be a whole number of at least 1.", "error");
    return;
  }
  if (String(value) === previous) return;

  input.disabled = true;
  try {
    await apiSetLowStockThreshold(card.dataset.id, value);
    input.defaultValue = String(value);
    setMessage(rowMessage, "Saved.", "success");
    // The row may no longer belong on the page -- a lowered threshold can
    // clear the condition entirely -- so reload rather than trusting the
    // card that is on screen.
    loadLowStock({ background: true });
  } catch (err) {
    input.value = previous;
    setMessage(rowMessage, friendlyError(err, "Could not save that threshold."), "error");
  } finally {
    input.disabled = false;
  }
}

if (listEl) {
  listEl.addEventListener("blur", (event) => {
    if (event.target.classList.contains("low-stock-threshold-input")) {
      commitThreshold(event.target);
    }
  }, true);

  listEl.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && event.target.classList.contains("low-stock-threshold-input")) {
      event.preventDefault();
      event.target.blur();
    }
  });
}

if (refreshBtn) refreshBtn.addEventListener("click", () => loadLowStock());

// A matching invalidation or a recovered connection both mean the queue
// may be stale. Inactive pages need no dirty flag: `nav.js` reloads this
// page on entry.
subscribe(LOW_STOCK_CHANGED_EVENT, ({ activePage }) => {
  if (activePage !== LOW_STOCK_PAGE) return;
  return loadLowStock({ background: true });
});
```

- [ ] **Step 9: Register the module**

In `backend/static/main.js`, add beside the other side-effect imports (after `import "./views/userRequests.js";`):

```javascript
import "./views/lowStock.js";
```

- [ ] **Step 10: Add the styles**

Append to `backend/static/styles.css`, after the `.user-request-*` block:

```css
/* --- Low Stock page ------------------------------------------------- */

.low-stock-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
    gap: var(--space-3);
}

.low-stock-card {
    border: 1px solid var(--panel-border);
    border-left: 5px solid var(--color-error);
    border-radius: var(--radius-md);
    padding: var(--space-4);
    background: var(--panel-nested);
}

.low-stock-card-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: var(--space-3);
}

.low-stock-card-header h3 {
    margin: var(--space-1) 0 0;
}

/* Status accent as a badge, never a filled panel -- the palette rule. */
.low-stock-count {
    color: var(--color-error);
    font-weight: var(--fw-bold);
    white-space: nowrap;
}

.low-stock-details {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    font-size: var(--fs-sm);
    margin-top: var(--space-2);
}

.low-stock-actions {
    margin-top: var(--space-3);
    padding-top: var(--space-3);
    border-top: 1px solid var(--panel-rule);
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
    flex-wrap: wrap;
}

.low-stock-usage {
    font-size: var(--fs-sm);
    font-weight: var(--fw-semibold);
}

.low-stock-threshold {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: var(--fs-sm);
}

.low-stock-threshold-input {
    width: 5rem;
}

.low-stock-row-message:empty {
    display: none;
}
```

- [ ] **Step 11: Run the tests**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_low_stock_shell.py -q`
Expected: PASS.

- [ ] **Step 12: Full suite**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/ -q`
Expected: PASS except the known environmental `test_cascade_deletes_with_user`.

- [ ] **Step 13: Commit**

```bash
git add backend/static/pages/low-stock.html backend/static/views/lowStock.js backend/static/shell-head.html backend/static/views/nav.js backend/static/api.js backend/static/main.js backend/static/styles.css backend/app/main.py backend/tests/test_low_stock_shell.py
git commit -m "feat(ui): Low Stock page with inline threshold editing and 7-day usage"
```

---

### Task 13: Documentation

**Files:**
- Modify: `docs/notification-events.md`
- Modify: `docs/adding-a-notification-trigger.md`
- Modify: `docs/endpoint-map.md`
- Modify: `docs/current-state.md`

These are living, current-truth documents. State what is true now; do not narrate how the feature came to be. An update that breaches a doc's soft word budget should delete something stale in the same edit.

- [ ] **Step 1: Register the push event**

In `docs/notification-events.md`, add to the Part 1 "Who is told" table:

```
| `item.low_stock` | any stock write, or a threshold raise | `POST /transactions/`, `POST /transactions/adjust`, `DELETE /transactions/{id}`, `POST /mass-stages/{id}/load`, `POST /mass-stages/{id}/return`, the three `/work-orders/{id}/items` routes, `PATCH /items/{id}/low-stock-threshold` | everyone at `LOW_STOCK_AUDIENCE_MIN_ROLE` (**TechFM OA** and above), **including the actor** |
```

Add to the exceptions/inversions section, beside the existing `build_netfacilities_chain_message` note:

```
`item.low_stock` does not suppress the actor. It is a state alarm about
the stockroom rather than a report of somebody's action, and whoever just
took the last of an item is standing in front of the empty shelf. The
inversion is expressed as `actor_id=None` in
`recipients_for_low_stock`, not by skipping `select_recipients`.
```

Add to the realtime part:

```
| `item.low_stock.changed` | an item entered or left the low-stock set; a threshold edit; item create or archive | TechFM OA and above |
```

- [ ] **Step 2: Record the widened text rule**

In `docs/adding-a-notification-trigger.md`, under "The five rules", amend rule 1's closing sentence to:

```
The line is *catalogue identifiers, counts, and quantities yes; customer,
job, and price detail no*, and `build_message` takes exactly `number`,
`count`, `name`, and `quantity` to keep it there. An item `name` is a
manufacturer/catalogue string and identifies no person, site, or job; a
price on the same item remains forbidden. Widening that signature further
is the change to argue about, not the strings.
```

- [ ] **Step 3: Add the routes**

In `docs/endpoint-map.md`, add to the items section:

```
| `GET /items/low-stock` | TechFM OA+ | Live items at or below their own `low_stock_threshold`, deepest below first, with `dispensed_last_7_days`. Registered above `GET /items/{barcode}`, which would otherwise shadow it. |
| `PATCH /items/{item_id}/low-stock-threshold` | TechFM OA+ | Sets the threshold (whole number >= 1). A raise past the current count pushes like a dispense. |
```

- [ ] **Step 4: Record the page and the column**

In `docs/current-state.md`, add the Low Stock page to the pages list (Review group, TechFM OA+) and `items.low_stock_threshold` to the schema notes, in the same clipped form the surrounding entries use.

- [ ] **Step 5: Commit**

```bash
git add docs/notification-events.md docs/adding-a-notification-trigger.md docs/endpoint-map.md docs/current-state.md
git commit -m "docs: register the low-stock event, routes, page, and column"
```

---

### Task 14: Verification on a real device

CI cannot prove push delivery. This is the user's step, not an agent's — report it and stop.

- [ ] **Step 1: Confirm the suite is green**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/ -q`
Expected: PASS except the known environmental `test_cascade_deletes_with_user`. Report the actual output.

- [ ] **Step 2: Hand off the manual checks**

Report to the user, and do not perform these unprompted — the user validates manually and does not want the preview server started for them:

1. On a phone with the app installed to the Home Screen and notifications granted, dispense an item down past its threshold **from a different account**. Confirm the notification arrives with the app fully closed and reads `<item name> is down to <n>`.
2. Repeat from the **same** account and confirm it arrives there too — the actor is deliberately in the audience, and this is the one behaviour that inverts every other event.
3. Open Low Stock on a second device and dispense on the first. The row should appear without a manual refresh.
4. Raise a threshold above an item's current count and confirm both the push and the row appearing.
5. Restock the item above its threshold and confirm the row disappears and no push is sent.

- [ ] **Step 3: Do not push**

Pushing `main` deploys to production. Leave the commits local and tell the user the branch is ready.
