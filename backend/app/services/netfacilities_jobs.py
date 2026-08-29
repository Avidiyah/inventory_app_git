"""One process-local, serialized NetFacilities enrichment job."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import logging
from typing import Literal, TypeAlias
from uuid import UUID, uuid4

from app.database import SessionLocal
from app.integrations.netfacilities.config import NetFacilitiesConfig
from app.integrations.netfacilities.contracts import (
    NetFacilitiesClientContextProtocol,
)
from app.integrations.netfacilities.errors import (
    NetFacilitiesAuthenticationRequired,
    NetFacilitiesError,
)
from app.services.netfacilities import (
    NetFacilitiesEnrichmentSummary,
    SessionFactory,
    enrich_work_orders,
)


logger = logging.getLogger(__name__)

JobState: TypeAlias = Literal[
    "queued",
    "running",
    "completed",
    "authentication_required",
    "timed_out",
    "failed",
    "cancelled",
]
FailureClass: TypeAlias = Literal[
    "authentication_required",
    "unavailable",
    "unexpected_failure",
    "cancelled",
]
JobSource: TypeAlias = Literal["cloud_session"]
EnrichmentRunner: TypeAlias = Callable[..., Awaitable[NetFacilitiesEnrichmentSummary]]


@dataclass(frozen=True, slots=True)
class NetFacilitiesJobSnapshot:
    """Immutable, source-value-free state safe for a gated API response.

    ``user_id`` is internal plumbing so the router can find and expire that
    user's saved cloud session on `authentication_required` (spec D8); it is
    never part of the response schema
    (`schemas.netfacilities.NetFacilitiesEnrichmentJob` has no such field)."""

    job_id: UUID
    state: JobState
    started_at: datetime | None = None
    finished_at: datetime | None = None
    failure: FailureClass | None = None
    summary: NetFacilitiesEnrichmentSummary | None = None
    current_work_order_number: str | None = None
    source: JobSource | None = None
    user_id: UUID | None = None


class NetFacilitiesJobCoordinator:
    """Admit at most one batch and own its browser lifetime through shutdown."""

    def __init__(
        self,
        *,
        session_factory: SessionFactory = SessionLocal,
        enrichment_runner: EnrichmentRunner = enrich_work_orders,
    ) -> None:
        self._session_factory = session_factory
        self._enrichment_runner = enrichment_runner
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._latest: NetFacilitiesJobSnapshot | None = None

    async def start(
        self,
        config: NetFacilitiesConfig,
        *,
        cloud_client_context: NetFacilitiesClientContextProtocol | None = None,
        cloud_user_id: UUID | None = None,
        cloud_batch_session_seconds: float | None = None,
    ) -> tuple[NetFacilitiesJobSnapshot, bool]:
        """Start a batch using the calling user's own cloud session, or
        return the currently active batch unchanged."""

        if not config.enabled:
            raise NetFacilitiesAuthenticationRequired(
                "NetFacilities enrichment is not enabled on this host."
            )
        if cloud_client_context is None:
            raise NetFacilitiesAuthenticationRequired(
                "Sign in to NetFacilities before enrichment."
            )

        async with self._lock:
            if self._task is not None and not self._task.done():
                if self._latest is None:  # defensive invariant
                    raise RuntimeError("active NetFacilities task has no job state")
                return self._latest, False

            job = NetFacilitiesJobSnapshot(
                job_id=uuid4(),
                state="queued",
                source="cloud_session",
                user_id=cloud_user_id,
            )
            self._latest = job
            self._task = asyncio.create_task(
                self._run(
                    job.job_id,
                    cloud_client_context,
                    job.user_id,
                    config.batch_timeout_seconds,
                    cloud_batch_session_seconds,
                ),
                name=f"netfacilities-enrichment-{job.job_id}",
            )
            return job, True

    async def latest(self) -> NetFacilitiesJobSnapshot | None:
        async with self._lock:
            return self._latest

    async def get(self, job_id: UUID) -> NetFacilitiesJobSnapshot | None:
        async with self._lock:
            if self._latest is None or self._latest.job_id != job_id:
                return None
            return self._latest

    async def shutdown(self) -> None:
        """Cancel an active job so its source client closes before exit."""

        async with self._lock:
            task = self._task
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _set(self, snapshot: NetFacilitiesJobSnapshot) -> None:
        async with self._lock:
            if self._latest is not None and self._latest.job_id == snapshot.job_id:
                self._latest = snapshot

    async def _report_request_started(
        self,
        job_id: UUID,
        work_order_number: str,
    ) -> None:
        async with self._lock:
            snapshot = self._latest
            if (
                snapshot is not None
                and snapshot.job_id == job_id
                and snapshot.state == "running"
            ):
                self._latest = replace(
                    snapshot,
                    current_work_order_number=work_order_number,
                )

    async def _run(
        self,
        job_id: UUID,
        client_context: NetFacilitiesClientContextProtocol,
        user_id: UUID | None,
        batch_timeout_seconds: float,
        cloud_batch_session_seconds: float | None,
    ) -> None:
        started_at = datetime.now(timezone.utc)
        started_clock = asyncio.get_running_loop().time()
        await self._set(
            NetFacilitiesJobSnapshot(
                job_id=job_id,
                state="running",
                started_at=started_at,
                source="cloud_session",
                user_id=user_id,
            )
        )
        logger.info(
            "netfacilities.enrichment_started",
            extra={"fields": {"operation_id": str(job_id)}},
        )

        try:
            async with client_context as client:
                summary = await self._enrichment_runner(
                    session_factory=self._session_factory,
                    client=client,
                    batch_timeout_seconds=batch_timeout_seconds,
                    on_request_started=lambda number: self._report_request_started(
                        job_id,
                        number,
                    ),
                    # Steel caps a session at 15 minutes (spec §4); whichever
                    # deadline is tighter governs.
                    cloud_session_deadline_seconds=cloud_batch_session_seconds,
                )
        except asyncio.CancelledError:
            await self._finish(
                job_id,
                started_at,
                state="cancelled",
                failure="cancelled",
                user_id=user_id,
            )
            raise
        except NetFacilitiesAuthenticationRequired:
            await self._finish(
                job_id,
                started_at,
                state="authentication_required",
                failure="authentication_required",
                user_id=user_id,
            )
        except NetFacilitiesError:
            await self._finish(
                job_id,
                started_at,
                state="failed",
                failure="unavailable",
                user_id=user_id,
            )
        except Exception:
            logger.error(
                "netfacilities.enrichment_failed",
                extra={
                    "fields": {
                        "operation_id": str(job_id),
                        "failure": "unexpected_failure",
                    }
                },
            )
            await self._finish(
                job_id,
                started_at,
                state="failed",
                failure="unexpected_failure",
                user_id=user_id,
            )
        else:
            if summary.authentication_required:
                state: JobState = "authentication_required"
                failure: FailureClass | None = "authentication_required"
            elif summary.timed_out:
                state = "timed_out"
                failure = None
            else:
                state = "completed"
                failure = None
            await self._finish(
                job_id,
                started_at,
                state=state,
                failure=failure,
                summary=summary,
                user_id=user_id,
            )
        finally:
            elapsed_ms = round(
                (asyncio.get_running_loop().time() - started_clock) * 1_000
            )
            snapshot = await self.get(job_id)
            fields: dict[str, object] = {
                "operation_id": str(job_id),
                "ms": elapsed_ms,
            }
            if snapshot is not None:
                fields["state"] = snapshot.state
                if snapshot.summary is not None:
                    fields.update(
                        {
                            "candidates": snapshot.summary.candidates,
                            "fetched": snapshot.summary.fetched,
                            "descriptions_updated": (
                                snapshot.summary.descriptions_updated
                            ),
                            "priorities_updated": snapshot.summary.priorities_updated,
                        }
                    )
            logger.info(
                "netfacilities.enrichment_finished",
                extra={"fields": fields},
            )

    async def _finish(
        self,
        job_id: UUID,
        started_at: datetime,
        *,
        state: JobState,
        failure: FailureClass | None,
        summary: NetFacilitiesEnrichmentSummary | None = None,
        user_id: UUID | None = None,
    ) -> None:
        await self._set(
            NetFacilitiesJobSnapshot(
                job_id=job_id,
                state=state,
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                failure=failure,
                summary=summary,
                source="cloud_session",
                user_id=user_id,
            )
        )


coordinator = NetFacilitiesJobCoordinator()
