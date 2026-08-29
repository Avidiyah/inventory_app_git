"""Route tests for the per-user NetFacilities cloud-auth endpoints (D7, D9)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
import pytest

from app.integrations.netfacilities.config import NetFacilitiesConfig
from app.routers import netfacilities as router
from app.services.netfacilities_cloud_auth import (
    NetFacilitiesCloudAuthenticationSnapshot,
)


def _enabled_config(_tmp_path=None):
    return NetFacilitiesConfig(
        enabled=True,
        request_timeout_seconds=30,
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
        live_view_url="https://api.steel.dev/v1/sessions/sess-1/player",
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


class FakeDbWithCloudRow:
    """Returns one NetFacilitiesCloudSession-shaped row for any query."""

    def __init__(self, row):
        self._row = row

    def query(self, *_args, **_kwargs):
        return self

    def filter_by(self, *_args, **_kwargs):
        return self

    def one_or_none(self):
        return self._row


def test_enrichment_uses_the_callers_own_cloud_session(tmp_path, monkeypatch):
    from app.integrations.netfacilities import factory as factory_module

    monkeypatch.setattr(router, "load_netfacilities_config", lambda: _enabled_config(tmp_path))
    monkeypatch.setenv("NETFACILITIES_CLOUD_AUTH_ENABLED", "true")
    monkeypatch.setenv("STEEL_API_KEY", "test-key")
    from cryptography.fernet import Fernet

    monkeypatch.setenv("NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY", Fernet.generate_key().decode())

    from app.services import netfacilities_cloud_crypto as crypto

    token = crypto.encrypt_storage_state('{"cookies": []}').decode("ascii")
    row = SimpleNamespace(storage_state=token, expires_at=None)
    db = FakeDbWithCloudRow(row)

    captured = {}

    def fake_create(
        config, encrypted_storage_state, *, render_document, render_settle_ms
    ):
        captured["called"] = True
        captured["render_document"] = render_document
        captured["render_settle_ms"] = render_settle_ms
        return object()

    monkeypatch.setattr(
        factory_module, "create_netfacilities_cloud_enrichment_client", fake_create
    )

    from app.services.netfacilities_jobs import NetFacilitiesJobSnapshot

    snapshot = NetFacilitiesJobSnapshot(
        job_id=uuid4(), state="queued", source="cloud_session"
    )

    class FakeJobsCapturingCloud:
        async def start(
            self,
            _config,
            *,
            cloud_client_context=None,
            cloud_user_id=None,
            cloud_batch_session_seconds=None,
        ):
            captured["cloud_client_context"] = cloud_client_context
            captured["cloud_user_id"] = cloud_user_id
            captured["cloud_batch_session_seconds"] = cloud_batch_session_seconds
            return snapshot, True

    caller_id = uuid4()
    result = asyncio.run(
        router.start_netfacilities_enrichment(
            user=SimpleNamespace(id=caller_id),
            db=db,
            jobs=FakeJobsCapturingCloud(),
        )
    )

    assert result.source == "cloud_session"
    assert captured["called"] is True
    assert captured["cloud_client_context"] is not None
    assert captured["cloud_user_id"] == caller_id
    # Default login/batch cap (spec §4): 840s, leaving margin under Steel's
    # 15-minute session cap.
    assert captured["cloud_batch_session_seconds"] == 840
    # The render settings reach the only enrichment client that still exists.
    assert captured["render_document"] is False
    assert captured["render_settle_ms"] == 5_000


class RefusingJobs:
    async def start(self, *_args, **_kwargs):
        raise AssertionError("a job must not start without a usable configuration")

    async def get(self, _job_id):
        return None


def _disabled_config():
    return NetFacilitiesConfig(
        enabled=False,
        request_timeout_seconds=30,
        batch_timeout_seconds=1_800,
    )


def test_enrichment_is_unavailable_when_the_host_has_it_disabled(monkeypatch):
    monkeypatch.setattr(router, "load_netfacilities_config", _disabled_config)

    with pytest.raises(HTTPException) as raised:
        asyncio.run(
            router.start_netfacilities_enrichment(
                user=SimpleNamespace(id=uuid4()),
                db=FakeDbNoRow(),
                jobs=RefusingJobs(),
            )
        )

    assert raised.value.status_code == 503


def test_enrichment_without_a_saved_cloud_session_asks_the_caller_to_sign_in(
    monkeypatch,
):
    """No shared saved-state fallback survives: no session means 409, not a run."""

    monkeypatch.setattr(router, "load_netfacilities_config", _enabled_config)
    monkeypatch.setenv("NETFACILITIES_CLOUD_AUTH_ENABLED", "true")
    monkeypatch.setenv("STEEL_API_KEY", "test-key")

    from app.services.netfacilities_jobs import NetFacilitiesJobCoordinator

    with pytest.raises(HTTPException) as raised:
        asyncio.run(
            router.start_netfacilities_enrichment(
                user=SimpleNamespace(id=uuid4()),
                db=FakeDbNoRow(),
                jobs=NetFacilitiesJobCoordinator(),
            )
        )

    assert raised.value.status_code == 409
    assert "Sign in" in raised.value.detail


def test_enrichment_status_is_404_for_a_job_this_process_never_ran():
    with pytest.raises(HTTPException) as raised:
        asyncio.run(
            router.get_netfacilities_enrichment(
                job_id=uuid4(),
                _user=SimpleNamespace(id=uuid4()),
                db=FakeDbNoRow(),
                jobs=RefusingJobs(),
            )
        )

    assert raised.value.status_code == 404


def test_enrichment_status_returns_only_aggregate_counts():
    from app.services.netfacilities import NetFacilitiesEnrichmentSummary
    from app.services.netfacilities_jobs import NetFacilitiesJobSnapshot

    job_id = uuid4()
    snapshot = NetFacilitiesJobSnapshot(
        job_id=job_id,
        state="completed",
        source="cloud_session",
        summary=NetFacilitiesEnrichmentSummary(candidates=3, fetched=3),
    )

    class FakeJobs:
        async def get(self, requested_id):
            assert requested_id == job_id
            return snapshot

    result = asyncio.run(
        router.get_netfacilities_enrichment(
            job_id=job_id,
            _user=SimpleNamespace(id=uuid4()),
            db=FakeDbNoRow(),
            jobs=FakeJobs(),
        )
    )

    assert result.state == "completed"
    assert result.source == "cloud_session"
    assert result.counts.candidates == 3


def test_authentication_loss_expires_that_users_saved_cloud_session():
    """Spec D8: the row is expired only once an attempt actually reports it."""

    from app.services.netfacilities_jobs import NetFacilitiesJobSnapshot

    job_id = uuid4()
    user_id = uuid4()
    finished_at = datetime.now(timezone.utc)
    row = SimpleNamespace(storage_state="token", expires_at=None)

    class FakeDb(FakeDbWithCloudRow):
        def __init__(self):
            super().__init__(row)
            self.commits = 0

        def commit(self):
            self.commits += 1

    snapshot = NetFacilitiesJobSnapshot(
        job_id=job_id,
        state="authentication_required",
        failure="authentication_required",
        finished_at=finished_at,
        source="cloud_session",
        user_id=user_id,
    )

    class FakeJobs:
        async def get(self, _job_id):
            return snapshot

    db = FakeDb()
    asyncio.run(
        router.get_netfacilities_enrichment(
            job_id=job_id,
            _user=SimpleNamespace(id=user_id),
            db=db,
            jobs=FakeJobs(),
        )
    )

    assert row.expires_at == finished_at
    assert db.commits == 1
