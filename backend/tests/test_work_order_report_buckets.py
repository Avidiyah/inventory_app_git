"""The four-bucket table and the distribution built on it.

Spec: docs/superpowers/specs/2026-08-30-hub-report-xlsx-redesign-design.md
(§2, E1-E3, E8).

Pure: no `db` fixture. Rows are `SimpleNamespace`s carrying only the five
attributes `distribution` reads, which is also the point -- the aggregate
must not depend on anything a `ReportRow` does not already carry.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.domain import work_orders as wo
from app.services import work_order_report_buckets as buckets

CLOSED_AT = datetime(2026, 8, 25, 15, 30, tzinfo=timezone.utc)


def _row(
    *,
    status=wo.STATUS_CREATED,
    community=None,
    location=None,
    service_type="Plumbing",
    archived=False,
):
    return SimpleNamespace(
        status=status,
        community=community,
        location=location,
        service_type=service_type,
        archived_at=CLOSED_AT if archived else None,
    )


def _community(result, key):
    return next(entry for entry in result.communities if entry.key == key)


# --- the table (E2) ---------------------------------------------------------


def test_every_status_lands_in_exactly_one_live_bucket():
    placed = [buckets.bucket_of(status) for status in wo.ALL_STATUSES]

    assert placed == [
        "accepted",
        "in_progress",
        "in_progress",
        "in_progress",
        "ready_to_close",
        "ready_to_close",
        "ready_to_close",
    ]
    assert buckets.BUCKET_CLOSED not in placed


def test_bucket_order_and_labels_are_lifecycle_order():
    assert buckets.BUCKET_KEYS == ("accepted", "in_progress", "ready_to_close", "closed")
    assert [bucket.label for bucket in buckets.REPORT_BUCKETS] == [
        "Accepted",
        "In progress",
        "Ready to close",
        "Closed",
    ]
    assert buckets.BUCKET_LABELS["ready_to_close"] == "Ready to close"


def test_unknown_status_fails_loudly():
    with pytest.raises(ValueError, match="cancelled"):
        buckets.bucket_of("cancelled")


def test_an_archived_row_is_closed_whatever_its_status():
    assert buckets.row_bucket(_row(status=wo.STATUS_REVIEW, archived=True)) == "closed"
    assert buckets.row_bucket(_row(status=wo.STATUS_REVIEW)) == "ready_to_close"


def test_empty_counts_is_zero_filled_in_bucket_order():
    assert list(buckets.empty_counts().items()) == [
        ("accepted", 0),
        ("in_progress", 0),
        ("ready_to_close", 0),
        ("closed", 0),
    ]


# --- community attribution (E14) -------------------------------------------


def test_communities_of_is_the_membership_labels_in_filter_order():
    assert buckets.communities_of(_row(community="Scholars")) == ("Scholars",)
    # Filter order, not text order: Scholars precedes Commons however the
    # location phrases it.
    assert buckets.communities_of(
        _row(location="Commons annex / Scholars 3")
    ) == ("Scholars", "Commons")
    # Nothing named: the Academics fallback, never an empty tuple.
    assert buckets.communities_of(_row()) == ("Academics",)


def test_primary_community_is_the_first_membership():
    assert buckets.primary_community(_row(location="Commons annex / Scholars 3")) == "Scholars"
    assert buckets.primary_community(_row(community="Young Hall")) == "Young Hall"
    assert buckets.primary_community(_row()) == "Academics"


# --- the distribution (E1, E3, §2.1) ---------------------------------------


def test_a_multi_community_row_is_counted_in_both():
    rows = [
        _row(community="Scholars", location="Scholars 3 / Commons annex"),
        _row(community="Centennial", status=wo.STATUS_ASSIGNED),
        _row(community="Centennial", status=wo.STATUS_REVIEW, archived=True, service_type="HVAC"),
        _row(community="Centennial", status=wo.STATUS_CREATED),
    ]

    result = buckets.distribution(rows)

    assert _community(result, "scholars").total == 1
    assert _community(result, "commons").total == 1
    assert _community(result, "centennial").counts == {
        "accepted": 1,
        "in_progress": 1,
        "ready_to_close": 0,
        "closed": 1,
    }
    assert result.company.total == 4
    # Deliberately not 4: memberships, not tags (§2.1). A future "fix" that
    # makes these sum trips this line.
    assert sum(entry.total for entry in result.communities) == 5


def test_every_group_sums_to_its_total():
    rows = [
        _row(community="Commons", status=status)
        for status in wo.ALL_STATUSES
    ] + [_row(community="Commons", status=wo.STATUS_COMPLETED, archived=True)]

    result = buckets.distribution(rows)

    for group in (result.company, *result.communities):
        assert sum(group.counts.values()) == group.total
        for service_type in group.service_types:
            assert sum(service_type.counts.values()) == service_type.total
    assert _community(result, "commons").counts == {
        "accepted": 1,
        "in_progress": 3,
        "ready_to_close": 3,
        "closed": 1,
    }


def test_blank_service_type_is_unspecified_and_a_closed_row_leaves_the_live_buckets():
    rows = [_row(community="Commons", service_type="  ", status=wo.STATUS_COMPLETED, archived=True)]

    commons = _community(buckets.distribution(rows), "commons")

    assert [(s.label, s.total, s.counts["closed"]) for s in commons.service_types] == [
        ("Unspecified", 1, 1)
    ]
    assert commons.counts["ready_to_close"] == 0


def test_service_type_labels_are_shared_company_wide_and_sorted_by_total_then_label():
    rows = [
        _row(community="Commons", service_type="hvac"),
        _row(community="Scholars", service_type="HVAC"),
        _row(community="Scholars", service_type="HVAC"),
        _row(community="Scholars", service_type="Doors"),
        _row(community="Scholars", service_type="appliances"),
    ]

    result = buckets.distribution(rows)

    # `HVAC` < `hvac` by code point, chosen once for every sheet.
    assert [s.label for s in _community(result, "commons").service_types] == ["HVAC"]
    assert [s.label for s in _community(result, "scholars").service_types] == [
        "HVAC",
        "appliances",
        "Doors",
    ]


def test_no_rows_still_produces_every_community_in_fixed_order():
    result = buckets.distribution([])

    assert [entry.key for entry in result.communities] == list(wo.ALL_COMMUNITY_FILTERS)
    assert [entry.label for entry in result.communities] == [
        "Scholars",
        "Centennial",
        "Commons",
        "Young Hall",
        "Academics",
    ]
    assert result.company.key == buckets.COMPANY_KEY
    assert result.company.total == 0
    assert result.company.service_types == []


# --- the grid (E8) ----------------------------------------------------------


def _entry(label, total):
    return buckets.ServiceTypeDistribution(
        key=label.lower(),
        label=label,
        total=total,
        counts={"accepted": total, "in_progress": 0, "ready_to_close": 0, "closed": 0},
    )


def test_grid_shows_everything_when_nine_or_fewer():
    nine = [_entry(f"T{index}", 20 - index) for index in range(9)]

    assert buckets.grid_of(nine) == (nine, 0)


def test_grid_folds_the_tail_into_other_past_nine():
    eleven = [_entry(f"T{index}", 20 - index) for index in range(11)]

    cards, folded = buckets.grid_of(eleven)

    assert folded == 3
    assert [card.label for card in cards] == [f"T{index}" for index in range(8)] + ["Other"]
    assert cards[-1].key == buckets.OTHER_KEY
    assert cards[-1].total == sum(entry.total for entry in eleven[8:])
    assert cards[-1].counts["accepted"] == cards[-1].total
