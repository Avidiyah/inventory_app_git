"""Tests pinning the per-route minimum role gates.

Layer: unit (no DB, no HTTP client). FastAPI stores a
`require_min_role(minimum)` gate as a closure over `minimum`, whether it
is attached via the decorator's `dependencies=[...]` or via a `user=
Depends(...)` parameter. `_find_min_role` walks the route's full
dependant tree so the assertion does not care which style a route uses
-- only that the effective minimum is correct. A future tweak to the
wrong route fails loudly.

Matches the "pure, no DB" style of the rest of the suite
(`test_roles.py`, `test_auth_password.py`).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.routing import APIRoute

from app.domain import roles
from app.routers import items as items_router
from app.routers import transactions as transactions_router


def _route(router, endpoint_name):
    """Find a route by its handler function name."""
    for route in router.router.routes:
        if isinstance(route, APIRoute) and route.endpoint.__name__ == endpoint_name:
            return route
    raise AssertionError(f"route {endpoint_name!r} not found on {router.__name__}")


def _find_min_role(dependant):
    """Recursively search a route's dependant tree for the `minimum`
    role captured by a `require_min_role(...)` closure, returning it (or
    None). Covers gates attached via the decorator's `dependencies=[...]`
    AND via a `user= Depends(require_min_role(...))` parameter, at any
    nesting depth."""
    for sub in dependant.dependencies:
        call = getattr(sub, "call", None)
        closure = getattr(call, "__closure__", None) or ()
        freevars = call.__code__.co_freevars if call is not None else ()
        for name, cell in zip(freevars, closure):
            if name == "minimum" and isinstance(cell.cell_contents, str):
                return cell.cell_contents
        found = _find_min_role(sub)
        if found is not None:
            return found
    return None


def _min_role_for(router, endpoint_name):
    return _find_min_role(_route(router, endpoint_name).dependant)


def test_update_item_notes_requires_supervisor():
    # Notes are operational, not administrative.
    assert _min_role_for(items_router, "update_item_notes") == roles.ROLE_SUPERVISOR


def test_update_item_requires_admin():
    assert _min_role_for(items_router, "update_item") == roles.ROLE_ADMIN


def test_delete_item_requires_admin():
    assert _min_role_for(items_router, "delete_item") == roles.ROLE_ADMIN


def test_create_correction_requires_admin():
    # `POST /transactions/adjust`.
    assert _min_role_for(transactions_router, "create_correction") == roles.ROLE_ADMIN


def test_void_transaction_requires_supervisor():
    # `DELETE /transactions/{transaction_id}`. Owner/Admin/Supervisor may
    # void a mis-clicked transaction; Technician may not.
    assert _min_role_for(transactions_router, "void_transaction") == roles.ROLE_SUPERVISOR
