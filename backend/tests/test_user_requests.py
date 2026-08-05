"""Inventory recount requests and Technician scan-removal permissions."""

import os
import sys
import uuid
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from app.domain.errors import RoleManagementError
from app.models import Item, User, UserRequest, WorkOrderItem
from app.services import auth
from app.services import items as item_service
from app.services import user_requests as request_service
from app.services import work_orders as wos
from app.services.transactions import apply_transaction, void_transaction


def _user(db, role):
    user = User(
        username=f"request-{uuid.uuid4().hex[:10]}",
        first_name="Test",
        last_name=role.title(),
        password_hash=auth.hash_password("hunter2"),
        role=role,
    )
    db.add(user)
    db.flush()
    return user


def _item(db, quantity="0", price="1.00", product_link=None):
    item = Item(
        barcode=f"REQ-{uuid.uuid4().hex[:10]}",
        name="Recount Item",
        quantity=Decimal(quantity),
        location="Shelf R",
        price=None if price is None else Decimal(price),
        product_link=product_link,
    )
    db.add(item)
    db.flush()
    return item


def _assigned_work_order(db, supervisor, technician):
    work_order = wos.get_or_create_work_order(
        db,
        number=f"WO-REQ-{uuid.uuid4().hex[:8]}",
        created_by_id=supervisor.id,
    )
    return wos.update_work_order(
        db,
        work_order.id,
        user=supervisor,
        fields={"assigned_to_ids": [technician.id]},
    )


def test_short_scan_is_recorded_and_creates_open_recount_request(db):
    supervisor = _user(db, "supervisor")
    technician = _user(db, "technician")
    item = _item(db, "0")
    work_order = _assigned_work_order(db, supervisor, technician)

    transaction = apply_transaction(
        db,
        item_id=item.id,
        transaction_type="dispense",
        quantity=Decimal("3"),
        user_id=technician.id,
        work_order_number=work_order.number,
        work_order_id=work_order.id,
    )

    db.refresh(item)
    db.refresh(work_order)
    request = (
        db.query(UserRequest)
        .filter(UserRequest.transaction_id == transaction.id)
        .one()
    )
    line = (
        db.query(WorkOrderItem)
        .filter(
            WorkOrderItem.work_order_id == work_order.id,
            WorkOrderItem.item_id == item.id,
        )
        .one()
    )

    assert transaction.recount_required is True
    assert transaction.item_quantity == Decimal("-3")
    assert item.quantity == Decimal("-3")
    assert line.quantity == Decimal("3")
    assert work_order.status == "in_progress"
    assert request.status == "open"
    assert request.request_type == "inventory_recount"
    assert request.message == "Please re-count stock"
    assert request.details == {
        "recorded_quantity_before": "0",
        "dispensed_quantity": "3",
        "shortage_quantity": "3",
        "work_order_number": work_order.number,
    }


def test_technician_can_remove_own_scan_and_request_is_resolved(db):
    supervisor = _user(db, "supervisor")
    technician = _user(db, "technician")
    item = _item(db, "1")
    work_order = _assigned_work_order(db, supervisor, technician)
    transaction = apply_transaction(
        db,
        item_id=item.id,
        transaction_type="dispense",
        quantity=Decimal("2"),
        user_id=technician.id,
        work_order_number=work_order.number,
        work_order_id=work_order.id,
    )

    void_transaction(
        db,
        transaction_id=transaction.id,
        user_id=technician.id,
        user_role="technician",
    )

    db.refresh(item)
    request = (
        db.query(UserRequest)
        .filter(UserRequest.transaction_id == transaction.id)
        .one()
    )
    assert item.quantity == Decimal("1")
    assert request.status == "resolved"
    assert request.resolved_by_id == technician.id
    assert request.resolution_note == "Source transaction removed."
    assert (
        db.query(WorkOrderItem)
        .filter(WorkOrderItem.work_order_id == work_order.id)
        .count()
        == 0
    )


def test_technician_cannot_remove_someone_elses_scan(db):
    supervisor = _user(db, "supervisor")
    technician = _user(db, "technician")
    item = _item(db, "5")
    work_order = _assigned_work_order(db, supervisor, technician)
    transaction = apply_transaction(
        db,
        item_id=item.id,
        transaction_type="dispense",
        quantity=Decimal("1"),
        user_id=supervisor.id,
        work_order_number=work_order.number,
        work_order_id=work_order.id,
    )

    with pytest.raises(RoleManagementError):
        void_transaction(
            db,
            transaction_id=transaction.id,
            user_id=technician.id,
            user_role="technician",
        )


def test_admin_can_resolve_and_reopen_request(db):
    admin = _user(db, "admin")
    supervisor = _user(db, "supervisor")
    technician = _user(db, "technician")
    item = _item(db, "0")
    work_order = _assigned_work_order(db, supervisor, technician)
    transaction = apply_transaction(
        db,
        item_id=item.id,
        transaction_type="dispense",
        quantity=Decimal("1"),
        user_id=technician.id,
        work_order_number=work_order.number,
        work_order_id=work_order.id,
    )
    request = (
        db.query(UserRequest)
        .filter(UserRequest.transaction_id == transaction.id)
        .one()
    )
    assert request.transaction_id == transaction.id

    resolved = request_service.update_user_request(
        db,
        request.id,
        status="resolved",
        resolution_note="Count corrected.",
        resolved_by_id=admin.id,
    )
    assert resolved.status == "resolved"
    assert resolved.resolution_note == "Count corrected."
    assert resolved.resolved_by_id == admin.id

    reopened = request_service.update_user_request(
        db,
        request.id,
        status="open",
        resolution_note=None,
        resolved_by_id=admin.id,
    )
    assert reopened.status == "open"
    assert reopened.resolved_at is None
    assert reopened.resolved_by_id is None


def test_unpriced_work_order_item_creates_one_request_and_collects_work_orders(db):
    supervisor = _user(db, "supervisor")
    technician = _user(db, "technician")
    item = _item(db, "10", price=None)
    first = _assigned_work_order(db, supervisor, technician)
    second = _assigned_work_order(db, supervisor, technician)

    for work_order in (first, first, second):
        apply_transaction(
            db,
            item_id=item.id,
            transaction_type="dispense",
            quantity=Decimal("1"),
            user_id=technician.id,
            work_order_number=work_order.number,
            work_order_id=work_order.id,
        )

    requests = (
        db.query(UserRequest)
        .filter(
            UserRequest.request_type == "missing_item_price",
            UserRequest.status == "open",
            UserRequest.item_id == item.id,
        )
        .all()
    )
    assert len(requests) == 1
    request = requests[0]
    assert request.transaction_id is None
    assert request.message == "Please add a price and product link to this item"
    assert set(request.details["work_order_numbers"]) == {first.number, second.number}


def test_missing_price_request_dedupes_before_one_transaction_flush(db):
    supervisor = _user(db, "supervisor")
    technician = _user(db, "technician")
    item = _item(db, "10", price=None)
    first = _assigned_work_order(db, supervisor, technician)
    second = _assigned_work_order(db, supervisor, technician)

    first_request = request_service.create_or_update_missing_price_request(
        db,
        item_id=item.id,
        work_order_id=first.id,
        work_order_number=first.number,
        created_by_id=technician.id,
    )
    second_request = request_service.create_or_update_missing_price_request(
        db,
        item_id=item.id,
        work_order_id=second.id,
        work_order_number=second.number,
        created_by_id=technician.id,
    )

    assert second_request is first_request
    assert set(first_request.details["work_order_numbers"]) == {
        first.number,
        second.number,
    }


def test_adding_item_price_and_link_auto_resolves_missing_price_request(db):
    admin = _user(db, "admin")
    supervisor = _user(db, "supervisor")
    technician = _user(db, "technician")
    item = _item(db, "5", price=None)
    work_order = _assigned_work_order(db, supervisor, technician)
    apply_transaction(
        db,
        item_id=item.id,
        transaction_type="dispense",
        quantity=Decimal("1"),
        user_id=technician.id,
        work_order_number=work_order.number,
        work_order_id=work_order.id,
    )
    request = (
        db.query(UserRequest)
        .filter(
            UserRequest.request_type == "missing_item_price",
            UserRequest.item_id == item.id,
        )
        .one()
    )

    item_service.update_item(
        db,
        item.id,
        price=Decimal("12.34"),
        performed_by_id=admin.id,
    )

    db.refresh(request)
    assert request.status == "open"

    item_service.update_item(
        db,
        item.id,
        product_link="https://example.com/recount-item",
        performed_by_id=admin.id,
    )

    db.refresh(request)
    assert request.status == "resolved"
    assert request.resolved_by_id == admin.id
    assert request.resolution_note == "Item price and product link added."
    assert not any(
        candidate.item_id == item.id
        and candidate.request_type == "missing_item_price"
        for candidate in request_service.list_user_requests(db, status="open")
    )
    assert db.get(Item, item.id).price == Decimal("12.34")
    assert db.get(Item, item.id).product_link == "https://example.com/recount-item"


def test_short_unpriced_scan_can_raise_both_request_types(db):
    supervisor = _user(db, "supervisor")
    technician = _user(db, "technician")
    item = _item(db, "0", price=None)
    work_order = _assigned_work_order(db, supervisor, technician)

    apply_transaction(
        db,
        item_id=item.id,
        transaction_type="dispense",
        quantity=Decimal("1"),
        user_id=technician.id,
        work_order_number=work_order.number,
        work_order_id=work_order.id,
    )

    assert {
        request.request_type
        for request in request_service.list_user_requests(db)
        if request.item_id == item.id
    } == {"inventory_recount", "missing_item_price"}


def test_zero_price_is_missing_until_a_positive_price_is_saved(db):
    admin = _user(db, "admin")
    supervisor = _user(db, "supervisor")
    technician = _user(db, "technician")
    item = _item(
        db,
        "5",
        price="0.00",
        product_link="https://example.com/zero-price-item",
    )
    work_order = _assigned_work_order(db, supervisor, technician)
    apply_transaction(
        db,
        item_id=item.id,
        transaction_type="dispense",
        quantity=Decimal("1"),
        user_id=technician.id,
        work_order_number=work_order.number,
        work_order_id=work_order.id,
    )
    request = (
        db.query(UserRequest)
        .filter(
            UserRequest.request_type == "missing_item_price",
            UserRequest.item_id == item.id,
        )
        .one()
    )

    item_service.update_item(
        db,
        item.id,
        price=Decimal("0.00"),
        performed_by_id=admin.id,
    )
    db.refresh(request)
    assert request.status == "open"

    item_service.update_item(
        db,
        item.id,
        price=Decimal("0.01"),
        performed_by_id=admin.id,
    )
    db.refresh(request)
    assert request.status == "resolved"
