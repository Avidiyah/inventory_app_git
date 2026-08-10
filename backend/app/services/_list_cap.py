"""Apply the list-size ceiling and report when it bites.

Layer: services. Shared internal helper, named with the leading
underscore `routers/_uploads.py` and `routers/_errors.py` already use for
this role. The policy -- the number, the `+1` fetch, what counts as
truncation -- lives in `app.domain.list_limits`; this module only applies
it and logs.

**Logging from a service is new here.** Today only `routers/auth.py` and
`routers/_uploads.py` emit N1 lines. It is consistent with the layer rule
(services forbid *FastAPI*, not logging) and it is the correct layer for
this: the cap is applied here, and a log emitted from the router would be
reporting something it did not observe.

The log line is the entire early-warning system for X3. If
`event=list.truncated` never appears, the ceiling never bit and nothing
needs doing. When it does appear it names the list, so whoever picks up
real pagination knows which one actually overflowed rather than guessing.
"""

import logging
from typing import Sequence, TypeVar

from app.domain import list_limits

logger = logging.getLogger(__name__)

T = TypeVar("T")


def report_if_truncated(fetched_count: int, *, what: str) -> None:
    """Emit the trigger line if `fetched_count` proves the ceiling bit.

    Split out from `capped` because `services.work_orders.list_work_orders`
    cannot use it: its ordering is decided in Python (X2), so it slices its
    own already-sorted list rather than letting a query do the capping. It
    still needs to report, and reporting is the half that matters.

    `what` names the list in the log line (`list=items`). Keep it short and
    stable: it is the field someone will filter on.
    """
    # The module is imported rather than its names, so the ceiling is read at
    # call time. That keeps the `cap=` field honest and lets a test lower the
    # ceiling instead of building 5,001 rows.
    if list_limits.was_truncated(fetched_count):
        logger.warning(
            "list.truncated",
            extra={"fields": {
                "list": what,
                "cap": list_limits.MAX_LIST_ROWS,
            }},
        )


def capped(rows: Sequence[T], *, what: str) -> list[T]:
    """Trim `rows` to the ceiling, logging once if anything was dropped.

    `rows` is expected to be the result of a query limited to
    `list_limits.fetch_limit()` -- one more than the ceiling -- so the
    extra row is what makes truncation detectable. Passing an unlimited
    result still works and still caps correctly; it just does not bound
    the database work, which is the point of using `fetch_limit()` at the
    query.
    """
    report_if_truncated(len(rows), what=what)
    return list_limits.cap(rows)
