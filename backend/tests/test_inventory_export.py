"""`GET /items/export`: the print workbook, over real HTTP."""

import io
import os
import sys
import uuid
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.database import get_db
from app.main import app
from app.models import Item, User
from app.services import auth as auth_service
from app.services import user_requests as request_service


def _export(db, role):
    user = User(
        username=f"u-{uuid.uuid4().hex[:10]}",
        password_hash=auth_service.hash_password("hunter2"),
        role=role,
    )
    db.add(user)
    db.commit()
    token = auth_service.create_session(db, user)
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            client.cookies.set("session", token)
            return client.get("/items/export")
    finally:
        del app.dependency_overrides[get_db]


def test_export_is_gated_at_techfm_oa(db):
    assert _export(db, "supervisor").status_code == 403


def test_export_holds_items_and_every_request_tab(db):
    name = f"Export widget {uuid.uuid4().hex[:6]}"
    db.add(Item(barcode=f"BC-{uuid.uuid4().hex[:10]}", name=name,
                quantity=Decimal("3"), location="Bay 1", notes={"color": "red"}))
    request_service.create_catalogue_request(
        db, searched_text="Mystery pipe", quantity=Decimal("2"), note=None,
        work_order_id=None, work_order_number=None, source="find_item", created_by_id=None,
    )
    db.commit()

    response = _export(db, "techfm_oa")

    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    book = load_workbook(io.BytesIO(response.content))
    assert book.sheetnames == [
        "Items", "Material requests", "Catalogue requests",
        "Stock recounts", "Missing price - link",
    ]
    item_names = [row[0] for row in book["Items"].iter_rows(min_row=5, values_only=True)]
    assert name in item_names
    requests = [row[2] for row in book["Catalogue requests"].iter_rows(min_row=5, values_only=True)]
    assert "Mystery pipe" in requests
    assert book["Items"].print_title_rows == "$4:$4"
