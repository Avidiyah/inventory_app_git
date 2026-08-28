"""Route tests for the per-user NetFacilities cloud-auth endpoints (D7, D9)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.integrations.netfacilities.config import NetFacilitiesConfig
from app.routers import netfacilities as router
from app.services.netfacilities_cloud_auth import (
    NetFacilitiesCloudAuthenticationSnapshot,
)


def _enabled_config(tmp_path):
    return NetFacilitiesConfig(
        enabled=True,
        profile_dir=tmp_path,
        browser_channel="chrome",
        request_timeout_seconds=30,
        auth_timeout_seconds=900,
        batch_timeout_seconds=1_800,
    )


class FakeCloudAuth:
    def __init__(self, snapshot=None, *, start_error=None, cancel_error=None):
        self.snapshot = snapshot
        self.start_error = start_error
        self.cancel_error = cancel_error

    async def latest(self, _user_id):
        return self.snapshot

    async def start(self, _user_id, _config):
        if self.start_error is not None:
            raise self.start_error
        return self.snapshot

    async def cancel(self, _user_id):
        if self.cancel_error is not None:
            raise self.cancel_error
        return self.snapshot

    def captured_csv_bytes(self, _user_id):
        return None


class FakeDbNoRow:
    def query(self, *_args, **_kwargs):
        return self

    def filter_by(self, *_args, **_kwargs):
        return self

    def first(self):
        return None

    def one_or_none(self):
        return None


def _snapshot(*, state="awaiting_sign_in", user_id=None):
    now = datetime.now(timezone.utc)
    return NetFacilitiesCloudAuthenticationSnapshot(
        user_id=user_id or uuid4(),
        attempt_id=uuid4(),
        state=state,
        started_at=now,
        session_viewer_url="https://app.steel.dev/sessions/sess-1",
    )


def test_cloud_session_reports_unavailable_when_flag_off(tmp_path, monkeypatch):
    monkeypatch.setattr(router, "load_netfacilities_config", lambda: _enabled_config(tmp_path))
    monkeypatch.delenv("NETFACILITIES_CLOUD_AUTH_ENABLED", raising=False)

    result = asyncio.run(
        router.netfacilities_cloud_session(
            user=SimpleNamespace(id=uuid4()),
            db=FakeDbNoRow(),
            cloud_auth=FakeCloudAuth(),
        )
    )

    assert result.available is False


def test_cloud_session_response_never_carries_storage_state(tmp_path, monkeypatch):
    monkeypatch.setattr(router, "load_netfacilities_config", lambda: _enabled_config(tmp_path))
    monkeypatch.setenv("NETFACILITIES_CLOUD_AUTH_ENABLED", "true")
    monkeypatch.setenv("STEEL_API_KEY", "test-key")
    from cryptography.fernet import Fernet

    monkeypatch.setenv("NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY", Fernet.generate_key().decode())

    result = asyncio.run(
        router.netfacilities_cloud_session(
            user=SimpleNamespace(id=uuid4()),
            db=FakeDbNoRow(),
            cloud_auth=FakeCloudAuth(_snapshot(state="signed_in")),
        )
    )

    dumped = str(result.model_dump())
    assert "storage_state" not in dumped
    assert "steel_profile_id" not in dumped
