"""One process-local, serialized NetFacilities enrichment job."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
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
ClientFactory: TypeAlias = Callable[
    [NetFacilitiesConfig], NetFacilitiesClientContextProtocol
]
EnrichmentRunner: TypeAlias = Callable[..., Awaitable[NetFacilitiesEnrichmentSummary]]


@dataclass(frozen=True, slots=True)
class NetFacilitiesJobSnapshot:
    """Immutable, source-value-free state safe for an Admin API response."""

    job_id: UUID
    state: JobState
    started_at: datetime | None = None
    finished_at: datetime | None = None
    failure: FailureClass | None = None
    summary: NetFacilitiesEnrichmentSummary | None = None


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
    ) -> tuple[NetFacilitiesJobSnapshot, bool]:
        """Start a batch, or return the currently active batch unchanged."""

        if not config.enabled or config.profile_dir is None:
            raise NetFacilitiesAuthenticationRequired(
                "NetFacilities enrichment is not enabled on this host."
            )
        if not config.has_saved_authentication:
            raise NetFacilitiesAuthenticationRequired(
                "Sign in to NetFacilities before enrichment."
            )

        async with self._lock:
            if self._task is not None and not self._task.done():
                if self._latest is None:  # defensive invariant
                    raise RuntimeError("active NetFacilities task has no job state")
                return self._latest, False

            lease = await self._profile_gate.acquire("enrichment")
            job = NetFacilitiesJobSnapshot(job_id=uuid4(), state="queued")
            self._latest = job
            self._lease = lease
            try:
                self._task = asyncio.create_task(
                    self._run(job.job_id, config),
                    name=f"netfacilities-enrichment-{job.job_id}",
                )
            except BaseException:
                self._lease = None
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
        """Cancel an active job so its browser context closes before exit."""

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

    async def _run(self, job_id: UUID, config: NetFacilitiesConfig) -> None:
        started_at = datetime.now(timezone.utc)
        started_clock = asyncio.get_running_loop().time()
        await self._set(
            NetFacilitiesJobSnapshot(
                job_id=job_id,
                state="running",
                started_at=started_at,
            )
        )
        logger.info(
            "netfacilities.enrichment_started",
            extra={"fields": {"operation_id": str(job_id)}},
        )

        try:
            async with self._client_factory(config) as client:
                summary = await self._enrichment_runner(
                    session_factory=self._session_factory,
                    client=client,
                    batch_timeout_seconds=config.batch_timeout_seconds,
                )
        except asyncio.CancelledError:
            await self._finish(
                job_id,
                started_at,
                state="cancelled",
                failure="cancelled",
            )
            raise
        except NetFacilitiesAuthenticationRequired:
            await self._finish(
                job_id,
                started_at,
                state="authentication_required",
                failure="authentication_required",
            )
        except NetFacilitiesError:
            await self._finish(
                job_id,
                started_at,
                state="failed",
                failure="unavailable",
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
        summary: NetFacilitiesEnrichmentSummary | None = None,
    ) -> None:
        await self._set(
            NetFacilitiesJobSnapshot(
                job_id=job_id,
                state=state,
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                failure=failure,
                summary=summary,
            )
        )


coordinator = NetFacilitiesJobCoordinator()
