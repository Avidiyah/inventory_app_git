"""Offline tests for serialized, saved-state enrichment jobs."""

from __future__ import annotations

import asyncio

import pytest

from app.integrations.netfacilities.config import NetFacilitiesConfig
from app.integrations.netfacilities.errors import (
    NetFacilitiesAuthenticationRequired,
    NetFacilitiesError,
)
from app.services.netfacilities import NetFacilitiesEnrichmentSummary
from app.services.netfacilities_jobs import NetFacilitiesJobCoordinator


class FakeClientContext:
    def __init__(self, *, enter_error=None):
        self.enter_error = enter_error
        self.entered = 0
        self.exited = 0

    async def __aenter__(self):
        self.entered += 1
        if self.enter_error is not None:
            raise self.enter_error
        return object()

    async def __aexit__(self, *_args):
        self.exited += 1


def _config(tmp_path, *, authenticated=True, hosted=False):
    profile = None if hosted else tmp_path / "profile"
    if profile is not None:
        profile.mkdir()
    storage_state = tmp_path / "hosted-storage-state.json" if hosted else None
    config = NetFacilitiesConfig(
        enabled=True,
        profile_dir=profile,
        browser_channel="chrome",
        request_timeout_seconds=30,
        auth_timeout_seconds=900,
        batch_timeout_seconds=1_800,
        storage_state_file=storage_state,
        interactive_authentication_available=not hosted,
    )
    if authenticated:
        config.storage_state_path.write_text("sanitized-test-state", encoding="utf-8")
    return config


async def _wait_for_terminal(coordinator, job_id):
    for _ in range(100):
        snapshot = await coordinator.get(job_id)
        if snapshot is not None and snapshot.state not in {"queued", "running"}:
            return snapshot
        await asyncio.sleep(0)
    raise AssertionError("job did not reach a terminal state")


def test_job_refuses_missing_cli_auth_state_before_client_creation(tmp_path):
    calls = []
    coordinator = NetFacilitiesJobCoordinator(
        client_factory=lambda config: calls.append(config),
    )

    async def exercise():
        with pytest.raises(NetFacilitiesAuthenticationRequired, match="Sign in"):
            await coordinator.start(_config(tmp_path, authenticated=False))

    asyncio.run(exercise())
    assert calls == []


def test_job_owns_client_lifetime_and_returns_only_aggregate_counts(tmp_path):
    context = FakeClientContext()
    captured = {}

    async def enrich(**kwargs):
        captured.update(kwargs)
        return NetFacilitiesEnrichmentSummary(
            candidates=2,
            requests_attempted=2,
            fetched=2,
            descriptions_updated=1,
            priorities_updated=2,
        )

    coordinator = NetFacilitiesJobCoordinator(
        session_factory=lambda: None,
        client_factory=lambda _config: context,
        enrichment_runner=enrich,
    )

    async def exercise():
        started, created = await coordinator.start(_config(tmp_path))
        assert created
        finished = await _wait_for_terminal(coordinator, started.job_id)
        assert finished.state == "completed"
        assert finished.failure is None
        assert finished.summary.descriptions_updated == 1
        assert finished.summary.priorities_updated == 2

    asyncio.run(exercise())

    assert context.entered == 1
    assert context.exited == 1
    assert captured["batch_timeout_seconds"] == 1_800
    assert "client" in captured
    assert "session_factory" in captured


def test_hosted_job_accepts_saved_state_without_a_browser_profile(tmp_path):
    context = FakeClientContext()

    async def enrich(**_kwargs):
        return NetFacilitiesEnrichmentSummary()

    coordinator = NetFacilitiesJobCoordinator(
        client_factory=lambda _config: context,
        enrichment_runner=enrich,
    )

    async def exercise():
        started, created = await coordinator.start(_config(tmp_path, hosted=True))
        assert created
        finished = await _wait_for_terminal(coordinator, started.job_id)
        assert finished.state == "completed"

    asyncio.run(exercise())
    assert context.entered == 1
    assert context.exited == 1


def test_duplicate_start_returns_the_active_job(tmp_path):
    release = None

    async def exercise():
        nonlocal release
        release = asyncio.Event()

        async def enrich(**_kwargs):
            await release.wait()
            return NetFacilitiesEnrichmentSummary()

        coordinator = NetFacilitiesJobCoordinator(
            client_factory=lambda _config: FakeClientContext(),
            enrichment_runner=enrich,
        )
        config = _config(tmp_path)
        first, first_created = await coordinator.start(config)
        await asyncio.sleep(0)
        duplicate, duplicate_created = await coordinator.start(config)
        assert first_created
        assert not duplicate_created
        assert duplicate.job_id == first.job_id
        release.set()
        finished = await _wait_for_terminal(coordinator, first.job_id)
        assert finished.state == "completed"

    asyncio.run(exercise())


def test_in_flight_progress_is_shared_and_cleared_on_completion(tmp_path):
    number = "12345678901"

    async def exercise():
        reported = asyncio.Event()
        release = asyncio.Event()

        async def enrich(**kwargs):
            await kwargs["on_request_started"](number)
            reported.set()
            await release.wait()
            return NetFacilitiesEnrichmentSummary(candidates=1, fetched=1)

        coordinator = NetFacilitiesJobCoordinator(
            client_factory=lambda _config: FakeClientContext(),
            enrichment_runner=enrich,
        )
        config = _config(tmp_path)
        started, created = await coordinator.start(config)
        assert created
        await reported.wait()

        polled = await coordinator.get(started.job_id)
        duplicate, duplicate_created = await coordinator.start(config)
        assert polled.current_work_order_number == number
        assert duplicate == polled
        assert not duplicate_created

        release.set()
        finished = await _wait_for_terminal(coordinator, started.job_id)
        assert finished.state == "completed"
        assert finished.current_work_order_number is None

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("outcome", "expected_state"),
    [
        ("authentication_required", "authentication_required"),
        ("timed_out", "timed_out"),
        ("failed", "failed"),
    ],
)
def test_non_completed_terminal_states_clear_progress(
    tmp_path,
    outcome,
    expected_state,
):
    async def enrich(**kwargs):
        await kwargs["on_request_started"]("12345678901")
        if outcome == "authentication_required":
            return NetFacilitiesEnrichmentSummary(authentication_required=1)
        if outcome == "timed_out":
            return NetFacilitiesEnrichmentSummary(timed_out=True)
        raise NetFacilitiesError("sanitized failure")

    coordinator = NetFacilitiesJobCoordinator(
        client_factory=lambda _config: FakeClientContext(),
        enrichment_runner=enrich,
    )

    async def exercise():
        started, _ = await coordinator.start(_config(tmp_path))
        finished = await _wait_for_terminal(coordinator, started.job_id)
        assert finished.state == expected_state
        assert finished.current_work_order_number is None

    asyncio.run(exercise())


def test_authentication_loss_becomes_a_recoverable_job_state(tmp_path):
    context = FakeClientContext(
        enter_error=NetFacilitiesAuthenticationRequired("expired")
    )
    coordinator = NetFacilitiesJobCoordinator(
        client_factory=lambda _config: context,
    )

    async def exercise():
        started, _ = await coordinator.start(_config(tmp_path))
        finished = await _wait_for_terminal(coordinator, started.job_id)
        assert finished.state == "authentication_required"
        assert finished.failure == "authentication_required"
        assert finished.summary is None

    asyncio.run(exercise())
    assert context.entered == 1
    # __aenter__ failed, so Python correctly does not invoke __aexit__.
    assert context.exited == 0


def test_service_reported_authentication_loss_marks_job_expired(tmp_path):
    async def enrich(**_kwargs):
        return NetFacilitiesEnrichmentSummary(
            candidates=5,
            requests_attempted=2,
            authentication_required=1,
            remaining=3,
        )

    coordinator = NetFacilitiesJobCoordinator(
        client_factory=lambda _config: FakeClientContext(),
        enrichment_runner=enrich,
    )

    async def exercise():
        started, _ = await coordinator.start(_config(tmp_path))
        finished = await _wait_for_terminal(coordinator, started.job_id)
        assert finished.state == "authentication_required"
        assert finished.summary.remaining == 3

    asyncio.run(exercise())


def test_shutdown_cancels_the_batch_and_closes_its_client(tmp_path):
    context = FakeClientContext()

    async def enrich(**kwargs):
        await kwargs["on_request_started"]("12345678901")
        await asyncio.Event().wait()

    coordinator = NetFacilitiesJobCoordinator(
        client_factory=lambda _config: context,
        enrichment_runner=enrich,
    )

    async def exercise():
        started, _ = await coordinator.start(_config(tmp_path))
        for _ in range(100):
            if context.entered:
                break
            await asyncio.sleep(0)
        await coordinator.shutdown()
        finished = await coordinator.get(started.job_id)
        assert finished.state == "cancelled"
        assert finished.failure == "cancelled"
        assert finished.current_work_order_number is None

    asyncio.run(exercise())
    assert context.entered == 1
    assert context.exited == 1
