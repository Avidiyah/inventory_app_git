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
from app.integrations.netfacilities.factory import create_netfacilities_client
from app.services.netfacilities import (
    NetFacilitiesEnrichmentSummary,
    SessionFactory,
    enrich_work_orders,
)
from app.services.netfacilities_operations import (
    NetFacilitiesOperationGate,
    operation_gate,
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
JobSource: TypeAlias = Literal["live_session", "saved_state", "cloud_session"]
ClientFactory: TypeAlias = Callable[
    [NetFacilitiesConfig], NetFacilitiesClientContextProtocol
]
EnrichmentRunner: TypeAlias = Callable[..., Awaitable[NetFacilitiesEnrichmentSummary]]


@dataclass(frozen=True, slots=True)
class NetFacilitiesJobSnapshot:
    """Immutable, source-value-free state safe for a gated API response.

    ``user_id`` is populated only for a ``cloud_session`` job -- internal
    plumbing so the router can find and expire that user's saved cloud
    session on `authentication_required` (spec D8); it is never part of the
    response schema (`schemas.netfacilities.NetFacilitiesEnrichmentJob`
    has no such field)."""

    job_id: UUID
    state: JobState
    started_at: datetime | None = None
    finished_at: datetime | None = None
    failure: FailureClass | None = None
    summary: NetFacilitiesEnrichmentSummary | None = None
    current_work_order_number: str | None = None
    source: JobSource | None = None
    user_id: UUID | None = None


def _default_client_factory(
    config: NetFacilitiesConfig,
) -> NetFacilitiesClientContextProtocol:
    return create_netfacilities_client(
        config,
        headless=True,
        use_saved_state=True,
    )


class NetFacilitiesJobCoordinator:
    """Admit at most one batch and own its browser lifetime through shutdown."""

    def __init__(
        self,
        *,
        session_factory: SessionFactory = SessionLocal,
        client_factory: ClientFactory = _default_client_factory,
        enrichment_runner: EnrichmentRunner = enrich_work_orders,
        profile_gate: NetFacilitiesOperationGate = operation_gate,
    ) -> None:
        self._session_factory = session_factory
        self._client_factory = client_factory
        self._enrichment_runner = enrichment_runner
        self._profile_gate = profile_gate
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._latest: NetFacilitiesJobSnapshot | None = None
        self._lease: UUID | None = None

    async def start(
        self,
        config: NetFacilitiesConfig,
        *,
        live_client_context: NetFacilitiesClientContextProtocol | None = None,
        cloud_client_context: NetFacilitiesClientContextProtocol | None = None,
        cloud_user_id: UUID | None = None,
    ) -> tuple[NetFacilitiesJobSnapshot, bool]:
        """Start a batch, or return the currently active batch unchanged.

        Precedence: the operator's open live window (spec D4, D8) first, then
        the calling user's own cloud session (spec D10), then the shared
        saved-state file. A cloud session never takes the shared profile
        lease -- it is not the same physical resource live_session/saved_state
        contend for (spec D10).
        """

        if not config.enabled:
            raise NetFacilitiesAuthenticationRequired(
                "NetFacilities enrichment is not enabled on this host."
            )
        if (
            live_client_context is None
            and cloud_client_context is None
            and not config.has_saved_authentication
        ):
            raise NetFacilitiesAuthenticationRequired(
                "Sign in to NetFacilities before enrichment."
            )

        async with self._lock:
            if self._task is not None and not self._task.done():
                if self._latest is None:  # defensive invariant
                    raise RuntimeError("active NetFacilities task has no job state")
                return self._latest, False

            if live_client_context is not None:
                source: JobSource = "live_session"
            elif cloud_client_context is not None:
                source = "cloud_session"
            else:
                source = "saved_state"
            client_context = live_client_context or cloud_client_context
            lease = None
            if client_context is None:
                lease = await self._profile_gate.acquire("enrichment")
            job = NetFacilitiesJobSnapshot(
                job_id=uuid4(),
                state="queued",
                source=source,
                user_id=cloud_user_id if source == "cloud_session" else None,
            )
            self._latest = job
            self._lease = lease
            try:
                self._task = asyncio.create_task(
                    self._run(job.job_id, config, client_context, source, job.user_id),
                    name=f"netfacilities-enrichment-{job.job_id}",
                )
            except BaseException:
                self._lease = None
                if lease is not None:
                    await self._profile_gate.release(lease)
                raise
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
        config: NetFacilitiesConfig,
        client_context: NetFacilitiesClientContextProtocol | None,
        source: JobSource,
        user_id: UUID | None = None,
    ) -> None:
        started_at = datetime.now(timezone.utc)
        started_clock = asyncio.get_running_loop().time()
        await self._set(
            NetFacilitiesJobSnapshot(
                job_id=job_id,
                state="running",
                started_at=started_at,
                source=source,
                user_id=user_id,
            )
        )
        logger.info(
            "netfacilities.enrichment_started",
            extra={"fields": {"operation_id": str(job_id)}},
        )

        try:
            client_context = (
                client_context
                if client_context is not None
                else self._client_factory(config)
            )
            async with client_context as client:
                summary = await self._enrichment_runner(
                    session_factory=self._session_factory,
                    client=client,
                    batch_timeout_seconds=config.batch_timeout_seconds,
                    on_request_started=lambda number: self._report_request_started(
                        job_id,
                        number,
                    ),
                )
        except asyncio.CancelledError:
            await self._finish(
                job_id,
                started_at,
                state="cancelled",
                failure="cancelled",
                source=source,
                user_id=user_id,
            )
            raise
        except NetFacilitiesAuthenticationRequired:
            await self._finish(
                job_id,
                started_at,
                state="authentication_required",
                failure="authentication_required",
                source=source,
                user_id=user_id,
            )
        except NetFacilitiesError:
            await self._finish(
                job_id,
                started_at,
                state="failed",
                failure="unavailable",
                source=source,
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
                source=source,
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
                source=source,
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
            await self._release_profile(job_id)

    async def _release_profile(self, job_id: UUID) -> None:
        async with self._lock:
            if self._latest is None or self._latest.job_id != job_id:
                return
            lease = self._lease
            self._lease = None
        if lease is not None:
            await self._profile_gate.release(lease)

    async def _finish(
        self,
        job_id: UUID,
        started_at: datetime,
        *,
        state: JobState,
        failure: FailureClass | None,
        source: JobSource,
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
                source=source,
                user_id=user_id,
            )
        )


coordinator = NetFacilitiesJobCoordinator()
