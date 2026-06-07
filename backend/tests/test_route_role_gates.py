"""Tests pinning the per-route minimum role gates on Saved Items.

Layer: unit (no DB, no HTTP client). FastAPI stores route
dependencies as closures over the `minimum` argument to
`require_min_role`. We walk those closure cells to assert the
minimum each Saved-Items route requires, so a future tweak to the
wrong route would fail loudly.

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


def _min_role_for(route):
    """Return the `minimum` role string from the route's
    `require_min_role(...)`-produced dependency, or None if no such
    dependency is attached.
    """
    for dep in route.dependencies:
        closure = getattr(dep.dependency, "__closure__", None) or ()
        freevars = dep.dependency.__code__.co_freevars
        for name, cell in zip(freevars, closure):
            if name == "minimum" and isinstance(cell.cell_contents, str):
                return cell.cell_contents
    return None


def test_update_item_notes_requires_supervisor():
    # Q3.1: notes is operational, not administrative.
    route = _route(items_router, "update_item_notes")
    assert _min_role_for(route) == roles.ROLE_SUPERVISOR


def test_update_item_requires_admin():
    route = _route(items_router, "update_item")
    assert _min_role_for(route) == roles.ROLE_ADMIN


def test_delete_item_requires_admin():
    route = _route(items_router, "delete_item")
    assert _min_role_for(route) == roles.ROLE_ADMIN


def _min_role_from_dependant(route):
    """Return the `minimum` role from a `require_min_role(...)` gate
    attached via the endpoint's `user=` Depends parameter (rather than
    the decorator's `dependencies=[...]`), or None if absent."""
    for sub in route.dependant.dependencies:
        call = getattr(sub, "call", None)
        closure = getattr(call, "__closure__", None) or ()
        freevars = call.__code__.co_freevars if call is not None else ()
        for name, cell in zip(freevars, closure):
            if name == "minimum" and isinstance(cell.cell_contents, str):
                return cell.cell_contents
    return None


def test_create_correction_requires_admin():
    # `POST /transactions/adjust`. Gate is on the `user=` Depends in the
    # signature, not on the decorator's `dependencies=[...]`, so walk
    # the endpoint's own dependant tree instead of `route.dependencies`.
    route = _route(transactions_router, "create_correction")
    assert _min_role_from_dependant(route) == roles.ROLE_ADMIN


def test_void_transaction_requires_supervisor():
    # `DELETE /transactions/{transaction_id}`. Owner/Admin/Supervisor may
    # void a mis-clicked transaction; Technician may not. The gate is on
    # the `user=` Depends so the handler can record who voided it.
    route = _route(transactions_router, "void_transaction")
    assert _min_role_from_dependant(route) == roles.ROLE_SUPERVISOR
