"""Role vocabulary and the subordinate-management hierarchy.

Layer: pure domain (no FastAPI, no SQLAlchemy, no Pydantic).

There are four roles. Authority is strictly ordered by rank, and the
single rule that drives every user-management decision is: *an actor
may create, reset, or delete a user only when the actor outranks that
user* (`can_manage`). The set of roles an actor may hand out is exactly
the set ranked below them (`assignable_roles`).

Owner is the top of the hierarchy and is created only by the bootstrap
script (`backend/scripts/create_owner.py`); no API caller can manage an
Owner because no role outranks it.
"""

ROLE_OWNER = "owner"
ROLE_ADMIN = "admin"
ROLE_SUPERVISOR = "supervisor"
ROLE_TECHNICIAN = "technician"

# Higher number = more authority. Used only for `>` comparisons.
ROLE_RANK: dict[str, int] = {
    ROLE_TECHNICIAN: 0,
    ROLE_SUPERVISOR: 1,
    ROLE_ADMIN: 2,
    ROLE_OWNER: 3,
}

# Newest-first is irrelevant here; this is the canonical list of every
# role the system recognises.
ALL_ROLES: tuple[str, ...] = (
    ROLE_OWNER,
    ROLE_ADMIN,
    ROLE_SUPERVISOR,
    ROLE_TECHNICIAN,
)


def is_valid_role(role: str) -> bool:
    """True if `role` is one of the four recognised roles."""
    return role in ROLE_RANK


def rank(role: str) -> int:
    """Numeric authority of a role. Unknown roles rank below everything
    so a corrupt value can never accidentally outrank a real one."""
    return ROLE_RANK.get(role, -1)


def role_at_least(role: str, minimum: str) -> bool:
    """True if `role` has at least the authority of `minimum`. This is
    the backend route-gate primitive (e.g. "supervisor or above")."""
    return rank(role) >= rank(minimum)


def can_manage(actor_role: str, target_role: str) -> bool:
    """True if an actor may create / reset / delete a user holding
    `target_role`. The actor must strictly outrank the target, so no
    one can manage their own level or above (and no one manages an
    Owner)."""
    return rank(actor_role) > rank(target_role) and is_valid_role(target_role)


def assignable_roles(actor_role: str) -> list[str]:
    """Roles `actor_role` is allowed to assign when creating a user --
    every role ranked strictly below the actor, most-senior first."""
    actor_rank = rank(actor_role)
    return [r for r in ALL_ROLES if rank(r) < actor_rank]
