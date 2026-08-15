"""DB-free tests for the sanitized NetFacilities Stage 1 HTML parser."""

from pathlib import Path

import pytest

from app.integrations.netfacilities.errors import (
    NetFacilitiesAuthenticationRequired,
    NetFacilitiesInvalidWorkOrderNumber,
    NetFacilitiesUnexpectedDocument,
)
from app.integrations.netfacilities.parser import (
    parse_work_order_html,
    validate_work_order_number,
)


FIXTURE = Path(__file__).parent / "fixtures" / "netfacilities_work_order_sanitized.html"


def _html() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def test_parses_confirmed_core_work_order_fields():
    parsed = parse_work_order_html(
        _html(),
        expected_work_order_number="12345678",
    )

    assert parsed.to_dict() == {
        "work_order_number": "12345678",
        "description": (
            "Inspect and repair the test fixture door.\n"
            "Confirm the latch closes correctly."
        ),
        "location": "Example Building / Second Floor / Room 200 / North entrance",
        "location_parts": [
            "Example Building",
            "Second Floor",
            "Room 200",
            "North entrance",
        ],
        "status": "In Progress",
        "priority": "Normal",
        "task_type": "Maintenance",
        "work_order_type": "Non-Asset - Corrective",
        "created_date": "01/02/2026",
        "scheduled_date": "01/03/2026",
        "overdue_date": "01/10/2026",
    }


def test_rejects_a_different_returned_work_order_number():
    with pytest.raises(
        NetFacilitiesUnexpectedDocument,
        match="different work-order identifier",
    ):
        parse_work_order_html(
            _html(),
            expected_work_order_number="87654321",
        )


def test_rejects_login_html_instead_of_parsing_it_as_a_work_order():
    login_html = """
        <html><head><title>NetFacilities Login</title></head>
        <body><form id="signin"><input type="password"></form></body></html>
    """

    with pytest.raises(NetFacilitiesAuthenticationRequired):
        parse_work_order_html(
            login_html,
            expected_work_order_number="12345678",
        )


def test_rejects_missing_required_description():
    html = _html().replace('class="code_task"', 'class="removed"')
    html = html.replace("Inspect and repair the test fixture door.", "")
    html = html.replace("Confirm the latch closes correctly.", "")

    with pytest.raises(NetFacilitiesUnexpectedDocument, match="missing a description"):
        parse_work_order_html(
            html,
            expected_work_order_number="12345678",
        )


def test_rejects_conflicting_statuses():
    html = _html().replace(
        '<span class="p-gern">Status:</span>In Progress',
        '<span class="p-gern">Status:</span>Complete',
    )

    with pytest.raises(NetFacilitiesUnexpectedDocument, match="conflicting"):
        parse_work_order_html(
            html,
            expected_work_order_number="12345678",
        )


@pytest.mark.parametrize(
    "value",
    ["", "0", "01234", "123-45", "abc", "1" * 21],
)
def test_rejects_unsafe_work_order_numbers(value):
    with pytest.raises(NetFacilitiesInvalidWorkOrderNumber):
        validate_work_order_number(value)


def test_normalizes_surrounding_work_order_whitespace():
    assert validate_work_order_number(" 12345678 ") == "12345678"
