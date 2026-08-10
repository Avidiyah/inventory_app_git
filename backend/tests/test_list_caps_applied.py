"""The X3 ceiling is actually wired into each list service.

Layer: unit + DB. Kept as one cross-cutting file rather than scattered
across five service test files, because "every list is capped" is itself
the property under test -- a new list endpoint that forgets the cap is
the regression this file exists to catch, and it is easier to notice a
missing entry in one table than a missing test in one of five files.

**The ceiling is lowered rather than satisfied.** `services._list_cap`
and `domain.list_limits.fetch_limit` both read `MAX_LIST_ROWS` at call
time, so a test can set it to 1 instead of inserting 5,001 rows. That
keeps these tests fast and makes them independent of the chosen number --
they would still pass if the ceiling moved to 10,000.

The complementary half -- that a caller passing nothing still gets
everything below the ceiling -- is already covered broadly: the rest of
the suite exercises these same list functions with small datasets
throughout, and all of it passes unchanged.
"""

import logging
import os
import sys
import uuid
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from app.domain import list_limits
from app.models import Item, MassStage, Tool, User
from app.services import auth
from app.services import items as items_service
from app.services import mass_staging as stages_service
from app.services import tools as tools_service
from app.services import users as users_service

TRUNCATION_EVENT = "list.truncated"


@pytest.fixture
def ceiling_of_one(monkeypatch):
    """Lower the ceiling to 1 row for the duration of a test."""
    monkeypatch.setattr(list_limits, "MAX_LIST_ROWS", 1)
    return 1


def _truncation_lists(caplog):
    return [
        record.fields["list"]
        for record in caplog.records
        if record.getMessage() == TRUNCATION_EVENT
    ]


def _seed_items(db, count):
    for index in range(count):
        token = uuid.uuid4().hex[:10]
        db.add(
            Item(
                barcode=f"CAP-{token}-{index}",
                name=f"Cap Item {token}",
                quantity=Decimal("1"),
                location="Cap test shelf",
            )
        )
    db.flush()


def _seed_users(db, count):
    for _ in range(count):
        token = uuid.uuid4().hex[:10]
        db.add(
            User(
                username=f"cap-{token}",
                first_name="Cap",
                last_name=f"User {token}",
                password_hash=auth.hash_password("hunter2"),
                role="technician",
            )
        )
    db.flush()


def _seed_tools(db, count):
    for index in range(count):
        token = uuid.uuid4().hex[:10]
        db.add(
            Tool(
                barcode=f"CAPTOOL-{token}-{index}",
                name=f"Cap Tool {token}",
                quantity=Decimal("1"),
            )
        )
    db.flush()


# --------------------------------------------------------------------------
# Each list truncates and reports
# --------------------------------------------------------------------------

def test_items_are_capped_and_reported(db, ceiling_of_one, caplog):
    caplog.set_level(logging.WARNING)
    _seed_items(db, 3)

    rows = items_service.list_items(db)

    assert len(rows) == 1
    assert "items" in _truncation_lists(caplog)


def test_tools_are_capped_and_reported(db, ceiling_of_one, caplog):
    caplog.set_level(logging.WARNING)
    _seed_tools(db, 3)

    rows = tools_service.list_tools(db)

    assert len(rows) == 1
    assert "tools" in _truncation_lists(caplog)


def test_users_are_capped_and_reported(db, ceiling_of_one, caplog):
    caplog.set_level(logging.WARNING)
    # Seed explicitly rather than relying on the database already holding
    # users. An earlier version asserted that precondition instead, which
    # passed against a populated local database and failed in CI against an
    # empty one -- ambient data is not a fixture.
    _seed_users(db, 3)

    rows = users_service.list_users(db)

    assert len(rows) == 1
    assert "users" in _truncation_lists(caplog)


def test_mass_stages_are_capped_and_reported(db, ceiling_of_one, caplog):
    caplog.set_level(logging.WARNING)
    for index in range(3):
        token = uuid.uuid4().hex[:8]
        db.add(
            MassStage(
                community=f"Cap Community {token}",
                building_name=f"B{index}-{token}",
                status="planning",
            )
        )
    db.flush()

    rows = stages_service.list_stages(db)

    assert len(rows) == 1
    assert "mass_stages" in _truncation_lists(caplog)


# --------------------------------------------------------------------------
# Below the ceiling, nothing is trimmed and nothing is logged
# --------------------------------------------------------------------------

def test_a_list_below_the_ceiling_is_untouched_and_silent(db, caplog):
    # Real ceiling this time -- the everyday case.
    caplog.set_level(logging.DEBUG)
    before = len(items_service.list_items(db))
    _seed_items(db, 3)

    rows = items_service.list_items(db)

    assert len(rows) == before + 3
    assert _truncation_lists(caplog) == []
