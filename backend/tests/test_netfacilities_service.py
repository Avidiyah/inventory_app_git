"""Database-backed, offline tests for the NetFacilities enrichment contract."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
import uuid

from sqlalchemy.orm import Session

from app.domain import work_orders as wo
from app.integrations.netfacilities.errors import (
    NetFacilitiesAuthenticationRequired,
    NetFacilitiesPermissionDenied,
    NetFacilitiesWorkOrderNotFound,
)
from app.models import WorkOrder
from app.services import netfacilities as service


@dataclass(frozen=True)
class SourceWorkOrder:
    work_order_number: str
    description: str
    priority: str | None

    @property
    def status(self):  # pragma: no cover - access is a test failure
        raise AssertionError("enrichment must not read source status")


class FakeClient:
    def __init__(self, outcomes, *, before_return=None, delay=0):
        self.outcomes = outcomes
        self.before_return = before_return
        self.delay = delay
        self.calls = []

    async def get_work_order(self, number):
        self.calls.append(number)
        if self.delay:
            await asyncio.sleep(self.delay)
        outcome = self.outcomes[number]
        if self.before_return is not None:
            self.before_return(number)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _number() -> str:
    return str(10_000_000_000 + uuid.uuid4().int % 8_000_000_000)


def _row(
    number: str,
    *,
    description: str | None,
    priority: str | None,
    archived=False,
) -> WorkOrder:
    return WorkOrder(
        number=number,
        description=description,
        priority=priority,
        status="in_progress",
        entry_mode="dispense",
        archived_at=datetime.now(timezone.utc) if archived else None,
        legacy=False,
    )


def _session_factory(db):
    """Fresh sessions sharing pytest's rollback-owned connection."""

    connection = db.connection()

    def factory():
        return Session(
            bind=connection,
            join_transaction_mode="create_savepoint",
            autoflush=False,
        )

    return factory


def _candidate(row: WorkOrder) -> service.EnrichmentCandidate:
    return service.EnrichmentCandidate(
        id=row.id,
        number=row.number,
        description=row.description,
        priority=row.priority,
    )


def _run(factory, client, *, timeout=30):
    return asyncio.run(
        service.enrich_work_orders(
            session_factory=factory,
            client=client,
            batch_timeout_seconds=timeout,
        )
    )


def test_candidate_union_is_exact_deterministic_and_excludes_archived_rows(db):
    fallback_only = _row(
        _number(),
        description=None,
        priority="Normal",
    )
    fallback_only.description = wo.work_order_task_fallback(fallback_only.number)
    priority_only = _row(
        _number(),
        description="Manual description",
        priority="   ",
    )
    complete = _row(
        _number(),
        description="Manual description",
        priority="Normal",
    )
    lookalike = _row(_number(), description=None, priority="Normal")
    lookalike.description = f"{wo.work_order_task_fallback(lookalike.number)}/extra"
    archived = _row(
        _number(),
        description="placeholder",
        priority=None,
        archived=True,
    )
    archived.description = wo.work_order_task_fallback(archived.number)
    db.add_all([fallback_only, priority_only, complete, lookalike, archived])
    db.commit()

    candidates = service._load_candidates(_session_factory(db))
    selected = [candidate for candidate in candidates if candidate.id in {
        fallback_only.id,
        priority_only.id,
        complete.id,
        lookalike.id,
        archived.id,
    }]

    assert {candidate.id for candidate in selected} == {
        fallback_only.id,
        priority_only.id,
    }
    assert [candidate.number for candidate in selected] == sorted(
        [fallback_only.number, priority_only.number]
    )


def test_apply_never_creates_a_missing_work_order(db):
    factory = _session_factory(db)
    candidate = service.EnrichmentCandidate(
        id=uuid.uuid4(),
        number=_number(),
        description=None,
        priority=None,
    )

    result = service._apply_candidate(
        factory,
        candidate,
        "Source task",
        "Emergency",
    )

    assert result == service.ApplyResult()
    assert db.get(WorkOrder, candidate.id) is None


def test_independent_updates_and_stale_candidate_retry_are_idempotent(db, monkeypatch):
    both = _row(_number(), description=None, priority=None)
    both.description = wo.work_order_task_fallback(both.number)
    description_only = _row(_number(), description=None, priority="Existing")
    description_only.description = wo.work_order_task_fallback(description_only.number)
    priority_only = _row(_number(), description="Manual task", priority=" ")
    db.add_all([both, description_only, priority_only])
    db.commit()
    candidates = [_candidate(row) for row in (both, description_only, priority_only)]
    candidates.sort(key=lambda candidate: candidate.number)
    monkeypatch.setattr(service, "_load_candidates", lambda _factory: candidates)

    outcomes = {
        both.number: SourceWorkOrder(both.number, "Source both", "Emergency"),
        description_only.number: SourceWorkOrder(
            description_only.number, "Source description", "Ignored"
        ),
        priority_only.number: SourceWorkOrder(
            priority_only.number, "Ignored description", "Routine"
        ),
    }
    factory = _session_factory(db)
    first = _run(factory, FakeClient(outcomes))

    assert first.candidates == 3
    assert first.requests_attempted == 3
    assert first.fetched == 3
    assert first.descriptions_updated == 2
    assert first.priorities_updated == 2
    assert first.unchanged == 0
    db.expire_all()
    assert db.get(WorkOrder, both.id).description == "Source both"
    assert db.get(WorkOrder, both.id).priority == "Emergency"
    assert db.get(WorkOrder, description_only.id).description == "Source description"
    assert db.get(WorkOrder, description_only.id).priority == "Existing"
    assert db.get(WorkOrder, priority_only.id).description == "Manual task"
    assert db.get(WorkOrder, priority_only.id).priority == "Routine"
    assert all(db.get(WorkOrder, row.id).status == "in_progress" for row in (
        both,
        description_only,
        priority_only,
    ))

    second = _run(factory, FakeClient(outcomes))
    assert second.descriptions_updated == 0
    assert second.priorities_updated == 0
    assert second.unchanged == 3


def test_compare_and_set_preserves_concurrent_manual_values(db, monkeypatch):
    row = _row(_number(), description=None, priority=None)
    row.description = wo.work_order_task_fallback(row.number)
    db.add(row)
    db.commit()
    candidate = _candidate(row)
    monkeypatch.setattr(service, "_load_candidates", lambda _factory: [candidate])
    factory = _session_factory(db)

    def edit_while_fetching(_number):
        with factory() as other:
            current = other.get(WorkOrder, row.id)
            current.description = "Concurrent manual task"
            current.priority = "Concurrent manual priority"
            other.commit()

    client = FakeClient(
        {row.number: SourceWorkOrder(row.number, "Source task", "Emergency")},
        before_return=edit_while_fetching,
    )
    summary = _run(factory, client)

    assert summary.unchanged == 1
    assert summary.descriptions_updated == 0
    assert summary.priorities_updated == 0
    db.expire_all()
    assert db.get(WorkOrder, row.id).description == "Concurrent manual task"
    assert db.get(WorkOrder, row.id).priority == "Concurrent manual priority"


def test_compare_and_set_skips_rows_archived_or_renumbered_during_fetch(db, monkeypatch):
    archived = _row(_number(), description=None, priority=None)
    archived.description = wo.work_order_task_fallback(archived.number)
    renumbered = _row(_number(), description=None, priority=None)
    renumbered.description = wo.work_order_task_fallback(renumbered.number)
    db.add_all([archived, renumbered])
    db.commit()
    candidates = sorted(
        [_candidate(archived), _candidate(renumbered)],
        key=lambda candidate: candidate.number,
    )
    monkeypatch.setattr(service, "_load_candidates", lambda _factory: candidates)
    factory = _session_factory(db)

    def change_row(number):
        with factory() as other:
            if number == archived.number:
                current = other.get(WorkOrder, archived.id)
                current.archived_at = datetime.now(timezone.utc)
            else:
                current = other.get(WorkOrder, renumbered.id)
                current.number = _number()
            other.commit()

    client = FakeClient(
        {
            candidate.number: SourceWorkOrder(
                candidate.number,
                "Source task",
                "Emergency",
            )
            for candidate in candidates
        },
        before_return=change_row,
    )
    summary = _run(factory, client)

    assert summary.fetched == 2
    assert summary.unchanged == 2
    assert summary.descriptions_updated == 0
    assert summary.priorities_updated == 0


def test_invalid_number_never_calls_source_and_does_not_block_later_rows(monkeypatch):
    invalid = service.EnrichmentCandidate(
        id=uuid.uuid4(),
        number="WO-BAD",
        description=None,
        priority=None,
    )
    valid_number = _number()
    valid = service.EnrichmentCandidate(
        id=uuid.uuid4(),
        number=valid_number,
        description=None,
        priority=None,
    )
    monkeypatch.setattr(service, "_load_candidates", lambda _factory: [invalid, valid])
    monkeypatch.setattr(
        service,
        "_apply_candidate",
        lambda *_args: service.ApplyResult(),
    )
    client = FakeClient(
        {valid_number: SourceWorkOrder(valid_number, "Source task", "Routine")}
    )

    summary = _run(lambda: Session(), client)

    assert client.calls == [valid_number]
    assert summary.invalid_numbers == 1
    assert summary.requests_attempted == 1
    assert summary.fetched == 1
    assert summary.unchanged == 1


def test_request_progress_precedes_each_valid_serial_request(monkeypatch):
    valid_numbers = [_number(), _number()]
    candidates = [
        service.EnrichmentCandidate(uuid.uuid4(), "invalid", None, None),
        *[
            service.EnrichmentCandidate(uuid.uuid4(), number, None, None)
            for number in valid_numbers
        ],
    ]
    monkeypatch.setattr(service, "_load_candidates", lambda _factory: candidates)
    monkeypatch.setattr(
        service,
        "_apply_candidate",
        lambda *_args: service.ApplyResult(),
    )
    events = []

    class EventClient:
        async def get_work_order(self, number):
            events.append(("request", number))
            return SourceWorkOrder(number, "Source task", "Routine")

    async def observe(number):
        events.append(("progress", number))

    summary = asyncio.run(
        service.enrich_work_orders(
            session_factory=lambda: Session(),
            client=EventClient(),
            batch_timeout_seconds=30,
            on_request_started=observe,
        )
    )

    assert events == [
        ("progress", valid_numbers[0]),
        ("request", valid_numbers[0]),
        ("progress", valid_numbers[1]),
        ("request", valid_numbers[1]),
    ]
    assert summary.invalid_numbers == 1
    assert summary.requests_attempted == 2


def test_mixed_failures_continue_until_authentication_loss(monkeypatch):
    numbers = [_number() for _ in range(4)]
    candidates = [
        service.EnrichmentCandidate(uuid.uuid4(), number, None, None)
        for number in numbers
    ]
    monkeypatch.setattr(service, "_load_candidates", lambda _factory: candidates)
    client = FakeClient(
        {
            numbers[0]: NetFacilitiesWorkOrderNotFound("not found"),
            numbers[1]: NetFacilitiesPermissionDenied("forbidden"),
            numbers[2]: NetFacilitiesAuthenticationRequired("expired"),
            numbers[3]: SourceWorkOrder(numbers[3], "Must not fetch", "Routine"),
        }
    )

    summary = _run(lambda: Session(), client)

    assert client.calls == numbers[:3]
    assert summary.candidates == 4
    assert summary.requests_attempted == 3
    assert summary.fetched == 0
    assert summary.not_found == 1
    assert summary.permission_denied == 1
    assert summary.authentication_required == 1
    assert summary.remaining == 1
    assert summary.other_failures == 0


def test_malformed_source_projection_fails_closed_without_writes(monkeypatch):
    numbers = [_number() for _ in range(3)]
    candidates = [
        service.EnrichmentCandidate(uuid.uuid4(), number, None, None)
        for number in numbers
    ]
    monkeypatch.setattr(service, "_load_candidates", lambda _factory: candidates)
    client = FakeClient(
        {
            numbers[0]: SourceWorkOrder(_number(), "Source task", "Routine"),
            numbers[1]: SourceWorkOrder(numbers[1], "   ", "Routine"),
            numbers[2]: SimpleNamespace(
                work_order_number=numbers[2],
                description="Source task",
                priority=123,
            ),
        }
    )

    summary = _run(lambda: Session(), client)

    assert summary.requests_attempted == 3
    assert summary.fetched == 3
    assert summary.other_failures == 3
    assert summary.descriptions_updated == 0
    assert summary.priorities_updated == 0


def test_batch_timeout_cancels_current_read_and_leaves_remaining(monkeypatch):
    numbers = [_number(), _number()]
    candidates = [
        service.EnrichmentCandidate(uuid.uuid4(), number, None, None)
        for number in numbers
    ]
    monkeypatch.setattr(service, "_load_candidates", lambda _factory: candidates)
    client = FakeClient(
        {
            number: SourceWorkOrder(number, "Source task", "Routine")
            for number in numbers
        },
        delay=0.1,
    )

    summary = _run(lambda: Session(), client, timeout=0.01)

    assert summary.timed_out
    assert summary.requests_attempted == 1
    assert summary.other_failures == 1
    assert summary.remaining == 1
    assert client.calls == [numbers[0]]


def test_successful_projection_reads_no_unapproved_source_fields(monkeypatch):
    number = _number()
    candidate = service.EnrichmentCandidate(uuid.uuid4(), number, None, None)
    monkeypatch.setattr(service, "_load_candidates", lambda _factory: [candidate])
    monkeypatch.setattr(
        service,
        "_apply_candidate",
        lambda *_args: service.ApplyResult(),
    )
    client = FakeClient(
        {number: SourceWorkOrder(number, "Source task", "Routine")}
    )

    summary = _run(lambda: Session(), client)

    assert summary.fetched == 1
    assert summary.unchanged == 1
