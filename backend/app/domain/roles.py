"""Role vocabulary and the subordinate-management hierarchy.

Layer: pure domain (no FastAPI, no SQLAlchemy, no Pydantic).

There are five roles. Authority is strictly ordered by rank, and the
single rule that drives every user-management decision is: *an actor
may create, reset, or delete a user only when the actor outranks that
user* (`can_manage`). The set of roles an actor may hand out is exactly
the set ranked below them (`assignable_roles`).

TechFM OA sits between Supervisor and Admin. It holds the whole Admin
toolkit with two subtractions, and both of them are consequences of its
rank rather than special cases written anywhere:

* it fails `role_at_least(role, ROLE_ADMIN)`, which is the floor
  `services.work_orders._require_review_handoff_permission` requires, so
  it cannot send a work order to Review; and
* `can_manage` is false against Admin and Owner, so it can neither
  re-role them nor hand those roles out.

Every *other* gate that once read "Admin or above" now reads
`ROLE_TECHFM_OA`. A new route written with `ROLE_ADMIN` out of habit
would silently lock TechFM OA out of a capability it is meant to have,
so `tests/test_route_role_gates.py` asserts that no route gate is left
at the Admin floor.

Owner is the top of the hierarchy and is created only by the bootstrap
script (`backend/scripts/create_owner.py`); no API caller can manage an
Owner because no role outranks it.
"""

ROLE_OWNER = "owner"
ROLE_ADMIN = "admin"
ROLE_TECHFM_OA = "techfm_oa"
ROLE_SUPERVISOR = "supervisor"
ROLE_TECHNICIAN = "technician"

# Higher number = more authority. Used only for `>` comparisons.
ROLE_RANK: dict[str, int] = {
    ROLE_TECHNICIAN: 0,
    ROLE_SUPERVISOR: 1,
    ROLE_TECHFM_OA: 2,
    ROLE_ADMIN: 3,
    ROLE_OWNER: 4,
}

# Newest-first is irrelevant here; this is the canonical list of every
# role the system recognises.
ALL_ROLES: tuple[str, ...] = (
    ROLE_OWNER,
    ROLE_ADMIN,
    ROLE_TECHFM_OA,
    ROLE_SUPERVISOR,
    ROLE_TECHNICIAN,
)

# Human-facing names. Every other role's label is just its capitalised
# slug, but "TechFM OA" is not derivable that way, so the mapping is
# explicit and the UI and the OpenAPI descriptions both read from it.
# `static/roles.js` carries the same table; the pair is pinned by
# `tests/test_role_mirror_parity.py`.
ROLE_LABELS: dict[str, str] = {
    ROLE_OWNER: "Owner",
    ROLE_ADMIN: "Admin",
    ROLE_TECHFM_OA: "TechFM OA",
    ROLE_SUPERVISOR: "Supervisor",
    ROLE_TECHNICIAN: "Technician",
}

# Work-order assignment roles are intentionally narrower than authority floors.
# Owners retain full access but are not operational routing/worker choices.
# TechFM OA is a routing choice for the same reason Admin is; it is not a
# worker, for the same reason Admin is not.
WORK_ORDER_SUPERVISOR_ROLES: tuple[str, ...] = (
    ROLE_ADMIN,
    ROLE_TECHFM_OA,
    ROLE_SUPERVISOR,
)
WORK_ORDER_TECHNICIAN_ROLES: tuple[str, ...] = (
    ROLE_SUPERVISOR,
    ROLE_TECHNICIAN,
)


def is_valid_role(role: str) -> bool:
    """True if `role` is one of the five recognised roles."""
    return role in ROLE_RANK


def label(role: str) -> str:
    """Human-facing name for `role`, for UI copy and OpenAPI descriptions.
    An unrecognised value is returned unchanged rather than raising -- a
    description string is never worth a 500."""
    return ROLE_LABELS.get(role, role)


def rank(role: str) -> int:
    """Numeric authority of a role. Unknown roles rank below everything
    so a corrupt value can never accidentally outrank a real one."""
    return ROLE_RANK.get(role, -1)


def role_at_least(role: str, minimum: str) -> bool:
    """True if `role` has at least the authority of `minimum`. This is
    the backend route-gate primitive (e.g. "supervisor or above")."""
    return rank(role) >= rank(minimum)


def can_be_work_order_supervisor(role: str) -> bool:
    """Whether an account may be selected for work-order supervision."""
    return role in WORK_ORDER_SUPERVISOR_ROLES


def can_be_work_order_technician(role: str) -> bool:
    """Whether an account may perform work as an assigned technician."""
    return role in WORK_ORDER_TECHNICIAN_ROLES


def can_transact(actor_role: str, transaction_type: str) -> bool:
    """True if `actor_role` may record a stock/dispense transaction of
    `transaction_type`.

    Dispense is the floor-crew action: any recognised role (Technician
    and above) may take stock out. Adding stock is a supervisory action,
    so `stock` requires Supervisor or above. Any other transaction type
    (e.g. the impossible-from-the-schema case, or `adjust`, which has its
    own TechFM-OA-gated route) is refused here."""
    if transaction_type == "dispense":
        return is_valid_role(actor_role)
    if transaction_type == "stock":
        return role_at_least(actor_role, ROLE_SUPERVISOR)
    return False


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
