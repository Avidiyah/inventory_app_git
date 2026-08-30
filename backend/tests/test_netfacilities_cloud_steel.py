"""Offline tests for the Steel cloud-browser adapter (spec D1, D3, D4).

Fakes stand in for the Steel SDK and Playwright's CDP connection -- the
adapter's own state machine (session bookkeeping, seen-files tracking,
session teardown) is what these tests verify, not the real vendor.

This project has no pytest-asyncio -- every async exercise is wrapped in a
plain `def test_...(): asyncio.run(...)`, the convention across this suite.
"""

from __future__ import annotations

import asyncio

from app.integrations.netfacilities import cloud_steel
from app.integrations.netfacilities.errors import NetFacilitiesUnavailable


class FakePage:
    def __init__(self, url):
        self.url = url
        self.handlers = {}

    def on(self, event, handler):
        self.handlers[event] = handler

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


class FakeCdpSession:
    def __init__(self, *, fail=False):
        self.sent = []
        self._fail = fail

    async def send(self, method, params=None):
        if self._fail:
            raise RuntimeError("CDP refused setDownloadBehavior")
        self.sent.append((method, params))
        return {}


class FakeContext:
    def __init__(self, *, pages=None, state=None):
        self.pages = pages or []
        self._state = state or {"cookies": []}
        self.closed = False
        self.request = FakeRequestContext()
        self.created_pages = []
        self.handlers = {}

    async def storage_state(self):
        return self._state

    def on(self, event, handler):
        self.handlers[event] = handler

    async def new_page(self):
        page = FakePage("about:blank")
        self.created_pages.append(page)
        self.pages.append(page)
        return page


class FakeBrowser:
    def __init__(self, context, *, cdp_fails=False):
        self.contexts = [context]
        self.closed = False
        self.cdp_session = FakeCdpSession(fail=cdp_fails)

    async def new_browser_cdp_session(self):
        return self.cdp_session

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


class FakeFileEntry:
    def __init__(self, path, size=128):
        self.path = path
        self.size = size


class FakeFileListing:
    def __init__(self, data):
        self.data = data


class FakeDownloadResponse:
    def __init__(self, content):
        self._content = content

    async def read(self):
        return self._content


class FakeFilesResource:
    """Mirrors Steel's real shape: listing returns `/files/`-prefixed
    absolute paths, download takes a *relative* one and 400s otherwise."""

    def __init__(self):
        self.entries = []
        self.requested_paths = []
        self.contents = {}
        self.fail_next_download = False

    async def list(self, _session_id):
        return FakeFileListing(list(self.entries))

    async def download(self, path, *, session_id):  # noqa: ARG002
        self.requested_paths.append(path)
        if path.startswith("/"):
            raise AssertionError(
                "Steel rejects a leading '/' in the download path (400)."
            )
        if self.fail_next_download:
            self.fail_next_download = False
            raise RuntimeError("transient vendor failure")
        return FakeDownloadResponse(self.contents.get(path, b"col\n1\n"))


class FakeDownload:
    def __init__(self, suggested_filename):
        self.suggested_filename = suggested_filename


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


def test_download_behavior_is_set_on_a_browser_level_cdp_session(monkeypatch):
    provider, _fake_client = _provider(monkeypatch)
    context = FakeContext(pages=[FakePage("https://system.netfacilities.com/account/login")])
    browser = FakeBrowser(context)
    monkeypatch.setattr(
        cloud_steel, "_connect_over_cdp", lambda *_args, **_kwargs: _resolved((None, browser))
    )

    asyncio.run(provider.open_login_session())

    method, params = browser.cdp_session.sent[0]
    assert method == "Browser.setDownloadBehavior"
    assert params["downloadPath"] == "/files"
    assert params["eventsEnabled"] is True
    # No stray blank page: the ceremony's only page is the sign-in page the
    # user is looking at in the live view.
    assert context.created_pages == []


def test_a_ceremony_that_cannot_capture_downloads_fails_to_open(monkeypatch):
    provider, _fake_client = _provider(monkeypatch)
    context = FakeContext(pages=[FakePage("https://system.netfacilities.com/account/login")])
    browser = FakeBrowser(context, cdp_fails=True)
    monkeypatch.setattr(
        cloud_steel, "_connect_over_cdp", lambda *_args, **_kwargs: _resolved((None, browser))
    )

    try:
        asyncio.run(provider.open_login_session())
    except NetFacilitiesUnavailable:
        return
    raise AssertionError("expected NetFacilitiesUnavailable")


def _provider_with_files(monkeypatch):
    provider, fake_client = _provider(monkeypatch)
    fake_client.sessions.files = FakeFilesResource()
    context = FakeContext(pages=[FakePage("https://system.netfacilities.com/myhome")])
    browser = FakeBrowser(context)
    monkeypatch.setattr(
        cloud_steel, "_connect_over_cdp", lambda *_args, **_kwargs: _resolved((None, browser))
    )
    return provider, fake_client


def test_poll_downloaded_csv_strips_the_listed_prefix_before_downloading(monkeypatch):
    provider, fake_client = _provider_with_files(monkeypatch)
    files = fake_client.sessions.files
    files.entries = [FakeFileEntry("/files/work-orders.csv")]
    files.contents["work-orders.csv"] = b"NUMBER\n1001\n"

    async def _exercise():
        session = await provider.open_login_session()
        return await provider.poll_downloaded_csv(session)

    found = asyncio.run(_exercise())

    assert found == ("work-orders.csv", b"NUMBER\n1001\n")
    assert files.requested_paths == ["work-orders.csv"]


def test_poll_downloaded_csv_skips_zero_byte_and_partial_entries(monkeypatch):
    provider, fake_client = _provider_with_files(monkeypatch)
    files = fake_client.sessions.files
    files.entries = [
        FakeFileEntry("/files/half.csv", size=0),
        FakeFileEntry("/files/still-writing.csv.crdownload"),
        FakeFileEntry("/files/done.csv"),
    ]

    async def _exercise():
        session = await provider.open_login_session()
        return await provider.poll_downloaded_csv(session)

    filename, _content = asyncio.run(_exercise())

    assert filename == "done.csv"
    assert files.requested_paths == ["done.csv"]


def test_a_failed_download_is_retried_on_the_next_poll(monkeypatch):
    provider, fake_client = _provider_with_files(monkeypatch)
    files = fake_client.sessions.files
    files.entries = [FakeFileEntry("/files/work-orders.csv")]
    files.fail_next_download = True

    async def _exercise():
        session = await provider.open_login_session()
        try:
            await provider.poll_downloaded_csv(session)
        except RuntimeError:
            pass
        return await provider.poll_downloaded_csv(session)

    found = asyncio.run(_exercise())

    # Blacklisting before the read is what made a transient failure permanent.
    assert found is not None
    assert files.requested_paths == ["work-orders.csv", "work-orders.csv"]


def test_an_already_captured_file_is_not_captured_twice(monkeypatch):
    provider, fake_client = _provider_with_files(monkeypatch)
    fake_client.sessions.files.entries = [FakeFileEntry("/files/work-orders.csv")]

    async def _exercise():
        session = await provider.open_login_session()
        first = await provider.poll_downloaded_csv(session)
        second = await provider.poll_downloaded_csv(session)
        return first, second

    first, second = asyncio.run(_exercise())

    assert first is not None
    assert second is None


def test_relative_strips_the_files_prefix_the_listing_returns():
    # Steel's listing returns `/files/`-prefixed paths and its download
    # endpoint rejects any leading slash -- the 400 that shipped.
    assert cloud_steel._relative("/files/export.csv") == "export.csv"


def test_relative_strips_a_bare_leading_slash():
    assert cloud_steel._relative("/downloads/export.csv") == "downloads/export.csv"


def test_relative_leaves_an_already_relative_path_alone():
    assert cloud_steel._relative("files/export.csv") == "files/export.csv"
    assert cloud_steel._relative("export.csv") == "export.csv"


def test_relative_keeps_interior_separators():
    # Steel accepts nested relative paths; only the leading slash is fatal.
    assert cloud_steel._relative("/files/a/b/export.csv") == "a/b/export.csv"


def test_download_path_is_steels_documented_directory():
    assert cloud_steel.DOWNLOAD_PATH == "/files"


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


def test_a_download_event_is_recorded_for_pages_open_and_pages_created(monkeypatch):
    # E2: the listener is the trigger; the bytes still come from the Files
    # API. Whether it fires at all over `connect_over_cdp` is unverified
    # (spec 3) -- the safety-net poll is what makes that acceptable, and
    # the capture_path log line settles it in production.
    provider, _fake_client = _provider(monkeypatch)
    page = FakePage("https://system.netfacilities.com/account/login")
    context = FakeContext(pages=[page])
    browser = FakeBrowser(context)
    monkeypatch.setattr(
        cloud_steel, "_connect_over_cdp", lambda *_args, **_kwargs: _resolved((None, browser))
    )

    async def _exercise():
        session = await provider.open_login_session()
        # The live view's own export click, as Playwright would report it.
        page.handlers["download"](FakeDownload("work-orders.csv"))
        return session

    session = asyncio.run(_exercise())

    # Pages the user opens later are covered too.
    assert "page" in context.handlers
    late_page = FakePage("https://system.netfacilities.com/tools")
    context.handlers["page"](late_page)
    late_page.handlers["download"](FakeDownload("late.csv"))

    assert session.download_events == ["work-orders.csv", "late.csv"]
