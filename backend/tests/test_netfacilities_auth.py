"""Offline tests for the in-app NetFacilities live session lifecycle."""

from __future__ import annotations

import asyncio

import pytest

from app.integrations.netfacilities.config import NetFacilitiesConfig
from app.integrations.netfacilities.errors import (
    NetFacilitiesAuthenticationRequired,
    NetFacilitiesOperationInProgress,
    NetFacilitiesUnavailable,
    NetFacilitiesUnexpectedResponse,
)
from app.services.netfacilities import NetFacilitiesEnrichmentSummary
from app.services.netfacilities_auth import NetFacilitiesAuthenticationCoordinator
from app.services.netfacilities_jobs import NetFacilitiesJobCoordinator
from app.services.netfacilities_operations import NetFacilitiesOperationGate


class FakeAuthenticationClient:
    def __init__(self, *, verify_error=None, prime_error=None):
        self.verify_error = verify_error
        self.prime_error = prime_error
        self.opened = 0
        self.verified = 0
        self.primed = 0
        self.persisted = 0
        self.download_destination = None
        self.on_saved = None
        self.close_callback = None
        self.work_orders_requested = []

    async def open_authentication_page(self):
        self.opened += 1

    async def verify_authentication_page(self):
        self.verified += 1
        if self.verify_error is not None:
            raise self.verify_error

    async def prime_session(self):
        self.primed += 1
        if self.prime_error is not None:
            raise self.prime_error

    async def persist_authentication_state(self):
        self.persisted += 1

    def capture_downloads(self, destination, on_saved):
        self.download_destination = destination
        self.on_saved = on_saved

    def on_context_closed(self, callback):
        self.close_callback = callback

    async def get_work_order(self, work_order_number):
        self.work_orders_requested.append(work_order_number)
        return object()


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


def _config(tmp_path, *, timeout=900, session_timeout=7_200, authenticated=False):
    profile = tmp_path / "profile"
    profile.mkdir(exist_ok=True)
    config = NetFacilitiesConfig(
        enabled=True,
        profile_dir=profile,
        browser_channel="chrome",
        request_timeout_seconds=30,
        auth_timeout_seconds=timeout,
        batch_timeout_seconds=1_800,
        session_timeout_seconds=session_timeout,
        download_dir=tmp_path / "downloads",
    )
    if authenticated:
        config.storage_state_path.write_text("sanitized-test-state", encoding="utf-8")
    return config


def _coordinator(context, gate=None, **overrides):
    """A coordinator whose auto-confirm poller is effectively off unless a test
    opts in with ``auto_confirm_poll_seconds``."""

    settings = {"auto_confirm_poll_seconds": 60.0}
    settings.update(overrides)
    return NetFacilitiesAuthenticationCoordinator(
        client_factory=lambda _config: context,
        profile_gate=gate or NetFacilitiesOperationGate(),
        **settings,
    )


async def _wait_for_state(coordinator, state, *, attempts=300):
    for _ in range(attempts):
        latest = await coordinator.latest()
        if latest is not None and latest.state == state:
            return latest
        await asyncio.sleep(0.002)
    raise AssertionError(f"coordinator never reached {state!r}")


def test_duplicate_start_returns_same_pending_attempt(tmp_path):
    context = FakeAuthenticationContext()
    coordinator = _coordinator(context)

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
    coordinator = _coordinator(context)

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
        auto_confirm_poll_seconds=60.0,
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
    coordinator = _coordinator(context, gate)

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
        auto_confirm_poll_seconds=60.0,
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


def test_start_and_confirm_keep_the_window_open_and_signed_in(tmp_path):
    gate = NetFacilitiesOperationGate()
    context = FakeAuthenticationContext()
    coordinator = _coordinator(context, gate)

    async def exercise():
        config = _config(tmp_path)
        started, created = await coordinator.start(config)
        assert created
        assert started.state == "awaiting_confirmation"
        assert context.client.download_destination == config.download_dir
        assert context.client.close_callback is not None

        signed_in = await coordinator.confirm()
        assert signed_in.attempt_id == started.attempt_id
        assert signed_in.state == "signed_in"
        assert signed_in.signed_in_at is not None
        assert signed_in.finished_at is None
        assert await gate.active_kind() == "authentication"
        assert context.exited == 0

        closed = await coordinator.cancel()
        assert closed.state == "closed"
        assert closed.failure is None
        assert closed.finished_at is not None
        assert await gate.active_kind() is None

    asyncio.run(exercise())
    assert context.entered == 1
    assert context.exited == 1
    assert context.client.verified == 1
    assert context.client.primed == 1
    assert context.client.persisted == 1


def test_manual_confirm_probe_failure_keeps_the_window_open(tmp_path):
    client = FakeAuthenticationClient(
        verify_error=NetFacilitiesAuthenticationRequired("still on login")
    )
    context = FakeAuthenticationContext(client)
    coordinator = _coordinator(context)

    async def exercise():
        await coordinator.start(_config(tmp_path))
        with pytest.raises(NetFacilitiesAuthenticationRequired):
            await coordinator.confirm()
        assert (await coordinator.latest()).state == "awaiting_confirmation"
        assert context.exited == 0

        client.verify_error = None
        client.prime_error = NetFacilitiesUnexpectedResponse("vendor returned 503")
        with pytest.raises(NetFacilitiesUnexpectedResponse):
            await coordinator.confirm()
        assert (await coordinator.latest()).state == "awaiting_confirmation"
        assert client.persisted == 0
        assert context.exited == 0

        client.prime_error = None
        assert (await coordinator.confirm()).state == "signed_in"
        await coordinator.cancel()

    asyncio.run(exercise())
    assert context.exited == 1
    assert client.persisted == 1


def test_sign_in_is_confirmed_automatically_once_a_page_leaves_the_login_screen(
    tmp_path,
):
    client = FakeAuthenticationClient(
        verify_error=NetFacilitiesAuthenticationRequired("still on login")
    )
    context = FakeAuthenticationContext(client)
    coordinator = _coordinator(
        context, auto_confirm_poll_seconds=0.001, auto_confirm_retry_seconds=0.001
    )

    async def exercise():
        await coordinator.start(_config(tmp_path))
        await asyncio.sleep(0.01)
        assert (await coordinator.latest()).state == "awaiting_confirmation"
        assert client.persisted == 0

        client.verify_error = None
        signed_in = await _wait_for_state(coordinator, "signed_in")
        assert signed_in.signed_in_at is not None
        assert client.primed == 1
        assert client.persisted == 1
        assert context.exited == 0
        await coordinator.cancel()

    asyncio.run(exercise())


def test_auto_confirm_stays_pending_until_the_server_probe_succeeds(tmp_path):
    client = FakeAuthenticationClient(
        prime_error=NetFacilitiesAuthenticationRequired("cookies not set yet")
    )
    context = FakeAuthenticationContext(client)
    coordinator = _coordinator(
        context, auto_confirm_poll_seconds=0.001, auto_confirm_retry_seconds=0.001
    )

    async def exercise():
        await coordinator.start(_config(tmp_path))
        for _ in range(300):
            if client.primed >= 2:
                break
            await asyncio.sleep(0.002)
        assert client.primed >= 2
        assert (await coordinator.latest()).state == "awaiting_confirmation"
        assert client.persisted == 0
        assert context.exited == 0

        client.prime_error = None
        await _wait_for_state(coordinator, "signed_in")
        await coordinator.cancel()

    asyncio.run(exercise())


def test_start_while_signed_in_returns_the_live_session_unchanged(tmp_path):
    context = FakeAuthenticationContext()
    coordinator = _coordinator(context)

    async def exercise():
        first, _created = await coordinator.start(_config(tmp_path))
        await coordinator.confirm()
        again, created = await coordinator.start(_config(tmp_path))
        assert not created
        assert again.attempt_id == first.attempt_id
        assert again.state == "signed_in"
        await coordinator.cancel()

    asyncio.run(exercise())
    assert context.entered == 1


def test_borrow_hands_out_the_live_client_and_blocks_cancel_until_returned(tmp_path):
    context = FakeAuthenticationContext()
    coordinator = _coordinator(context)

    async def exercise():
        assert await coordinator.borrow_live_client() is None
        await coordinator.start(_config(tmp_path))
        assert await coordinator.borrow_live_client() is None
        await coordinator.confirm()

        borrowed = await coordinator.borrow_live_client()
        assert borrowed is not None
        async with borrowed as client:
            assert client is context.client
            with pytest.raises(NetFacilitiesOperationInProgress):
                await coordinator.cancel()
            assert (await coordinator.latest()).state == "signed_in"
            assert context.exited == 0
        assert (await coordinator.cancel()).state == "closed"

    asyncio.run(exercise())
    assert context.exited == 1


def test_borrowing_after_the_window_closed_is_authentication_required(tmp_path):
    context = FakeAuthenticationContext()
    coordinator = _coordinator(context)

    async def exercise():
        await coordinator.start(_config(tmp_path))
        await coordinator.confirm()
        borrowed = await coordinator.borrow_live_client()
        await coordinator.cancel()
        with pytest.raises(NetFacilitiesAuthenticationRequired):
            async with borrowed:
                pass

    asyncio.run(exercise())


def test_window_closed_by_the_operator_ends_the_session_and_releases_the_profile(
    tmp_path,
):
    gate = NetFacilitiesOperationGate()
    context = FakeAuthenticationContext()
    coordinator = _coordinator(context, gate)

    async def exercise():
        await coordinator.start(_config(tmp_path))
        await coordinator.confirm()
        context.client.close_callback()
        closed = await _wait_for_state(coordinator, "closed")
        assert closed.failure is None
        assert await gate.active_kind() is None

    asyncio.run(exercise())
    assert context.exited == 1


def test_window_closed_before_sign_in_is_recorded_as_cancelled(tmp_path):
    gate = NetFacilitiesOperationGate()
    context = FakeAuthenticationContext()
    coordinator = _coordinator(context, gate)

    async def exercise():
        await coordinator.start(_config(tmp_path))
        context.client.close_callback()
        cancelled = await _wait_for_state(coordinator, "cancelled")
        assert cancelled.failure == "cancelled"
        assert await gate.active_kind() is None

    asyncio.run(exercise())
    assert context.exited == 1


def test_csv_download_is_recorded_by_name_and_other_files_are_ignored(tmp_path):
    context = FakeAuthenticationContext()
    coordinator = _coordinator(context)
    downloads = tmp_path / "downloads"

    async def exercise():
        await coordinator.start(_config(tmp_path))
        await coordinator.confirm()

        await context.client.on_saved(downloads / "report.pdf")
        assert (await coordinator.latest()).last_download_filename is None
        assert coordinator.captured_csv_path() is None

        await context.client.on_saved(downloads / "WorkOrders.CSV")
        latest = await coordinator.latest()
        assert latest.state == "signed_in"
        assert latest.last_download_filename == "WorkOrders.CSV"
        assert latest.last_download_at is not None
        assert coordinator.captured_csv_path() == downloads / "WorkOrders.CSV"

        closed = await coordinator.cancel()
        assert closed.last_download_filename == "WorkOrders.CSV"
        assert coordinator.captured_csv_path() == downloads / "WorkOrders.CSV"

        await coordinator.start(_config(tmp_path))
        assert (await coordinator.latest()).last_download_filename is None
        assert coordinator.captured_csv_path() is None
        await coordinator.cancel()

    asyncio.run(exercise())


def test_signed_in_session_times_out_when_idle(tmp_path):
    gate = NetFacilitiesOperationGate()
    context = FakeAuthenticationContext()
    coordinator = _coordinator(context, gate)

    async def exercise():
        await coordinator.start(_config(tmp_path, session_timeout=0.001))
        await coordinator.confirm()
        timed_out = await _wait_for_state(coordinator, "timed_out")
        assert timed_out.failure == "timed_out"
        assert await gate.active_kind() is None

    asyncio.run(exercise())
    assert context.exited == 1


def test_session_timeout_waits_while_enrichment_borrows_the_window(tmp_path):
    context = FakeAuthenticationContext()
    coordinator = _coordinator(context, timeout_retry_seconds=0.001)

    async def exercise():
        await coordinator.start(_config(tmp_path, session_timeout=0.001))
        await coordinator.confirm()
        borrowed = await coordinator.borrow_live_client()
        async with borrowed:
            await asyncio.sleep(0.02)
            assert (await coordinator.latest()).state == "signed_in"
            assert context.exited == 0
        await _wait_for_state(coordinator, "timed_out")

    asyncio.run(exercise())
    assert context.exited == 1


def test_shutdown_closes_a_signed_in_window(tmp_path):
    gate = NetFacilitiesOperationGate()
    context = FakeAuthenticationContext()
    coordinator = _coordinator(context, gate)

    async def exercise():
        await coordinator.start(_config(tmp_path))
        await coordinator.confirm()
        await coordinator.shutdown()
        assert (await coordinator.latest()).state == "closed"
        assert await gate.active_kind() is None

    asyncio.run(exercise())
    assert context.exited == 1


async def _completed_summary():
    return NetFacilitiesEnrichmentSummary()
