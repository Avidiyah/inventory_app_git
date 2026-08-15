"""Offline tests for the in-app headed NetFacilities sign-in lifecycle."""

from __future__ import annotations

import asyncio

import pytest

from app.integrations.netfacilities.config import NetFacilitiesConfig
from app.integrations.netfacilities.errors import (
    NetFacilitiesAuthenticationRequired,
    NetFacilitiesOperationInProgress,
    NetFacilitiesUnavailable,
)
from app.services.netfacilities import NetFacilitiesEnrichmentSummary
from app.services.netfacilities_auth import NetFacilitiesAuthenticationCoordinator
from app.services.netfacilities_jobs import NetFacilitiesJobCoordinator
from app.services.netfacilities_operations import NetFacilitiesOperationGate


class FakeAuthenticationClient:
    def __init__(self, *, verify_error=None):
        self.verify_error = verify_error
        self.opened = 0
        self.verified = 0
        self.persisted = 0

    async def open_authentication_page(self):
        self.opened += 1

    async def verify_authentication_page(self):
        self.verified += 1
        if self.verify_error is not None:
            raise self.verify_error

    async def persist_authentication_state(self):
        self.persisted += 1


class FakeAuthenticationContext:
    def __init__(self, client=None):
        self.client = client or FakeAuthenticationClient()
        self.entered = 0
        self.exited = 0

    async def __aenter__(self):
        self.entered += 1
        return self.client

    async def __aexit__(self, *_args):
        self.exited += 1


class FakeEnrichmentContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *_args):
        return None


def _config(tmp_path, *, timeout=900, authenticated=False):
    profile = tmp_path / "profile"
    profile.mkdir(exist_ok=True)
    config = NetFacilitiesConfig(
        enabled=True,
        profile_dir=profile,
        browser_channel="chrome",
        request_timeout_seconds=30,
        auth_timeout_seconds=timeout,
        batch_timeout_seconds=1_800,
    )
    if authenticated:
        config.storage_state_path.write_text("sanitized-test-state", encoding="utf-8")
    return config


def test_start_and_confirm_save_state_then_release_the_profile(tmp_path):
    gate = NetFacilitiesOperationGate()
    context = FakeAuthenticationContext()
    coordinator = NetFacilitiesAuthenticationCoordinator(
        client_factory=lambda _config: context,
        profile_gate=gate,
    )

    async def exercise():
        started, created = await coordinator.start(_config(tmp_path))
        assert created
        assert started.state == "awaiting_confirmation"
        assert await gate.active_kind() == "authentication"

        finished = await coordinator.confirm()
        assert finished.attempt_id == started.attempt_id
        assert finished.state == "authenticated"
        assert await gate.active_kind() is None

    asyncio.run(exercise())
    assert context.entered == 1
    assert context.exited == 1
    assert context.client.opened == 1
    assert context.client.verified == 1
    assert context.client.persisted == 1


def test_confirm_too_early_keeps_browser_open_for_another_attempt(tmp_path):
    client = FakeAuthenticationClient(
        verify_error=NetFacilitiesAuthenticationRequired("still on login")
    )
    context = FakeAuthenticationContext(client)
    coordinator = NetFacilitiesAuthenticationCoordinator(
        client_factory=lambda _config: context,
        profile_gate=NetFacilitiesOperationGate(),
    )

    async def exercise():
        await coordinator.start(_config(tmp_path))
        with pytest.raises(NetFacilitiesAuthenticationRequired):
            await coordinator.confirm()
        assert (await coordinator.latest()).state == "awaiting_confirmation"
        assert context.exited == 0
        assert client.persisted == 0

        client.verify_error = None
        assert (await coordinator.confirm()).state == "authenticated"

    asyncio.run(exercise())
    assert context.exited == 1
    assert client.persisted == 1


def test_duplicate_start_returns_same_pending_attempt(tmp_path):
    context = FakeAuthenticationContext()
    coordinator = NetFacilitiesAuthenticationCoordinator(
        client_factory=lambda _config: context,
        profile_gate=NetFacilitiesOperationGate(),
    )

    async def exercise():
        first, created = await coordinator.start(_config(tmp_path))
        duplicate, duplicate_created = await coordinator.start(_config(tmp_path))
        assert created
        assert not duplicate_created
        assert duplicate.attempt_id == first.attempt_id
        await coordinator.cancel()

    asyncio.run(exercise())
    assert context.entered == 1
    assert context.exited == 1


def test_cancel_closes_browser_without_persisting_state(tmp_path):
    context = FakeAuthenticationContext()
    coordinator = NetFacilitiesAuthenticationCoordinator(
        client_factory=lambda _config: context,
        profile_gate=NetFacilitiesOperationGate(),
    )

    async def exercise():
        await coordinator.start(_config(tmp_path))
        assert (await coordinator.cancel()).state == "cancelled"

    asyncio.run(exercise())
    assert context.exited == 1
    assert context.client.persisted == 0


def test_client_factory_failure_releases_profile_gate(tmp_path):
    gate = NetFacilitiesOperationGate()

    def unavailable(_config):
        raise NetFacilitiesUnavailable("dependencies unavailable")

    coordinator = NetFacilitiesAuthenticationCoordinator(
        client_factory=unavailable,
        profile_gate=gate,
    )

    async def exercise():
        with pytest.raises(NetFacilitiesUnavailable):
            await coordinator.start(_config(tmp_path))
        assert (await coordinator.latest()).state == "failed"
        assert await gate.active_kind() is None

    asyncio.run(exercise())


def test_abandoned_sign_in_times_out_and_releases_profile(tmp_path):
    gate = NetFacilitiesOperationGate()
    context = FakeAuthenticationContext()
    coordinator = NetFacilitiesAuthenticationCoordinator(
        client_factory=lambda _config: context,
        profile_gate=gate,
    )

    async def exercise():
        await coordinator.start(_config(tmp_path, timeout=0.001))
        for _ in range(100):
            if (await coordinator.latest()).state == "timed_out":
                break
            await asyncio.sleep(0.001)
        assert (await coordinator.latest()).state == "timed_out"
        assert await gate.active_kind() is None

    asyncio.run(exercise())
    assert context.exited == 1


def test_enrichment_cannot_start_while_sign_in_owns_profile(tmp_path):
    gate = NetFacilitiesOperationGate()
    authentication = NetFacilitiesAuthenticationCoordinator(
        client_factory=lambda _config: FakeAuthenticationContext(),
        profile_gate=gate,
    )
    jobs = NetFacilitiesJobCoordinator(
        client_factory=lambda _config: FakeEnrichmentContext(),
        enrichment_runner=lambda **_kwargs: _completed_summary(),
        profile_gate=gate,
    )

    async def exercise():
        config = _config(tmp_path, authenticated=True)
        await authentication.start(config)
        with pytest.raises(NetFacilitiesOperationInProgress):
            await jobs.start(config)
        await authentication.cancel()

        started, created = await jobs.start(config)
        assert created
        for _ in range(100):
            finished = await jobs.get(started.job_id)
            if finished is not None and finished.state == "completed":
                break
            await asyncio.sleep(0)
        assert finished.state == "completed"

    asyncio.run(exercise())


async def _completed_summary():
    return NetFacilitiesEnrichmentSummary()
