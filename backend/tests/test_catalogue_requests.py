"""Catalogue Requests: material the app has no catalogue row for at all.

Distinct from `inventory_recount`, which covers an in-app item whose recorded
count is wrong. `list_items` filters on `archived_at` only and never on
quantity, so an item at zero is still findable -- a catalogue request is raised
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
    request = request_service.create_catalogue_request(
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

def test_filing_a_catalogue_request_stores_the_search_text_and_work_order(db):
    tech = _user(db)
    work_order = _work_order(db, tech)

    request = request_service.create_catalogue_request(
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

    assert request.request_type == "catalogue_request"
    assert request.status == "open"
    assert request.item_id is None
    assert request.transaction_id is None
    assert request.work_order_id == work_order.id
    assert request.details["searched_text"] == "3/4 copper elbow"
    assert request.details["note"] == "sweat not press"
    assert request.details["quantity"] == "2"
    assert request.details["source"] == "work_orders"
    assert request.details["work_order_number"] == work_order.number


def test_catalogue_request_from_find_item_has_no_work_order(db):
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

    siblings = request_service.find_sibling_catalogue_requests(db, first)

    assert [s.id for s in siblings] == [second.id]


def test_siblings_do_not_match_a_superset_of_tokens(db):
    tech = _user(db)
    first = _file(db, tech, "copper elbow", _work_order(db, tech))
    _file(db, tech, "copper elbow press", _work_order(db, tech))

    assert request_service.find_sibling_catalogue_requests(db, first) == []


def test_siblings_exclude_resolved_rows(db):
    tech = _user(db)
    first = _file(db, tech, "copper elbow", _work_order(db, tech))
    other = _file(db, tech, "copper elbow", _work_order(db, tech))
    other.status = "resolved"
    db.flush()

    assert request_service.find_sibling_catalogue_requests(db, first) == []


# --------------------------------------------------------------------------
# Fulfilment
# --------------------------------------------------------------------------

def test_fulfilment_links_the_item_and_adds_it_retroactively(db):
    admin = _user(db, "admin")
    tech = _user(db)
    work_order = _work_order(db, tech)
    request = _file(db, tech, "3/4 copper elbow", work_order, quantity="2")
    item = _catalogue_item(db)

    fulfilled, skipped = request_service.fulfill_catalogue_request(
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

    fulfilled, skipped = request_service.fulfill_catalogue_request(
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

    fulfilled, skipped = request_service.fulfill_catalogue_request(
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


def test_a_find_item_catalogue_request_resolves_with_no_work_order_to_add_to(db):
    admin = _user(db, "admin")
    tech = _user(db)
    request = _file(db, tech, "grommet 1in")
    item = _catalogue_item(db, name="1 in Grommet")

    fulfilled, skipped = request_service.fulfill_catalogue_request(
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

    request_service.fulfill_catalogue_request(
        db, request.id, item_id=item.id, sibling_ids=[], resolved_by_id=admin.id
    )

    with pytest.raises(ItemRequestStateError):
        request_service.fulfill_catalogue_request(
            db, request.id, item_id=item.id, sibling_ids=[], resolved_by_id=admin.id
        )


# --------------------------------------------------------------------------
# The rename
# --------------------------------------------------------------------------

def test_the_type_key_is_catalogue_request():
    assert request_service.REQUEST_CATALOGUE == "catalogue_request"
    assert not hasattr(request_service, "REQUEST_ITEM")


def test_the_migration_rewrites_old_rows_both_ways(db):
    """The revision's upgrade/downgrade are plain UPDATEs, so they can be run
    against the fixture's savepoint connection through the module's own
    `op` proxy. Round-trip proves downgrade really reverses upgrade."""
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text

    tech = _user(db)
    row = UserRequest(
        request_type="item_request",
        status="open",
        message="legacy",
        created_by_id=tech.id,
        details={},
    )
    db.add(row)
    db.flush()

    path = (
        Path(__file__).resolve().parents[1]
        / "alembic" / "versions"
        / "d1e3f5a7b9c2_rename_item_request_to_catalogue_request.py"
    )
    spec = importlib.util.spec_from_file_location("rename_rev", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    ctx = MigrationContext.configure(db.connection())
    with Operations.context(ctx):
        module.upgrade()
    assert db.execute(
        text("SELECT request_type FROM user_requests WHERE id = :id"), {"id": row.id}
    ).scalar() == "catalogue_request"

    with Operations.context(ctx):
        module.downgrade()
    assert db.execute(
        text("SELECT request_type FROM user_requests WHERE id = :id"), {"id": row.id}
    ).scalar() == "item_request"


# --------------------------------------------------------------------------
# UI contract pins (no JS harness; same approach as test_work_orders_router)
# --------------------------------------------------------------------------

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[1] / "static"


def _src(rel):
    return (_STATIC / rel).read_text(encoding="utf-8")


def test_api_client_has_the_material_request_wrappers():
    api = _src("api.js")
    assert 'jsonRequest("/user-requests/material-request", "POST"' in api
    assert "/user-requests/counts" in api
    assert "/mark-stocked`" in api
    assert "/cancel`" in api
    assert "/requests`" in api
    assert "material_request_id: materialRequestId" in api
    assert 'params.set("type", type)' in api


def test_the_user_requests_page_has_four_type_tabs_with_counts():
    html = _src("pages/user-requests.html")
    assert 'id="user-requests-tabs"' in html
    assert 'role="tablist"' in html
    for key in ("material_request", "catalogue_request", "inventory_recount", "missing_item_price"):
        assert f'data-request-type="{key}"' in html
    assert 'id="user-requests-type"' not in html  # the dropdown is gone
    assert "user-requests-tab-count" in html


def test_the_material_card_offers_the_manual_fire_and_the_stocked_status():
    cards = _src("views/userRequestCards.js")
    assert "Mark stocked &amp; notify" in cards
    assert 'class="user-request-stock"' in cards
    assert 'if (status === "stocked") return "Stocked"' in cards
    assert 'if (type === "material_request") return "Material request"' in cards
    assert "user-request-edit-link" in cards
    controller = _src("views/userRequests.js")
    assert "apiMarkRequestStocked" in controller
    assert "apiListUserRequestCounts" in controller
    assert 'subscribe("user_request.changed"' in controller or "USER_REQUEST_CHANGED_EVENT" in controller
    tips = _src("tips.js")
    assert '"requests.stocked"' in tips


def test_the_work_order_card_mounts_the_request_section_and_stocked_lines():
    wo = _src("views/workOrders.js")
    assert "wo-request-section" in wo
    assert '".wo-edit-card, .wo-notes-section, .wo-materials-section, .wo-labor-section, .wo-request-section"' in wo
    assert 'class="wo-requested-lines"' in wo
    assert "mountWorkOrderRequests(" in wo
    assert "materialRequestId: container.dataset.materialRequestId || null" in wo
    module = _src("views/workOrderRequests.js")
    assert "apiListWorkOrderRequests" in module
    assert "apiCreateMaterialRequest" in module
    assert "apiCancelMaterialRequest" in module
    assert "Add requested material" in module
    assert "Request sent. Staff have been notified." in module
    assert "Updated your earlier request." in module
    assert "Staff will verify the count" in module
    assert 'source: "request_card"' in module
    assert '"user_request.changed"' in module
    assert 'import "./views/workOrderRequests.js";' in _src("main.js")
    assert '"request_card"' in _src("views/catalogueRequest.js")
