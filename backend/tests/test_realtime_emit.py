"""Review-queue invalidation at the work-order command boundary.

Task 10 deliberately does not publish a general work-order aggregate event.
Only commands capable of changing Admin Review membership or card fields emit
the collection-style invalidation consumed by that view.
"""

import inspect
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.domain import realtime as realtime_policy
from app.domain import roles
from app.domain.errors import WorkOrderStateError
from app.logging_config import new_request_context, request_context
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
        lambda work_order, *, include_price: work_order,
    )


def test_update_emits_after_the_command_and_before_response_hydration(monkeypatch):
    work_order_id = uuid.uuid4()
    saved = SimpleNamespace(id=work_order_id)
    user = SimpleNamespace(role=roles.ROLE_ADMIN)
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
        user=user,
        db=None,
    )

    assert result is saved
    assert order == ["command", "emit", "hydrate"]
    assert envelopes == [
        {
            "type": realtime_policy.EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED,
            "id": str(work_order_id),
            "req": REQUEST_ID,
        }
    ]


def test_archive_emits_one_entity_invalidation(monkeypatch):
    work_order_id = uuid.uuid4()
    user = SimpleNamespace(role=roles.ROLE_ADMIN)
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
        }
    ]


def test_restore_emits_even_when_the_successful_command_is_a_noop(monkeypatch):
    work_order_id = uuid.uuid4()
    saved = SimpleNamespace(id=work_order_id)
    user = SimpleNamespace(role=roles.ROLE_SUPERVISOR)
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
    user = SimpleNamespace(role=roles.ROLE_ADMIN)
    envelopes = _capture_emits(monkeypatch)
    monkeypatch.setattr(work_orders_router, "read_capped", lambda *args, **kwargs: b"csv")
    monkeypatch.setattr(
        work_orders_router.wo_service,
        "import_work_orders",
        lambda db, *, csv_bytes, user: IMPORT_SUMMARY,
    )

    result = work_orders_router.import_work_orders(file=object(), user=user, db=None)

    assert result.created == 1
    assert envelopes == [
        {
            "type": realtime_policy.EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED,
            "id": None,
            "req": REQUEST_ID,
        }
    ]


def test_zero_row_legacy_archive_still_emits_one_collection_invalidation(monkeypatch):
    user = SimpleNamespace(role=roles.ROLE_OWNER)
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
        }
    ]


def test_a_command_failure_emits_nothing(monkeypatch):
    work_order_id = uuid.uuid4()
    user = SimpleNamespace(role=roles.ROLE_ADMIN)
    envelopes = _capture_emits(monkeypatch)

    def fail(db, incoming_id, *, user, fields):
        raise WorkOrderStateError("not durable")

    monkeypatch.setattr(work_orders_router.wo_service, "update_work_order", fail)

    with pytest.raises(HTTPException):
        work_orders_router.update_work_order(
            work_order_id,
            WorkOrderUpdate(notes="Changed"),
            user=user,
            db=None,
        )

    assert envelopes == []


def test_a_dropped_invalidation_never_changes_the_http_result(monkeypatch):
    work_order_id = uuid.uuid4()
    saved = SimpleNamespace(id=work_order_id)
    user = SimpleNamespace(role=roles.ROLE_ADMIN)
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
        user=user,
        db=None,
    )

    assert result is saved
    assert len(envelopes) == 1


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
    user = SimpleNamespace(role=roles.ROLE_TECHNICIAN)
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

    result = getattr(work_orders_router, route_name)(
        work_order_id, user=user, db=None
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
    user = SimpleNamespace(role=roles.ROLE_TECHNICIAN)
    envelopes = _capture_emits(monkeypatch)

    def fail(db, incoming_id, *, user):
        raise WorkOrderStateError("not in progress")

    monkeypatch.setattr(work_orders_router.wo_service, "complete_work_order", fail)

    with pytest.raises(HTTPException):
        work_orders_router.complete_work_order(work_order_id, user=user, db=None)

    assert envelopes == []


def test_the_review_queue_emitter_set_is_exactly_the_five_capable_routes():
    emitters = {
        route.endpoint.__name__
        for route in work_orders_router.router.routes
        if route.endpoint.__module__ == work_orders_router.__name__
        and "_emit_review_queue_changed(" in inspect.getsource(route.endpoint)
    }

    assert emitters == {
        "import_work_orders",
        "archive_legacy_work_orders",
        "update_work_order",
        "archive_work_order",
        "restore_work_order",
    }
