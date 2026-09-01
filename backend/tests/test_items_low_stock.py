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
