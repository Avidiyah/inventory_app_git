"""Pure graph-bucket and vocabulary rules for the Admin User Hub."""

from datetime import datetime, timedelta, timezone

import pytest

from app.domain import hub
from app.domain import work_orders as wo


def test_graph_week_ranges_are_monday_sunday_and_mark_current_partial():
    ranges = hub.graph_week_ranges(datetime(2026, 8, 21, 18, tzinfo=timezone.utc), 12)

    assert len(ranges) == 12
    assert ranges[0][1] == ranges[0][0] + timedelta(days=6)
    assert ranges[-1] == (ranges[-1][0], ranges[-1][1], True)
    assert ranges[-1][0].weekday() == 0
    assert ranges[-1][1].weekday() == 6


def test_graph_week_ranges_rejects_unapproved_presets():
    with pytest.raises(ValueError):
        hub.graph_week_ranges(datetime.now(timezone.utc), 13)


def test_community_membership_matches_filters_and_academics_fallback():
    assert wo.community_memberships(None, "Cimarron / Young Hall") == (
        wo.COMMUNITY_COMMONS,
        wo.COMMUNITY_YOUNG_HALL,
    )
    assert wo.community_memberships(None, "Academic Building") == (wo.COMMUNITY_ACADEMICS,)


def test_service_type_normalization_keeps_blanks_visible():
    assert wo.normalize_service_type(" Electrical ") == ("electrical", "Electrical")
    assert wo.normalize_service_type("   ") == ("__unspecified__", "Unspecified")
