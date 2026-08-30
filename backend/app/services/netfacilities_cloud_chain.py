"""The unattended capture chain: import -> close -> enrich -> notify.

The other half of `NetFacilitiesCloudAuthenticationCoordinator`
(`netfacilities_cloud_auth.py`), split out purely to keep both files under
the repo's size rule -- `CaptureChainMixin` is not a boundary and reads the
coordinator's own private state (`_lock`, `_ceremonies`, `_session_factory`,
and the injected collaborators). `dispatch_capture` is the one entry point
both the automatic trigger and the manual Import button run (E8).
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
import logging
from typing import TYPE_CHECKING, Literal, TypeAlias
from uuid import UUID

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from app.domain.errors import DomainError
from app.integrations.netfacilities.cloud_config import NetFacilitiesCloudConfig
from app.integrations.netfacilities.errors import (
    NetFacilitiesError,
    NetFacilitiesUnavailable,
)

if TYPE_CHECKING:  # pragma: no cover - annotation-only, avoids the import cycle
    from app.integrations.netfacilities.cloud_contracts import CloudBrowserProvider
    from app.services.netfacilities_cloud_auth import (
        NetFacilitiesCloudAuthenticationSnapshot,
    )

logger = logging.getLogger(__name__)

ChainStage: TypeAlias = Literal["importing", "imported", "enriching", "done", "failed"]


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


class CaptureChainMixin:
    """Chain methods mixed into `NetFacilitiesCloudAuthenticationCoordinator`."""

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
