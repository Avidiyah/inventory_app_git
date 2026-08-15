"""Secret-safe route behavior for local NetFacilities enrichment."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
import pytest

from app.integrations.netfacilities.config import NetFacilitiesConfig
from app.integrations.netfacilities.errors import NetFacilitiesAuthenticationRequired
from app.routers import netfacilities as router
from app.services.netfacilities import NetFacilitiesEnrichmentSummary
from app.services.netfacilities_auth import NetFacilitiesAuthenticationSnapshot
from app.services.netfacilities_jobs import NetFacilitiesJobSnapshot


def _config(
    tmp_path,
    *,
    enabled=True,
    authenticated=True,
    interactive_authentication_available=True,
):
    profile = tmp_path / "profile" if interactive_authentication_available else None
    if profile is not None:
        profile.mkdir()
    storage_state = (
        None
        if interactive_authentication_available
        else tmp_path / "netfacilities-storage-state.json"
    )
    config = NetFacilitiesConfig(
        enabled=enabled,
        profile_dir=profile if enabled else None,
        browser_channel="chrome",
        request_timeout_seconds=30,
        auth_timeout_seconds=900,
        batch_timeout_seconds=1_800,
        storage_state_file=storage_state if enabled else None,
        interactive_authentication_available=(
            interactive_authentication_available if enabled else False
        ),
    )
    if enabled and authenticated:
        config.storage_state_path.write_text("test-state", encoding="utf-8")
    return config


class FakeJobs:
    def __init__(self, snapshot=None, start_error=None):
        self.snapshot = snapshot
        self.start_error = start_error

    async def latest(self):
        return self.snapshot

    async def start(self, _config):
        if self.start_error is not None:
            raise self.start_error
        return self.snapshot, True

    async def get(self, job_id):
        if self.snapshot is not None and self.snapshot.job_id == job_id:
            return self.snapshot
        return None


class FakeAuthentication:
    def __init__(self, snapshot=None, *, confirm_error=None):
        self.snapshot = snapshot
        self.confirm_error = confirm_error

    async def latest(self):
        return self.snapshot

    async def start(self, _config):
        return self.snapshot, True

    async def confirm(self):
        if self.confirm_error is not None:
            raise self.confirm_error
        return self.snapshot

    async def cancel(self):
        return self.snapshot


def _authentication_snapshot(*, state="awaiting_confirmation"):
    now = datetime.now(timezone.utc)
    return NetFacilitiesAuthenticationSnapshot(
        attempt_id=uuid4(),
        state=state,
        started_at=now,
        finished_at=now if state not in {"starting", "awaiting_confirmation", "confirming"} else None,
    )


def test_session_reports_disabled_without_exposing_configuration(monkeypatch):
    # Use a deliberately disabled config without creating or returning a path.
    disabled = NetFacilitiesConfig(
        enabled=False,
        profile_dir=None,
        browser_channel="chrome",
        request_timeout_seconds=30,
        auth_timeout_seconds=900,
        batch_timeout_seconds=1_800,
    )
    monkeypatch.setattr(router, "load_netfacilities_config", lambda: disabled)
    result = asyncio.run(
        router.netfacilities_session(
            _user=SimpleNamespace(),
            jobs=FakeJobs(),
            authentication=FakeAuthentication(),
        )
    )

    assert not result.available
    assert result.state == "unavailable"
    assert "profile" not in result.model_dump()


def test_session_reports_ready_after_saved_state(tmp_path, monkeypatch):
    config = _config(tmp_path)
    monkeypatch.setattr(router, "load_netfacilities_config", lambda: config)

    result = asyncio.run(
        router.netfacilities_session(
            _user=SimpleNamespace(),
            jobs=FakeJobs(),
            authentication=FakeAuthentication(),
        )
    )

    assert result.available
    assert result.state == "ready"
    assert result.latest_job is None
    assert result.interactive_authentication_available


def test_session_reports_hosted_saved_state_without_interactive_sign_in(
    tmp_path, monkeypatch
):
    config = _config(
        tmp_path,
        interactive_authentication_available=False,
    )
    monkeypatch.setattr(router, "load_netfacilities_config", lambda: config)

    result = asyncio.run(
        router.netfacilities_session(
            _user=SimpleNamespace(),
            jobs=FakeJobs(),
            authentication=FakeAuthentication(),
        )
    )

    assert result.available
    assert result.state == "ready"
    assert not result.interactive_authentication_available


def test_hosted_mode_rejects_interactive_sign_in(tmp_path, monkeypatch):
    config = _config(
        tmp_path,
        interactive_authentication_available=False,
    )
    monkeypatch.setattr(router, "load_netfacilities_config", lambda: config)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            router.start_netfacilities_authentication(
                _user=SimpleNamespace(),
                authentication=FakeAuthentication(),
            )
        )

    assert exc.value.status_code == 503
    assert "unavailable on this host" in exc.value.detail


def test_session_reports_pending_in_app_authentication(tmp_path, monkeypatch):
    config = _config(tmp_path, authenticated=False)
    monkeypatch.setattr(router, "load_netfacilities_config", lambda: config)
    attempt = _authentication_snapshot()

    result = asyncio.run(
        router.netfacilities_session(
            _user=SimpleNamespace(),
            jobs=FakeJobs(),
            authentication=FakeAuthentication(attempt),
        )
    )

    assert result.available
    assert result.state == "authenticating"
    assert result.latest_authentication.attempt_id == attempt.attempt_id
    assert "profile" not in result.model_dump()


def test_authentication_routes_return_only_safe_attempt_state(tmp_path, monkeypatch):
    config = _config(tmp_path, authenticated=False)
    monkeypatch.setattr(router, "load_netfacilities_config", lambda: config)
    waiting = _authentication_snapshot()
    authenticated = _authentication_snapshot(state="authenticated")

    started = asyncio.run(
        router.start_netfacilities_authentication(
            _user=SimpleNamespace(),
            authentication=FakeAuthentication(waiting),
        )
    )
    confirmed = asyncio.run(
        router.confirm_netfacilities_authentication(
            _user=SimpleNamespace(),
            authentication=FakeAuthentication(authenticated),
        )
    )
    cancelled = asyncio.run(
        router.cancel_netfacilities_authentication(
            _user=SimpleNamespace(),
            authentication=FakeAuthentication(
                _authentication_snapshot(state="cancelled")
            ),
        )
    )

    assert started.state == "awaiting_confirmation"
    assert confirmed.state == "authenticated"
    assert cancelled.state == "cancelled"
    assert "profile" not in started.model_dump()


def test_confirm_too_early_is_recoverable_without_exposing_details():
    authentication = FakeAuthentication(
        _authentication_snapshot(),
        confirm_error=NetFacilitiesAuthenticationRequired("protected detail omitted"),
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            router.confirm_netfacilities_authentication(
                _user=SimpleNamespace(),
                authentication=authentication,
            )
        )

    assert exc.value.status_code == 409
    assert "Finish signing in" in exc.value.detail
    assert "protected" not in exc.value.detail


def test_start_translates_missing_authentication_to_recoverable_409(
    tmp_path, monkeypatch
):
    config = _config(tmp_path, authenticated=False)
    monkeypatch.setattr(router, "load_netfacilities_config", lambda: config)
    jobs = FakeJobs(
        start_error=NetFacilitiesAuthenticationRequired("protected path omitted")
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            router.start_netfacilities_enrichment(
                _user=SimpleNamespace(),
                jobs=jobs,
            )
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == "Sign in to NetFacilities before enrichment."
    assert "path" not in exc.value.detail


def test_job_response_contains_counts_but_no_source_values(tmp_path, monkeypatch):
    config = _config(tmp_path)
    monkeypatch.setattr(router, "load_netfacilities_config", lambda: config)
    snapshot = NetFacilitiesJobSnapshot(
        job_id=uuid4(),
        state="completed",
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
        summary=NetFacilitiesEnrichmentSummary(
            candidates=3,
            fetched=3,
            descriptions_updated=2,
            priorities_updated=1,
        ),
    )

    response = asyncio.run(
        router.start_netfacilities_enrichment(
            _user=SimpleNamespace(),
            jobs=FakeJobs(snapshot=snapshot),
        )
    )
    payload = response.model_dump(mode="json")

    assert payload["counts"]["descriptions_updated"] == 2
    assert payload["counts"]["priorities_updated"] == 1
    assert "description" not in payload
    assert "priority" not in payload
    assert "profile" not in payload


def test_unknown_process_local_job_returns_404():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            router.get_netfacilities_enrichment(
                uuid4(),
                _user=SimpleNamespace(),
                jobs=FakeJobs(),
            )
        )

    assert exc.value.status_code == 404
