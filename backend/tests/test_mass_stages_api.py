"""Tests for the mass-staging planning API.

Pure, no DB -- consistent with the rest of this suite. The DB-bound behaviours
(one-active-per-building, cascades, status guards, upsert) are exercised by the
rolled-back verification script and by the Phase-5 integration harness. What is
unit-testable lives here:

- request-schema validation (non-blank strings, positive planned quantity,
  at-least-one-field updates),
- the Supervisor+ gate on every route,
- the response builders (`_stage_summary` counts, `_stage_detail` nesting +
  flattening the joined item into item_name/item_barcode).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.routing import APIRoute
from pydantic import ValidationError

from app.domain import roles
from app.routers import mass_stages as ms_router
from app.routers.mass_stages import _merged_items, _stage_detail, _stage_summary
from app.schemas.mass_stages import (
    MassStageCreate,
    MassStageUpdate,
    RoomCreate,
    RoomUpdate,
    StageItemCreate,
    StageItemUpdate,
)


# --- request-schema validation ----------------------------------------

def test_building_name_trimmed_and_required():
    assert MassStageCreate(building_name="  Tower A 3 ").building_name == "Tower A 3"
    with pytest.raises(ValidationError):
        MassStageCreate(building_name="   ")


def test_stage_update_requires_a_field():
    assert MassStageUpdate(status="loading").status == "loading"
    with pytest.raises(ValidationError):
        MassStageUpdate()


def test_room_create_requires_both_fields():
    RoomCreate(room_number="101", work_order_number="WO-7")
    with pytest.raises(ValidationError):
        RoomCreate(room_number="  ", work_order_number="WO-7")
    with pytest.raises(ValidationError):
        RoomCreate(room_number="101", work_order_number="")


def test_room_update_requires_a_field():
    assert RoomUpdate(room_number="102").room_number == "102"
    with pytest.raises(ValidationError):
        RoomUpdate()


def test_planned_quantity_must_be_positive():
    StageItemCreate(item_id=uuid.uuid4(), planned_quantity=Decimal("3"))
    with pytest.raises(ValidationError):
        StageItemCreate(item_id=uuid.uuid4(), planned_quantity=Decimal("0"))
    with pytest.raises(ValidationError):
        StageItemCreate(item_id=uuid.uuid4(), planned_quantity=Decimal("-1"))
    with pytest.raises(ValidationError):
        StageItemUpdate(planned_quantity=Decimal("0"))


# --- route gate (every route is Supervisor+) --------------------------

def _route(router, endpoint_name):
    for route in router.router.routes:
        if isinstance(route, APIRoute) and route.endpoint.__name__ == endpoint_name:
            return route
    raise AssertionError(f"route {endpoint_name!r} not found")


def _find_min_role(dependant):
    for sub in dependant.dependencies:
        call = getattr(sub, "call", None)
        closure = getattr(call, "__closure__", None) or ()
        freevars = call.__code__.co_freevars if call is not None else ()
        for name, cell in zip(freevars, closure):
            if name == "minimum" and isinstance(cell.cell_contents, str):
                return cell.cell_contents
        found = _find_min_role(sub)
        if found is not None:
            return found
    return None


@pytest.mark.parametrize(
    "endpoint_name",
    [
        "create_stage",
        "list_stages",
        "get_stage",
        "update_stage",
        "delete_stage",
        "reuse_stage",
        "quick_room",
        "list_active_rooms",
        "add_room",
        "update_room",
        "delete_room",
        "add_item",
        "update_item",
        "delete_item",
    ],
)
def test_every_route_requires_supervisor(endpoint_name):
    route = _route(ms_router, endpoint_name)
    assert _find_min_role(route.dependant) == roles.ROLE_SUPERVISOR


# --- response builders ------------------------------------------------

def _fake_stage_item(item_id, name, barcode, planned, loaded="0", returned="0", on_hand="100"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        item_id=item_id,
        item=SimpleNamespace(name=name, barcode=barcode, quantity=Decimal(on_hand)),
        planned_quantity=Decimal(planned),
        loaded_quantity=Decimal(loaded),
        returned_quantity=Decimal(returned),
    )


def _fake_room(number, wo, sort_order, items):
    return SimpleNamespace(
        id=uuid.uuid4(),
        room_number=number,
        work_order_number=wo,
        sort_order=sort_order,
        items=items,
    )


def _fake_stage(rooms, status="planning"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        building_name="Tower A 3",
        status=status,
        created_at=datetime.now(timezone.utc),
        rooms=rooms,
    )


def test_stage_detail_nests_rooms_and_flattens_item():
    item_id = uuid.uuid4()
    stage = _fake_stage(
        [_fake_room("101", "WO-1", 0, [_fake_stage_item(item_id, "Spray Paint", "012345678905", "10")])]
    )
    detail = _stage_detail(stage)
    assert detail.building_name == "Tower A 3"
    assert len(detail.rooms) == 1
    item = detail.rooms[0].items[0]
    assert item.item_name == "Spray Paint"
    assert item.item_barcode == "012345678905"
    assert item.item_quantity == Decimal("100")  # on-hand surfaced
    assert item.planned_quantity == Decimal("10")
    assert item.loaded_quantity == Decimal("0")


def test_merged_items_carry_on_hand_and_overflow():
    item_id = uuid.uuid4()
    # planned 10 + 5 = 15, loaded 16 (overflow 1), on-hand 4.
    stage = _fake_stage(
        [
            _fake_room("101", "WO-1", 0, [_fake_stage_item(item_id, "Paint", "AAA", "10", loaded="10", on_hand="4")]),
            _fake_room("102", "WO-2", 1, [_fake_stage_item(item_id, "Paint", "AAA", "5", loaded="6", on_hand="4")]),
        ],
        status="loading",
    )
    merged = _merged_items(stage)
    assert len(merged) == 1
    m = merged[0]
    assert m.on_hand == Decimal("4")
    assert m.planned_total == Decimal("15")
    assert m.loaded_total == Decimal("16")
    assert m.overflow == Decimal("1")


def test_stage_summary_counts_rooms_and_distinct_items():
    shared = uuid.uuid4()  # same item planned in two rooms
    other = uuid.uuid4()
    stage = _fake_stage(
        [
            _fake_room("101", "WO-1", 0, [_fake_stage_item(shared, "Spray Paint", "AAA", "10")]),
            _fake_room(
                "102",
                "WO-2",
                1,
                [
                    _fake_stage_item(shared, "Spray Paint", "AAA", "5"),
                    _fake_stage_item(other, "Caulk", "BBB", "2"),
                ],
            ),
        ]
    )
    summary = _stage_summary(stage)
    assert summary.room_count == 2
    assert summary.item_count == 2  # distinct: {shared, other}
