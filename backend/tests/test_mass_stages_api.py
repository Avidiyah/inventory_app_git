"""Tests for the mass-staging (truck planning) API.

Pure, no DB. Covers request-schema validation, the Supervisor+ gate on every
route, and the response builders (`_stage_summary` counts, `_stage_detail`
nesting of slots + flattening the joined item/work order).
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
    StageItemCreate,
    StageItemUpdate,
    StageWorkOrderCreate,
)


# --- request-schema validation ----------------------------------------

def test_stage_create_trims_and_requires_fields():
    c = MassStageCreate(community="  Scholars ", building_name="  19 ")
    assert c.community == "Scholars"
    assert c.building_name == "19"
    with pytest.raises(ValidationError):
        MassStageCreate(community="Scholars", building_name="   ")
    with pytest.raises(ValidationError):
        MassStageCreate(community="   ", building_name="19")


def test_stage_update_requires_a_field():
    assert MassStageUpdate(status="loading").status == "loading"
    with pytest.raises(ValidationError):
        MassStageUpdate()


def test_stage_work_order_create_requires_number_unit_optional():
    sw = StageWorkOrderCreate(work_order_number="WO-7")
    assert sw.work_order_number == "WO-7"
    assert sw.unit_number is None
    StageWorkOrderCreate(work_order_number="WO-7", unit_number="1101")
    with pytest.raises(ValidationError):
        StageWorkOrderCreate(work_order_number="  ")


def test_planned_quantity_must_be_positive():
    StageItemCreate(item_id=uuid.uuid4(), planned_quantity=Decimal("3"))
    with pytest.raises(ValidationError):
        StageItemCreate(item_id=uuid.uuid4(), planned_quantity=Decimal("0"))
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
        "add_work_order",
        "delete_work_order",
        "add_item",
        "update_item",
        "delete_item",
        "load_item",
        "return_item",
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


def _fake_slot(number, unit, sort_order, items, status="in_progress", assignee_name=None):
    work_order = SimpleNamespace(
        number=number,
        unit_number=unit,
        status=status,
        assigned_to_id=None,
        assignee=SimpleNamespace(username=assignee_name) if assignee_name else None,
    )
    return SimpleNamespace(
        id=uuid.uuid4(),
        work_order_id=uuid.uuid4(),
        sort_order=sort_order,
        items=items,
        work_order=work_order,
    )


def _fake_stage(slots, status="planning"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        community="Scholars",
        building_name="Tower A 3",
        status=status,
        created_at=datetime.now(timezone.utc),
        work_order_slots=slots,
    )


def test_stage_detail_nests_slots_and_flattens_item():
    item_id = uuid.uuid4()
    stage = _fake_stage(
        [_fake_slot("WO-1", "1101", 0, [_fake_stage_item(item_id, "Spray Paint", "012345678905", "10")])]
    )
    detail = _stage_detail(stage)
    assert detail.community == "Scholars"
    assert detail.building_name == "Tower A 3"
    assert len(detail.work_orders) == 1
    slot = detail.work_orders[0]
    assert slot.work_order_number == "WO-1"
    assert slot.unit_number == "1101"
    assert slot.status == "in_progress"
    item = slot.items[0]
    assert item.item_name == "Spray Paint"
    assert item.item_quantity == Decimal("100")


def test_merged_items_carry_on_hand_and_overflow():
    item_id = uuid.uuid4()
    stage = _fake_stage(
        [
            _fake_slot("WO-1", "1101", 0, [_fake_stage_item(item_id, "Paint", "AAA", "10", loaded="10", on_hand="4")]),
            _fake_slot("WO-2", "1102", 1, [_fake_stage_item(item_id, "Paint", "AAA", "5", loaded="6", on_hand="4")]),
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


def test_stage_summary_counts_units_and_distinct_items():
    shared = uuid.uuid4()
    other = uuid.uuid4()
    stage = _fake_stage(
        [
            _fake_slot("WO-1", "1101", 0, [_fake_stage_item(shared, "Spray Paint", "AAA", "10")]),
            _fake_slot(
                "WO-2",
                "1102",
                1,
                [
                    _fake_stage_item(shared, "Spray Paint", "AAA", "5"),
                    _fake_stage_item(other, "Caulk", "BBB", "2"),
                ],
            ),
        ]
    )
    summary = _stage_summary(stage)
    assert summary.unit_count == 2
    assert summary.item_count == 2
