"""Material Requests: a catalogue item the shelf does not have.

Distinct from a Catalogue Request (no row at all) and a recount (count is
wrong): here the row exists, `item_id` is never NULL, and the interesting
behaviour is the automatic `open -> stocked -> open` movement driven by
the item's on-hand crossing zero.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.domain.errors import ItemRequestStateError, MaterialRequestOwnershipError
from app.models import Item, User, UserRequest, WorkOrderItem, WorkOrderTechnician
from app.services import auth
from app.services import material_requests as material_service
from app.services import user_requests as request_service
from app.services import work_orders as wos


@pytest.fixture(autouse=True)
def _clean_buffer():
    material_service.drain()
    yield
    material_service.drain()


def _user(db, role="technician"):
    user = User(
        username=f"mreq-{uuid.uuid4().hex[:10]}",
        first_name="Test",
        last_name=role.title(),
        password_hash=auth.hash_password("hunter2"),
        role=role,
    )
    db.add(user)
    db.flush()
    return user


def _work_order(db, creator, *, assigned_to=None, supervisor=None):
    return wos.get_or_create_work_order(
        db,
        number=f"WO-MR-{uuid.uuid4().hex[:8]}",
        created_by_id=creator.id,
        assigned_to_id=assigned_to.id if assigned_to else None,
        supervisor_id=supervisor.id if supervisor else None,
    )


def _item(db, quantity="0", name=None):
    item = Item(
        barcode=f"MR-{uuid.uuid4().hex[:10]}",
        name=name or f"Widget {uuid.uuid4().hex[:6]}",
        quantity=Decimal(quantity),
        location="Shelf C",
        price=Decimal("3.50"),
        product_link="https://example.com/widget",
    )
    db.add(item)
    db.flush()
    return item


def _file(db, tech, work_order, item, quantity="1", link=None, note=None):
    request, created = material_service.create_or_update(
        db,
        item_id=item.id,
        work_order=work_order,
        quantity=Decimal(quantity),
        product_link=link,
        note=note,
        created_by_id=tech.id,
        origin="request_card",
    )
    db.flush()
    return request, created


# --------------------------------------------------------------------------
# Filing and dedupe
# --------------------------------------------------------------------------

def test_filing_stores_the_item_work_order_and_details(db):
    tech = _user(db)
    work_order = _work_order(db, tech)
    item = _item(db)

    request, created = _file(
        db, tech, work_order, item, quantity="2.5",
        link="https://shop.example/x", note="  blue one  ",
    )

    assert created is True
    assert request.request_type == "material_request"
    assert request.status == "open"
    assert request.item_id == item.id
    assert request.work_order_id == work_order.id
    assert request.message == "Please stock this item"
    assert request.details["quantity"] == "2.5"
    assert request.details["product_link"] == "https://shop.example/x"
    assert request.details["note"] == "blue one"
    assert request.details["work_order_number"] == work_order.number
    assert request.details["origin"] == "request_card"
    assert request.details["stock_cycles"] == 0


def test_a_second_filing_for_the_same_pair_updates_instead_of_inserting(db):
    tech = _user(db)
    work_order = _work_order(db, tech)
    item = _item(db)
    first, _ = _file(db, tech, work_order, item, quantity="1")

    second, created = _file(db, tech, work_order, item, quantity="4", note="more")

    assert created is False
    assert second.id == first.id
    assert second.details["quantity"] == "4"
    assert second.details["note"] == "more"
    assert (
        db.query(UserRequest)
        .filter(UserRequest.request_type == "material_request", UserRequest.item_id == item.id)
        .count()
        == 1
    )


def test_other_work_orders_get_their_own_request(db):
    tech = _user(db)
    item = _item(db)
    first, _ = _file(db, tech, _work_order(db, tech), item)
    second, created = _file(db, tech, _work_order(db, tech), item)

    assert created is True
    assert second.id != first.id


def test_a_resolved_request_does_not_absorb_a_new_filing(db):
    tech = _user(db)
    work_order = _work_order(db, tech)
    item = _item(db)
    old, _ = _file(db, tech, work_order, item)
    old.status = "resolved"
    db.flush()

    fresh, created = _file(db, tech, work_order, item)

    assert created is True
    assert fresh.id != old.id


def test_filing_is_allowed_when_the_app_shows_stock(db):
    """Advisory only: counts are sometimes wrong, staff verify."""
    tech = _user(db)
    item = _item(db, quantity="3")
    request, created = _file(db, tech, _work_order(db, tech), item)
    assert created is True
    assert request.status == "open"


# --------------------------------------------------------------------------
# The automatic edges
# --------------------------------------------------------------------------

def _restock(db, item, to="5"):
    """Simulate what every stock service does: mutate under the lock, then
    call the recorder before commit."""
    before = item.quantity
    item.quantity = Decimal(to)
    material_service.record_stock_change(db, item, quantity_before=before)
    db.flush()


def test_a_restock_moves_every_open_request_for_the_item_to_stocked(db):
    tech = _user(db)
    supervisor = _user(db, "supervisor")
    wo_a = _work_order(db, tech, assigned_to=tech, supervisor=supervisor)
    wo_b = _work_order(db, tech)
    item = _item(db)
    a, _ = _file(db, tech, wo_a, item)
    b, _ = _file(db, tech, wo_b, item)

    _restock(db, item)

    assert a.status == "stocked"
    assert b.status == "stocked"
    assert a.details["stocked_by"] == "auto"
    assert a.details["stock_cycles"] == 1
    datetime.fromisoformat(a.details["stocked_at"])  # parses
    facts = material_service.drain()
    assert {f.request_id for f in facts} == {a.id, b.id}
    fact_a = next(f for f in facts if f.request_id == a.id)
    assert fact_a.item_name == item.name
    assert fact_a.work_order_number == wo_a.number
    assert fact_a.assignee_ids == (tech.id,)
    assert fact_a.supervisor_id == supervisor.id
    assert fact_a.requester_id == tech.id


def test_the_fact_reads_plural_assignments_with_the_legacy_column_folded_in(db):
    tech = _user(db)
    second = _user(db)
    work_order = _work_order(db, tech, assigned_to=tech)
    db.add(WorkOrderTechnician(work_order_id=work_order.id, technician_id=second.id))
    db.flush()
    db.refresh(work_order)
    item = _item(db)
    _file(db, tech, work_order, item)

    _restock(db, item)

    (fact,) = material_service.drain()
    assert set(fact.assignee_ids) == {tech.id, second.id}


def test_a_negative_count_coming_back_positive_is_a_restock(db):
    tech = _user(db)
    item = _item(db, quantity="-3")
    request, _ = _file(db, tech, _work_order(db, tech), item)

    _restock(db, item, to="1")

    assert request.status == "stocked"
    assert len(material_service.drain()) == 1


def test_a_move_that_stays_positive_or_stays_nonpositive_changes_nothing(db):
    tech = _user(db)
    item = _item(db, quantity="0")
    request, _ = _file(db, tech, _work_order(db, tech), item)

    _restock(db, item, to="-2")
    assert request.status == "open"
    assert material_service.drain() == []

    item.quantity = Decimal("4")
    db.flush()
    request.status = "stocked"
    db.flush()
    _restock(db, item, to="9")
    assert request.status == "stocked"
    assert material_service.drain() == []


def test_running_out_again_sends_a_stocked_request_back_to_open(db):
    tech = _user(db)
    item = _item(db)
    request, _ = _file(db, tech, _work_order(db, tech), item)
    _restock(db, item, to="2")
    material_service.drain()

    _restock(db, item, to="0")

    assert request.status == "open"
    assert "stocked_at" not in request.details
    assert "stocked_by" not in request.details
    assert request.details["stock_cycles"] == 1
    assert material_service.drain() == []


def test_a_second_restock_counts_a_second_cycle(db):
    tech = _user(db)
    item = _item(db)
    request, _ = _file(db, tech, _work_order(db, tech), item)
    _restock(db, item, to="2")
    _restock(db, item, to="0")
    _restock(db, item, to="2")

    assert request.status == "stocked"
    assert request.details["stock_cycles"] == 2


def test_a_restock_against_a_closed_work_order_resolves_quietly(db):
    tech = _user(db)
    work_order = _work_order(db, tech)
    item = _item(db)
    request, _ = _file(db, tech, work_order, item)
    work_order.archived_at = datetime.now(timezone.utc)
    db.flush()

    _restock(db, item)

    assert request.status == "resolved"
    assert request.resolution_note == "Work order was closed before the item was stocked."
    assert material_service.drain() == []


def test_the_buffer_is_bounded(db):
    tech = _user(db)
    item = _item(db)
    for _ in range(3):
        _file(db, tech, _work_order(db, tech), item)
    # Fill the buffer by hand, then prove the real transition drops overflow.
    for _ in range(material_service.MAX_BUFFERED_FACTS):
        material_service._buffer_fact(
            material_service.StockedFact(
                request_id=uuid.uuid4(), item_name="x", work_order_id=None,
                work_order_number="WO", assignee_ids=(), supervisor_id=None,
                requester_id=None,
            )
        )
    _restock(db, item)
    assert len(material_service.drain()) == material_service.MAX_BUFFERED_FACTS


# --------------------------------------------------------------------------
# Manual fire, cancel, resolve-from-line, reopen
# --------------------------------------------------------------------------

def test_mark_stocked_fires_at_any_on_hand_and_buffers_one_fact(db):
    tech = _user(db)
    staff = _user(db, "techfm_oa")
    item = _item(db, quantity="0")
    request, _ = _file(db, tech, _work_order(db, tech, assigned_to=tech), item)

    marked = material_service.mark_stocked(db, request.id, actor_id=staff.id)

    assert marked.status == "stocked"
    assert marked.details["stocked_by"] == str(staff.id)
    assert marked.details["stock_cycles"] == 1
    assert len(material_service.drain()) == 1


def test_mark_stocked_refuses_a_stocked_or_resolved_request(db):
    tech = _user(db)
    staff = _user(db, "techfm_oa")
    request, _ = _file(db, tech, _work_order(db, tech), _item(db))
    material_service.mark_stocked(db, request.id, actor_id=staff.id)
    with pytest.raises(ItemRequestStateError):
        material_service.mark_stocked(db, request.id, actor_id=staff.id)


def test_a_manually_stocked_request_stays_stocked_through_a_later_restock_edge(db):
    """The crew was already told; only `went_out` can send it back."""
    tech = _user(db)
    staff = _user(db, "techfm_oa")
    item = _item(db, quantity="0")
    request, _ = _file(db, tech, _work_order(db, tech), item)
    material_service.mark_stocked(db, request.id, actor_id=staff.id)
    material_service.drain()

    _restock(db, item, to="5")

    assert request.status == "stocked"
    assert request.details["stock_cycles"] == 1
    assert material_service.drain() == []


def test_the_filer_can_cancel_their_own_open_request(db):
    tech = _user(db)
    request, _ = _file(db, tech, _work_order(db, tech), _item(db))

    cancelled = material_service.cancel(db, request.id, actor_id=tech.id)

    assert cancelled.status == "resolved"
    assert cancelled.resolution_note == "Cancelled by requester"
    assert cancelled.resolved_by_id == tech.id


def test_someone_else_cannot_cancel_it(db):
    tech = _user(db)
    other = _user(db)
    request, _ = _file(db, tech, _work_order(db, tech), _item(db))
    with pytest.raises(MaterialRequestOwnershipError):
        material_service.cancel(db, request.id, actor_id=other.id)


def test_a_stocked_request_cannot_be_cancelled(db):
    tech = _user(db)
    item = _item(db)
    request, _ = _file(db, tech, _work_order(db, tech), item)
    _restock(db, item)
    with pytest.raises(ItemRequestStateError):
        material_service.cancel(db, request.id, actor_id=tech.id)


def test_resolve_from_line_records_the_added_quantity(db):
    tech = _user(db)
    work_order = _work_order(db, tech)
    item = _item(db)
    request, _ = _file(db, tech, work_order, item, quantity="4")
    _restock(db, item)

    resolved = material_service.resolve_from_line(
        db,
        request_id=request.id,
        work_order_id=work_order.id,
        work_order_number=work_order.number,
        item_id=item.id,
        quantity=Decimal("3"),
        resolved_by_id=tech.id,
    )

    assert resolved.status == "resolved"
    assert resolved.resolution_note == f"Added to {work_order.number}."
    assert resolved.details["added_quantity"] == "3"


@pytest.mark.parametrize("wrong", ["status", "work_order", "item"])
def test_resolve_from_line_refuses_a_mismatch(db, wrong):
    tech = _user(db)
    work_order = _work_order(db, tech)
    item = _item(db)
    request, _ = _file(db, tech, work_order, item)
    if wrong != "status":
        _restock(db, item)
    wo_id = _work_order(db, tech).id if wrong == "work_order" else work_order.id
    item_id = _item(db).id if wrong == "item" else item.id

    with pytest.raises(ItemRequestStateError):
        material_service.resolve_from_line(
            db, request_id=request.id, work_order_id=wo_id,
            work_order_number=work_order.number, item_id=item_id,
            quantity=Decimal("1"), resolved_by_id=tech.id,
        )


def test_reopening_a_resolved_material_request_clears_the_stamps(db):
    tech = _user(db)
    staff = _user(db, "techfm_oa")
    item = _item(db)
    request, _ = _file(db, tech, _work_order(db, tech), item)
    _restock(db, item)
    request_service.update_user_request(
        db, request.id, status="resolved", resolution_note=None, resolved_by_id=staff.id
    )

    reopened = request_service.update_user_request(
        db, request.id, status="open", resolution_note=None, resolved_by_id=staff.id
    )

    assert reopened.status == "open"
    assert "stocked_at" not in reopened.details
    assert "stocked_by" not in reopened.details


# --------------------------------------------------------------------------
# Reads
# --------------------------------------------------------------------------

def test_list_for_work_order_returns_material_and_catalogue_rows_newest_first(db):
    tech = _user(db)
    work_order = _work_order(db, tech)
    material, _ = _file(db, tech, work_order, _item(db))
    catalogue = request_service.create_catalogue_request(
        db, searched_text="grommet", quantity=Decimal("1"), note=None,
        work_order_id=work_order.id, work_order_number=work_order.number,
        source="work_orders", created_by_id=tech.id,
    )
    db.flush()
    _file(db, tech, _work_order(db, tech), _item(db))  # other WO, excluded

    rows = material_service.list_for_work_order(db, work_order.id)

    assert [r.id for r in rows] == [catalogue.id, material.id]


def test_open_counts_groups_by_type_and_status(db):
    tech = _user(db)
    item = _item(db)
    a, _ = _file(db, tech, _work_order(db, tech), item)
    b, _ = _file(db, tech, _work_order(db, tech), item)
    baseline = material_service.open_counts(db)
    _restock(db, item)  # both to stocked

    counts = material_service.open_counts(db)

    mat_before = baseline.get("material_request", {})
    mat_after = counts["material_request"]
    assert mat_after.get("stocked", 0) - mat_before.get("stocked", 0) == 2
    assert mat_before.get("open", 0) - mat_after.get("open", 0) == 2


def test_stocked_requests_for_user_scope(db):
    tech = _user(db)
    other_tech = _user(db)
    supervisor = _user(db, "supervisor")
    staff = _user(db, "techfm_oa")
    item = _item(db)
    mine, _ = _file(db, tech, _work_order(db, other_tech, assigned_to=tech), item)
    routed, _ = _file(db, other_tech, _work_order(db, other_tech, supervisor=supervisor), item)
    filed, _ = _file(db, tech, _work_order(db, other_tech), item)
    theirs, _ = _file(db, other_tech, _work_order(db, other_tech, assigned_to=other_tech), item)
    _restock(db, item)
    still_open, _ = _file(db, tech, _work_order(db, other_tech, assigned_to=tech), _item(db))

    ids = lambda rows: {r.id for r in rows}
    assert ids(material_service.stocked_requests_for_user(db, tech)) == {mine.id, filed.id}
    assert ids(material_service.stocked_requests_for_user(db, supervisor)) == {routed.id}
    assert {mine.id, routed.id, filed.id, theirs.id} <= ids(
        material_service.stocked_requests_for_user(db, staff)
    )
    assert still_open.id not in ids(material_service.stocked_requests_for_user(db, staff))


# --------------------------------------------------------------------------
# The eight sites, through the real services
# --------------------------------------------------------------------------

def _stocked_after(db, request, fn):
    material_service.drain()
    fn()
    db.refresh(request)
    return request.status, material_service.drain()


def test_add_stock_stocks_the_request(db):
    from app.services import transactions as txn_service

    supervisor = _user(db, "supervisor")
    item = _item(db, quantity="0")
    request, _ = _file(db, supervisor, _work_order(db, supervisor), item)
    db.commit()

    status, facts = _stocked_after(
        db, request,
        lambda: txn_service.apply_transaction(
            db, item_id=item.id, transaction_type="stock", quantity=Decimal("6"),
            user_id=supervisor.id, work_order_number=None,
        ),
    )
    assert status == "stocked"
    assert len(facts) == 1


def test_an_upward_correction_stocks_the_request(db):
    from app.services import transactions as txn_service

    staff = _user(db, "techfm_oa")
    item = _item(db, quantity="-2")
    request, _ = _file(db, staff, _work_order(db, staff), item)
    db.commit()

    status, facts = _stocked_after(
        db, request,
        lambda: txn_service.apply_correction(
            db, item_id=item.id, new_quantity=Decimal("4"), reason="Recount", user_id=staff.id
        ),
    )
    assert status == "stocked"
    assert len(facts) == 1


def test_voiding_the_dispense_that_emptied_the_shelf_stocks_the_request(db):
    from app.services import transactions as txn_service

    supervisor = _user(db, "supervisor")
    item = _item(db, quantity="2")
    txn = txn_service.apply_transaction(
        db, item_id=item.id, transaction_type="dispense", quantity=Decimal("2"),
        user_id=supervisor.id, work_order_number=None,
    )
    request, _ = _file(db, supervisor, _work_order(db, supervisor), item)
    db.commit()

    status, facts = _stocked_after(
        db, request,
        lambda: txn_service.void_transaction(
            db, transaction_id=txn.id, user_id=supervisor.id, user_role="supervisor"
        ),
    )
    assert status == "stocked"
    assert len(facts) == 1


def test_a_mass_stage_return_stocks_the_request(db):
    from app.services.mass_staging import (
        add_item, add_work_order_to_stage, create_stage, load_item, return_item, update_stage,
    )

    supervisor = _user(db, "supervisor")
    item = _item(db, quantity="5")
    stage = create_stage(db, community="Scholars", building_name=f"B-{uuid.uuid4().hex[:6]}", created_by_id=None)
    number = f"WO-MS-{uuid.uuid4().hex[:8]}"
    wos.get_or_create_work_order(db, number=number, created_by_id=supervisor.id)
    slot = add_work_order_to_stage(db, stage.id, work_order_number=number)
    add_item(db, stage.id, slot.id, item_id=item.id, planned_quantity=Decimal("5"))
    update_stage(db, stage.id, status="loading")
    load_item(db, stage.id, item_id=item.id, quantity=Decimal("5"), user_id=supervisor.id)
    request, _ = _file(db, supervisor, _work_order(db, supervisor), item)
    db.commit()

    status, facts = _stocked_after(
        db, request,
        lambda: return_item(db, stage.id, item_id=item.id, quantity=Decimal("2")),
    )
    assert status == "stocked"
    assert len(facts) == 1


def test_removing_a_work_order_line_stocks_the_request(db):
    supervisor = _user(db, "supervisor")
    item = _item(db, quantity="3")
    consuming = _work_order(db, supervisor)
    line = wos.add_work_order_item(db, consuming.id, user=supervisor, item_id=item.id, quantity=Decimal("3"))
    request, _ = _file(db, supervisor, _work_order(db, supervisor), item)
    db.commit()

    status, facts = _stocked_after(
        db, request,
        lambda: wos.delete_work_order_item(db, consuming.id, line.id, user=supervisor),
    )
    assert status == "stocked"
    assert len(facts) == 1


def test_a_dispense_that_empties_the_shelf_sends_a_stocked_request_back_to_open(db):
    supervisor = _user(db, "supervisor")
    item = _item(db, quantity="0")
    request, _ = _file(db, supervisor, _work_order(db, supervisor), item)
    from app.services import transactions as txn_service
    txn_service.apply_transaction(
        db, item_id=item.id, transaction_type="stock", quantity=Decimal("2"),
        user_id=supervisor.id, work_order_number=None,
    )
    material_service.drain()
    consuming = _work_order(db, supervisor)

    status, facts = _stocked_after(
        db, request,
        lambda: wos.add_work_order_item(db, consuming.id, user=supervisor, item_id=item.id, quantity=Decimal("2")),
    )
    assert status == "open"
    assert facts == []


# --------------------------------------------------------------------------
# Over real HTTP
# --------------------------------------------------------------------------

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.services import push as push_service


def _client(db):
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def _as(db, user):
    return auth.create_session(db, user)


def _post(db, user, path, json=None):
    token = _as(db, user)
    try:
        with _client(db) as client:
            client.cookies.set("session", token)
            return client.post(path, json=json or {})
    finally:
        del app.dependency_overrides[get_db]


def _get(db, user, path):
    token = _as(db, user)
    try:
        with _client(db) as client:
            client.cookies.set("session", token)
            return client.get(path)
    finally:
        del app.dependency_overrides[get_db]


def test_filing_over_http_returns_the_on_hand_and_pushes_once(db, monkeypatch):
    monkeypatch.setattr(push_service, "VAPID_PRIVATE_KEY", "test-private-key")
    sent = []
    monkeypatch.setattr(
        push_service, "send_to_users",
        lambda session, ids, title, body: sent.append((title, body)) or {"sent": 1, "dropped": 0, "failed": 0},
    )
    _user(db, "techfm_oa")
    tech = _user(db)
    work_order = _work_order(db, tech, assigned_to=tech)
    item = _item(db, quantity="3")
    db.commit()

    response = _post(db, tech, "/user-requests/material-request", {
        "item_id": str(item.id), "work_order_id": str(work_order.id),
        "quantity": "2", "product_link": "https://shop.example/x", "note": "blue",
    })

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["request_type"] == "material_request"
    assert body["status"] == "open"
    assert body["item_quantity"] == "3"
    assert body["updated"] is False
    assert body["work_order_number"] == work_order.number
    assert sent == [("Material requested", f"{item.name} is needed for {work_order.number}.")]


def test_a_duplicate_filing_over_http_says_updated_and_pushes_nobody(db, monkeypatch):
    monkeypatch.setattr(push_service, "VAPID_PRIVATE_KEY", "test-private-key")
    sent = []
    monkeypatch.setattr(
        push_service, "send_to_users",
        lambda session, ids, title, body: sent.append(title) or {"sent": 1, "dropped": 0, "failed": 0},
    )
    _user(db, "techfm_oa")
    tech = _user(db)
    work_order = _work_order(db, tech, assigned_to=tech)
    item = _item(db)
    db.commit()
    payload = {"item_id": str(item.id), "work_order_id": str(work_order.id), "quantity": "1"}
    first = _post(db, tech, "/user-requests/material-request", payload)
    sent.clear()

    second = _post(db, tech, "/user-requests/material-request", {**payload, "quantity": "5"})

    assert second.status_code == 201
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["updated"] is True
    assert second.json()["details"]["quantity"] == "5"
    assert sent == []


def test_a_technician_cannot_file_against_a_work_order_they_are_not_on(db):
    tech = _user(db)
    other = _user(db)
    work_order = _work_order(db, other, assigned_to=other)
    item = _item(db)
    db.commit()

    response = _post(db, tech, "/user-requests/material-request", {
        "item_id": str(item.id), "work_order_id": str(work_order.id), "quantity": "1",
    })

    assert response.status_code == 404
    assert response.json()["detail"] == "Work order not found."
    assert work_order.number not in response.text
    assert db.query(UserRequest).filter(UserRequest.item_id == item.id).count() == 0


def test_filing_against_an_archived_work_order_is_404(db):
    tech = _user(db)
    work_order = _work_order(db, tech, assigned_to=tech)
    work_order.archived_at = datetime.now(timezone.utc)
    item = _item(db)
    db.commit()
    response = _post(db, tech, "/user-requests/material-request", {
        "item_id": str(item.id), "work_order_id": str(work_order.id), "quantity": "1",
    })
    assert response.status_code == 404


def test_filing_an_unknown_item_is_404(db):
    tech = _user(db)
    work_order = _work_order(db, tech, assigned_to=tech)
    db.commit()
    response = _post(db, tech, "/user-requests/material-request", {
        "item_id": str(uuid.uuid4()), "work_order_id": str(work_order.id), "quantity": "1",
    })
    assert response.status_code == 404
    assert response.json()["detail"] == "Item not found."


@pytest.mark.parametrize(
    "bad",
    [
        {"quantity": "0"},
        {"quantity": "-1"},
        {"product_link": "ftp://nope"},
        {"product_link": "shop.example"},
        {"note": "x" * 501},
    ],
)
def test_bad_filing_bodies_are_422(db, bad):
    tech = _user(db)
    work_order = _work_order(db, tech, assigned_to=tech)
    item = _item(db)
    db.commit()
    payload = {"item_id": str(item.id), "work_order_id": str(work_order.id), "quantity": "1", **bad}
    assert _post(db, tech, "/user-requests/material-request", payload).status_code == 422


def test_mark_stocked_over_http_pushes_the_crew(db, monkeypatch):
    monkeypatch.setattr(push_service, "VAPID_PRIVATE_KEY", "test-private-key")
    sent = []
    monkeypatch.setattr(
        push_service, "send_to_users",
        lambda session, ids, title, body: sent.append((list(ids), title)) or {"sent": 1, "dropped": 0, "failed": 0},
    )
    staff = _user(db, "techfm_oa")
    tech = _user(db)
    item = _item(db, quantity="0")
    request, _ = _file(db, tech, _work_order(db, tech, assigned_to=tech), item)
    db.commit()

    response = _post(db, staff, f"/user-requests/{request.id}/mark-stocked")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "stocked"
    assert sent == [([tech.id], "Material in stock")]
    again = _post(db, staff, f"/user-requests/{request.id}/mark-stocked")
    assert again.status_code == 409


def test_cancel_over_http_is_filer_only(db):
    tech = _user(db)
    other = _user(db)
    request, _ = _file(db, tech, _work_order(db, tech, assigned_to=tech), _item(db))
    db.commit()

    assert _post(db, other, f"/user-requests/{request.id}/cancel").status_code == 403
    mine = _post(db, tech, f"/user-requests/{request.id}/cancel")
    assert mine.status_code == 200
    assert mine.json()["resolution_note"] == "Cancelled by requester"
    assert _post(db, tech, f"/user-requests/{request.id}/cancel").status_code == 409


def test_list_filters_by_type_and_accepts_stocked(db):
    staff = _user(db, "techfm_oa")
    tech = _user(db)
    item = _item(db)
    request, _ = _file(db, tech, _work_order(db, tech), item)
    _restock(db, item)
    material_service.drain()
    db.commit()

    stocked = _get(db, staff, "/user-requests/?status=stocked&type=material_request")
    assert stocked.status_code == 200
    assert request.id.__str__() in {row["id"] for row in stocked.json()}
    assert all(row["request_type"] == "material_request" for row in stocked.json())

    other_type = _get(db, staff, "/user-requests/?status=stocked&type=inventory_recount")
    assert other_type.status_code == 200
    assert other_type.json() == []

    assert _get(db, staff, "/user-requests/?status=stocked&type=bogus").status_code == 422


def test_counts_over_http_group_open_and_stocked(db):
    staff = _user(db, "techfm_oa")
    tech = _user(db)
    item = _item(db)
    _file(db, tech, _work_order(db, tech), item)
    db.commit()

    response = _get(db, staff, "/user-requests/counts")

    assert response.status_code == 200, response.text
    assert response.json()["material_request"]["open"] >= 1


def test_patch_to_stocked_is_422(db):
    staff = _user(db, "techfm_oa")
    tech = _user(db)
    request, _ = _file(db, tech, _work_order(db, tech), _item(db))
    db.commit()
    token = _as(db, staff)
    try:
        with _client(db) as client:
            client.cookies.set("session", token)
            response = client.patch(f"/user-requests/{request.id}", json={"status": "stocked"})
    finally:
        del app.dependency_overrides[get_db]
    assert response.status_code == 422


# --------------------------------------------------------------------------
# The work-order side
# --------------------------------------------------------------------------

def test_the_work_order_requests_list_is_visibility_scoped(db):
    tech = _user(db)
    other = _user(db)
    work_order = _work_order(db, tech, assigned_to=tech)
    request, _ = _file(db, tech, work_order, _item(db))
    db.commit()

    mine = _get(db, tech, f"/work-orders/{work_order.id}/requests")
    assert mine.status_code == 200
    assert [row["id"] for row in mine.json()] == [str(request.id)]
    assert mine.json()[0]["item_quantity"] == "0"

    assert _get(db, other, f"/work-orders/{work_order.id}/requests").status_code == 404


def test_adding_from_the_stocked_line_resolves_the_request(db, monkeypatch):
    tech = _user(db)
    work_order = _work_order(db, tech, assigned_to=tech)
    item = _item(db, quantity="0")
    request, _ = _file(db, tech, work_order, item, quantity="4")
    _restock(db, item, to="10")
    material_service.drain()
    db.commit()

    response = _post(db, tech, f"/work-orders/{work_order.id}/items", {
        "item_id": str(item.id), "quantity": "3", "material_request_id": str(request.id),
    })

    assert response.status_code == 201, response.text
    db.refresh(request)
    assert request.status == "resolved"
    assert request.resolution_note == f"Added to {work_order.number}."
    assert request.details["added_quantity"] == "3"
    db.refresh(item)
    assert item.quantity == Decimal("7")


def test_adding_with_a_stale_request_id_is_409_and_adds_nothing(db):
    tech = _user(db)
    work_order = _work_order(db, tech, assigned_to=tech)
    item = _item(db, quantity="5")
    request, _ = _file(db, tech, work_order, item)  # still open, not stocked
    db.commit()

    response = _post(db, tech, f"/work-orders/{work_order.id}/items", {
        "item_id": str(item.id), "quantity": "1", "material_request_id": str(request.id),
    })

    assert response.status_code == 409
    db.refresh(item)
    assert item.quantity == Decimal("5")
    assert db.query(WorkOrderItem).filter(WorkOrderItem.work_order_id == work_order.id).count() == 0


def test_adding_without_a_request_id_is_unchanged(db):
    tech = _user(db)
    work_order = _work_order(db, tech, assigned_to=tech)
    item = _item(db, quantity="5")
    db.commit()
    response = _post(db, tech, f"/work-orders/{work_order.id}/items", {
        "item_id": str(item.id), "quantity": "1",
    })
    assert response.status_code == 201
