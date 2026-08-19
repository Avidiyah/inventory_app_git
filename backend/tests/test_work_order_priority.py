"""Priority is response-visible and editable like the other imported metadata
fields (TechFM OA+, subject to being overwritten by a later NetFacilities
re-enrichment) -- not part of the CSV import contract itself."""

from pathlib import Path

from app.domain import work_orders as wo
from app.models import WorkOrder
from app.schemas.work_orders import WorkOrderCard, WorkOrderUpdate


def test_priority_column_and_response_field_are_nullable():
    column = WorkOrder.__table__.c.priority
    assert column.nullable
    assert column.server_default is None

    fields = WorkOrderCard.model_fields
    assert fields["priority"].default is None


def test_priority_is_accepted_as_a_generic_update():
    update = WorkOrderUpdate.model_validate({"priority": "Emergency"})
    assert update.model_dump(exclude_unset=True) == {"priority": "Emergency"}

    update = WorkOrderUpdate.model_validate(
        {"description": "Manual task", "priority": "Emergency"}
    )
    assert update.model_dump(exclude_unset=True) == {
        "description": "Manual task",
        "priority": "Emergency",
    }

    # Blank means "clear it", same as the other imported metadata fields.
    blanked = WorkOrderUpdate.model_validate({"priority": "  "})
    assert blanked.priority is None


def test_work_orders_ui_renders_an_editable_priority():
    source = (
        Path(__file__).resolve().parents[1] / "static" / "views" / "workOrders.js"
    ).read_text(encoding="utf-8")

    assert '["Priority", detail.priority || "Not imported"]' in source
    assert "wo-edit-priority" in source


# --- the list filter -----------------------------------------------------

def test_normalize_priority_filter_blank_means_no_filter():
    assert wo.normalize_priority_filter(None) is None
    assert wo.normalize_priority_filter("") is None
    assert wo.normalize_priority_filter("   ") is None


def test_normalize_priority_filter_keeps_unknown_vendor_text():
    """Priority is raw NetFacilities text with no fixed vocabulary, so an
    unrecognized value filters on itself rather than raising the way an
    unrecognized community does."""
    assert wo.normalize_priority_filter("  Emergency ") == "Emergency"
    assert wo.normalize_priority_filter("Whatever NetFacilities Adds") == (
        "Whatever NetFacilities Adds"
    )


def test_normalize_priority_filter_recognizes_the_unimported_sentinel():
    assert (
        wo.normalize_priority_filter(wo.PRIORITY_FILTER_NONE)
        == wo.PRIORITY_FILTER_NONE
    )


def test_work_orders_ui_wires_a_priority_filter():
    static_dir = Path(__file__).resolve().parents[1] / "static"
    page = (static_dir / "pages" / "work-orders.html").read_text(encoding="utf-8")
    view = (static_dir / "views" / "workOrders.js").read_text(encoding="utf-8")

    assert 'id="work-orders-priority-filter"' in page
    assert "work-orders-priority-filter" in view
    # It has to join currentFilters(), or hasActiveFilters() stays false and a
    # priority browse silently keeps the RECENT_LIMIT cap -- showing the first
    # ten scheduled dates as if they were every match.
    assert "priority: priorityFilter" in view
