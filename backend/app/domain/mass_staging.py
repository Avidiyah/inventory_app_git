"""Pure mass-staging business rules.

Layer: pure domain (no SQLAlchemy, no FastAPI, no models).

Owns three rules used by the mass-staging services (`app/services/
mass_staging.py`) so they can be exercised by plain unit tests with no database
-- exactly like `domain.quantity`:

- `allocate_load`   -- split one merged load quantity across the rooms that
  planned an item: fill rooms in `sort_order`, push any overflow onto the
  last room, and stop early on an under-load.
- `allocate_return` -- reverse-fill a returned quantity back across the
  rooms, capped at what is still loaded (net of prior returns).
- `validate_transition` -- guard the stage lifecycle
  `planning -> loading -> completed`.

The allocation functions take and return small framework-free dataclasses
keyed by an opaque room id (a `UUID` in practice), so the service can build
them from ORM rows and map the results back without this module importing
SQLAlchemy. Quantities are `Decimal` and assumed already validated (> 0) by
the schema/service layer -- the same non-re-validation stance as
`domain.quantity`.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Sequence

from app.domain.errors import (
    InvalidStageTransitionError,
    ReturnExceedsLoadedError,
)


# --- Status vocabulary + lifecycle ---------------------------------------

STATUS_PLANNING = "planning"
STATUS_LOADING = "loading"
STATUS_COMPLETED = "completed"

ALL_STATUSES: tuple[str, ...] = (STATUS_PLANNING, STATUS_LOADING, STATUS_COMPLETED)

# Forward-only transitions. Anything not listed -- backward moves,
# same-state moves, unknown statuses -- is rejected by `validate_transition`.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    STATUS_PLANNING: {STATUS_LOADING},
    STATUS_LOADING: {STATUS_COMPLETED},
    STATUS_COMPLETED: set(),
}


# --- Allocation data shapes ----------------------------------------------

@dataclass(frozen=True)
class RoomPlan:
    """A room's planned and already-loaded amounts for one item, in fill
    (`sort_order`) order. Input to `allocate_load`."""

    key: Any
    planned: Decimal
    loaded: Decimal = Decimal(0)


@dataclass(frozen=True)
class RoomLoaded:
    """A room's loaded and already-returned amounts for one item, in
    `sort_order` order. Input to `allocate_return`."""

    key: Any
    loaded: Decimal
    returned: Decimal = Decimal(0)


@dataclass(frozen=True)
class Allocation:
    """How much to apply to a single room -- the output of both allocators.
    `key` echoes the matching input room's `key`."""

    key: Any
    quantity: Decimal


# --- Allocation rules ----------------------------------------------------

def allocate_load(rooms: Sequence[RoomPlan], quantity: Decimal) -> list[Allocation]:
    """Distribute `quantity` units of one item across `rooms` (in `sort_order`).

    Each room is filled up to its remaining planned need (`planned - loaded`)
    in order; any surplus beyond the total remaining need (overflow, e.g.
    box-of-4 packaging) lands on the LAST room. An under-load simply stops
    filling once `quantity` is exhausted, so later rooms receive nothing.
    Returns at most one `Allocation` per room, in `sort_order`, omitting rooms
    that get zero.

    `quantity` is assumed validated (> 0) upstream. `rooms` must be non-empty
    -- the service guards "item not planned in this stage" with
    `StageItemNotFoundError` before calling, so an empty sequence here is
    caller misuse and raises `ValueError`.
    """
    if not rooms:
        raise ValueError("allocate_load requires at least one room")

    remaining = quantity
    taken: dict[Any, Decimal] = {room.key: Decimal(0) for room in rooms}
    for room in rooms:
        take = min(remaining, max(Decimal(0), room.planned - room.loaded))
        taken[room.key] += take
        remaining -= take

    if remaining > 0:  # overflow beyond total planned -> last room's work order
        taken[rooms[-1].key] += remaining

    return [Allocation(key, qty) for key, qty in taken.items() if qty > 0]


def allocate_return(rooms: Sequence[RoomLoaded], quantity: Decimal) -> list[Allocation]:
    """Distribute a returned `quantity` of one item back across `rooms`,
    walking them in REVERSE `sort_order` -- the last-filled room (which
    absorbed any overflow) gives its units back first.

    Each room can give back at most its net loaded (`loaded - returned`). If
    `quantity` exceeds the total returnable across all rooms, raises
    `ReturnExceedsLoadedError`. Returns at most one `Allocation` per room, in
    `sort_order`, omitting zero rooms.

    `quantity` is assumed validated (> 0) upstream.
    """
    returnable = sum(
        (max(Decimal(0), room.loaded - room.returned) for room in rooms),
        Decimal(0),
    )
    if quantity > returnable:
        raise ReturnExceedsLoadedError(requested=quantity, returnable=returnable)

    remaining = quantity
    taken: dict[Any, Decimal] = {room.key: Decimal(0) for room in rooms}
    for room in reversed(rooms):
        take = min(remaining, max(Decimal(0), room.loaded - room.returned))
        taken[room.key] += take
        remaining -= take

    return [Allocation(key, qty) for key, qty in taken.items() if qty > 0]


# --- Lifecycle rules -----------------------------------------------------

def validate_transition(current: str, target: str) -> None:
    """Raise `InvalidStageTransitionError` unless moving a stage from
    `current` to `target` is allowed. Only the forward steps
    `planning -> loading` and `loading -> completed` are permitted; every
    backward move, same-state move, and unknown status is rejected."""
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise InvalidStageTransitionError(current=current, target=target)


def can_edit_plan(status: str) -> bool:
    """True if a stage's rooms/items may be edited -- only while planning."""
    return status == STATUS_PLANNING


def can_load(status: str) -> bool:
    """True if a stage may be loaded or returned against -- only while
    loading (return reuses this; `completed` is read-only)."""
    return status == STATUS_LOADING
