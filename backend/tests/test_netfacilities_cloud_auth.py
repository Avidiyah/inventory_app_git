"""Offline tests for the per-user NetFacilities cloud-auth coordinator
(spec D2, D3, D7)."""

from __future__ import annotations

import asyncio
import uuid

from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from app.domain.errors import DomainError
from app.integrations.netfacilities.cloud_config import NetFacilitiesCloudConfig
from app.integrations.netfacilities.errors import NetFacilitiesError
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


# --- the chain (Task 8: E4, E5, E6, E11) ----------------------------------
#
# `dispatch_capture` is the one function both the automatic trigger and the
# manual Import button run (E8). Collaborators are injected through the
# constructor -- real defaults in production -- so these tests are hermetic:
# no env vars, no real import route, no real push.


IMPORT_SUMMARY = {
    "total": 3,
    "created": 3,
    "opened": 0,
    "closed": 0,
    "supervisors_matched": 1,
    "supervisors_unmatched": 2,
    "skipped": 0,
    "auto_closed": 0,
    "reopened": 0,
}


class FakeImportRunner:
    def __init__(self):
        self.calls = []
        self.raise_domain_error = False

    def __call__(self, db, background, *, data, user_id):  # noqa: ARG002
        self.calls.append((data, user_id))
        if self.raise_domain_error:
            raise DomainError("That file is not a NetFacilities export.")
        return dict(IMPORT_SUMMARY)


class _FakeJobSnapshot:
    def __init__(self, job_id):
        self.job_id = job_id


class FakeJobs:
    def __init__(self, busy_times=0):
        self.starts = 0
        self.busy_times = busy_times
        self.job_id = uuid.uuid4()

    async def start(self, _config, **_kwargs):
        self.starts += 1
        # E5: `created=False` while another batch holds the coordinator.
        return _FakeJobSnapshot(self.job_id), self.starts > self.busy_times


class FakeNotifier:
    def __init__(self):
        self.sent = []

    def __call__(self, *, user_id, ok, stage, import_result, job_id):
        self.sent.append(
            {
                "user_id": user_id,
                "ok": ok,
                "stage": stage,
                "import_result": import_result,
                "job_id": job_id,
            }
        )


def _chain_coordinator(db, provider, importer, jobs, notifier):
    return NetFacilitiesCloudAuthenticationCoordinator(
        provider_factory=lambda _config: provider,
        session_factory=_session_factory(db),
        poll_seconds=0.01,
        import_runner=importer,
        job_coordinator=jobs,
        notifier=notifier,
        # Hermetic stand-in for `resolve_cloud_enrichment_context` + config
        # loading; the real default is exercised by the route tests.
        enrichment_resolver=lambda _db, _user_id: (object(), object(), 840),
    )


async def _run_chain(coordinator, user_id, **config_overrides):
    settings = {"capture_poll_seconds": 0.01, "enrichment_retry_seconds": 0.5}
    settings.update(config_overrides)
    await coordinator.start(user_id, _config(**settings))
    for _ in range(600):
        await asyncio.sleep(0.01)
        snapshot = await coordinator.latest(user_id)
        if snapshot.chain_stage in {"done", "failed"}:
            break
    return await coordinator.latest(user_id)


def test_the_chain_imports_closes_and_enriches(db, monkeypatch):
    monkeypatch.setenv(
        "NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY", Fernet.generate_key().decode()
    )
    user = _user(db)
    importer, jobs, notifier = FakeImportRunner(), FakeJobs(), FakeNotifier()
    provider = FakeCloudBrowserProvider()
    provider.csv_to_return = ("work-orders.csv", b"NUMBER\n1001\n")
    coordinator = _chain_coordinator(db, provider, importer, jobs, notifier)

    snapshot = asyncio.run(_run_chain(coordinator, user.id))

    assert importer.calls == [(b"NUMBER\n1001\n", user.id)]
    assert provider.closed_sessions == ["sess-1"]  # E6, success path
    assert jobs.starts == 1
    assert snapshot.state == "closed"
    assert snapshot.chain_stage == "done"
    # §2a: the whole import result rides on the snapshot, so reconcile's
    # auto_closed/reopened counts appear here with no further plumbing.
    assert snapshot.import_result == IMPORT_SUMMARY
    assert snapshot.enrichment_job_id == jobs.job_id
    assert snapshot.capture_consumed is True
    assert snapshot.live_view_url is None
    assert notifier.sent[0]["ok"] is True
    assert notifier.sent[0]["import_result"] == IMPORT_SUMMARY
    assert notifier.sent[0]["job_id"] == jobs.job_id


def test_a_failed_import_keeps_the_session_open_and_skips_enrichment(db, monkeypatch):
    monkeypatch.setenv(
        "NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY", Fernet.generate_key().decode()
    )
    user = _user(db)
    importer, jobs, notifier = FakeImportRunner(), FakeJobs(), FakeNotifier()
    importer.raise_domain_error = True
    provider = FakeCloudBrowserProvider()
    provider.csv_to_return = ("wrong.csv", b"nope")
    coordinator = _chain_coordinator(db, provider, importer, jobs, notifier)

    snapshot = asyncio.run(_run_chain(coordinator, user.id))

    # E6: the user re-exports the right file without repeating the ceremony.
    assert provider.closed_sessions == []
    assert snapshot.state == "signed_in"
    assert snapshot.chain_stage == "failed"
    assert jobs.starts == 0
    assert snapshot.import_error
    assert snapshot.capture_consumed is False
    # Capture retained so the manual button can retry it.
    assert coordinator.captured_csv_bytes(user.id) is not None
    assert notifier.sent[0]["ok"] is False
    assert notifier.sent[0]["stage"] == "import"


def test_enrichment_retries_while_a_batch_is_running(db, monkeypatch):
    monkeypatch.setenv(
        "NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY", Fernet.generate_key().decode()
    )
    user = _user(db)
    importer, notifier = FakeImportRunner(), FakeNotifier()
    jobs = FakeJobs(busy_times=2)  # E5: created=False twice, then true
    provider = FakeCloudBrowserProvider()
    provider.csv_to_return = ("work-orders.csv", b"NUMBER\n1001\n")
    coordinator = _chain_coordinator(db, provider, importer, jobs, notifier)

    snapshot = asyncio.run(_run_chain(coordinator, user.id))

    assert jobs.starts == 3
    assert snapshot.enrichment_job_id == jobs.job_id
    assert snapshot.chain_stage == "done"


def test_enrichment_giving_up_leaves_the_import_standing(db, monkeypatch):
    monkeypatch.setenv(
        "NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY", Fernet.generate_key().decode()
    )
    user = _user(db)
    importer, notifier = FakeImportRunner(), FakeNotifier()
    jobs = FakeJobs(busy_times=10_000)  # never free
    provider = FakeCloudBrowserProvider()
    provider.csv_to_return = ("work-orders.csv", b"NUMBER\n1001\n")
    coordinator = _chain_coordinator(db, provider, importer, jobs, notifier)

    snapshot = asyncio.run(
        _run_chain(coordinator, user.id, enrichment_retry_seconds=0.2)
    )

    assert snapshot.import_result == IMPORT_SUMMARY
    assert snapshot.enrichment_job_id is None
    assert snapshot.chain_stage == "done"
    assert notifier.sent[0]["ok"] is False
    assert notifier.sent[0]["stage"] == "enrichment"


def test_dispatch_capture_without_a_capture_is_refused(db, monkeypatch):
    monkeypatch.setenv(
        "NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY", Fernet.generate_key().decode()
    )
    user = _user(db)
    importer, jobs, notifier = FakeImportRunner(), FakeJobs(), FakeNotifier()
    provider = FakeCloudBrowserProvider()  # no CSV ever appears
    coordinator = _chain_coordinator(db, provider, importer, jobs, notifier)

    async def _exercise():
        await coordinator.start(user.id, _config(capture_poll_seconds=0.01))
        await asyncio.sleep(0.05)
        try:
            await coordinator.dispatch_capture(user.id)
        except NetFacilitiesError:
            return "refused"
        return "ran"

    assert asyncio.run(_exercise()) == "refused"
    assert importer.calls == []


def test_the_default_notifier_is_the_real_chain_push():
    # Pins the lazy wiring: a renamed service function would otherwise fail
    # only in production, as a logged exception after every chain.
    from app.services.notifications import notify_netfacilities_chain_finished

    coordinator = NetFacilitiesCloudAuthenticationCoordinator(
        provider_factory=lambda _config: None
    )

    assert coordinator._resolve_notifier() is notify_netfacilities_chain_finished
