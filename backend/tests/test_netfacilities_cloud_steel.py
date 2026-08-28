"""Offline tests for the Steel cloud-browser adapter (spec D1, D3, D4).

Fakes stand in for the Steel SDK and Playwright's CDP connection -- the
adapter's own state machine (session bookkeeping, seen-files tracking,
session teardown) is what these tests verify, not the real vendor.

This project has no pytest-asyncio -- every async exercise is wrapped in a
plain `def test_...(): asyncio.run(...)`, matching test_netfacilities_auth.py.
"""

from __future__ import annotations

import asyncio

from app.integrations.netfacilities import cloud_steel


class FakePage:
    def __init__(self, url):
        self.url = url

    async def goto(self, *_args, **_kwargs):
        return None


class FakeResponse:
    def __init__(self, *, status=200, url="https://system.netfacilities.com/myhome"):
        self.status = status
        self.url = url
        self.headers = {}


class FakeRequestContext:
    async def get(self, *_args, **_kwargs):
        return FakeResponse()


class FakeContext:
    def __init__(self, *, pages=None, state=None):
        self.pages = pages or []
        self._state = state or {"cookies": []}
        self.closed = False
        self.request = FakeRequestContext()

    async def storage_state(self):
        return self._state

    def on(self, *_args, **_kwargs):
        return None


class FakeBrowser:
    def __init__(self, context):
        self.contexts = [context]
        self.closed = False

    async def close(self):
        self.closed = True


class FakeSteelSession:
    def __init__(self, session_id="sess-1"):
        self.id = session_id
        # `session_viewer_url` is Steel's own dashboard page (unused by the
        # adapter -- see cloud_contracts.CloudLoginSession); `debug_url` is
        # the bare interactive live view the adapter actually reads.
        self.session_viewer_url = f"https://app.steel.dev/sessions/{session_id}"
        self.debug_url = f"https://api.steel.dev/v1/sessions/{session_id}/player"
        self.websocket_url = f"wss://connect.steel.dev/{session_id}"


class FakeSessionsResource:
    def __init__(self):
        self.created = []
        self.released = []

    async def create(self):
        session = FakeSteelSession()
        self.created.append(session)
        return session

    async def release(self, session_id):
        self.released.append(session_id)


class FakeSteelClient:
    def __init__(self):
        self.sessions = FakeSessionsResource()


async def _resolved(value):
    return value


def _provider(monkeypatch):
    provider = cloud_steel.SteelCloudBrowserProvider.__new__(cloud_steel.SteelCloudBrowserProvider)
    provider._api_key = "test-key"
    fake_client = FakeSteelClient()
    provider._client = fake_client
    return provider, fake_client


def test_open_login_session_creates_and_tracks_a_context(monkeypatch):
    provider, fake_client = _provider(monkeypatch)
    context = FakeContext(pages=[FakePage("https://system.netfacilities.com/account/login")])
    browser = FakeBrowser(context)
    monkeypatch.setattr(
        cloud_steel, "_connect_over_cdp", lambda *_args, **_kwargs: _resolved((None, browser))
    )

    session = asyncio.run(provider.open_login_session())

    assert session.session_id == "sess-1"
    # The bare live-view player URL, not Steel's account dashboard.
    assert session.live_view_url.endswith("/player")
    assert "sess-1" in session.live_view_url
    assert len(fake_client.sessions.created) == 1


def test_poll_signed_in_returns_none_before_login(monkeypatch):
    provider, _fake_client = _provider(monkeypatch)
    context = FakeContext(pages=[FakePage("https://system.netfacilities.com/account/login")])
    browser = FakeBrowser(context)
    monkeypatch.setattr(
        cloud_steel, "_connect_over_cdp", lambda *_args, **_kwargs: _resolved((None, browser))
    )

    async def _exercise():
        session = await provider.open_login_session()
        return await provider.poll_signed_in(session)

    result = asyncio.run(_exercise())

    assert result is None


def test_poll_signed_in_returns_state_json_after_login(monkeypatch):
    provider, _fake_client = _provider(monkeypatch)
    context = FakeContext(
        pages=[FakePage("https://system.netfacilities.com/myhome")],
        state={"cookies": [{"name": "session", "value": "abc"}]},
    )
    browser = FakeBrowser(context)
    monkeypatch.setattr(
        cloud_steel, "_connect_over_cdp", lambda *_args, **_kwargs: _resolved((None, browser))
    )

    async def _exercise():
        session = await provider.open_login_session()
        return await provider.poll_signed_in(session)

    result = asyncio.run(_exercise())

    assert result is not None
    assert "abc" in result


def test_close_login_session_releases_the_steel_session(monkeypatch):
    provider, fake_client = _provider(monkeypatch)
    context = FakeContext(pages=[FakePage("https://system.netfacilities.com/myhome")])
    browser = FakeBrowser(context)
    monkeypatch.setattr(
        cloud_steel, "_connect_over_cdp", lambda *_args, **_kwargs: _resolved((None, browser))
    )

    async def _exercise():
        session = await provider.open_login_session()
        await provider.close_login_session(session)

    asyncio.run(_exercise())

    assert browser.closed is True
    assert fake_client.sessions.released == ["sess-1"]
