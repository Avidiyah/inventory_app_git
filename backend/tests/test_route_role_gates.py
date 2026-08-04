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
import uuid
from datetime import date
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import HTTPException
from fastapi.routing import APIRoute

import pytest

from app.domain import roles
from app.domain.errors import WorkOrderAssignmentConflictError
from app.routers import items as items_router
from app.routers import tools as tools_router
from app.routers import users as users_router
from app.routers import transactions as transactions_router
from app.routers import work_orders as work_orders_router
from app.routers._errors import to_http
from app.schemas.work_orders import WorkOrderUpdate


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


def test_update_user_role_requires_admin():
    # Changing someone's role is Admin+; the outranks-the-target rule inside
    # the handler is additional, not a substitute (a Supervisor outranks a
    # Technician but still may not re-role them).
    assert _min_role_for(users_router, "update_user_role") == roles.ROLE_ADMIN


def test_update_user_name_has_no_static_min_role():
    # Editing name/username is self-or-manager, decided per target inside the
    # handler, so no static minimum should be discoverable.
    assert _min_role_for(users_router, "update_user_name") is None


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


def test_create_transaction_has_no_static_min_role():
    # `POST /transactions/` is open to any logged-in user at the route
    # level; the stock-vs-dispense split is enforced in the handler via
    # `roles.can_transact` (covered by test_roles.py), not a
    # `require_min_role` gate. So no static minimum should be discoverable.
    assert _min_role_for(transactions_router, "create_transaction") is None


@pytest.mark.parametrize(
    "endpoint_name",
    [
        "list_work_orders",
        "work_order_filter_options",
        "get_work_order",
        "update_work_order",
        "add_work_order_item",
        "update_work_order_item",
        "delete_work_order_item",
    ],
)
def test_work_order_routes_have_no_static_min_role(endpoint_name):
    # The Work Orders page is open to any authenticated user (technicians
    # included) at the route level; visibility is scoped *server-side* in
    # `services.work_orders` (covered by test_work_orders_service.py), not by a
    # `require_min_role` gate. So no static minimum should be discoverable.
    assert _min_role_for(work_orders_router, endpoint_name) is None


def test_work_order_list_forwards_joinable_filters(monkeypatch):
    supervisor_id = uuid.uuid4()
    user = SimpleNamespace(role=roles.ROLE_ADMIN)
    captured = {}

    def list_filtered(db, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(
        work_orders_router.wo_service, "list_work_orders", list_filtered
    )

    result = work_orders_router.list_work_orders(
        status="in_progress",
        service_type="SMR27 - Belfor",
        supervisor_id=supervisor_id,
        community="commons",
        scheduled_date=date(2026, 7, 28),
        q="2349",
        limit=None,
        user=user,
        db=None,
    )

    assert result == []
    assert captured == {
        "user": user,
        "status": "in_progress",
        "service_type": "SMR27 - Belfor",
        "supervisor_id": supervisor_id,
        "community": "commons",
        "scheduled_date": date(2026, 7, 28),
        "search": "2349",
        "limit": None,
    }


def test_archive_work_order_requires_admin():
    assert _min_role_for(work_orders_router, "archive_work_order") == roles.ROLE_ADMIN


@pytest.mark.parametrize(
    "endpoint_name",
    ["preview_legacy_work_order_archive", "archive_legacy_work_orders"],
)
def test_legacy_work_order_rearchive_requires_owner(endpoint_name):
    assert _min_role_for(work_orders_router, endpoint_name) == roles.ROLE_OWNER


@pytest.mark.parametrize(
    "status", ["created", "assigned", "in_progress", "on_hold", "completed", "review"]
)
def test_technician_cannot_change_work_order_status(status):
    with pytest.raises(HTTPException) as exc:
        work_orders_router.update_work_order(
            uuid.uuid4(),
            WorkOrderUpdate(status=status),
            user=SimpleNamespace(role=roles.ROLE_TECHNICIAN),
            db=None,
        )
    assert exc.value.status_code == 403


def test_supervisor_cannot_edit_imported_work_order_metadata():
    with pytest.raises(HTTPException) as exc:
        work_orders_router.update_work_order(
            uuid.uuid4(),
            WorkOrderUpdate(location="Commons 101"),
            user=SimpleNamespace(role=roles.ROLE_SUPERVISOR),
            db=None,
        )
    assert exc.value.status_code == 403


def test_technician_can_save_work_order_notes(monkeypatch):
    work_order_id = uuid.uuid4()
    saved = SimpleNamespace(id=work_order_id)
    user = SimpleNamespace(role=roles.ROLE_TECHNICIAN)
    captured = {}

    def save(db, incoming_id, *, user, fields):
        captured.update(fields)
        return saved

    monkeypatch.setattr(work_orders_router.wo_service, "update_work_order", save)
    monkeypatch.setattr(
        work_orders_router.wo_service,
        "get_work_order",
        lambda db, incoming_id, *, user: saved,
    )
    monkeypatch.setattr(
        work_orders_router,
        "_detail",
        lambda work_order, *, include_price: work_order,
    )

    result = work_orders_router.update_work_order(
        work_order_id,
        WorkOrderUpdate(notes="  Gate code is 4123.  "),
        user=user,
        db=None,
    )

    assert result is saved
    assert captured == {"notes": "Gate code is 4123."}


def test_work_order_route_passes_precondition_and_returns_internal_detail(monkeypatch):
    work_order_id = uuid.uuid4()
    target_id = uuid.uuid4()
    saved = SimpleNamespace(id=work_order_id)
    user = SimpleNamespace(role=roles.ROLE_SUPERVISOR)
    captured = {}

    def save(db, incoming_id, *, user, fields, expected_supervisor_id):
        captured["fields"] = fields
        captured["expected"] = expected_supervisor_id
        return saved

    def get(db, incoming_id, *, user):
        captured["detail_user"] = user
        return saved

    monkeypatch.setattr(work_orders_router.wo_service, "update_work_order", save)
    monkeypatch.setattr(work_orders_router.wo_service, "get_work_order", get)
    monkeypatch.setattr(
        work_orders_router,
        "_detail",
        lambda work_order, *, include_price: work_order,
    )

    result = work_orders_router.update_work_order(
        work_order_id,
        WorkOrderUpdate(
            supervisor_id=target_id,
            expected_supervisor_id=None,
        ),
        user=user,
        db=None,
    )

    assert result is saved
    assert captured == {
        "fields": {"supervisor_id": target_id},
        "expected": None,
        "detail_user": None,
    }


def test_stale_work_order_assignment_maps_to_named_http_409():
    error = to_http(WorkOrderAssignmentConflictError("Avery Anderson"))
    assert error.status_code == 409
    assert error.detail == (
        "This Work Order was already assigned to Avery Anderson"
    )


def test_create_tool_requires_admin():
    assert _min_role_for(tools_router, "create_tool") == roles.ROLE_ADMIN


def test_update_tool_requires_admin():
    assert _min_role_for(tools_router, "update_tool") == roles.ROLE_ADMIN


def test_delete_tool_requires_admin():
    assert _min_role_for(tools_router, "delete_tool") == roles.ROLE_ADMIN


def test_checkout_tool_requires_admin():
    assert _min_role_for(tools_router, "checkout_tool") == roles.ROLE_ADMIN


def test_adjust_tool_requires_admin():
    assert _min_role_for(tools_router, "adjust_tool") == roles.ROLE_ADMIN


@pytest.mark.parametrize(
    "endpoint_name",
    ["list_tools", "get_tool_by_barcode", "return_tool"],
)
def test_tool_routes_open_to_any_session_have_no_static_min_role(endpoint_name):
    # Viewing the Tools page/lookup and processing a return are open to any
    # authenticated role -- only checkout/create/edit/archive are Admin+.
    assert _min_role_for(tools_router, endpoint_name) is None
