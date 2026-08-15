"""Serial NetFacilities enrichment with short compare-and-set database writes."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeAlias
from uuid import UUID

from sqlalchemy import func, or_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.domain import work_orders as wo
from app.integrations.netfacilities.contracts import NetFacilitiesClientProtocol
from app.integrations.netfacilities.errors import (
    NetFacilitiesAuthenticationRequired,
    NetFacilitiesError,
    NetFacilitiesInvalidWorkOrderNumber,
    NetFacilitiesPermissionDenied,
    NetFacilitiesUnexpectedDocument,
    NetFacilitiesWorkOrderNotFound,
)
from app.integrations.netfacilities.validation import validate_work_order_number
from app.models import WorkOrder


SessionFactory: TypeAlias = Callable[[], Session]
RequestProgressObserver: TypeAlias = Callable[[str], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class EnrichmentCandidate:
    """Detached local state captured before an external request."""

    id: UUID
    number: str
    description: str | None
    priority: str | None


@dataclass(frozen=True, slots=True)
class ApplyResult:
    description_updated: bool = False
    priority_updated: bool = False


@dataclass(slots=True)
class NetFacilitiesEnrichmentSummary:
    """Secret-safe process counts; source values never enter this object."""

    candidates: int = 0
    requests_attempted: int = 0
    fetched: int = 0
    descriptions_updated: int = 0
    priorities_updated: int = 0
    unchanged: int = 0
    invalid_numbers: int = 0
    not_found: int = 0
    permission_denied: int = 0
    authentication_required: int = 0
    other_failures: int = 0
    remaining: int = 0
    timed_out: bool = False


async def enrich_work_orders(
    *,
    session_factory: SessionFactory,
    client: NetFacilitiesClientProtocol,
    batch_timeout_seconds: float,
    on_request_started: RequestProgressObserver | None = None,
) -> NetFacilitiesEnrichmentSummary:
    """Enrich eligible existing rows serially through a fakeable source client.

    Candidate reads and conditional writes run in worker threads with separate
    sessions.  No database transaction or row lock is retained while awaiting
    NetFacilities.
    """

    if batch_timeout_seconds <= 0:
        raise ValueError("batch_timeout_seconds must be positive")

    loop = asyncio.get_running_loop()
    deadline = loop.time() + batch_timeout_seconds
    candidates = await asyncio.to_thread(_load_candidates, session_factory)
    summary = NetFacilitiesEnrichmentSummary(candidates=len(candidates))

    for index, candidate in enumerate(candidates):
        seconds_left = deadline - loop.time()
        if seconds_left <= 0:
            summary.timed_out = True
            summary.remaining = len(candidates) - index
            break

        try:
            number = validate_work_order_number(candidate.number)
        except (NetFacilitiesInvalidWorkOrderNumber, AttributeError):
            summary.invalid_numbers += 1
            continue

        summary.requests_attempted += 1
        if on_request_started is not None:
            await on_request_started(number)
        try:
            async with asyncio.timeout(seconds_left):
                source = await client.get_work_order(number)
        except TimeoutError:
            summary.timed_out = True
            summary.other_failures += 1
            summary.remaining = len(candidates) - index - 1
            break
        except NetFacilitiesAuthenticationRequired:
            summary.authentication_required += 1
            summary.remaining = len(candidates) - index - 1
            break
        except NetFacilitiesWorkOrderNotFound:
            summary.not_found += 1
            continue
        except NetFacilitiesPermissionDenied:
            summary.permission_denied += 1
            continue
        except NetFacilitiesError:
            summary.other_failures += 1
            continue

        summary.fetched += 1
        try:
            source_description, source_priority = _source_values(
                source,
                expected_number=number,
            )
        except NetFacilitiesUnexpectedDocument:
            summary.other_failures += 1
            continue

        try:
            applied = await asyncio.to_thread(
                _apply_candidate,
                session_factory,
                candidate,
                source_description,
                source_priority,
            )
        except SQLAlchemyError:
            summary.other_failures += 1
            continue

        if applied.description_updated:
            summary.descriptions_updated += 1
        if applied.priority_updated:
            summary.priorities_updated += 1
        if not applied.description_updated and not applied.priority_updated:
            summary.unchanged += 1

    return summary


def _load_candidates(session_factory: SessionFactory) -> list[EnrichmentCandidate]:
    """Return detached candidate snapshots in deterministic source-read order."""

    with session_factory() as db:
        rows = (
            db.query(WorkOrder)
            .filter(WorkOrder.archived_at.is_(None))
            .filter(
                or_(
                    WorkOrder.priority.is_(None),
                    func.btrim(WorkOrder.priority) == "",
                    WorkOrder.description.like(
                        f"{wo.NETFACILITIES_WORK_ORDER_URL}/%"
                    ),
                )
            )
            .order_by(func.lower(func.btrim(WorkOrder.number)), WorkOrder.id)
            .all()
        )
        return [
            EnrichmentCandidate(
                id=row.id,
                number=row.number,
                description=row.description,
                priority=row.priority,
            )
            for row in rows
            if wo.is_work_order_task_fallback(row.description, row.number)
            or _is_blank(row.priority)
        ]


def _source_values(
    source: object,
    *,
    expected_number: str,
) -> tuple[str, str | None]:
    """Validate and retain only the two source values approved for persistence."""

    try:
        returned_number = validate_work_order_number(source.work_order_number)  # type: ignore[attr-defined]
        description_value = source.description  # type: ignore[attr-defined]
        priority_value = source.priority  # type: ignore[attr-defined]
    except (AttributeError, NetFacilitiesInvalidWorkOrderNumber) as exc:
        raise NetFacilitiesUnexpectedDocument(
            "NetFacilities returned an invalid enrichment projection."
        ) from exc

    if returned_number != expected_number or not isinstance(description_value, str):
        raise NetFacilitiesUnexpectedDocument(
            "NetFacilities returned an invalid enrichment projection."
        )
    description = description_value.strip()
    if not description:
        raise NetFacilitiesUnexpectedDocument(
            "NetFacilities returned an invalid enrichment projection."
        )
    if priority_value is not None and not isinstance(priority_value, str):
        raise NetFacilitiesUnexpectedDocument(
            "NetFacilities returned an invalid enrichment projection."
        )
    priority = priority_value.strip() if priority_value is not None else None
    return description, priority or None


def _apply_candidate(
    session_factory: SessionFactory,
    candidate: EnrichmentCandidate,
    source_description: str,
    source_priority: str | None,
) -> ApplyResult:
    """Lock, re-check, and conditionally update one local row."""

    with session_factory() as db:
        try:
            row = (
                db.query(WorkOrder)
                .populate_existing()
                .filter(WorkOrder.id == candidate.id)
                .with_for_update()
                .first()
            )
            if (
                row is None
                or row.archived_at is not None
                or row.number != candidate.number
            ):
                db.rollback()
                return ApplyResult()

            description_updated = False
            priority_updated = False
            if (
                wo.is_work_order_task_fallback(row.description, row.number)
                and row.description != source_description
            ):
                row.description = source_description
                description_updated = True
            if (
                _is_blank(row.priority)
                and source_priority is not None
                and row.priority != source_priority
            ):
                row.priority = source_priority
                priority_updated = True

            if description_updated or priority_updated:
                db.commit()
            else:
                db.rollback()
            return ApplyResult(
                description_updated=description_updated,
                priority_updated=priority_updated,
            )
        except Exception:
            db.rollback()
            raise


def _is_blank(value: str | None) -> bool:
    return value is None or not value.strip()
