"""Per-user NetFacilities cloud-auth login ceremony (spec D2, D3, D7).

Structurally mirrors `NetFacilitiesAuthenticationCoordinator`
(`services/netfacilities_auth.py`) -- same starting/signed_in/closed state
machine, same auto-poll-until-signed-in idea -- but keyed per `user_id`
instead of one process-global window, and persisting the successful capture
to `netfacilities_cloud_sessions` (encrypted, spec D9) instead of a local
file. No sharing between users (spec D2): each user's ceremony and captured
session are independent.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import logging
from typing import Literal, TypeAlias
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.integrations.netfacilities.cloud_config import NetFacilitiesCloudConfig
from app.integrations.netfacilities.cloud_contracts import CloudBrowserProvider
from app.integrations.netfacilities.errors import NetFacilitiesError
from app.models import NetFacilitiesCloudSession
from app.services import netfacilities_cloud_crypto as crypto


logger = logging.getLogger(__name__)

CloudAuthenticationState: TypeAlias = Literal[
    "starting", "awaiting_sign_in", "signed_in", "closed", "failed", "cancelled", "timed_out"
]
CloudAuthenticationFailure: TypeAlias = Literal["unavailable", "cancelled", "timed_out"]
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
    session_viewer_url: str | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class _Ceremony:
    snapshot: NetFacilitiesCloudAuthenticationSnapshot
    provider: CloudBrowserProvider
    cloud_session: object
    poll_task: "asyncio.Task[None] | None" = None
    captured_csv: tuple[str, bytes] | None = None


class NetFacilitiesCloudAuthenticationCoordinator:
    """Own one login ceremony per user, keyed by `user_id`."""

    def __init__(
        self,
        *,
        provider_factory: ProviderFactory,
        session_factory: SessionFactory = SessionLocal,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
    ) -> None:
        self._provider_factory = provider_factory
        self._session_factory = session_factory
        self._poll_seconds = poll_seconds
        self._lock = asyncio.Lock()
        self._ceremonies: dict[UUID, _Ceremony] = {}

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
                    snapshot=failed, provider=provider, cloud_session=None
                )
                raise

            awaiting = replace(
                attempt,
                state="awaiting_sign_in",
                session_viewer_url=cloud_session.session_viewer_url,
            )
            ceremony = _Ceremony(snapshot=awaiting, provider=provider, cloud_session=cloud_session)
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
                ceremony.snapshot, state="cancelled", finished_at=_now(), failure="cancelled"
            )
            ceremony.snapshot = finished
            return finished

    def captured_csv_bytes(self, user_id: UUID) -> tuple[str, bytes] | None:
        ceremony = self._ceremonies.get(user_id)
        return ceremony.captured_csv if ceremony is not None else None

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
                await self._poll_for_csv(user_id, attempt_id)
                return
            await self._timeout(user_id, attempt_id)
        except asyncio.CancelledError:
            pass

    async def _poll_for_csv(self, user_id: UUID, attempt_id: UUID) -> None:
        while True:
            await asyncio.sleep(self._poll_seconds * 3)
            async with self._lock:
                ceremony = self._ceremonies.get(user_id)
                if (
                    ceremony is None
                    or ceremony.snapshot.attempt_id != attempt_id
                    or ceremony.snapshot.state != "signed_in"
                ):
                    return
                provider, cloud_session = ceremony.provider, ceremony.cloud_session
            found = await provider.poll_downloaded_csv(cloud_session)
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
            provider, cloud_session = ceremony.provider, ceremony.cloud_session
            ceremony.snapshot = replace(
                ceremony.snapshot, state="timed_out", finished_at=_now(), failure="timed_out"
            )
        await provider.close_login_session(cloud_session)
        logger.info(
            "netfacilities.cloud_auth_timed_out",
            extra={"fields": {"user_id": str(user_id)}},
        )
