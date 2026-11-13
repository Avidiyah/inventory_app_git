"""SQL statements for the full item list over the real TestClient route.
Guards the alternate-barcode N+1 (2026-11-12): `_item_response` reads
`item.alt_barcodes` per row, so without an eager load every extra item cost
one more query. Low stock goes through the same serializer."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import event

from app.database import engine
from app.services import items as items_service
from tests.test_work_order_open_queries import _TX_CONTROL, _client, _user


def _seed(db, count: int) -> None:
    for _ in range(count):
        item = items_service.create_item(db, barcode=f"Q-{uuid.uuid4().hex[:12]}", name="Query probe",
                                         quantity=Decimal("0"), location="Shelf")
        items_service.replace_barcodes(db, item.id, [f"A-{uuid.uuid4().hex[:12]}", f"B-{uuid.uuid4().hex[:12]}"])
    db.commit()


def _count(db, client, path: str) -> int:
    db.expunge_all()
    statements = []

    def listener(conn, cursor, statement, params, context, executemany):
        if not statement.lstrip().upper().startswith(_TX_CONTROL):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", listener)
    try:
        response = client.get(path)
    finally:
        event.remove(engine, "before_cursor_execute", listener)
    assert response.status_code == 200, response.text
    assert any(row["barcodes"] for row in response.json())
    return len(statements)


@pytest.mark.parametrize("path", ["/items/", "/items/low-stock"])
def test_item_list_query_count_does_not_grow_with_items(db, path):
    admin = _user(db)
    with _client(db, admin) as client:
        _seed(db, 2)
        small = _count(db, client, path)
        _seed(db, 10)
        large = _count(db, client, path)
    assert small == large, f"{path}: {small} statements with 2 items, {large} with 12"
