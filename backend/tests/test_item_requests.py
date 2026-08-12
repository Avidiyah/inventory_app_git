"""Item Requests: material the app has no catalogue row for at all.

Distinct from `inventory_recount`, which covers an in-app item whose recorded
count is wrong. `list_items` filters on `archived_at` only and never on
quantity, so an item at zero is still findable -- an item request is raised
precisely when a search returns nothing because nothing exists to return.
"""

import os
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from app.domain.errors import ItemRequestStateError
from app.models import Item, User, UserRequest, WorkOrderItem
from app.services import auth
from app.services import user_requests as request_service
from app.services import work_orders as wos


def _user(db, role="technician"):
    user = User(
        username=f"ireq-{uuid.uuid4().hex[:10]}",
        first_name="Test",
        last_name=role.title(),
        password_hash=auth.hash_password("hunter2"),
        role=role,
    )
    db.add(user)
    db.flush()
    return user


def _work_order(db, creator):
    return wos.get_or_create_work_order(
        db, number=f"WO-IR-{uuid.uuid4().hex[:8]}", created_by_id=creator.id
    )


def _file(db, tech, text, work_order=None, quantity="1", note=None):
    request = request_service.create_item_request(
        db,
        searched_text=text,
        quantity=Decimal(quantity),
        note=note,
        work_order_id=work_order.id if work_order else None,
        work_order_number=work_order.number if work_order else None,
        source="work_orders" if work_order else "find_item",
        created_by_id=tech.id,
    )
    db.flush()
    return request


def _catalogue_item(db, name="3/4 Copper Elbow, Sweat"):
    item = Item(
        barcode=f"IR-{uuid.uuid4().hex[:10]}",
        name=name,
        quantity=Decimal("0"),
        location="Shelf C",
        price=Decimal("3.50"),
        product_link="https://example.com/elbow",
    )
    db.add(item)
    db.flush()
    return item


# --------------------------------------------------------------------------
# Filing
# --------------------------------------------------------------------------

def test_filing_an_item_request_stores_the_search_text_and_work_order(db):
    tech = _user(db)
    work_order = _work_order(db, tech)

    request = request_service.create_item_request(
        db,
        searched_text="  3/4 copper elbow  ",
        quantity=Decimal("2"),
        note="  sweat not press  ",
        work_order_id=work_order.id,
        work_order_number=work_order.number,
        source="work_orders",
        created_by_id=tech.id,
    )
    db.flush()

    assert request.request_type == "item_request"
    assert request.status == "open"
    assert request.item_id is None
    assert request.transaction_id is None
    assert request.work_order_id == work_order.id
    assert request.details["searched_text"] == "3/4 copper elbow"
    assert request.details["note"] == "sweat not press"
    assert request.details["quantity"] == "2"
    assert request.details["source"] == "work_orders"
    assert request.details["work_order_number"] == work_order.number


def test_item_request_from_find_item_has_no_work_order(db):
    tech = _user(db)

    request = _file(db, tech, "grommet 1in")

    assert request.work_order_id is None
    assert request.details["note"] is None
    assert request.details["source"] == "find_item"


# --------------------------------------------------------------------------
# Sibling matching
# --------------------------------------------------------------------------

def test_siblings_match_on_token_set_regardless_of_word_order(db):
    tech = _user(db)
    first = _file(db, tech, "3/4 copper elbow", _work_order(db, tech))
    second = _file(db, tech, "copper elbow 3/4", _work_order(db, tech))

    siblings = request_service.find_sibling_item_requests(db, first)

    assert [s.id for s in siblings] == [second.id]


def test_siblings_do_not_match_a_superset_of_tokens(db):
    tech = _user(db)
    first = _file(db, tech, "copper elbow", _work_order(db, tech))
    _file(db, tech, "copper elbow press", _work_order(db, tech))

    assert request_service.find_sibling_item_requests(db, first) == []


def test_siblings_exclude_resolved_rows(db):
    tech = _user(db)
    first = _file(db, tech, "copper elbow", _work_order(db, tech))
    other = _file(db, tech, "copper elbow", _work_order(db, tech))
    other.status = "resolved"
    db.flush()

    assert request_service.find_sibling_item_requests(db, first) == []


# --------------------------------------------------------------------------
# Fulfilment
# --------------------------------------------------------------------------

def test_fulfilment_links_the_item_and_adds_it_retroactively(db):
    admin = _user(db, "admin")
    tech = _user(db)
    work_order = _work_order(db, tech)
    request = _file(db, tech, "3/4 copper elbow", work_order, quantity="2")
    item = _catalogue_item(db)

    fulfilled, skipped = request_service.fulfill_item_request(
        db, request.id, item_id=item.id, sibling_ids=[], resolved_by_id=admin.id
    )

    line = (
        db.query(WorkOrderItem)
        .filter(
            WorkOrderItem.work_order_id == work_order.id,
            WorkOrderItem.item_id == item.id,
        )
        .one()
    )
    db.refresh(item)

    assert fulfilled.status == "resolved"
    assert fulfilled.item_id == item.id
    assert fulfilled.resolved_by_id == admin.id
    assert skipped == []
    assert line.quantity == Decimal("2")
    assert line.mode == "retroactive"
    # Fulfilment records material already consumed; it must never move stock.
    assert item.quantity == Decimal("0")


def test_fulfilment_cascades_to_confirmed_siblings(db):
    admin = _user(db, "admin")
    tech = _user(db)
    first_wo = _work_order(db, tech)
    second_wo = _work_order(db, tech)
    first = _file(db, tech, "3/4 copper elbow", first_wo, quantity="2")
    second = _file(db, tech, "copper elbow 3/4", second_wo, quantity="5")
    item = _catalogue_item(db)

    fulfilled, skipped = request_service.fulfill_item_request(
        db,
        first.id,
        item_id=item.id,
        sibling_ids=[second.id],
        resolved_by_id=admin.id,
    )
    db.refresh(second)

    second_line = (
        db.query(WorkOrderItem)
        .filter(WorkOrderItem.work_order_id == second_wo.id)
        .one()
    )

    assert fulfilled.status == "resolved"
    assert second.status == "resolved"
    assert second.item_id == item.id
    assert second_line.quantity == Decimal("5")
    assert second_line.mode == "retroactive"
    assert skipped == []


def test_a_closed_work_order_is_skipped_but_the_request_still_resolves(db):
    admin = _user(db, "admin")
    tech = _user(db)
    work_order = _work_order(db, tech)
    request = _file(db, tech, "3/4 copper elbow", work_order, quantity="2")
    item = _catalogue_item(db)
    work_order.archived_at = datetime.now(timezone.utc)
    db.flush()

    fulfilled, skipped = request_service.fulfill_item_request(
        db, request.id, item_id=item.id, sibling_ids=[], resolved_by_id=admin.id
    )

    assert fulfilled.status == "resolved"
    assert fulfilled.item_id == item.id
    assert len(skipped) == 1
    assert work_order.number in skipped[0]
    assert (
        db.query(WorkOrderItem)
        .filter(WorkOrderItem.work_order_id == work_order.id)
        .count()
        == 0
    )


def test_a_find_item_request_resolves_with_no_work_order_to_add_to(db):
    admin = _user(db, "admin")
    tech = _user(db)
    request = _file(db, tech, "grommet 1in")
    item = _catalogue_item(db, name="1 in Grommet")

    fulfilled, skipped = request_service.fulfill_item_request(
        db, request.id, item_id=item.id, sibling_ids=[], resolved_by_id=admin.id
    )

    assert fulfilled.status == "resolved"
    assert fulfilled.item_id == item.id
    assert skipped == []


def test_an_already_resolved_request_cannot_be_fulfilled_twice(db):
    admin = _user(db, "admin")
    tech = _user(db)
    request = _file(db, tech, "grommet 1in")
    item = _catalogue_item(db, name="1 in Grommet")

    request_service.fulfill_item_request(
        db, request.id, item_id=item.id, sibling_ids=[], resolved_by_id=admin.id
    )

    with pytest.raises(ItemRequestStateError):
        request_service.fulfill_item_request(
            db, request.id, item_id=item.id, sibling_ids=[], resolved_by_id=admin.id
        )
