"""Review-queue invalidation at the work-order command boundary.

Task 10 deliberately does not publish a general work-order aggregate event.
Only commands capable of changing Admin Review membership or card fields emit
the collection-style invalidation consumed by that view.
"""

import inspect
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks
from fastapi import HTTPException

from app.domain import realtime as realtime_policy
from app.domain import roles
from app.domain.errors import PunchAlreadyOpenError, WorkOrderStateError
from app.logging_config import new_request_context, request_context
from app.routers import attendance as attendance_router
from app.routers import hub as hub_router
from app.routers import work_orders as work_orders_router
from app.schemas.work_orders import WorkOrderUpdate


REQUEST_ID = "task10req001"
IMPORT_SUMMARY = {
    "total": 1,
    "created": 1,
    "opened": 0,
    "closed": 0,
    "supervisors_matched": 0,
    "supervisors_unmatched": 0,
    "skipped": 0,
}


@pytest.fixture(autouse=True)
def _request_scope():
    token = request_context.set(new_request_context(REQUEST_ID))
    try:
        yield
    finally:
        request_context.reset(token)


def _capture_emits(monkeypatch, *, accepted=True):
    envelopes = []

    def capture(envelope):
        envelopes.append(envelope)
        return accepted

    monkeypatch.setattr(work_orders_router.realtime_service, "emit", capture)
    return envelopes


def _passthrough_detail(monkeypatch):
    monkeypatch.setattr(
        work_orders_router,
        "_detail",
        lambda work_order, *, include_price, viewer_id=None: work_order,
    )


def test_update_emits_after_the_command_and_before_response_hydration(monkeypatch):
    work_order_id = uuid.uuid4()
    saved = SimpleNamespace(id=work_order_id)
    user = SimpleNamespace(id=uuid.uuid4(), role=roles.ROLE_ADMIN)
    order = []
    envelopes = []

    def update(db, incoming_id, *, user, fields):
        order.append("command")
        return saved

    def emit(envelope):
        order.append("emit")
        envelopes.append(envelope)
        return True

    def get(db, incoming_id, *, user):
        order.append("hydrate")
        return saved

    monkeypatch.setattr(work_orders_router.wo_service, "update_work_order", update)
    monkeypatch.setattr(work_orders_router.realtime_service, "emit", emit)
    monkeypatch.setattr(work_orders_router.wo_service, "get_work_order", get)
    _passthrough_detail(monkeypatch)

    result = work_orders_router.update_work_order(
        work_order_id,
        WorkOrderUpdate(notes="Changed"),
        BackgroundTasks(),
        user=user,
        db=None,
    )

    assert result is saved
    assert order == ["command", "emit", "emit", "hydrate"]
    assert envelopes == [
        {
            "type": realtime_policy.EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED,
            "id": str(work_order_id),
            "req": REQUEST_ID,
        },
        {
            "type": realtime_policy.EVENT_WORK_ORDER_STATUS_CHANGED,
            "id": str(work_order_id),
            "req": REQUEST_ID,
        },
    ]


def test_archive_emits_one_entity_invalidation(monkeypatch):
    work_order_id = uuid.uuid4()
    user = SimpleNamespace(id=uuid.uuid4(), role=roles.ROLE_ADMIN)
    envelopes = _capture_emits(monkeypatch)
    monkeypatch.setattr(
        work_orders_router.wo_service,
        "archive_work_order",
        lambda db, incoming_id, *, user: None,
    )

    result = work_orders_router.archive_work_order(work_order_id, user=user, db=None)

    assert result is None
    assert envelopes == [
        {
            "type": realtime_policy.EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED,
            "id": str(work_order_id),
            "req": REQUEST_ID,
        },
        {
            "type": realtime_policy.EVENT_WORK_ORDER_STATUS_CHANGED,
            "id": str(work_order_id),
            "req": REQUEST_ID,
        },
    ]


def test_restore_emits_even_when_the_successful_command_is_a_noop(monkeypatch):
    work_order_id = uuid.uuid4()
    saved = SimpleNamespace(id=work_order_id)
    user = SimpleNamespace(id=uuid.uuid4(), role=roles.ROLE_SUPERVISOR)
    envelopes = _capture_emits(monkeypatch)
    monkeypatch.setattr(
        work_orders_router.wo_service,
        "restore_work_order",
        lambda db, incoming_id, *, user: saved,
    )
    monkeypatch.setattr(
        work_orders_router.wo_service,
        "get_work_order",
        lambda db, incoming_id, *, user: saved,
    )
    _passthrough_detail(monkeypatch)

    result = work_orders_router.restore_work_order(work_order_id, user=user, db=None)

    assert result is saved
    assert envelopes[0]["id"] == str(work_order_id)


def test_import_emits_one_collection_invalidation(monkeypatch):
    user = SimpleNamespace(id=uuid.uuid4(), role=roles.ROLE_ADMIN)
    envelopes = _capture_emits(monkeypatch)
    monkeypatch.setattr(work_orders_router, "read_capped", lambda *args, **kwargs: b"csv")
    monkeypatch.setattr(
        work_orders_router.wo_service,
        "import_work_orders",
        lambda db, *, csv_bytes, user: IMPORT_SUMMARY,
    )

    result = work_orders_router.import_work_orders(
        BackgroundTasks(), file=object(), user=user, db=None
    )

    assert result.created == 1
    assert envelopes == [
        {
            "type": realtime_policy.EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED,
            "id": None,
            "req": REQUEST_ID,
        },
        {
            "type": realtime_policy.EVENT_WORK_ORDER_STATUS_CHANGED,
            "id": None,
            "req": REQUEST_ID,
        }
    ]


def test_zero_row_legacy_archive_still_emits_one_collection_invalidation(monkeypatch):
    user = SimpleNamespace(id=uuid.uuid4(), role=roles.ROLE_OWNER)
    envelopes = _capture_emits(monkeypatch)
    monkeypatch.setattr(
        work_orders_router.wo_service,
        "archive_live_legacy_work_orders",
        lambda db, *, user: 0,
    )

    result = work_orders_router.archive_legacy_work_orders(user=user, db=None)

    assert result.archived == 0
    assert envelopes == [
        {
            "type": realtime_policy.EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED,
            "id": None,
            "req": REQUEST_ID,
        },
        {
            "type": realtime_policy.EVENT_WORK_ORDER_STATUS_CHANGED,
            "id": None,
            "req": REQUEST_ID,
        }
    ]


def test_a_command_failure_emits_nothing(monkeypatch):
    work_order_id = uuid.uuid4()
    user = SimpleNamespace(id=uuid.uuid4(), role=roles.ROLE_ADMIN)
    envelopes = _capture_emits(monkeypatch)

    def fail(db, incoming_id, *, user, fields):
        raise WorkOrderStateError("not durable")

    monkeypatch.setattr(work_orders_router.wo_service, "update_work_order", fail)

    with pytest.raises(HTTPException):
        work_orders_router.update_work_order(
            work_order_id,
            WorkOrderUpdate(notes="Changed"),
            BackgroundTasks(),
            user=user,
            db=None,
        )

    assert envelopes == []


def test_a_dropped_invalidation_never_changes_the_http_result(monkeypatch):
    work_order_id = uuid.uuid4()
    saved = SimpleNamespace(id=work_order_id)
    user = SimpleNamespace(id=uuid.uuid4(), role=roles.ROLE_ADMIN)
    envelopes = _capture_emits(monkeypatch, accepted=False)
    monkeypatch.setattr(
        work_orders_router.wo_service,
        "update_work_order",
        lambda db, incoming_id, *, user, fields: saved,
    )
    monkeypatch.setattr(
        work_orders_router.wo_service,
        "get_work_order",
        lambda db, incoming_id, *, user: saved,
    )
    _passthrough_detail(monkeypatch)

    result = work_orders_router.update_work_order(
        work_order_id,
        WorkOrderUpdate(notes="Changed"),
        BackgroundTasks(),
        user=user,
        db=None,
    )

    assert result is saved
    assert len(envelopes) == 2


@pytest.mark.parametrize(
    "route_name",
    ["start_work_order", "complete_work_order", "hold_work_order", "resume_work_order"],
)
def test_each_walkthrough_transition_emits_one_status_invalidation(
    monkeypatch, route_name
):
    """The four assigned-worker transitions are the whole reason this event
    exists: they change the status a card renders and emitted nothing before."""
    work_order_id = uuid.uuid4()
    saved = SimpleNamespace(id=work_order_id)
    user = SimpleNamespace(id=uuid.uuid4(), role=roles.ROLE_TECHNICIAN)
    envelopes = _capture_emits(monkeypatch)
    monkeypatch.setattr(
        work_orders_router.wo_service,
        route_name,
        lambda db, incoming_id, *, user: saved,
    )
    monkeypatch.setattr(
        work_orders_router.wo_service,
        "get_work_order",
        lambda db, incoming_id, *, user: saved,
    )
    _passthrough_detail(monkeypatch)

    # Finishing and pausing both notify, so both take a BackgroundTasks.
    # Start and resume still do not.
    extra = (
        {"background": BackgroundTasks()}
        if route_name in ("complete_work_order", "hold_work_order")
        else {}
    )
    result = getattr(work_orders_router, route_name)(
        work_order_id, user=user, db=None, **extra
    )

    assert result is saved
    assert envelopes == [
        {
            "type": realtime_policy.EVENT_WORK_ORDER_STATUS_CHANGED,
            "id": str(work_order_id),
            "req": REQUEST_ID,
        }
    ]


def test_a_failed_transition_emits_nothing(monkeypatch):
    work_order_id = uuid.uuid4()
    user = SimpleNamespace(id=uuid.uuid4(), role=roles.ROLE_TECHNICIAN)
    envelopes = _capture_emits(monkeypatch)

    def fail(db, incoming_id, *, user):
        raise WorkOrderStateError("not in progress")

    monkeypatch.setattr(work_orders_router.wo_service, "complete_work_order", fail)

    with pytest.raises(HTTPException):
        work_orders_router.complete_work_order(
            work_order_id, BackgroundTasks(), user=user, db=None
        )

    assert envelopes == []


def _route_source(endpoint):
    """A route's own source, plus `run_csv_import`'s when it delegates there.

    `import_work_orders` calls the shared `run_csv_import` (IMP-039) rather
    than emitting inline, so a literal scan of the route alone would miss it.
    """

    source = inspect.getsource(endpoint)
    if "run_csv_import(" in source:
        source += inspect.getsource(work_orders_router.run_csv_import)
    return source


def test_the_review_queue_emitter_set_is_exactly_the_capable_routes():
    emitters = {
        route.endpoint.__name__
        for route in work_orders_router.router.routes
        if route.endpoint.__module__ == work_orders_router.__name__
        and "_emit_review_queue_changed(" in _route_source(route.endpoint)
    }

    assert emitters == {
        "import_work_orders",
        "archive_legacy_work_orders",
        "update_work_order",
        "archive_work_order",
        "restore_work_order",
    }


def test_restore_emits_a_collection_style_status_invalidation(monkeypatch):
    """A restored work order is on nobody's screen, so no on-screen card can be
    updated in place. `None` is the established collection signal (import and
    bulk legacy archive both use it) and tells the client to refetch its list."""
    work_order_id = uuid.uuid4()
    saved = SimpleNamespace(id=work_order_id)
    user = SimpleNamespace(id=uuid.uuid4(), role=roles.ROLE_SUPERVISOR)
    envelopes = _capture_emits(monkeypatch)
    monkeypatch.setattr(
        work_orders_router.wo_service,
        "restore_work_order",
        lambda db, incoming_id, *, user: saved,
    )
    monkeypatch.setattr(
        work_orders_router.wo_service,
        "get_work_order",
        lambda db, incoming_id, *, user: saved,
    )
    _passthrough_detail(monkeypatch)

    work_orders_router.restore_work_order(work_order_id, user=user, db=None)

    assert [e["type"] for e in envelopes] == [
        realtime_policy.EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED,
        realtime_policy.EVENT_WORK_ORDER_STATUS_CHANGED,
    ]
    assert envelopes[1]["id"] is None


def test_archive_emits_an_entity_style_status_invalidation(monkeypatch):
    """Archive is surgical, not collection: the card IS on screen, so the client
    refetches it, gets a 404 from the scoping, and drops that one row."""
    work_order_id = uuid.uuid4()
    user = SimpleNamespace(id=uuid.uuid4(), role=roles.ROLE_ADMIN)
    envelopes = _capture_emits(monkeypatch)
    monkeypatch.setattr(
        work_orders_router.wo_service,
        "archive_work_order",
        lambda db, incoming_id, *, user: None,
    )

    work_orders_router.archive_work_order(work_order_id, user=user, db=None)

    assert envelopes[1] == {
        "type": realtime_policy.EVENT_WORK_ORDER_STATUS_CHANGED,
        "id": str(work_order_id),
        "req": REQUEST_ID,
    }


def test_the_status_emitter_set_includes_the_two_membership_commands():
    """Mirrors the review-queue emitter-set test. Any future route able to change
    a work order's status or its card summary must join this set deliberately.

    The two tracking routes belong here because starting a clock advances a
    pre-work row to In-Progress (and resumes an On-Hold one), and stopping the
    last clock puts the row back On-Hold -- both change the badge on a card
    somebody else may be looking at."""
    emitters = {
        route.endpoint.__name__
        for route in work_orders_router.router.routes
        if route.endpoint.__module__ == work_orders_router.__name__
        and "_emit_status_changed(" in _route_source(route.endpoint)
    }

    assert emitters == {
        "import_work_orders",
        "archive_legacy_work_orders",
        "start_work_order",
        "start_work_order_tracking",
        "stop_work_order_tracking",
        "complete_work_order",
        "hold_work_order",
        "resume_work_order",
        "update_work_order",
        "archive_work_order",
        "restore_work_order",
        # S12: the witness sign-off changes the card another copy may be showing.
        "save_work_order_signature",
        "clear_work_order_signature",
        # Live card body: material and labor lines change the open card.
        *(route for route, *_ in LINE_ROUTES),
    }


def test_the_labor_session_emitter_set_is_exactly_the_two_tracking_routes():
    """A crew board (spec §5.3) needs to know when *anyone's* clock starts or
    stops. Only the two tracking routes can change that -- adding a route
    here without an audience decision is exactly what this tripwire catches."""
    emitters = {
        route.endpoint.__name__
        for route in work_orders_router.router.routes
        if route.endpoint.__module__ == work_orders_router.__name__
        and "_emit_labor_session_changed(" in inspect.getsource(route.endpoint)
    }

    assert emitters == {
        "start_work_order_tracking",
        "stop_work_order_tracking",
    }


def test_starting_a_clock_emits_a_labor_session_changed_envelope(monkeypatch):
    work_order_id = uuid.uuid4()
    saved = SimpleNamespace(id=work_order_id)
    user = SimpleNamespace(id=uuid.uuid4(), role=roles.ROLE_TECHNICIAN)
    envelopes = _capture_emits(monkeypatch)
    # The route now opens an attendance punch before starting the clock
    # (D3). This test drives the handler directly against `db=None`, so the
    # coupling is stubbed out the same way the labor call is.
    monkeypatch.setattr(
        work_orders_router.attendance_service,
        "ensure_punch_for_labor_start",
        lambda db, *, user: None,
    )
    monkeypatch.setattr(
        work_orders_router.wo_service,
        "start_labor_session",
        lambda db, incoming_id, *, user, notes_acknowledged=False: saved,
    )
    # Likewise the prior-work gate, which reads the row through `db`.
    monkeypatch.setattr(
        work_orders_router.wo_service,
        "get_visible_work_order",
        lambda db, incoming_id, user: saved,
    )
    monkeypatch.setattr(
        work_orders_router.wo_service,
        "require_prior_work_acknowledged",
        lambda db, work_order, user, acknowledged: None,
    )
    monkeypatch.setattr(
        work_orders_router.wo_service, "side_transitions", lambda work_order: []
    )
    monkeypatch.setattr(
        work_orders_router.wo_service,
        "get_work_order",
        lambda db, incoming_id, *, user: saved,
    )
    _passthrough_detail(monkeypatch)

    work_orders_router.start_work_order_tracking(
        work_order_id, BackgroundTasks(), user=user, db=None
    )

    assert [e["type"] for e in envelopes] == [
        realtime_policy.EVENT_WORK_ORDER_STATUS_CHANGED,
        realtime_policy.EVENT_LABOR_SESSION_CHANGED,
    ]
    assert envelopes[1]["id"] is None


def test_stopping_a_clock_emits_a_labor_session_changed_envelope(monkeypatch):
    work_order_id = uuid.uuid4()
    saved = SimpleNamespace(id=work_order_id)
    user = SimpleNamespace(id=uuid.uuid4(), role=roles.ROLE_TECHNICIAN)
    envelopes = _capture_emits(monkeypatch)
    monkeypatch.setattr(
        work_orders_router.wo_service,
        "stop_labor_session",
        lambda db, incoming_id, *, user: saved,
    )
    monkeypatch.setattr(
        work_orders_router,
        "_notify_auto_hold",
        lambda db, background, work_order, *, actor_id: None,
    )
    monkeypatch.setattr(
        work_orders_router.wo_service,
        "get_work_order",
        lambda db, incoming_id, *, user: saved,
    )
    _passthrough_detail(monkeypatch)

    work_orders_router.stop_work_order_tracking(
        work_order_id, BackgroundTasks(), user=user, db=None
    )

    assert [e["type"] for e in envelopes] == [
        realtime_policy.EVENT_WORK_ORDER_STATUS_CHANGED,
        realtime_policy.EVENT_LABOR_SESSION_CHANGED,
    ]
    assert envelopes[1]["id"] is None


# --- card-body lines (live card body, stage 2 Task 5) ---------------------

LINE_ROUTES = [
    # (route, service, call args after work_order_id)
    ("add_work_order_item", "add_work_order_item", ("payload", "background")),
    ("update_work_order_item", "update_work_order_item", ("line", "payload", "background")),
    ("set_work_order_item_billing", "set_work_order_item_billable", ("line", "payload")),
    ("delete_work_order_item", "delete_work_order_item", ("line", "background")),
    ("add_work_order_labor", "add_work_order_labor", ("payload",)),
    ("update_work_order_labor", "update_work_order_labor", ("line", "payload")),
    ("delete_work_order_labor", "delete_work_order_labor", ("line",)),
]


@pytest.mark.parametrize("route_name,service_name,args", LINE_ROUTES)
def test_each_material_and_labor_write_emits_the_work_order(
    monkeypatch, route_name, service_name, args
):
    """A material or labor change alters the open card's body, so another
    copy of the card must hear about it (risk register #28)."""
    work_order_id = uuid.uuid4()
    user = SimpleNamespace(id=uuid.uuid4(), role=roles.ROLE_OWNER)
    envelopes = _capture_emits(monkeypatch)
    monkeypatch.setattr(work_orders_router.wo_service, service_name, lambda *a, **k: object())
    monkeypatch.setattr(work_orders_router, "flush_stock_events", lambda db, background: None)
    monkeypatch.setattr(work_orders_router, "_line_detail", lambda line, *, include_price: line)
    monkeypatch.setattr(work_orders_router, "_labor_detail", lambda entry: entry)
    payload = SimpleNamespace(
        item_id=uuid.uuid4(), quantity=1, material_request_id=None,
        billable_quantity=None, technician_id=uuid.uuid4(), minutes=30,
        model_fields_set=set(),
    )
    values = {"payload": payload, "background": BackgroundTasks(), "line": uuid.uuid4()}

    getattr(work_orders_router, route_name)(
        work_order_id, *(values[a] for a in args), user=user, db=None
    )

    assert envelopes == [
        {
            "type": realtime_policy.EVENT_WORK_ORDER_STATUS_CHANGED,
            "id": str(work_order_id),
            "req": REQUEST_ID,
        }
    ]


def test_a_refused_material_write_emits_nothing(monkeypatch):
    user = SimpleNamespace(id=uuid.uuid4(), role=roles.ROLE_TECHNICIAN)
    envelopes = _capture_emits(monkeypatch)

    def refuse(*args, **kwargs):
        raise WorkOrderStateError("not allowed")

    monkeypatch.setattr(work_orders_router.wo_service, "delete_work_order_item", refuse)

    with pytest.raises(HTTPException):
        work_orders_router.delete_work_order_item(
            uuid.uuid4(), uuid.uuid4(), BackgroundTasks(), user=user, db=None
        )
    assert envelopes == []


def test_a_material_add_that_fails_validation_emits_nothing(monkeypatch, db):
    """Over real HTTP: a body the schema refuses never reaches the emit."""
    from fastapi.testclient import TestClient

    from app.database import get_db
    from app.main import app
    from app.models import User
    from app.services import auth as auth_service

    envelopes = _capture_emits(monkeypatch)
    owner = User(username=f"u-{uuid.uuid4().hex[:10]}",
                 password_hash=auth_service.hash_password("hunter2"), role=roles.ROLE_OWNER)
    db.add(owner); db.commit()
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            client.cookies.set("session", auth_service.create_session(db, owner))
            response = client.post(f"/work-orders/{uuid.uuid4()}/items", json={"quantity": "lots"})
    finally:
        del app.dependency_overrides[get_db]
    assert response.status_code == 422
    assert envelopes == []


SMR_ROUTES = [
    # (route, service module, service, first arg is the order or a line/block, extra args)
    ("set_ready", "smr_service", "set_ready", "order", (SimpleNamespace(ready=True),)),
    ("set_paper_reviewed", "smr_service", "set_paper_reviewed", "order", (SimpleNamespace(reviewed=True),)),
    ("generate_block", "lines_service", "generate_block", "order", (None,)),
    ("add_line", "lines_service", "add_line", "order", (SimpleNamespace(),)),
    ("edit_line", "lines_service", "edit_line", "line", (SimpleNamespace(),)),
    ("delete_line", "lines_service", "delete_line", "line", ()),
    ("mark_pasted", "lines_service", "mark_pasted", "line", ()),
]


@pytest.mark.parametrize("route_name,module_attr,service_name,first,extra", SMR_ROUTES)
def test_each_smr_card_write_emits_the_work_order(
    monkeypatch, route_name, module_attr, service_name, first, extra
):
    """Line routes carry no work order in the path: the id comes back from
    the service (the saved line or block, or the deleted line's order)."""
    from app.routers import work_orders_smr as smr_router

    work_order_id = uuid.uuid4()
    user = SimpleNamespace(id=uuid.uuid4(), role=roles.ROLE_OWNER)
    envelopes = _capture_emits(monkeypatch)
    result = work_order_id if route_name == "delete_line" else SimpleNamespace(work_order_id=work_order_id)
    monkeypatch.setattr(getattr(smr_router, module_attr), service_name, lambda *a, **k: result)
    first_arg = work_order_id if first == "order" else uuid.uuid4()

    getattr(smr_router, route_name)(first_arg, *extra, user=user, db=None)

    assert envelopes == [
        {
            "type": realtime_policy.EVENT_WORK_ORDER_STATUS_CHANGED,
            "id": str(work_order_id),
            "req": REQUEST_ID,
        }
    ]


def test_a_refused_smr_line_edit_emits_nothing(monkeypatch):
    from app.routers import work_orders_smr as smr_router

    user = SimpleNamespace(id=uuid.uuid4(), role=roles.ROLE_ADMIN)
    envelopes = _capture_emits(monkeypatch)

    def refuse(*args, **kwargs):
        raise WorkOrderStateError("Nothing to change.")

    monkeypatch.setattr(smr_router.lines_service, "edit_line", refuse)

    with pytest.raises(HTTPException):
        smr_router.edit_line(uuid.uuid4(), SimpleNamespace(), user=user, db=None)
    assert envelopes == []


def test_the_smr_status_emitter_set_is_exactly_the_card_writes():
    """Tripwire like the work-order set: an SMR route joins only by decision."""
    from app.routers import work_orders_smr as smr_router

    emitters = {
        route.endpoint.__name__
        for route in smr_router.router.routes
        if "_emit_status_changed(" in inspect.getsource(route.endpoint)
    }

    assert emitters == {route for route, *_ in SMR_ROUTES}


# --- attendance ---------------------------------------------------------


def test_the_attendance_emitter_set_is_exactly_the_punch_writes():
    """Every write to the pay record invalidates the Admin roster; nothing
    else may. The two reads (`GET /attendance/me`, the week) are absent by
    design. The set is the two self-scoped punch routes, the four Admin
    punch writes, plus the bulk week review, which clears punch review
    flags. The midnight sweep emits nothing: every read computes the cap.

    The auto-punch on a work-order clock start needs no emit of its own: that
    route already emits `labor.session.changed`, which the live layer also
    subscribes to."""
    emitters = {
        route.endpoint.__name__
        for module in (attendance_router, hub_router)
        for route in module.router.routes
        if route.endpoint.__module__ == module.__name__
        and "emit_attendance_changed(" in inspect.getsource(route.endpoint)
    }

    assert emitters == {
        "punch_in",
        "punch_out",
        "switch",
        "add_hub_attendance_punch",
        "edit_hub_attendance_punch",
        "clock_out_hub_attendance_user",
        "delete_hub_attendance_punch",
        "review_hub_attendance_week",
    }


def test_a_punch_in_emits_an_attendance_changed_envelope(monkeypatch):
    user = SimpleNamespace(id=uuid.uuid4(), role=roles.ROLE_TECHNICIAN)
    envelopes = _capture_emits(monkeypatch)
    monkeypatch.setattr(
        attendance_router.attendance_service, "punch_in",
        lambda db, *, user, shop=False: SimpleNamespace(id=uuid.uuid4()),
    )

    attendance_router.punch_in(user=user, db=None)

    assert [e["type"] for e in envelopes] == [
        realtime_policy.EVENT_ATTENDANCE_CHANGED
    ]
    assert envelopes[0]["id"] is None


def test_a_failed_punch_in_emits_nothing(monkeypatch):
    """The emit sits after the service returns, so a 409 on the already-open
    rule never tells an Admin something changed."""
    user = SimpleNamespace(id=uuid.uuid4(), role=roles.ROLE_TECHNICIAN)
    envelopes = _capture_emits(monkeypatch)

    def _refuse(db, *, user, shop=False):
        raise PunchAlreadyOpenError(
            "already on shift", punch_id=uuid.uuid4(),
            started_at=datetime(2026, 9, 21, 13, 0, tzinfo=timezone.utc))

    monkeypatch.setattr(attendance_router.attendance_service, "punch_in", _refuse)

    with pytest.raises(HTTPException):
        attendance_router.punch_in(user=user, db=None)
    assert envelopes == []


# --- messages -----------------------------------------------------------


def test_emit_message_changed_is_targeted_and_carries_no_text(monkeypatch):
    from app.routers import _message_events

    calls = []
    monkeypatch.setattr(
        _message_events.realtime_service,
        "emit",
        lambda envelope, *, user_ids=None: calls.append((envelope, user_ids)) or True,
    )
    conversation_id = uuid.uuid4()
    members = [uuid.uuid4(), uuid.uuid4()]

    _message_events.emit_message_changed(conversation_id, members)

    assert calls == [
        (
            {
                "type": realtime_policy.EVENT_MESSAGE_CHANGED,
                "id": str(conversation_id),
                "req": REQUEST_ID,
            },
            members,
        )
    ]


def test_the_message_emitter_set_is_exactly_the_chat_writes():
    """Sending, reading, starting and ending a group change what members
    see; opening a direct chat (no message yet) and every read do not."""
    from app.routers import messages as messages_router

    emitters = {
        route.endpoint.__name__
        for route in messages_router.router.routes
        if route.endpoint.__module__ == messages_router.__name__
        and "emit_message_changed(" in inspect.getsource(route.endpoint)
    }

    assert emitters == {"send_message", "broadcast", "mark_read", "create_group", "end_group"}
