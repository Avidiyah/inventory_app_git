"""Process-local lifecycle for the in-app NetFacilities live session.

One headed browser per process. ``start`` opens it on the sign-in page.
``confirm`` -- called automatically once a page leaves the login screen, or by
the operator -- verifies the session against the server, saves the storage
state for the headless fallback, and leaves the window **open**: the operator
exports the work-order CSV from it, and enrichment borrows the same signed-in
session instead of launching a second browser. ``cancel`` closes the window in
any state; the window closing on its own, the idle timeout, and application
shutdown do the same. Spec: docs/superpowers/specs/2026-08-28-netfacilities-
live-session-design.md.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import logging
from pathlib import Path
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
    NetFacilitiesOperationInProgress,
    NetFacilitiesUnexpectedResponse,
)
from app.integrations.netfacilities.factory import (
    create_netfacilities_authentication_client,
)
from app.services.netfacilities_live_session import LiveSessionClientContext
from app.services.netfacilities_operations import (
    NetFacilitiesOperationGate,
    operation_gate,
)


logger = logging.getLogger(__name__)

AuthenticationState: TypeAlias = Literal[
    "starting",
    "awaiting_confirmation",
    "confirming",
    "signed_in",
    "closed",
    "failed",
    "cancelled",
    "timed_out",
]
AuthenticationFailure: TypeAlias = Literal["unavailable", "cancelled", "timed_out"]
AuthenticationClientFactory: TypeAlias = Callable[
    [NetFacilitiesConfig], NetFacilitiesAuthenticationContextProtocol
]

# "Pending" is the window being open before anyone is signed in. ``signed_in``
# is deliberately not in this set: it is live, not pending, and not terminal.
PENDING_STATES: frozenset[str] = frozenset(
    {"starting", "awaiting_confirmation", "confirming"}
)
AUTO_CONFIRM_POLL_SECONDS = 1.0
AUTO_CONFIRM_RETRY_SECONDS = 5.0
TIMEOUT_RETRY_SECONDS = 60.0
CSV_SUFFIX = ".csv"


@dataclass(frozen=True, slots=True)
class NetFacilitiesAuthenticationSnapshot:
    """Secret-free state safe to return to an administrator.

    ``last_download_filename`` is a bare filename. The directory is
    configuration the operator already knows and never travels in a response.
    """

    attempt_id: UUID
    state: AuthenticationState
    started_at: datetime
    finished_at: datetime | None = None
    failure: AuthenticationFailure | None = None
    signed_in_at: datetime | None = None
    last_download_filename: str | None = None
    last_download_at: datetime | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


class NetFacilitiesAuthenticationCoordinator:
    """Own one headed browser from sign-in through the end of the live session."""

    def __init__(
        self,
        *,
        client_factory: AuthenticationClientFactory = (
            create_netfacilities_authentication_client
        ),
        profile_gate: NetFacilitiesOperationGate = operation_gate,
        auto_confirm_poll_seconds: float = AUTO_CONFIRM_POLL_SECONDS,
        auto_confirm_retry_seconds: float = AUTO_CONFIRM_RETRY_SECONDS,
        timeout_retry_seconds: float = TIMEOUT_RETRY_SECONDS,
    ) -> None:
        self._client_factory = client_factory
        self._profile_gate = profile_gate
        self._auto_confirm_poll_seconds = auto_confirm_poll_seconds
        self._auto_confirm_retry_seconds = auto_confirm_retry_seconds
        self._timeout_retry_seconds = timeout_retry_seconds
        self._lock = asyncio.Lock()
        self._latest: NetFacilitiesAuthenticationSnapshot | None = None
        self._lease: UUID | None = None
        self._context: NetFacilitiesAuthenticationContextProtocol | None = None
        self._client: NetFacilitiesAuthenticationClientProtocol | None = None
        self._timeout_task: asyncio.Task[None] | None = None
        self._auto_confirm_task: asyncio.Task[None] | None = None
        self._background_tasks: set[asyncio.Task[None]] = set()
        self._session_timeout_seconds: float = 0
        self._borrow_count = 0
        self._last_download_path: Path | None = None

    # ------------------------------------------------------------------ reads

    async def latest(self) -> NetFacilitiesAuthenticationSnapshot | None:
        async with self._lock:
            return self._latest

    def captured_csv_path(self) -> Path | None:
        """The most recent CSV exported through the live window, if any.

        Read without the lock on purpose: the route that consumes it is a sync
        handler (the import is one long transaction) and a single attribute read
        of a ``Path | None`` is atomic. The path never leaves the server.
        """

        return self._last_download_path

    async def borrow_live_client(self) -> LiveSessionClientContext | None:
        """A context that lends the signed-in client to one job, or None."""

        async with self._lock:
            if not self._signed_in_locked() or self._client is None:
                return None
            return LiveSessionClientContext(self)

    async def borrow_started(self) -> NetFacilitiesAuthenticationClientProtocol:
        async with self._lock:
            if not self._signed_in_locked() or self._client is None:
                raise NetFacilitiesAuthenticationRequired(
                    "The NetFacilities window is no longer signed in."
                )
            self._borrow_count += 1
            return self._client

    async def borrow_finished(self) -> None:
        async with self._lock:
            self._borrow_count = max(0, self._borrow_count - 1)

    # --------------------------------------------------------------- commands

    async def start(
        self,
        config: NetFacilitiesConfig,
    ) -> tuple[NetFacilitiesAuthenticationSnapshot, bool]:
        """Open the headed browser, or return the window that is already open."""

        async with self._lock:
            if self._active_locked() or self._signed_in_locked():
                if self._latest is None:  # defensive type narrowing
                    raise RuntimeError("active authentication has no snapshot")
                return self._latest, False

            lease = await self._profile_gate.acquire("authentication")
            attempt = NetFacilitiesAuthenticationSnapshot(
                attempt_id=uuid4(),
                state="starting",
                started_at=_now(),
            )
            self._latest = attempt
            self._lease = lease
            self._last_download_path = None
            self._session_timeout_seconds = config.session_timeout_seconds
            try:
                context = self._client_factory(config)
                self._context = context
                client = await context.__aenter__()
                self._client = client
                await client.open_authentication_page()
                if config.download_dir is not None:
                    client.capture_downloads(config.download_dir, self._record_download)
                client.on_context_closed(
                    lambda: self._schedule_context_closed(attempt.attempt_id)
                )
            except BaseException as exc:
                await self._terminal_failure_locked(attempt, exc)
                raise

            waiting = replace(attempt, state="awaiting_confirmation")
            self._latest = waiting
            self._timeout_task = asyncio.create_task(
                self._expire_after(attempt.attempt_id, config.auth_timeout_seconds),
                name=f"netfacilities-auth-timeout-{attempt.attempt_id}",
            )
            self._auto_confirm_task = asyncio.create_task(
                self._auto_confirm(attempt.attempt_id),
                name=f"netfacilities-auto-confirm-{attempt.attempt_id}",
            )
            logger.info(
                "netfacilities.authentication_started",
                extra={"fields": {"operation_id": str(attempt.attempt_id)}},
            )
            return waiting, True

    async def confirm(self) -> NetFacilitiesAuthenticationSnapshot:
        """Verify the sign-in against the server, save state, keep the window open."""

        async with self._lock:
            attempt = self._require_active_locked()
            client = self._client
            if client is None:  # defensive invariant
                raise RuntimeError("active NetFacilities authentication has no client")
            self._latest = replace(attempt, state="confirming")
            try:
                await client.verify_authentication_page()
                await client.prime_session()
                await client.persist_authentication_state()
            except (NetFacilitiesAuthenticationRequired, NetFacilitiesUnexpectedResponse):
                # Not signed in yet, or the server hiccupped: stay pending with
                # the window open so the operator or the poller can try again.
                self._latest = attempt
                raise
            except BaseException as exc:
                await self._terminal_failure_locked(attempt, exc)
                raise

            signed_in = replace(attempt, state="signed_in", signed_in_at=_now())
            self._latest = signed_in
            self._cancel_task(self._timeout_task)
            self._timeout_task = asyncio.create_task(
                self._expire_after(attempt.attempt_id, self._session_timeout_seconds),
                name=f"netfacilities-session-timeout-{attempt.attempt_id}",
            )
            self._cancel_task(self._auto_confirm_task)
            self._auto_confirm_task = None
            logger.info(
                "netfacilities.authentication_completed",
                extra={"fields": {"operation_id": str(attempt.attempt_id)}},
            )
            return signed_in

    async def cancel(self) -> NetFacilitiesAuthenticationSnapshot:
        """Close the window: abandon a pending sign-in or end the live session."""

        async with self._lock:
            if self._borrow_count > 0:
                raise NetFacilitiesOperationInProgress(
                    "Enrichment is still using the NetFacilities window."
                )
            if self._signed_in_locked():
                current = self._latest
                if current is None:  # defensive type narrowing
                    raise RuntimeError("signed-in session has no snapshot")
                finished = replace(current, state="closed", finished_at=_now())
                event = "netfacilities.session_closed"
            else:
                attempt = self._require_active_locked()
                finished = replace(
                    attempt,
                    state="cancelled",
                    finished_at=_now(),
                    failure="cancelled",
                )
                event = "netfacilities.authentication_cancelled"
            self._latest = finished
            await self._close_locked()
            logger.info(
                event,
                extra={"fields": {"operation_id": str(finished.attempt_id)}},
            )
            return finished

    async def shutdown(self) -> None:
        """Close a pending or live window during application shutdown."""

        async with self._lock:
            current = self._latest
            if current is None:
                return
            if self._signed_in_locked():
                self._latest = replace(current, state="closed", finished_at=_now())
            elif self._active_locked():
                self._latest = replace(
                    current,
                    state="cancelled",
                    finished_at=_now(),
                    failure="cancelled",
                )
            else:
                return
            await self._close_locked()

    # -------------------------------------------------------------- internals

    def _active_locked(self) -> bool:
        return self._latest is not None and self._latest.state in PENDING_STATES

    def _signed_in_locked(self) -> bool:
        return self._latest is not None and self._latest.state == "signed_in"

    def _require_active_locked(self) -> NetFacilitiesAuthenticationSnapshot:
        if not self._active_locked() or self._latest is None:
            raise NetFacilitiesAuthenticationNotPending(
                "No NetFacilities sign-in is waiting for confirmation."
            )
        return self._latest

    @staticmethod
    def _cancel_task(task: asyncio.Task[None] | None) -> None:
        if task is not None and task is not asyncio.current_task():
            task.cancel()

    async def _record_download(self, path: Path) -> None:
        """Remember the CSV the operator exported. Other downloads are saved
        by the client but not surfaced (spec D3)."""

        async with self._lock:
            current = self._latest
            if current is None or not (self._active_locked() or self._signed_in_locked()):
                return
            if path.suffix.casefold() != CSV_SUFFIX:
                return
            self._last_download_path = path
            self._latest = replace(
                current,
                last_download_filename=path.name,
                last_download_at=_now(),
            )
            attempt_id = current.attempt_id
        logger.info(
            "netfacilities.csv_captured",
            extra={"fields": {"operation_id": str(attempt_id)}},
        )

    def _schedule_context_closed(self, attempt_id: UUID) -> None:
        task = asyncio.get_running_loop().create_task(
            self._handle_context_closed(attempt_id),
            name=f"netfacilities-window-closed-{attempt_id}",
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _handle_context_closed(self, attempt_id: UUID) -> None:
        async with self._lock:
            current = self._latest
            if current is None or current.attempt_id != attempt_id:
                return
            if self._signed_in_locked():
                self._latest = replace(current, state="closed", finished_at=_now())
            elif self._active_locked():
                self._latest = replace(
                    current,
                    state="cancelled",
                    finished_at=_now(),
                    failure="cancelled",
                )
            else:
                return
            await self._close_locked()
            logger.info(
                "netfacilities.window_closed",
                extra={"fields": {"operation_id": str(attempt_id)}},
            )

    async def _auto_confirm(self, attempt_id: UUID) -> None:
        """Confirm on the operator's behalf once a page leaves the login screen.

        The local URL check is the cheap gate; ``confirm`` still performs the
        server probe, so a false local positive only costs one request (spec
        §3.4, D2).
        """

        try:
            while True:
                await asyncio.sleep(self._auto_confirm_poll_seconds)
                async with self._lock:
                    current = self._latest
                    if (
                        current is None
                        or current.attempt_id != attempt_id
                        or current.state != "awaiting_confirmation"
                    ):
                        return
                    client = self._client
                if client is None:
                    return
                try:
                    await client.verify_authentication_page()
                except NetFacilitiesAuthenticationRequired:
                    continue
                try:
                    await self.confirm()
                    return
                except (NetFacilitiesAuthenticationRequired, NetFacilitiesUnexpectedResponse):
                    await asyncio.sleep(self._auto_confirm_retry_seconds)
                except NetFacilitiesError:
                    return
        except asyncio.CancelledError:
            pass

    async def _expire_after(self, attempt_id: UUID, seconds: float) -> None:
        """Close the window when a pending sign-in or an idle session outlives
        its limit. A borrowed window is re-checked instead of closed."""

        try:
            await asyncio.sleep(seconds)
            while True:
                async with self._lock:
                    current = self._latest
                    if (
                        current is None
                        or current.attempt_id != attempt_id
                        or not (self._active_locked() or self._signed_in_locked())
                    ):
                        return
                    if self._borrow_count == 0:
                        was_signed_in = self._signed_in_locked()
                        self._latest = replace(
                            current,
                            state="timed_out",
                            finished_at=_now(),
                            failure="timed_out",
                        )
                        await self._close_locked()
                        logger.info(
                            "netfacilities.session_timed_out"
                            if was_signed_in
                            else "netfacilities.authentication_timed_out",
                            extra={"fields": {"operation_id": str(attempt_id)}},
                        )
                        return
                await asyncio.sleep(self._timeout_retry_seconds)
        except asyncio.CancelledError:
            pass

    async def _terminal_failure_locked(
        self,
        attempt: NetFacilitiesAuthenticationSnapshot,
        exc: BaseException,
    ) -> None:
        self._latest = replace(
            attempt,
            state="failed",
            finished_at=_now(),
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

    async def _close_locked(self) -> None:
        timeout_task = self._timeout_task
        self._timeout_task = None
        self._cancel_task(timeout_task)
        auto_confirm_task = self._auto_confirm_task
        self._auto_confirm_task = None
        self._cancel_task(auto_confirm_task)

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
