from datetime import datetime, timedelta, timezone

import pytest

from app.domain import messages
from app.domain.errors import InvalidMessageError


def test_direct_key_is_order_free():
    assert messages.direct_key("b", "a") == messages.direct_key("a", "b") == "a:b"


def test_clean_body_strips():
    assert messages.clean_body("  hi ") == "hi"


@pytest.mark.parametrize("bad", ["", "   ", None, "x" * 2001])
def test_clean_body_rejects_blank_and_too_long(bad):
    with pytest.raises(InvalidMessageError):
        messages.clean_body(bad)


def test_clean_group_name_limit():
    assert messages.clean_group_name(" Crew ") == "Crew"
    with pytest.raises(InvalidMessageError):
        messages.clean_group_name("x" * 61)


@pytest.mark.parametrize(
    "role,allowed",
    [("technician", False), ("supervisor", True), ("techfm_oa", True), ("admin", True), ("owner", True)],
)
def test_can_start_group(role, allowed):
    assert messages.can_start_group(role) is allowed


def test_unread_people_counts_distinct():
    assert messages.unread_people(["x", "x", "y"]) == 2


def test_cutoffs():
    now = datetime(2026, 11, 24, tzinfo=timezone.utc)
    assert messages.direct_cutoff(now) == now - timedelta(days=90)
    assert messages.group_cutoff(now) == now - timedelta(days=7)
