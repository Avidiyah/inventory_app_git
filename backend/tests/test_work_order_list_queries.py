"""SQL statements `GET /work-orders/` costs over the real TestClient route. A
guard for the list eager load (2026-11-13): each card reads `line.item.price`,
so without the items loaded with the list every distinct item cost a query."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import event

from app.database import engine
from app.models import Item, WorkOrderItem
from app.services import work_orders as wos
from tests.test_work_order_open_queries import _TX_CONTROL, _client, _user


def _seed(db, admin, *, orders: int, distinct_items: int) -> str:
    """`orders` live orders under one unique number tag, each with `distinct_items`
    material lines; with one item they all share it. Returns the tag for `q=`."""
    tag = uuid.uuid4().hex[:10]
    shared = [Item(barcode=f"BC-{uuid.uuid4().hex[:10]}", name="Rags", quantity=Decimal(100),
                   location="Bay", price=Decimal("1.50")) for _ in range(distinct_items)]
    db.add_all(shared)
    db.flush()
    for n in range(orders):
        order = wos.get_or_create_work_order(db, number=f"WO-{tag}-{n}", created_by_id=admin.id)
        db.add_all(WorkOrderItem(work_order_id=order.id, item_id=item.id, quantity=Decimal(1),
                                 mode="retroactive", created_by_id=admin.id) for item in shared)
    db.commit()
    return tag


def _count_list(db, client, tag) -> int:
    db.expunge_all()
    statements = []

    def listener(conn, cursor, statement, params, context, executemany):
        if not statement.lstrip().upper().startswith(_TX_CONTROL):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", listener)
    try:
        response = client.get("/work-orders/", params={"q": tag})
    finally:
        event.remove(engine, "before_cursor_execute", listener)
    assert response.status_code == 200 and len(response.json()) == 3, response.text
    return len(statements)


def test_list_query_count_does_not_grow_with_distinct_items(db):
    admin = _user(db)
    few = _seed(db, admin, orders=3, distinct_items=1)
    many = _seed(db, admin, orders=3, distinct_items=6)
    with _client(db, admin) as client:
        assert _count_list(db, client, few) == _count_list(db, client, many)
