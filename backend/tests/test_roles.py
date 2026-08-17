"""Unit tests for the role hierarchy (pure domain, no DB)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.domain import roles


def test_rank_ordering():
    assert (
        roles.rank("owner")
        > roles.rank("admin")
        > roles.rank("techfm_oa")
        > roles.rank("supervisor")
        > roles.rank("technician")
    )


def test_unknown_role_ranks_below_everything():
    assert roles.rank("bogus") < roles.rank("technician")
    assert roles.is_valid_role("bogus") is False


def test_role_at_least():
    assert roles.role_at_least("admin", "supervisor") is True
    assert roles.role_at_least("supervisor", "supervisor") is True
    assert roles.role_at_least("technician", "supervisor") is False


def test_work_order_assignment_role_eligibility():
    assert roles.can_be_work_order_supervisor("admin") is True
    assert roles.can_be_work_order_supervisor("supervisor") is True
    assert roles.can_be_work_order_supervisor("owner") is False
    assert roles.can_be_work_order_supervisor("technician") is False

    assert roles.can_be_work_order_technician("supervisor") is True
    assert roles.can_be_work_order_technician("technician") is True
    assert roles.can_be_work_order_technician("admin") is False
    assert roles.can_be_work_order_technician("owner") is False


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
    assert roles.assignable_roles("owner") == [
        "admin", "techfm_oa", "supervisor", "technician",
    ]
    assert roles.assignable_roles("admin") == [
        "techfm_oa", "supervisor", "technician",
    ]
    assert roles.assignable_roles("techfm_oa") == ["supervisor", "technician"]
    assert roles.assignable_roles("supervisor") == ["technician"]
    assert roles.assignable_roles("technician") == []


def test_can_transact_dispense_allowed_for_every_role():
    # Dispense is the floor-crew action: every recognised role may do it.
    for actor in roles.ALL_ROLES:
        assert roles.can_transact(actor, "dispense") is True


def test_can_transact_stock_requires_supervisor():
    assert roles.can_transact("owner", "stock") is True
    assert roles.can_transact("admin", "stock") is True
    assert roles.can_transact("techfm_oa", "stock") is True
    assert roles.can_transact("supervisor", "stock") is True
    # A Technician may not add stock.
    assert roles.can_transact("technician", "stock") is False


def test_techfm_oa_sits_between_supervisor_and_admin():
    assert (
        roles.rank(roles.ROLE_TECHNICIAN)
        < roles.rank(roles.ROLE_SUPERVISOR)
        < roles.rank(roles.ROLE_TECHFM_OA)
        < roles.rank(roles.ROLE_ADMIN)
        < roles.rank(roles.ROLE_OWNER)
    )
    assert roles.is_valid_role("techfm_oa") is True


def test_techfm_oa_clears_every_floor_below_admin():
    assert roles.role_at_least("techfm_oa", "supervisor") is True
    assert roles.role_at_least("techfm_oa", "techfm_oa") is True
    # The one floor it does not clear -- this is what removes Send to Review.
    assert roles.role_at_least("techfm_oa", "admin") is False


def test_techfm_oa_cannot_manage_admin_or_above():
    assert roles.can_manage("techfm_oa", "admin") is False
    assert roles.can_manage("techfm_oa", "owner") is False
    assert roles.can_manage("techfm_oa", "techfm_oa") is False
    # ...but it manages everything below.
    assert roles.can_manage("techfm_oa", "supervisor") is True
    assert roles.can_manage("techfm_oa", "technician") is True


def test_admin_retains_control_of_techfm_oa_accounts():
    # The reason the new role gets its own rank instead of sharing Admin's:
    # at equal rank an Admin could neither manage nor create one.
    assert roles.can_manage("admin", "techfm_oa") is True
    assert roles.can_manage("owner", "techfm_oa") is True
    assert roles.can_manage("supervisor", "techfm_oa") is False


def test_techfm_oa_is_a_work_order_supervisor_but_not_a_worker():
    assert roles.can_be_work_order_supervisor("techfm_oa") is True
    assert roles.can_be_work_order_technician("techfm_oa") is False


def test_techfm_oa_may_stock_and_dispense():
    assert roles.can_transact("techfm_oa", "dispense") is True
    assert roles.can_transact("techfm_oa", "stock") is True
    assert roles.can_transact("techfm_oa", "adjust") is False


def test_role_labels_cover_every_role_and_spell_techfm_oa_exactly():
    assert set(roles.ROLE_LABELS) == set(roles.ALL_ROLES)
    assert roles.label("techfm_oa") == "TechFM OA"
    assert roles.label("admin") == "Admin"
    # An unrecognised role must not crash a description string.
    assert roles.label("bogus") == "bogus"


def test_can_transact_refuses_unknown_type_and_role():
    # `adjust` has its own Admin-gated route; it is not transactable here.
    assert roles.can_transact("owner", "adjust") is False
    assert roles.can_transact("owner", "bogus") is False
    # A corrupt actor role can never transact, even to dispense.
    assert roles.can_transact("bogus", "dispense") is False
