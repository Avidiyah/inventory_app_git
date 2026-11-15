"""W5: every User Request write emits `user_request.changed` once, after commit.

The listener in `app/request_events.py` is the only emitter, so each writer is
driven through its service (or route) and the envelopes are counted.
"""

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app import request_events
from app.database import get_db
from app.domain import realtime as realtime_policy
from app.main import app
from app.models import Item, User, UserRequest
from app.services import auth
from app.services import items as item_service
from app.services import material_requests as material_service
from app.services import user_requests as request_service
from app.services import work_orders as wos
from app.services.transactions import apply_correction, apply_transaction, void_transaction


@pytest.fixture(autouse=True)
def _clean_buffer():
    material_service.drain()
    yield
    material_service.drain()


@pytest.fixture
def sent(monkeypatch):
    envelopes = []
    monkeypatch.setattr(request_events.realtime_service, "emit", envelopes.append)
    return envelopes


def _ids(envelopes):
    assert all(e["type"] == realtime_policy.EVENT_USER_REQUEST_CHANGED for e in envelopes)
    return [e["id"] for e in envelopes]


def _user(db, role="technician"):
    user = User(
        username=f"rev-{uuid.uuid4().hex[:10]}", first_name="Test", last_name=role.title(),
        password_hash=auth.hash_password("hunter2"), role=role,
    )
    db.add(user)
    db.flush()
    return user


def _item(db, quantity="0", price="1.00", link=None, name="Event Item"):
    item = Item(
        barcode=f"REV-{uuid.uuid4().hex[:10]}", name=name, quantity=Decimal(quantity),
        location="Shelf E", price=None if price is None else Decimal(price), product_link=link,
    )
    db.add(item)
    db.flush()
    return item


def _work_order(db, supervisor, tech):
    order = wos.get_or_create_work_order(db, number=f"WO-REV-{uuid.uuid4().hex[:8]}", created_by_id=supervisor.id)
    return wos.update_work_order(db, order.id, user=supervisor, fields={"assigned_to_ids": [tech.id]})


def _dispense(db, item, tech, order, quantity="3"):
    return apply_transaction(
        db, item_id=item.id, transaction_type="dispense", quantity=Decimal(quantity),
        user_id=tech.id, work_order_number=order.number, work_order_id=order.id,
    )


def _catalogue(db, tech, text="3/4 copper elbow", order=None):
    request = request_service.create_catalogue_request(
        db, searched_text=text, quantity=Decimal("1"), note=None,
        work_order_id=order.id if order else None, work_order_number=order.number if order else None,
        source="work_orders" if order else "find_item", created_by_id=tech.id,
    )
    db.commit()
    return request


def _of_type(db, item, request_type):
    return db.query(UserRequest).filter(
        UserRequest.item_id == item.id, UserRequest.request_type == request_type
    ).one()


def test_filing_a_catalogue_request_emits_once_with_no_request_id_outside_a_request(db, sent):
    request = _catalogue(db, _user(db))
    assert _ids(sent) == [str(request.id)]
    assert sent[0]["req"] is None


def test_filing_a_material_request_emits_once(db, sent):
    tech = _user(db)
    order = wos.get_or_create_work_order(db, number=f"WO-REV-{uuid.uuid4().hex[:8]}", created_by_id=tech.id)
    request, _ = material_service.create_or_update(
        db, item_id=_item(db).id, work_order=order, quantity=Decimal("1"),
        product_link=None, note=None, created_by_id=tech.id, origin="work_order",
    )
    db.commit()
    assert _ids(sent) == [str(request.id)]


def test_a_short_dispense_files_a_recount_and_emits_once(db, sent):
    sup, tech = _user(db, "supervisor"), _user(db)
    item = _item(db, "0")
    _dispense(db, item, tech, _work_order(db, sup, tech))
    assert _ids(sent) == [str(_of_type(db, item, "inventory_recount").id)]


def test_an_unpriced_material_files_a_missing_price_request_and_emits_once(db, sent):
    sup, tech = _user(db, "supervisor"), _user(db)
    item = _item(db, "10", price=None)
    _dispense(db, item, tech, _work_order(db, sup, tech), quantity="1")
    assert _ids(sent) == [str(_of_type(db, item, "missing_item_price").id)]


def test_a_price_edit_that_resolves_a_missing_price_request_emits_once(db, sent):
    admin, sup, tech = _user(db, "admin"), _user(db, "supervisor"), _user(db)
    item = _item(db, "10", price=None, link="https://example.com/x")
    _dispense(db, item, tech, _work_order(db, sup, tech), quantity="1")
    request = _of_type(db, item, "missing_item_price")
    sent.clear()

    item_service.update_item(db, item.id, price=Decimal("4.00"), performed_by_id=admin.id)

    db.refresh(request)
    assert request.status == "resolved"
    assert _ids(sent) == [str(request.id)]


def test_a_correction_that_resolves_a_recount_emits_once(db, sent):
    admin, sup, tech = _user(db, "admin"), _user(db, "supervisor"), _user(db)
    item = _item(db, "0")
    _dispense(db, item, tech, _work_order(db, sup, tech))
    request = _of_type(db, item, "inventory_recount")
    sent.clear()

    apply_correction(db, item_id=item.id, new_quantity=Decimal("9"), reason="Counted.", user_id=admin.id)

    assert _ids(sent) == [str(request.id)]


def test_voiding_the_transaction_resolves_its_recount_and_emits_once(db, sent):
    admin, sup, tech = _user(db, "admin"), _user(db, "supervisor"), _user(db)
    item = _item(db, "0")
    transaction = _dispense(db, item, tech, _work_order(db, sup, tech))
    request = _of_type(db, item, "inventory_recount")
    sent.clear()

    void_transaction(db, transaction_id=transaction.id, user_id=admin.id, user_role="admin")

    db.refresh(request)
    assert request.status == "resolved"
    assert _ids(sent) == [str(request.id)]


def test_mark_stocked_emits_once(db, sent):
    staff, tech = _user(db, "techfm_oa"), _user(db)
    order = wos.get_or_create_work_order(db, number=f"WO-REV-{uuid.uuid4().hex[:8]}", created_by_id=tech.id)
    request, _ = material_service.create_or_update(
        db, item_id=_item(db).id, work_order=order, quantity=Decimal("1"),
        product_link=None, note=None, created_by_id=tech.id, origin="work_order",
    )
    db.commit()
    sent.clear()

    material_service.mark_stocked(db, request.id, actor_id=staff.id)
    db.commit()

    assert _ids(sent) == [str(request.id)]


def test_resolve_and_reopen_each_emit_once(db, sent):
    admin = _user(db, "admin")
    request = _catalogue(db, _user(db))
    sent.clear()

    request_service.update_user_request(db, request.id, status="resolved", resolution_note="Dup.", resolved_by_id=admin.id)
    request_service.update_user_request(db, request.id, status="open", resolution_note=None, resolved_by_id=admin.id)

    assert _ids(sent) == [str(request.id)] * 2


def test_fulfilling_with_three_siblings_emits_four_distinct_ids(db, sent):
    admin, tech = _user(db, "admin"), _user(db)
    first = _catalogue(db, tech, "brass cap")
    siblings = [_catalogue(db, tech, "brass cap") for _ in range(3)]
    item = _item(db, price="2.00", link="https://example.com/cap")
    db.commit()
    sent.clear()

    request_service.fulfill_catalogue_request(
        db, first.id, item_id=item.id, sibling_ids=[s.id for s in siblings], resolved_by_id=admin.id,
    )

    assert sorted(_ids(sent)) == sorted(str(r.id) for r in (first, *siblings))


def test_a_write_rolled_back_before_commit_emits_nothing(db, sent):
    tech = _user(db)
    request_service.create_catalogue_request(
        db, searched_text="rolled back", quantity=Decimal("1"), note=None,
        work_order_id=None, work_order_number=None, source="find_item", created_by_id=tech.id,
    )
    db.flush()
    db.rollback()
    db.commit()
    assert sent == []


def test_an_unrelated_commit_emits_nothing(db, sent):
    item = _item(db)
    db.commit()
    item.name = "Renamed"
    db.commit()
    assert sent == []


def test_a_route_write_emits_exactly_once(db, sent):
    admin = _user(db, "admin")
    request = _catalogue(db, _user(db))
    sent.clear()
    token = auth.create_session(db, admin)
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            client.cookies.set("session", token)
            response = client.patch(
                f"/user-requests/{request.id}", json={"status": "resolved", "resolution_note": "Done."}
            )
    finally:
        del app.dependency_overrides[get_db]

    assert response.status_code == 200, response.text
    assert _ids(sent) == [str(request.id)]
    assert sent[0]["req"]
