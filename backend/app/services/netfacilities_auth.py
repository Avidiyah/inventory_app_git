"""Process-local lifecycle for manual in-app NetFacilities authentication."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Literal, TypeAlias
from uuid import UUID, uuid4

from app.integrations.netfacilities.config import NetFacilitiesConfig
from app.integrations.netfacilities.contracts import (
    NetFacilitiesAuthenticationClientProtocol,
    NetFacilitiesAuthenticationContextProtocol,
)
from app.integrations.netfacilities.errors import (
    NetFacilitiesAuthenticationNotPending,
    NetFacilitiesAuthenticationRequired,
    NetFacilitiesError,
)
from app.integrations.netfacilities.factory import (
    create_netfacilities_authentication_client,
)
from app.services.netfacilities_operations import (
    NetFacilitiesOperationGate,
    operation_gate,
)


logger = logging.getLogger(__name__)

AuthenticationState: TypeAlias = Literal[
    "starting",
    "awaiting_confirmation",
    "confirming",
    "authenticated",
    "failed",
    "cancelled",
    "timed_out",
]
AuthenticationFailure: TypeAlias = Literal["unavailable", "cancelled", "timed_out"]
AuthenticationClientFactory: TypeAlias = Callable[
    [NetFacilitiesConfig], NetFacilitiesAuthenticationContextProtocol
]


@dataclass(frozen=True, slots=True)
class NetFacilitiesAuthenticationSnapshot:
    """Secret-free state safe to return to an administrator."""

    attempt_id: UUID
    state: AuthenticationState
    started_at: datetime
    finished_at: datetime | None = None
    failure: AuthenticationFailure | None = None


class NetFacilitiesAuthenticationCoordinator:
    """Keep one headed browser open between start and confirm/cancel."""

    def __init__(
        self,
        *,
        client_factory: AuthenticationClientFactory = (
            create_netfacilities_authentication_client
        ),
        profile_gate: NetFacilitiesOperationGate = operation_gate,
    ) -> None:
        self._client_factory = client_factory
        self._profile_gate = profile_gate
        self._lock = asyncio.Lock()
        self._latest: NetFacilitiesAuthenticationSnapshot | None = None
        self._lease: UUID | None = None
        self._context: NetFacilitiesAuthenticationContextProtocol | None = None
        self._client: NetFacilitiesAuthenticationClientProtocol | None = None
        self._timeout_task: asyncio.Task[None] | None = None

    async def latest(self) -> NetFacilitiesAuthenticationSnapshot | None:
        async with self._lock:
            return self._latest

    async def start(
        self,
        config: NetFacilitiesConfig,
    ) -> tuple[NetFacilitiesAuthenticationSnapshot, bool]:
        """Open the headed browser, or return the active attempt unchanged."""

        async with self._lock:
            if self._active_locked():
                if self._latest is None:  # defensive type narrowing
                    raise RuntimeError("active authentication has no snapshot")
                return self._latest, False

            lease = await self._profile_gate.acquire("authentication")
            attempt = NetFacilitiesAuthenticationSnapshot(
                attempt_id=uuid4(),
                state="starting",
                started_at=datetime.now(timezone.utc),
            )
            self._latest = attempt
            self._lease = lease
            try:
                context = self._client_factory(config)
                self._context = context
                client = await context.__aenter__()
                self._client = client
                await client.open_authentication_page()
            except BaseException as exc:
                await self._terminal_failure_locked(attempt, exc)
                raise

            waiting = NetFacilitiesAuthenticationSnapshot(
                attempt_id=attempt.attempt_id,
                state="awaiting_confirmation",
                started_at=attempt.started_at,
            )
            self._latest = waiting
            self._timeout_task = asyncio.create_task(
                self._expire_after(
                    attempt.attempt_id,
                    config.auth_timeout_seconds,
                ),
                name=f"netfacilities-auth-timeout-{attempt.attempt_id}",
            )
            logger.info(
                "netfacilities.authentication_started",
                extra={"fields": {"operation_id": str(attempt.attempt_id)}},
            )
            return waiting, True

    async def confirm(self) -> NetFacilitiesAuthenticationSnapshot:
        """Verify the browser page and save its state before closing it."""

        async with self._lock:
            attempt = self._require_active_locked()
            client = self._client
            if client is None:  # defensive invariant
                raise RuntimeError("active NetFacilities authentication has no client")
            self._latest = NetFacilitiesAuthenticationSnapshot(
                attempt_id=attempt.attempt_id,
                state="confirming",
                started_at=attempt.started_at,
            )
            try:
                await client.verify_authentication_page()
                await client.persist_authentication_state()
            except NetFacilitiesAuthenticationRequired:
                self._latest = attempt
                raise
            except BaseException as exc:
                await self._terminal_failure_locked(attempt, exc)
                raise

            finished = NetFacilitiesAuthenticationSnapshot(
                attempt_id=attempt.attempt_id,
                state="authenticated",
                started_at=attempt.started_at,
                finished_at=datetime.now(timezone.utc),
            )
            self._latest = finished
            await self._close_locked()
            logger.info(
                "netfacilities.authentication_completed",
                extra={"fields": {"operation_id": str(attempt.attempt_id)}},
            )
            return finished

    async def cancel(self) -> NetFacilitiesAuthenticationSnapshot:
        """Cancel the active ceremony and close its dedicated browser."""

        async with self._lock:
            attempt = self._require_active_locked()
            finished = NetFacilitiesAuthenticationSnapshot(
                attempt_id=attempt.attempt_id,
                state="cancelled",
                started_at=attempt.started_at,
                finished_at=datetime.now(timezone.utc),
                failure="cancelled",
            )
            self._latest = finished
            await self._close_locked()
            logger.info(
                "netfacilities.authentication_cancelled",
                extra={"fields": {"operation_id": str(attempt.attempt_id)}},
            )
            return finished

    async def shutdown(self) -> None:
        """Close an abandoned headed browser during application shutdown."""

        async with self._lock:
            if not self._active_locked():
                return
            attempt = self._require_active_locked()
            self._latest = NetFacilitiesAuthenticationSnapshot(
                attempt_id=attempt.attempt_id,
                state="cancelled",
                started_at=attempt.started_at,
                finished_at=datetime.now(timezone.utc),
                failure="cancelled",
            )
            await self._close_locked()

    def _active_locked(self) -> bool:
        return (
            self._latest is not None
            and self._latest.state
            in {"starting", "awaiting_confirmation", "confirming"}
        )

    def _require_active_locked(self) -> NetFacilitiesAuthenticationSnapshot:
        if not self._active_locked() or self._latest is None:
            raise NetFacilitiesAuthenticationNotPending(
                "No NetFacilities sign-in is waiting for confirmation."
            )
        return self._latest

    async def _expire_after(self, attempt_id: UUID, seconds: int) -> None:
        try:
            await asyncio.sleep(seconds)
            async with self._lock:
                if (
                    not self._active_locked()
                    or self._latest is None
                    or self._latest.attempt_id != attempt_id
                ):
                    return
                attempt = self._latest
                self._latest = NetFacilitiesAuthenticationSnapshot(
                    attempt_id=attempt.attempt_id,
                    state="timed_out",
                    started_at=attempt.started_at,
                    finished_at=datetime.now(timezone.utc),
                    failure="timed_out",
                )
                await self._close_locked(cancel_timeout=False)
                logger.info(
                    "netfacilities.authentication_timed_out",
                    extra={"fields": {"operation_id": str(attempt.attempt_id)}},
                )
        except asyncio.CancelledError:
            pass

    async def _terminal_failure_locked(
        self,
        attempt: NetFacilitiesAuthenticationSnapshot,
        exc: BaseException,
    ) -> None:
        self._latest = NetFacilitiesAuthenticationSnapshot(
            attempt_id=attempt.attempt_id,
            state="failed",
            started_at=attempt.started_at,
            finished_at=datetime.now(timezone.utc),
            failure="unavailable",
        )
        logger.error(
            "netfacilities.authentication_failed",
            extra={
                "fields": {
                    "operation_id": str(attempt.attempt_id),
                    "failure": (
                        "expected" if isinstance(exc, NetFacilitiesError) else "unexpected"
                    ),
                    "exc_type": type(exc).__name__,
                }
            },
        )
        await self._close_locked()

    async def _close_locked(self, *, cancel_timeout: bool = True) -> None:
        timeout_task = self._timeout_task
        self._timeout_task = None
        if (
            cancel_timeout
            and timeout_task is not None
            and timeout_task is not asyncio.current_task()
        ):
            timeout_task.cancel()

        context = self._context
        lease = self._lease
        self._context = None
        self._client = None
        self._lease = None
        try:
            if context is not None:
                await context.__aexit__(None, None, None)
        except Exception as exc:
            logger.error(
                "netfacilities.authentication_close_failed",
                extra={"fields": {"exc_type": type(exc).__name__}},
            )
        finally:
            if lease is not None:
                await self._profile_gate.release(lease)


authentication_coordinator = NetFacilitiesAuthenticationCoordinator()
