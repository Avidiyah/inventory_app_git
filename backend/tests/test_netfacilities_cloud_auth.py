"""Offline tests for the per-user NetFacilities cloud-auth coordinator
(spec D2, D3, D7)."""

from __future__ import annotations

import asyncio
import uuid

from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from app.integrations.netfacilities.cloud_config import NetFacilitiesCloudConfig
from app.models import NetFacilitiesCloudSession, User
from app.services.netfacilities_cloud_auth import (
    NetFacilitiesCloudAuthenticationCoordinator,
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


class FakeLoginSession:
    def __init__(self, session_id="sess-1"):
        self.session_id = session_id
        self.live_view_url = f"https://api.steel.dev/v1/sessions/{session_id}/player"


class FakeCloudBrowserProvider:
    def __init__(self):
        self.signed_in_after_polls = 1
        self._polls = 0
        self.closed_sessions = []
        self.csv_to_return = None
        self.csv_poll_calls = 0
        self.raise_on_csv_poll = 0

    async def open_login_session(self):
        return FakeLoginSession()

    async def poll_signed_in(self, session):
        self._polls += 1
        if self._polls < self.signed_in_after_polls:
            return None
        return '{"cookies": [{"name": "session", "value": "abc"}]}'

    async def poll_downloaded_csv(self, session):
        self.csv_poll_calls += 1
        if self.csv_poll_calls <= self.raise_on_csv_poll:
            raise RuntimeError("Error code: 400 - Bad Request")
        return self.csv_to_return

    async def close_login_session(self, session):
        self.closed_sessions.append(session.session_id)

    async def open_replay_context(self, storage_state):
        raise NotImplementedError


def _config(**overrides):
    settings = {
        "enabled": True,
        "steel_api_key": "test-key",
        "login_timeout_seconds": 60,
        "signed_in_timeout_seconds": 600,
        "capture_poll_seconds": 5,
        "enrichment_retry_seconds": 120,
    }
    settings.update(overrides)
    return NetFacilitiesCloudConfig(**settings)


def _user(db):
    user = User(
        username=f"tech-{uuid.uuid4().hex[:8]}",
        first_name="Test",
        last_name="User",
        password_hash="x",
        role="technician",
    )
    db.add(user)
    db.commit()
    return user


def test_start_then_captures_state_and_writes_encrypted_row(db, monkeypatch):
    monkeypatch.setenv(
        "NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY", Fernet.generate_key().decode()
    )
    user = _user(db)
    provider = FakeCloudBrowserProvider()
    coordinator = NetFacilitiesCloudAuthenticationCoordinator(
        provider_factory=lambda _config: provider,
        session_factory=_session_factory(db),
        poll_seconds=0.01,
    )

    async def _run():
        snapshot = await coordinator.start(user.id, _config())
        assert snapshot.live_view_url.endswith("/player")
        for _ in range(200):
            latest = await coordinator.latest(user.id)
            if latest.state == "signed_in":
                return latest
            await asyncio.sleep(0.01)
        raise AssertionError("never reached signed_in")

    signed_in = asyncio.run(_run())
    assert signed_in.signed_in_at is not None

    row = (
        db.query(NetFacilitiesCloudSession)
        .filter_by(user_id=user.id)
        .one()
    )
    assert row.storage_state != '{"cookies": [{"name": "session", "value": "abc"}]}'


def test_two_users_get_independent_ceremonies(db, monkeypatch):
    monkeypatch.setenv("NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY", Fernet.generate_key().decode())
    user_a = _user(db)
    user_b = _user(db)
    coordinator = NetFacilitiesCloudAuthenticationCoordinator(
        provider_factory=lambda _config: FakeCloudBrowserProvider(),
        session_factory=_session_factory(db),
        poll_seconds=0.01,
    )

    async def _run():
        snap_a = await coordinator.start(user_a.id, _config())
        snap_b = await coordinator.start(user_b.id, _config())
        return snap_a, snap_b

    snap_a, snap_b = asyncio.run(_run())
    assert snap_a.attempt_id != snap_b.attempt_id


def test_cancel_closes_the_cloud_session(db, monkeypatch):
    monkeypatch.setenv("NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY", Fernet.generate_key().decode())
    user = _user(db)
    provider = FakeCloudBrowserProvider()
    provider.signed_in_after_polls = 10_000  # never signs in during this test
    coordinator = NetFacilitiesCloudAuthenticationCoordinator(
        provider_factory=lambda _config: provider,
        session_factory=_session_factory(db),
        poll_seconds=0.01,
    )

    async def _run():
        await coordinator.start(user.id, _config())
        await asyncio.sleep(0.02)
        return await coordinator.cancel(user.id)

    result = asyncio.run(_run())
    assert result.state == "cancelled"
    assert provider.closed_sessions == ["sess-1"]


def test_a_provider_error_does_not_kill_the_capture_loop(db, monkeypatch):
    # The shipped bug: one BadRequestError unwound the whole poll task and
    # nothing ever polled again for the life of the process.
    monkeypatch.setenv(
        "NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY", Fernet.generate_key().decode()
    )
    user = _user(db)
    provider = FakeCloudBrowserProvider()
    provider.raise_on_csv_poll = 1
    provider.csv_to_return = ("work-orders.csv", b"NUMBER\n1001\n")
    coordinator = NetFacilitiesCloudAuthenticationCoordinator(
        provider_factory=lambda _config: provider,
        session_factory=_session_factory(db),
        poll_seconds=0.01,
    )

    async def _exercise():
        await coordinator.start(user.id, _config(capture_poll_seconds=0.01))
        for _ in range(200):
            await asyncio.sleep(0.01)
            if coordinator.captured_csv_bytes(user.id) is not None:
                break
        return coordinator.captured_csv_bytes(user.id)

    captured = asyncio.run(_exercise())

    assert provider.csv_poll_calls >= 2
    assert captured == ("work-orders.csv", b"NUMBER\n1001\n")


def test_a_signed_in_ceremony_expires_and_releases_the_session(db, monkeypatch):
    # Observed in production: signed_in for 18 minutes against a session
    # Steel had already reaped, still billed, still advertising a dead
    # live-view URL (D-C). E7 gives the signed-in half its own deadline.
    monkeypatch.setenv(
        "NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY", Fernet.generate_key().decode()
    )
    user = _user(db)
    provider = FakeCloudBrowserProvider()
    coordinator = NetFacilitiesCloudAuthenticationCoordinator(
        provider_factory=lambda _config: provider,
        session_factory=_session_factory(db),
        poll_seconds=0.01,
    )

    async def _exercise():
        await coordinator.start(
            user.id, _config(signed_in_timeout_seconds=0.2, capture_poll_seconds=0.01)
        )
        for _ in range(300):
            await asyncio.sleep(0.01)
            snapshot = await coordinator.latest(user.id)
            if snapshot.state == "timed_out":
                break
        return await coordinator.latest(user.id)

    snapshot = asyncio.run(_exercise())

    assert snapshot.state == "timed_out"
    assert snapshot.failure == "timed_out"
    assert snapshot.live_view_url is None
    assert provider.closed_sessions == ["sess-1"]


def test_an_unconsumed_capture_is_reported_as_unconsumed(db, monkeypatch):
    monkeypatch.setenv(
        "NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY", Fernet.generate_key().decode()
    )
    user = _user(db)
    provider = FakeCloudBrowserProvider()
    provider.csv_to_return = ("work-orders.csv", b"NUMBER\n1001\n")
    coordinator = NetFacilitiesCloudAuthenticationCoordinator(
        provider_factory=lambda _config: provider,
        session_factory=_session_factory(db),
        poll_seconds=0.01,
    )

    async def _exercise():
        await coordinator.start(user.id, _config(capture_poll_seconds=0.01))
        for _ in range(200):
            await asyncio.sleep(0.01)
            if coordinator.captured_csv_bytes(user.id) is not None:
                break
        return await coordinator.latest(user.id)

    snapshot = asyncio.run(_exercise())

    assert snapshot.last_download_filename == "work-orders.csv"
    assert snapshot.capture_consumed is False
