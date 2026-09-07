"""Priority is response-visible and editable like the other imported metadata
fields (TechFM OA+) -- not part of the CSV import contract itself. A value set
by hand survives re-enrichment: the enricher writes only into a blank priority
(`test_netfacilities_service.test_independent_updates_and_stale_candidate_retry_are_idempotent`),
which is what makes the manually assigned Urgent level below trustworthy."""

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


# --- the manually assigned Urgent level ----------------------------------

def _static(*parts: str) -> str:
    return (
        Path(__file__).resolve().parents[1].joinpath("static", *parts)
    ).read_text(encoding="utf-8")


def test_urgent_is_suggested_in_the_priority_editor():
    """Urgent is the one level a person assigns rather than imports, so the
    editor offers it. A `datalist` and not a `select`: the field has to stay
    open to whatever text NetFacilities sends next."""
    source = _static("views", "workOrders.js")

    assert 'const MANUAL_PRIORITY = "Urgent";' in source
    assert "<datalist" in source
    assert 'list="${escapeHtml(listId)}"' in source


def test_every_work_order_card_class_comes_from_one_builder():
    """The urgent outline is a class on the card, so any place that rewrites a
    card's className without the shared builder would silently drop it -- and
    the repaint paths rewrite className on every socket update."""
    view = _static("views", "workOrders.js")

    assert "export function workOrderCardClass(card)" in view
    assert 'priorityBucket(card.priority) === "urgent"' in view
    # The builder itself holds the only hand-written copy of the class string.
    assert view.count("wo-card wo-card-status-") == 1
    for source in (_static("views", "transactions.js"), _static("views", "adminReview.js")):
        assert "wo-card wo-card-status-" not in source
        assert "workOrderCardClass(" in source


def test_the_urgent_pulse_is_removed_under_reduced_motion():
    """Emphasis, not information -- the badge text says Urgent either way, so
    the animation goes away entirely rather than slowing down, matching the
    loading skeletons."""
    css = _static("styles.css")

    assert "@keyframes wo-urgent-pulse" in css
    assert "@keyframes wo-urgent-card-pulse" in css
    reduced = css.split("@media (prefers-reduced-motion: reduce)")
    assert any(
        ".wo-priority-urgent" in block and ".wo-card-urgent" in block
        for block in reduced[1:]
    )


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
