"""Work-order responses expose human names for operational displays."""

import os
import sys
from types import SimpleNamespace
from uuid import uuid4

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.routers.work_orders import _card, _detail


def test_card_exposes_full_names_without_login_usernames():
    assignee_id = uuid4()
    supervisor_id = uuid4()
    work_order = SimpleNamespace(
        id=uuid4(),
        number="WO-123",
        community=None,
        building_number=None,
        unit_number=None,
        description=None,
        priority=None,
        notes="Resident requested an afternoon visit.",
        status="in_progress",
        entry_mode="dispense",
        created_by_id=None,
        assigned_to_id=assignee_id,
        assignee=SimpleNamespace(username="tech-login", full_name="Jamie Rivera"),
        items=[],
        location="Commons",
        output_to="Belfor",
        vendor_assignee="Alex Morgan (Belfor)",
        service_type="SMR27",
        schedule_date="8/2/2026",
        supervisor_id=supervisor_id,
        supervisor=SimpleNamespace(username="super-login", full_name="Alex Morgan"),
        legacy=False,
    )

    response = _card(work_order)

    assert response.assigned_to_name == "Jamie Rivera"
    assert response.assigned_to_ids == [assignee_id]
    assert response.assigned_to_names == ["Jamie Rivera"]
    assert response.supervisor_name == "Alex Morgan"
    assert response.priority is None
    assert "assigned_to_username" not in response.model_dump()
    assert "supervisor_username" not in response.model_dump()

    detail = _detail(work_order, include_price=False)
    assert detail.notes == "Resident requested an afternoon visit."
    assert detail.labor == []
    assert detail.labor_minutes == 0
    assert detail.labor_total is None


def test_detail_exposes_multiple_technicians_and_rounded_labor_total():
    primary_id, second_id = uuid4(), uuid4()
    primary = SimpleNamespace(id=primary_id, full_name="Jamie Rivera")
    second = SimpleNamespace(id=second_id, full_name="Taylor Chen")
    work_order = SimpleNamespace(
        id=uuid4(),
        number="WO-456",
        community=None,
        building_number=None,
        unit_number=None,
        description=None,
        priority="Emergency",
        notes=None,
        status="in_progress",
        entry_mode="dispense",
        created_by_id=None,
        assigned_to_id=primary_id,
        assignee=primary,
        technicians=[primary, second],
        items=[],
        labor_entries=[
            SimpleNamespace(
                id=uuid4(), technician_id=primary_id, technician=primary, minutes=35
            ),
            SimpleNamespace(
                id=uuid4(), technician_id=second_id, technician=second, minutes=40
            ),
        ],
        location=None,
        output_to=None,
        vendor_assignee=None,
        service_type=None,
        schedule_date=None,
        supervisor_id=None,
        supervisor=None,
        legacy=False,
    )

    detail = _detail(work_order, include_price=True)

    assert detail.assigned_to_ids == [primary_id, second_id]
    assert detail.assigned_to_names == ["Jamie Rivera", "Taylor Chen"]
    assert detail.priority == "Emergency"
    assert detail.labor_minutes == 75
    assert detail.labor_billed_minutes == 90
    assert detail.labor_total == 93.75
