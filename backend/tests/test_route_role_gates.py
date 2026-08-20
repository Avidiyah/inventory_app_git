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

import inspect
import os
import sys
import uuid
from datetime import date
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import HTTPException
from fastapi.routing import APIRoute

import pytest
from fastapi import BackgroundTasks

from app.domain import roles
from app.domain.errors import WorkOrderAssignmentConflictError
from app.routers import hub as hub_router
from app.routers import items as items_router
from app.routers import netfacilities as netfacilities_router
from app.routers import tools as tools_router
from app.routers import users as users_router
from app.routers import transactions as transactions_router
from app.routers import user_requests as user_requests_router
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


def test_update_user_role_requires_techfm_oa():
    # Changing someone's role is TechFM OA+; the outranks-the-target rule inside
    # the handler is additional, not a substitute. That inner rule is what stops
    # a TechFM OA from touching an Admin, and what stops a Supervisor from
    # re-roling a Technician they do outrank.
    assert _min_role_for(users_router, "update_user_role") == roles.ROLE_TECHFM_OA


def test_update_user_name_has_no_static_min_role():
    # Editing name/username is self-or-manager, decided per target inside the
    # handler, so no static minimum should be discoverable.
    assert _min_role_for(users_router, "update_user_name") is None


def test_update_item_requires_techfm_oa():
    assert _min_role_for(items_router, "update_item") == roles.ROLE_TECHFM_OA


def test_delete_item_requires_techfm_oa():
    assert _min_role_for(items_router, "delete_item") == roles.ROLE_TECHFM_OA


def test_create_correction_requires_techfm_oa():
    # `POST /transactions/adjust`.
    assert (
        _min_role_for(transactions_router, "create_correction")
        == roles.ROLE_TECHFM_OA
    )


def test_void_transaction_has_no_static_min_role():
    # Supervisor+ may void any actionable row; a Technician may remove only
    # their own work-order dispense. That ownership/type decision requires the
    # loaded transaction and therefore lives inside the service.
    assert _min_role_for(transactions_router, "void_transaction") is None


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
        "start_work_order",
        # Tracking sits at the Technician floor, enforced in the service
        # alongside the per-row assignment rule -- not at Admin, and not by a
        # declarative gate.
        "start_work_order_tracking",
        "stop_work_order_tracking",
        "complete_work_order",
        "hold_work_order",
        "resume_work_order",
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
    user = SimpleNamespace(id=uuid.uuid4(), role=roles.ROLE_ADMIN)
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
        priority="Emergency",
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
        "priority": "Emergency",
        "scheduled_date": date(2026, 7, 28),
        "search": "2349",
        "limit": None,
    }


def test_archive_work_order_requires_techfm_oa():
    assert (
        _min_role_for(work_orders_router, "archive_work_order")
        == roles.ROLE_TECHFM_OA
    )


@pytest.mark.parametrize(
    "endpoint_name",
    [
        "netfacilities_session",
        "start_netfacilities_authentication",
        "confirm_netfacilities_authentication",
        "cancel_netfacilities_authentication",
        "start_netfacilities_enrichment",
        "get_netfacilities_enrichment",
    ],
)
def test_netfacilities_routes_require_techfm_oa_and_document_403(endpoint_name):
    assert _min_role_for(netfacilities_router, endpoint_name) == roles.ROLE_TECHFM_OA
    assert 403 in _route(netfacilities_router, endpoint_name).responses


# --------------------------------------------------------------------------
# C1 -- the five gates that used to be written inside the handler body.
#
# They are `Depends(require_min_role(...))` now, so they are discoverable by
# `_min_role_for` like every other gate in the app. Before C1 these five were
# findable only by reading the handler, and their line numbers drifted three
# times in two days -- twice without anyone touching a gate.
#
# The roles are unchanged. `auth_deps.py` raises the identical detail string
# the in-body versions raised, so the response body is byte-identical.
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "endpoint_name,expected",
    [
        ("import_work_orders", roles.ROLE_TECHFM_OA),
        ("export_work_orders", roles.ROLE_TECHFM_OA),
        ("lookup_work_order", roles.ROLE_SUPERVISOR),
        ("restore_work_order", roles.ROLE_SUPERVISOR),
        ("set_work_order_item_billing", roles.ROLE_TECHFM_OA),
    ],
)
def test_folded_work_order_gates_are_declarative(endpoint_name, expected):
    assert _min_role_for(work_orders_router, endpoint_name) == expected


def test_no_work_order_route_gates_on_a_role_inside_the_handler():
    # The point of C1, stated as an assertion rather than a line number: this
    # module raises no 403 of its own. A future route that reintroduces an
    # in-body rank check fails here, which is the anchor the old gates lacked.
    source = inspect.getsource(work_orders_router)
    assert "status_code=403" not in source


def test_the_role_gate_still_runs_before_the_size_check():
    # Moved here from test_upload_limits.py by C1. Order matters: an
    # unauthorised caller should learn that they are unauthorised, not what
    # the upload cap is.
    #
    # It used to be provable by calling the handler and watching statement
    # order. Now the gate is a dependency and the upload is a body param, and
    # *that pairing is the guarantee* -- FastAPI solves declared dependencies
    # before it reads the form body, so the 403 cannot lose to the 413. Assert
    # the pairing, since the ordering itself now belongs to the framework.
    route = _route(work_orders_router, "import_work_orders")

    assert _find_min_role(route.dependant) == roles.ROLE_TECHFM_OA
    assert "file" in {param.name for param in route.dependant.body_params}


def test_billing_gate_answers_before_the_body_is_validated():
    # The one deliberate semantic change in C1, pinned so it stays deliberate.
    #
    # `set_work_order_item_billing` used to check `_can_see_price(user)` in its
    # body, which runs *after* Pydantic. As a dependency the gate runs first,
    # so a request that is both malformed AND unauthorized now answers 403
    # where it answered 422. The SPA cannot send a malformed body, so this is
    # unreachable in practice -- but it is a real change at a permission
    # boundary, recorded with C1's decision record in git history.
    #
    # Like the test above, this pins the *mechanism* (gate is a dependency,
    # payload is a body param) rather than an observed status code: asserting
    # the status would need a real request through the ASGI stack, and the
    # mechanism is what a future edit would break.
    route = _route(work_orders_router, "set_work_order_item_billing")

    assert _find_min_role(route.dependant) == roles.ROLE_TECHFM_OA
    assert "payload" in {param.name for param in route.dependant.body_params}


@pytest.mark.parametrize(
    "endpoint_name",
    [
        "import_work_orders",
        "export_work_orders",
        "lookup_work_order",
        "restore_work_order",
        "set_work_order_item_billing",
        # Already declarative before C1, documented by it for consistency.
        "archive_work_order",
        "preview_legacy_work_order_archive",
        "archive_legacy_work_orders",
    ],
)
def test_every_gated_work_order_route_documents_its_403(endpoint_name):
    # Moving a gate into a dependency does not document it: FastAPI does not
    # infer a 403 from a dependency merely capable of raising one. Without
    # this, a declarative gate is exactly as invisible in the schema as the
    # in-body `raise` it replaced.
    route = _route(work_orders_router, endpoint_name)
    assert 403 in route.responses


@pytest.mark.parametrize(
    "endpoint_name",
    [
        "list_user_requests",
        "update_user_request",
        "list_request_siblings",
        "fulfill_item_request",
    ],
)
def test_user_request_routes_require_techfm_oa(endpoint_name):
    assert _min_role_for(user_requests_router, endpoint_name) == roles.ROLE_TECHFM_OA


def test_filing_an_item_request_has_no_static_min_role():
    # The one non-admin route on this router. A Technician who cannot find a
    # material is exactly the person who has to report it, so filing is gated
    # by what the caller is doing rather than by rank -- the same shape as
    # `POST /transactions/` above. Reading and resolving the queue stay Admin+,
    # which the parametrized test above pins.
    assert _min_role_for(user_requests_router, "create_item_request") is None


@pytest.mark.parametrize(
    "endpoint_name", ["list_request_siblings", "fulfill_item_request"]
)
def test_gated_item_request_routes_document_their_403(endpoint_name):
    # Same reasoning as the work-order routes: a dependency capable of raising
    # 403 does not document itself in the schema.
    route = _route(user_requests_router, endpoint_name)
    assert 403 in route.responses


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
            BackgroundTasks(),
            user=SimpleNamespace(id=uuid.uuid4(), role=roles.ROLE_TECHNICIAN),
            db=None,
        )
    assert exc.value.status_code == 403


def test_supervisor_cannot_edit_imported_work_order_metadata():
    with pytest.raises(HTTPException) as exc:
        work_orders_router.update_work_order(
            uuid.uuid4(),
            WorkOrderUpdate(location="Commons 101"),
            BackgroundTasks(),
            user=SimpleNamespace(id=uuid.uuid4(), role=roles.ROLE_SUPERVISOR),
            db=None,
        )
    assert exc.value.status_code == 403


def test_technician_can_save_work_order_notes(monkeypatch):
    work_order_id = uuid.uuid4()
    saved = SimpleNamespace(id=work_order_id)
    user = SimpleNamespace(id=uuid.uuid4(), role=roles.ROLE_TECHNICIAN)
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
        lambda work_order, *, include_price, viewer_id=None: work_order,
    )

    result = work_orders_router.update_work_order(
        work_order_id,
        WorkOrderUpdate(notes="  Gate code is 4123.  "),
        BackgroundTasks(),
        user=user,
        db=None,
    )

    assert result is saved
    assert captured == {"notes": "Gate code is 4123."}


def test_work_order_route_passes_precondition_and_returns_internal_detail(monkeypatch):
    work_order_id = uuid.uuid4()
    target_id = uuid.uuid4()
    saved = SimpleNamespace(id=work_order_id)
    user = SimpleNamespace(id=uuid.uuid4(), role=roles.ROLE_SUPERVISOR)
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
        lambda work_order, *, include_price, viewer_id=None: work_order,
    )

    result = work_orders_router.update_work_order(
        work_order_id,
        WorkOrderUpdate(
            supervisor_id=target_id,
            expected_supervisor_id=None,
        ),
        BackgroundTasks(),
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


def test_create_tool_requires_techfm_oa():
    assert _min_role_for(tools_router, "create_tool") == roles.ROLE_TECHFM_OA


def test_update_tool_requires_techfm_oa():
    assert _min_role_for(tools_router, "update_tool") == roles.ROLE_TECHFM_OA


def test_delete_tool_requires_techfm_oa():
    assert _min_role_for(tools_router, "delete_tool") == roles.ROLE_TECHFM_OA


def test_checkout_tool_requires_techfm_oa():
    assert _min_role_for(tools_router, "checkout_tool") == roles.ROLE_TECHFM_OA


def test_adjust_tool_requires_techfm_oa():
    assert _min_role_for(tools_router, "adjust_tool") == roles.ROLE_TECHFM_OA


@pytest.mark.parametrize(
    "endpoint_name",
    ["list_tools", "get_tool_by_barcode", "return_tool"],
)
def test_tool_routes_open_to_any_session_have_no_static_min_role(endpoint_name):
    # Viewing the Tools page/lookup and processing a return are open to any
    # authenticated role -- only checkout/create/edit/archive are TechFM OA+.
    assert _min_role_for(tools_router, endpoint_name) is None


def test_no_route_gate_is_left_at_the_admin_floor():
    # After the TechFM OA insert, every route that once read "Admin or above"
    # means "TechFM OA or above" -- the Admin floor survives in exactly one
    # place, and it is a service-level check inside the Review handoff, not a
    # route gate. A new route written with ROLE_ADMIN out of habit would
    # silently lock TechFM OA out of a capability it is supposed to have, and
    # nothing else in the suite would notice. This is that notice.
    #
    # If a genuinely Admin-only route is ever added, add its endpoint name to
    # the expected set here, deliberately and with a reason.
    from app.main import app as fastapi_app

    offenders = {
        route.endpoint.__name__
        for route in fastapi_app.routes
        if isinstance(route, APIRoute)
        and _find_min_role(route.dependant) == roles.ROLE_ADMIN
    }
    assert offenders == set()


def test_the_hub_is_open_to_any_authenticated_role():
    # Every role gets the personal block, Admin included: `POST
    # /tracking/start` is already Supervisor+ on any visible row, so a
    # supervisor with a running clock and no way to see it would be a
    # regression. The rank-gated payloads are separate endpoints.
    assert _min_role_for(hub_router, "get_hub") is None


def test_the_hub_route_still_requires_a_session():
    # "No minimum role" must not mean "no gate". `get_current_user` is the
    # 401 boundary and has to be in the dependant tree.
    from app.auth_deps import get_current_user

    def _uses(dependant):
        return any(
            sub.call is get_current_user or _uses(sub)
            for sub in dependant.dependencies
        )

    assert _uses(_route(hub_router, "get_hub").dependant) is True
