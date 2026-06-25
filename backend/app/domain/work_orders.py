"""Pure work-order rules (identity, status, entry mode, visibility scope).

Layer: pure domain (no SQLAlchemy, no FastAPI, no models) -- exercised by plain
unit tests, like `domain.mass_staging` and `domain.roles`.

A work order is a standalone entity whose identity is its `number` (unique
case-insensitively + trimmed). Its lifecycle is two-state -- `in_progress ->
completed` (reopenable); "planning" is a Mass Stage *stage* concept, not a
work-order state. `entry_mode` is the default mode for newly logged materials:
`dispense` moves stock, `retroactive` is a stock-neutral paper backfill.
"""

from typing import Optional
from uuid import UUID

from app.domain import roles
from app.domain.errors import WorkOrderStateError


# --- identity ------------------------------------------------------------

def normalize_number(number: str) -> str:
    """The canonical comparison form of a work-order number: trimmed +
    lowercased. Mirrors the DB's `lower(btrim(number))` unique index, so
    find-or-create and the constraint agree on what "the same number" means.
    Internal whitespace is preserved (btrim only strips the ends)."""
    return number.strip().lower()


# --- status vocabulary (two-state) ---------------------------------------

STATUS_IN_PROGRESS = "in_progress"
STATUS_COMPLETED = "completed"

ALL_STATUSES: tuple[str, ...] = (STATUS_IN_PROGRESS, STATUS_COMPLETED)
# Both states are live work orders shown on the Work Orders page.
ACTIVE_STATUSES: tuple[str, ...] = ALL_STATUSES


# --- entry mode vocabulary -----------------------------------------------

MODE_DISPENSE = "dispense"
MODE_RETROACTIVE = "retroactive"

ALL_MODES: tuple[str, ...] = (MODE_DISPENSE, MODE_RETROACTIVE)


# --- validators ----------------------------------------------------------

def validate_status(status: str) -> None:
    """Raise `WorkOrderStateError` unless `status` is `in_progress` or
    `completed`."""
    if status not in ALL_STATUSES:
        raise WorkOrderStateError(
            "A work order can only be in_progress or completed."
        )


# Back-compat alias: the only settable statuses ARE the active ones.
validate_active_status = validate_status


def validate_mode(mode: str) -> None:
    """Raise `WorkOrderStateError` unless `mode` is `dispense` or
    `retroactive`."""
    if mode not in ALL_MODES:
        raise WorkOrderStateError("Mode must be dispense or retroactive.")


def affects_stock(mode: str) -> bool:
    """Whether logging a material in `mode` should move on-hand stock. Only
    `dispense` does; `retroactive` is a stock-neutral backfill."""
    return mode == MODE_DISPENSE


# --- attribute reconciliation (fill-blanks) ------------------------------

def is_blank(value) -> bool:
    """True for None or an all-whitespace string."""
    return value is None or (isinstance(value, str) and value.strip() == "")


def fill_blank(current, incoming):
    """Fill-blanks merge for a single attribute: keep a non-blank `current`,
    otherwise take `incoming`. Used by find-or-create so a later reference can
    populate empty attributes but never overwrites a value already set."""
    return current if not is_blank(current) else incoming


# --- visibility scope ----------------------------------------------------

def can_view_work_order(
    role: str,
    *,
    created_by_id: Optional[UUID],
    assigned_to_id: Optional[UUID],
    user_id: Optional[UUID],
) -> bool:
    """Whether a user of `role` may see/act on a work order.

    Admin/owner (and a `None`-role internal caller) see all; a supervisor sees
    only work orders they created; a technician sees only work orders assigned
    to them.
    """
    if role is None or roles.role_at_least(role, roles.ROLE_ADMIN):
        return True
    if role == roles.ROLE_SUPERVISOR:
        return created_by_id is not None and created_by_id == user_id
    return assigned_to_id is not None and assigned_to_id == user_id
