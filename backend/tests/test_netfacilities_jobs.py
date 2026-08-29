"""Offline tests for serialized, cloud-session enrichment jobs."""

from __future__ import annotations

import asyncio
from uuid import uuid4

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
        self.client = object()

    async def __aenter__(self):
        self.entered += 1
        if self.enter_error is not None:
            raise self.enter_error
        return self.client

    async def __aexit__(self, *_args):
        self.exited += 1


def _config(*, enabled=True):
    return NetFacilitiesConfig(
        enabled=enabled,
        request_timeout_seconds=30,
        batch_timeout_seconds=1_800,
    )


async def _never_called(**_kwargs):
    raise AssertionError("enrichment must not run without a client")


async def _wait_for_terminal(coordinator, job_id):
    for _ in range(100):
        snapshot = await coordinator.get(job_id)
        if snapshot is not None and snapshot.state not in {"queued", "running"}:
            return snapshot
        await asyncio.sleep(0)
    raise AssertionError("job did not reach a terminal state")


def test_disabled_host_refuses_before_any_client_is_entered():
    cloud = FakeClientContext()
    coordinator = NetFacilitiesJobCoordinator(enrichment_runner=_never_called)

    async def exercise():
        with pytest.raises(NetFacilitiesAuthenticationRequired, match="not enabled"):
            await coordinator.start(
                _config(enabled=False),
                cloud_client_context=cloud,
            )

    asyncio.run(exercise())
    assert cloud.entered == 0


def test_a_caller_without_a_cloud_session_is_told_to_sign_in():
    """There is no shared saved-state fallback: the caller's own session or nothing."""

    coordinator = NetFacilitiesJobCoordinator(enrichment_runner=_never_called)

    async def exercise():
        with pytest.raises(NetFacilitiesAuthenticationRequired, match="Sign in"):
            await coordinator.start(_config(), cloud_client_context=None)

    asyncio.run(exercise())


def test_job_owns_client_lifetime_and_returns_only_aggregate_counts():
    cloud = FakeClientContext()
    user_id = uuid4()
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
        enrichment_runner=enrich,
    )

    async def exercise():
        started, created = await coordinator.start(
            _config(),
            cloud_client_context=cloud,
            cloud_user_id=user_id,
            cloud_batch_session_seconds=900,
        )
        assert created
        assert started.source == "cloud_session"
        assert started.user_id == user_id
        finished = await _wait_for_terminal(coordinator, started.job_id)
        assert finished.state == "completed"
        assert finished.failure is None
        assert finished.source == "cloud_session"
        assert finished.user_id == user_id
        assert finished.summary.descriptions_updated == 1
        assert finished.summary.priorities_updated == 2

    asyncio.run(exercise())

    assert cloud.entered == 1
    assert cloud.exited == 1
    assert captured["client"] is cloud.client
    # The configured batch timeout still applies; Steel's tighter session cap
    # rides alongside it rather than replacing it.
    assert captured["batch_timeout_seconds"] == 1_800
    assert captured["cloud_session_deadline_seconds"] == 900
    assert "session_factory" in captured


def test_duplicate_start_returns_the_active_job():
    async def exercise():
        release = asyncio.Event()

        async def enrich(**_kwargs):
            await release.wait()
            return NetFacilitiesEnrichmentSummary()

        coordinator = NetFacilitiesJobCoordinator(enrichment_runner=enrich)
        first, first_created = await coordinator.start(
            _config(), cloud_client_context=FakeClientContext()
        )
        await asyncio.sleep(0)
        duplicate, duplicate_created = await coordinator.start(
            _config(), cloud_client_context=FakeClientContext()
        )
        assert first_created
        assert not duplicate_created
        assert duplicate.job_id == first.job_id
        release.set()
        finished = await _wait_for_terminal(coordinator, first.job_id)
        assert finished.state == "completed"

    asyncio.run(exercise())


def test_in_flight_progress_is_shared_and_cleared_on_completion():
    number = "12345678901"

    async def exercise():
        reported = asyncio.Event()
        release = asyncio.Event()

        async def enrich(**kwargs):
            await kwargs["on_request_started"](number)
            reported.set()
            await release.wait()
            return NetFacilitiesEnrichmentSummary(candidates=1, fetched=1)

        coordinator = NetFacilitiesJobCoordinator(enrichment_runner=enrich)
        started, created = await coordinator.start(
            _config(), cloud_client_context=FakeClientContext()
        )
        assert created
        await reported.wait()

        polled = await coordinator.get(started.job_id)
        duplicate, duplicate_created = await coordinator.start(
            _config(), cloud_client_context=FakeClientContext()
        )
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
def test_non_completed_terminal_states_clear_progress(outcome, expected_state):
    async def enrich(**kwargs):
        await kwargs["on_request_started"]("12345678901")
        if outcome == "authentication_required":
            return NetFacilitiesEnrichmentSummary(authentication_required=1)
        if outcome == "timed_out":
            return NetFacilitiesEnrichmentSummary(timed_out=True)
        raise NetFacilitiesError("sanitized failure")

    coordinator = NetFacilitiesJobCoordinator(enrichment_runner=enrich)

    async def exercise():
        started, _ = await coordinator.start(
            _config(), cloud_client_context=FakeClientContext()
        )
        finished = await _wait_for_terminal(coordinator, started.job_id)
        assert finished.state == expected_state
        assert finished.current_work_order_number is None
        assert finished.source == "cloud_session"

    asyncio.run(exercise())


def test_unexpected_failure_is_classified_without_a_summary():
    async def enrich(**_kwargs):
        raise RuntimeError("something the integration never modelled")

    coordinator = NetFacilitiesJobCoordinator(enrichment_runner=enrich)

    async def exercise():
        started, _ = await coordinator.start(
            _config(), cloud_client_context=FakeClientContext()
        )
        finished = await _wait_for_terminal(coordinator, started.job_id)
        assert finished.state == "failed"
        assert finished.failure == "unexpected_failure"
        assert finished.summary is None

    asyncio.run(exercise())


def test_authentication_loss_becomes_a_recoverable_job_state():
    cloud = FakeClientContext(
        enter_error=NetFacilitiesAuthenticationRequired("expired")
    )
    user_id = uuid4()
    coordinator = NetFacilitiesJobCoordinator(enrichment_runner=_never_called)

    async def exercise():
        started, _ = await coordinator.start(
            _config(),
            cloud_client_context=cloud,
            cloud_user_id=user_id,
        )
        finished = await _wait_for_terminal(coordinator, started.job_id)
        assert finished.state == "authentication_required"
        assert finished.failure == "authentication_required"
        assert finished.summary is None
        # The router expires exactly this user's saved cloud session (spec D8).
        assert finished.user_id == user_id

    asyncio.run(exercise())
    assert cloud.entered == 1
    # __aenter__ failed, so Python correctly does not invoke __aexit__.
    assert cloud.exited == 0


def test_service_reported_authentication_loss_marks_job_expired():
    async def enrich(**_kwargs):
        return NetFacilitiesEnrichmentSummary(
            candidates=5,
            requests_attempted=2,
            authentication_required=1,
            remaining=3,
        )

    coordinator = NetFacilitiesJobCoordinator(enrichment_runner=enrich)

    async def exercise():
        started, _ = await coordinator.start(
            _config(), cloud_client_context=FakeClientContext()
        )
        finished = await _wait_for_terminal(coordinator, started.job_id)
        assert finished.state == "authentication_required"
        assert finished.summary.remaining == 3

    asyncio.run(exercise())


def test_shutdown_cancels_the_batch_and_closes_its_client():
    cloud = FakeClientContext()

    async def enrich(**kwargs):
        await kwargs["on_request_started"]("12345678901")
        await asyncio.Event().wait()

    coordinator = NetFacilitiesJobCoordinator(enrichment_runner=enrich)

    async def exercise():
        started, _ = await coordinator.start(
            _config(), cloud_client_context=cloud
        )
        for _ in range(100):
            if cloud.entered:
                break
            await asyncio.sleep(0)
        await coordinator.shutdown()
        finished = await coordinator.get(started.job_id)
        assert finished.state == "cancelled"
        assert finished.failure == "cancelled"
        assert finished.current_work_order_number is None

    asyncio.run(exercise())
    assert cloud.entered == 1
    assert cloud.exited == 1
