"""Per-user NetFacilities cloud-auth login ceremony (spec D2, D3, D7).

A starting/signed_in/closed state machine that auto-polls until signed in,
keyed per `user_id` and persisting the successful capture to
`netfacilities_cloud_sessions` (encrypted, spec D9). No sharing between
users (spec D2): each user's ceremony and captured session are independent.
This replaced the process-global headed-window coordinator, removed
2026-08-29 along with the rest of the local-auth system.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import logging
from typing import Literal, TypeAlias
from uuid import UUID, uuid4

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.domain.errors import DomainError
from app.integrations.netfacilities.cloud_config import NetFacilitiesCloudConfig
from app.integrations.netfacilities.cloud_contracts import CloudBrowserProvider
from app.integrations.netfacilities.errors import (
    NetFacilitiesError,
    NetFacilitiesUnavailable,
)
from app.models import NetFacilitiesCloudSession
from app.services import netfacilities_cloud_crypto as crypto


logger = logging.getLogger(__name__)

CloudAuthenticationState: TypeAlias = Literal[
    "starting", "awaiting_sign_in", "signed_in", "closed", "failed", "cancelled", "timed_out"
]
CloudAuthenticationFailure: TypeAlias = Literal["unavailable", "cancelled", "timed_out"]
ChainStage: TypeAlias = Literal["importing", "imported", "enriching", "done", "failed"]
ProviderFactory: TypeAlias = Callable[[NetFacilitiesCloudConfig], CloudBrowserProvider]
SessionFactory: TypeAlias = Callable[[], Session]

ACTIVE_STATES: frozenset[str] = frozenset({"starting", "awaiting_sign_in"})
DEFAULT_POLL_SECONDS = 1.0


@dataclass(frozen=True, slots=True)
class NetFacilitiesCloudAuthenticationSnapshot:
    """Secret-free per-user state safe to return to that user."""

    user_id: UUID
    attempt_id: UUID
    state: CloudAuthenticationState
    started_at: datetime
    finished_at: datetime | None = None
    failure: CloudAuthenticationFailure | None = None
    signed_in_at: datetime | None = None
    last_download_filename: str | None = None
    last_download_at: datetime | None = None
    live_view_url: str | None = None
    # Whether the chain (or the manual button) already imported the capture
    # named above. The fallback Import button keys off this (E8).
    capture_consumed: bool = False
    # The whole `WorkOrderImportResult` as a dict (spec 2a), so reconcile's
    # auto_closed/reopened counts ride along once that work lands, with no
    # plumbing here.
    import_result: dict | None = None
    import_error: str | None = None
    enrichment_job_id: UUID | None = None
    chain_stage: ChainStage | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _default_import_runner(db: Session, background: BackgroundTasks, *, data: bytes, user_id: UUID) -> dict:
    """Run `run_csv_import` outside any request (E11).

    Lazy imports: a service must not import a router at module scope. The
    router raises `HTTPException` for a malformed CSV (`to_http`), which is
    translated back to the `DomainError` the chain classifies on -- the
    chain must never think in status codes.
    """
    from fastapi import HTTPException

    from app.models import User
    from app.routers.work_orders import run_csv_import

    user = db.query(User).filter_by(id=user_id).one()
    try:
        result = run_csv_import(db, background, data=data, user=user)
    except HTTPException as exc:
        raise DomainError(str(exc.detail)) from exc
    return result.model_dump()


def _default_enrichment_resolver(db: Session, user_id: UUID):
    """`(config, context, batch_seconds)` for the user's own saved session,
    or `(None, None, None)` when enrichment cannot start at all."""

    from app.integrations.netfacilities.config import load_netfacilities_config
    from app.services.netfacilities_cloud_enrichment import (
        resolve_cloud_enrichment_context,
    )

    try:
        enrichment_config = load_netfacilities_config()
    except NetFacilitiesUnavailable:
        return None, None, None
    if not enrichment_config.enabled:
        return None, None, None
    context, batch_seconds = resolve_cloud_enrichment_context(
        enrichment_config, db, user_id
    )
    return enrichment_config, context, batch_seconds


@dataclass
class _Ceremony:
    snapshot: NetFacilitiesCloudAuthenticationSnapshot
    provider: CloudBrowserProvider
    cloud_session: object
    config: NetFacilitiesCloudConfig | None = None
    poll_task: "asyncio.Task[None] | None" = None
    captured_csv: tuple[str, bytes] | None = None
    capture_consumed: bool = False


class NetFacilitiesCloudAuthenticationCoordinator:
    """Own one login ceremony per user, keyed by `user_id`."""

    def __init__(
        self,
        *,
        provider_factory: ProviderFactory,
        session_factory: SessionFactory = SessionLocal,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
        import_runner: "Callable[..., dict] | None" = None,
        job_coordinator: object | None = None,
        notifier: "Callable[..., None] | None" = None,
        enrichment_resolver: "Callable[..., tuple] | None" = None,
    ) -> None:
        self._provider_factory = provider_factory
        self._session_factory = session_factory
        self._poll_seconds = poll_seconds
        # Chain collaborators. `None` means "resolve the real one lazily":
        # importing routers or push delivery at module scope from a service
        # would invert the dependency direction, and tests substitute all
        # four without patching module globals.
        self._import_runner = import_runner
        self._job_coordinator = job_coordinator
        self._notifier = notifier
        self._enrichment_resolver = enrichment_resolver
        self._lock = asyncio.Lock()
        self._ceremonies: dict[UUID, _Ceremony] = {}

    def _resolve_import_runner(self):
        return self._import_runner if self._import_runner is not None else _default_import_runner

    def _resolve_job_coordinator(self):
        if self._job_coordinator is not None:
            return self._job_coordinator
        from app.services.netfacilities_jobs import coordinator

        return coordinator

    def _resolve_notifier(self):
        if self._notifier is not None:
            return self._notifier
        from app.services.notifications import notify_netfacilities_chain_finished

        return notify_netfacilities_chain_finished

    def _resolve_enrichment_resolver(self):
        return (
            self._enrichment_resolver
            if self._enrichment_resolver is not None
            else _default_enrichment_resolver
        )

    async def start(
        self, user_id: UUID, config: NetFacilitiesCloudConfig
    ) -> NetFacilitiesCloudAuthenticationSnapshot:
        async with self._lock:
            existing = self._ceremonies.get(user_id)
            if existing is not None and existing.snapshot.state in ACTIVE_STATES | {"signed_in"}:
                return existing.snapshot

            provider = self._provider_factory(config)
            attempt = NetFacilitiesCloudAuthenticationSnapshot(
                user_id=user_id,
                attempt_id=uuid4(),
                state="starting",
                started_at=_now(),
            )
            try:
                cloud_session = await provider.open_login_session()
            except NetFacilitiesError:
                failed = replace(
                    attempt, state="failed", finished_at=_now(), failure="unavailable"
                )
                self._ceremonies[user_id] = _Ceremony(
                    snapshot=failed, provider=provider, cloud_session=None, config=config
                )
                raise

            awaiting = replace(
                attempt,
                state="awaiting_sign_in",
                live_view_url=cloud_session.live_view_url,
            )
            ceremony = _Ceremony(
                snapshot=awaiting, provider=provider, cloud_session=cloud_session, config=config
            )
            self._ceremonies[user_id] = ceremony
            ceremony.poll_task = asyncio.create_task(
                self._poll_until_signed_in(user_id, attempt.attempt_id, config),
                name=f"netfacilities-cloud-auth-{user_id}",
            )
            return awaiting

    async def latest(self, user_id: UUID) -> NetFacilitiesCloudAuthenticationSnapshot | None:
        async with self._lock:
            ceremony = self._ceremonies.get(user_id)
            return ceremony.snapshot if ceremony is not None else None

    async def cancel(self, user_id: UUID) -> NetFacilitiesCloudAuthenticationSnapshot:
        async with self._lock:
            ceremony = self._ceremonies.get(user_id)
            if ceremony is None:
                raise NetFacilitiesError("No NetFacilities cloud session is active.")
            if ceremony.poll_task is not None:
                ceremony.poll_task.cancel()
            await ceremony.provider.close_login_session(ceremony.cloud_session)
            finished = replace(
                ceremony.snapshot,
                state="cancelled",
                finished_at=_now(),
                failure="cancelled",
                live_view_url=None,
            )
            ceremony.snapshot = finished
            return finished

    def captured_csv_bytes(self, user_id: UUID) -> tuple[str, bytes] | None:
        ceremony = self._ceremonies.get(user_id)
        return ceremony.captured_csv if ceremony is not None else None

    async def dispatch_capture(
        self, user_id: UUID
    ) -> NetFacilitiesCloudAuthenticationSnapshot:
        """Import the captured CSV, close the session, enrich, notify.

        The one function both the automatic trigger and the manual Import
        button run (E8), so the two paths cannot drift. Never raises for a
        chain-stage failure -- those land on the snapshot and in the push --
        only for having nothing to dispatch.
        """
        async with self._lock:
            ceremony = self._ceremonies.get(user_id)
            if ceremony is None or ceremony.captured_csv is None:
                raise NetFacilitiesError("No captured NetFacilities CSV to import.")
            if ceremony.capture_consumed or ceremony.snapshot.chain_stage in (
                "importing",
                "imported",
                "enriching",
            ):
                raise NetFacilitiesError(
                    "The captured NetFacilities CSV was already imported."
                )
            attempt_id = ceremony.snapshot.attempt_id
            _filename, data = ceremony.captured_csv
            provider, cloud_session = ceremony.provider, ceremony.cloud_session
            config = ceremony.config
            ceremony.snapshot = replace(
                ceremony.snapshot, chain_stage="importing", import_error=None
            )

        # E11: no request scope here, so the import gets its own Session and
        # its own BackgroundTasks. `import_work_orders` is synchronous, so
        # the whole call runs in a worker thread; the session is opened *in*
        # that thread and never crosses back to the event loop.
        background = BackgroundTasks()
        runner = self._resolve_import_runner()

        def _import_off_loop() -> dict:
            db = self._session_factory()
            try:
                return runner(db, background, data=data, user_id=user_id)
            finally:
                db.close()

        summary: dict | None = None
        import_error: str | None = None
        try:
            summary = await asyncio.to_thread(_import_off_loop)
        except DomainError as exc:
            import_error = str(exc)
        except Exception as exc:  # noqa: BLE001 - reported, never re-raised into the loop
            logger.exception(
                "netfacilities.cloud_import_failed",
                extra={"fields": {"user_id": str(user_id)}},
            )
            import_error = str(exc) or "The import failed unexpectedly."

        if import_error is not None:
            # E6: a wrong or malformed CSV keeps the session open so the
            # user can re-export immediately without repeating the sign-in
            # ceremony; the E7 deadline still bounds a kept-open session.
            return await self._finish_chain(
                user_id,
                attempt_id,
                stage="failed",
                failed_stage="import",
                import_error=import_error,
            )

        # Awaited here so the supervisor notification `run_csv_import`
        # queued still fires (E11).
        await background()

        async with self._lock:
            ceremony = self._ceremonies.get(user_id)
            if ceremony is not None and ceremony.snapshot.attempt_id == attempt_id:
                ceremony.capture_consumed = True
                ceremony.snapshot = replace(
                    ceremony.snapshot,
                    chain_stage="imported",
                    capture_consumed=True,
                    import_result=summary,
                )

        # E6 success path: close before enriching, so the ceremony's session
        # and enrichment's own short-lived replay session never overlap.
        await self._close(user_id, attempt_id, provider, cloud_session)

        async with self._lock:
            ceremony = self._ceremonies.get(user_id)
            if ceremony is not None and ceremony.snapshot.attempt_id == attempt_id:
                ceremony.snapshot = replace(ceremony.snapshot, chain_stage="enriching")

        job_id = await self._start_enrichment(user_id, config)
        return await self._finish_chain(
            user_id,
            attempt_id,
            stage="done",
            failed_stage=None if job_id is not None else "enrichment",
            job_id=job_id,
        )

    async def _start_enrichment(
        self, user_id: UUID, config: NetFacilitiesCloudConfig
    ) -> UUID | None:
        """E5: a running batch is a queue, not a loss. Retry under the cap."""

        resolver = self._resolve_enrichment_resolver()
        jobs = self._resolve_job_coordinator()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + config.enrichment_retry_seconds
        while True:
            db = self._session_factory()
            try:
                enrichment_config, context, batch_seconds = resolver(db, user_id)
            finally:
                db.close()
            if context is None:
                return None
            try:
                snapshot, created = await jobs.start(
                    enrichment_config,
                    cloud_client_context=context,
                    cloud_user_id=user_id,
                    cloud_batch_session_seconds=batch_seconds,
                )
            except NetFacilitiesError:
                logger.exception(
                    "netfacilities.cloud_enrichment_start_failed",
                    extra={"fields": {"user_id": str(user_id)}},
                )
                return None
            if created:
                return snapshot.job_id
            if loop.time() >= deadline:
                logger.info(
                    "netfacilities.cloud_enrichment_still_busy",
                    extra={"fields": {"user_id": str(user_id)}},
                )
                return None
            await asyncio.sleep(min(5.0, config.enrichment_retry_seconds / 10))

    async def _close(
        self,
        user_id: UUID,
        attempt_id: UUID,
        provider: CloudBrowserProvider,
        cloud_session: object,
    ) -> None:
        """Release the Steel session and mark the ceremony `closed` (E6).

        The snapshot moves first, under the lock; the vendor call happens
        outside it and a failure there is logged, not raised -- the session
        will fall to Steel's own cap, and the chain must keep going.
        """
        async with self._lock:
            ceremony = self._ceremonies.get(user_id)
            if (
                ceremony is None
                or ceremony.snapshot.attempt_id != attempt_id
                or ceremony.snapshot.state != "signed_in"
            ):
                return
            ceremony.snapshot = replace(
                ceremony.snapshot,
                state="closed",
                finished_at=_now(),
                live_view_url=None,
            )
        try:
            await provider.close_login_session(cloud_session)
        except Exception:  # noqa: BLE001 - logged, chain continues
            logger.exception(
                "netfacilities.cloud_session_close_failed",
                extra={"fields": {"user_id": str(user_id)}},
            )

    async def _finish_chain(
        self,
        user_id: UUID,
        attempt_id: UUID,
        *,
        stage: ChainStage,
        failed_stage: str | None = None,
        import_error: str | None = None,
        job_id: UUID | None = None,
    ) -> NetFacilitiesCloudAuthenticationSnapshot:
        async with self._lock:
            ceremony = self._ceremonies.get(user_id)
            if ceremony is None or ceremony.snapshot.attempt_id != attempt_id:
                raise NetFacilitiesError(
                    "The NetFacilities ceremony ended before the chain finished."
                )
            ceremony.snapshot = replace(
                ceremony.snapshot,
                chain_stage=stage,
                import_error=import_error,
                enrichment_job_id=job_id,
            )
            snapshot = ceremony.snapshot

        notifier = self._resolve_notifier()
        try:
            # Synchronous delivery (pywebpush), so off the loop it goes.
            # E10: the push is the only channel that reaches a user who
            # closed the tab, which an unattended chain makes the normal
            # case.
            await asyncio.to_thread(
                notifier,
                user_id=user_id,
                ok=failed_stage is None,
                stage=failed_stage,
                import_result=snapshot.import_result,
                job_id=job_id,
            )
        except Exception:  # noqa: BLE001 - best-effort by contract
            logger.exception(
                "netfacilities.cloud_chain_notify_failed",
                extra={"fields": {"user_id": str(user_id)}},
            )
        return snapshot

    async def _poll_until_signed_in(
        self, user_id: UUID, attempt_id: UUID, config: NetFacilitiesCloudConfig
    ) -> None:
        deadline = asyncio.get_running_loop().time() + config.login_timeout_seconds
        try:
            while asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(self._poll_seconds)
                async with self._lock:
                    ceremony = self._ceremonies.get(user_id)
                    if ceremony is None or ceremony.snapshot.attempt_id != attempt_id:
                        return
                    provider, cloud_session = ceremony.provider, ceremony.cloud_session
                state_json = await provider.poll_signed_in(cloud_session)
                if state_json is None:
                    continue
                await self._persist(user_id, state_json)
                async with self._lock:
                    ceremony = self._ceremonies.get(user_id)
                    if ceremony is None or ceremony.snapshot.attempt_id != attempt_id:
                        return
                    ceremony.snapshot = replace(
                        ceremony.snapshot, state="signed_in", signed_in_at=_now()
                    )
                await self._poll_for_csv(user_id, attempt_id, config)
                return
            await self._timeout(user_id, attempt_id)
        except asyncio.CancelledError:
            pass

    async def _poll_for_csv(
        self, user_id: UUID, attempt_id: UUID, config: NetFacilitiesCloudConfig
    ) -> None:
        loop = asyncio.get_running_loop()
        # A signed-in ceremony without a deadline is what left a released
        # Steel session advertised as live -- and billed -- for 18 minutes
        # (D-C). E7 bounds it under Steel's own 15-minute cap.
        deadline = loop.time() + config.signed_in_timeout_seconds
        while loop.time() < deadline:
            await asyncio.sleep(config.capture_poll_seconds)
            async with self._lock:
                ceremony = self._ceremonies.get(user_id)
                if (
                    ceremony is None
                    or ceremony.snapshot.attempt_id != attempt_id
                    or ceremony.snapshot.state != "signed_in"
                ):
                    return
                provider, cloud_session = ceremony.provider, ceremony.cloud_session
            try:
                found = await provider.poll_downloaded_csv(cloud_session)
            except asyncio.CancelledError:
                raise
            except Exception:
                # A vendor error is a bad poll, not a dead ceremony. The
                # shipped 400 unwound this task and left the user parked in
                # `signed_in` with nothing ever polling again (D-B).
                logger.exception(
                    "netfacilities.cloud_csv_poll_failed",
                    extra={"fields": {"user_id": str(user_id)}},
                )
                continue
            if found is None:
                continue
            filename, data = found
            async with self._lock:
                ceremony = self._ceremonies.get(user_id)
                if ceremony is None or ceremony.snapshot.attempt_id != attempt_id:
                    return
                ceremony.captured_csv = (filename, data)
                ceremony.snapshot = replace(
                    ceremony.snapshot,
                    last_download_filename=filename,
                    last_download_at=_now(),
                )
            logger.info(
                "netfacilities.cloud_csv_captured",
                extra={"fields": {"user_id": str(user_id)}},
            )
            # E4: automatic and unconditional. A chain failure is recorded
            # on the snapshot and pushed to the user; the loop survives it
            # for the same reason it survives a vendor error (D-B).
            try:
                await self.dispatch_capture(user_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "netfacilities.cloud_chain_failed",
                    extra={"fields": {"user_id": str(user_id)}},
                )
        await self._timeout(user_id, attempt_id)

    async def _persist(self, user_id: UUID, state_json: str) -> None:
        token = crypto.encrypt_storage_state(state_json)
        db = self._session_factory()
        try:
            row = (
                db.query(NetFacilitiesCloudSession)
                .filter_by(user_id=user_id)
                .one_or_none()
            )
            if row is None:
                row = NetFacilitiesCloudSession(user_id=user_id, signed_in_at=_now())
                db.add(row)
            row.storage_state = token.decode("ascii")
            row.signed_in_at = _now()
            row.expires_at = None
            db.commit()
        finally:
            db.close()

    async def _timeout(self, user_id: UUID, attempt_id: UUID) -> None:
        async with self._lock:
            ceremony = self._ceremonies.get(user_id)
            if ceremony is None or ceremony.snapshot.attempt_id != attempt_id:
                return
            # Only a still-open ceremony can time out: a chain that closed
            # (or a cancel that already released the session) must not be
            # re-labelled or double-released here.
            if ceremony.snapshot.state not in {"awaiting_sign_in", "signed_in"}:
                return
            provider, cloud_session = ceremony.provider, ceremony.cloud_session
            # `live_view_url` is cleared with the release: the status endpoint
            # must never advertise a player for a session we let go (§4.4).
            ceremony.snapshot = replace(
                ceremony.snapshot,
                state="timed_out",
                finished_at=_now(),
                failure="timed_out",
                live_view_url=None,
            )
        await provider.close_login_session(cloud_session)
        logger.info(
            "netfacilities.cloud_auth_timed_out",
            extra={"fields": {"user_id": str(user_id)}},
        )
