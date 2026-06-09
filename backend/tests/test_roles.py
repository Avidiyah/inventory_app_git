"""Unit tests for the role hierarchy (pure domain, no DB)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.domain import roles


def test_rank_ordering():
    assert roles.rank("owner") > roles.rank("admin") > roles.rank("supervisor") > roles.rank("technician")


def test_unknown_role_ranks_below_everything():
    assert roles.rank("bogus") < roles.rank("technician")
    assert roles.is_valid_role("bogus") is False


def test_role_at_least():
    assert roles.role_at_least("admin", "supervisor") is True
    assert roles.role_at_least("supervisor", "supervisor") is True
    assert roles.role_at_least("technician", "supervisor") is False


def test_can_manage_requires_strictly_higher_rank():
    assert roles.can_manage("owner", "admin") is True
    assert roles.can_manage("admin", "supervisor") is True
    assert roles.can_manage("supervisor", "technician") is True
    # same level or above is never manageable
    assert roles.can_manage("admin", "admin") is False
    assert roles.can_manage("admin", "owner") is False
    # technician manages no one
    assert roles.can_manage("technician", "technician") is False


def test_no_one_can_manage_an_owner():
    for actor in roles.ALL_ROLES:
        assert roles.can_manage(actor, "owner") is False


def test_assignable_roles():
    assert roles.assignable_roles("owner") == ["admin", "supervisor", "technician"]
    assert roles.assignable_roles("admin") == ["supervisor", "technician"]
    assert roles.assignable_roles("supervisor") == ["technician"]
    assert roles.assignable_roles("technician") == []


def test_can_transact_dispense_allowed_for_every_role():
    # Dispense is the floor-crew action: every recognised role may do it.
    for actor in roles.ALL_ROLES:
        assert roles.can_transact(actor, "dispense") is True


def test_can_transact_stock_requires_supervisor():
    assert roles.can_transact("owner", "stock") is True
    assert roles.can_transact("admin", "stock") is True
    assert roles.can_transact("supervisor", "stock") is True
    # A Technician may not add stock.
    assert roles.can_transact("technician", "stock") is False


def test_can_transact_refuses_unknown_type_and_role():
    # `adjust` has its own Admin-gated route; it is not transactable here.
    assert roles.can_transact("owner", "adjust") is False
    assert roles.can_transact("owner", "bogus") is False
    # A corrupt actor role can never transact, even to dispense.
    assert roles.can_transact("bogus", "dispense") is False
