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
from app.models import Item, User, UserRequest, WorkOrderTechnician
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
