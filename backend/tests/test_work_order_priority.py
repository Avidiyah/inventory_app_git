"""Priority is response-visible but not part of generic edits or CSV contracts."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.models import WorkOrder
from app.schemas.work_orders import WorkOrderCard, WorkOrderUpdate


def test_priority_column_and_response_field_are_nullable():
    column = WorkOrder.__table__.c.priority
    assert column.nullable
    assert column.server_default is None

    fields = WorkOrderCard.model_fields
    assert fields["priority"].default is None


def test_priority_is_not_accepted_as_a_generic_update():
    with pytest.raises(ValidationError, match="Provide at least one field"):
        WorkOrderUpdate.model_validate({"priority": "Emergency"})

    update = WorkOrderUpdate.model_validate(
        {"description": "Manual task", "priority": "Emergency"}
    )
    assert update.model_dump(exclude_unset=True) == {"description": "Manual task"}


def test_work_orders_ui_always_renders_read_only_priority():
    source = (
        Path(__file__).resolve().parents[1] / "static" / "views" / "workOrders.js"
    ).read_text(encoding="utf-8")

    assert '["Priority", detail.priority || "Not imported"]' in source
    assert "wo-edit-priority" not in source
