"""List-size ceiling policy -- pure rules, no I/O.

Layer: domain. No FastAPI, no SQLAlchemy, no clock reads, so the whole
policy is unit-testable without a database. `app.services._list_cap`
owns the logging and the call sites; this module only decides.

**This is a safety ceiling, not pagination.** The collection endpoints
return whole tables, and X3 was logged to paginate them. Measuring first
showed two things that changed the answer: production holds *hundreds* of
rows, so the symptom is not occurring; and `/items/` and `/users/` are
not merely list views but bulk reference-data loads backing client-side
search in Scan/Stock manual entry, History, and Mass Stage. Paginating
them would have meant rewriting core field workflow to fix a problem
nobody has.

So the ceiling is set far above anything real and exists to do two
things a caller never notices:

- **bound the blast radius** of a runaway query, a corrupted filter, or a
  bulk import gone wrong, so no single request can materialise an
  unbounded result set;
- **emit a trigger.** `services._list_cap` logs `event=list.truncated`
  when the ceiling bites. That log line is the signal that real
  pagination is finally needed -- and it names *which* list fired, so
  the work is scoped by evidence rather than by doing all six at once.

`MAX_LIST_ROWS` is a **chosen** number, not a measured one -- the same
status as B3's 60/s cap. It is roughly 10-50x current headroom. Anyone
changing it is changing a policy decision, not correcting an estimate.
"""

from typing import Sequence, TypeVar

T = TypeVar("T")

# Maximum rows any single list endpoint will return. Chosen, not fitted;
# see the module docstring.
MAX_LIST_ROWS = 5000


def fetch_limit() -> int:
    """How many rows to actually ask the database for.

    **One more than the cap, deliberately.** `routers/_uploads.py::
    read_capped` established this trick for B1's byte caps: fetching
    `limit + 1` is what distinguishes "exactly at the ceiling" from
    "more than the ceiling", so truncation is detectable from the result
    itself without a second `COUNT(*)` round trip.
    """
    return MAX_LIST_ROWS + 1


def was_truncated(fetched_count: int) -> bool:
    """Whether a fetch of `fetch_limit()` rows proves more exist.

    Exactly `MAX_LIST_ROWS` is **not** truncation -- that is a complete
    result that happens to sit on the boundary. Only the extra row proves
    there was more to return.
    """
    return fetched_count > MAX_LIST_ROWS


def cap(rows: Sequence[T]) -> list[T]:
    """Trim to the ceiling. A no-op for any result below it, which is
    every result in practice."""
    return list(rows[:MAX_LIST_ROWS])
