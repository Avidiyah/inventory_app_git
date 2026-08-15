"""Offline contract tests for the read-only NetFacilities Playwright client."""

import asyncio
from pathlib import Path

import pytest

from app.integrations.netfacilities import client as client_module
from app.integrations.netfacilities.client import (
    BASE_URL,
    MAX_RESPONSE_BYTES,
    NetFacilitiesClient,
    STORAGE_STATE_FILENAME,
)
from app.integrations.netfacilities.errors import (
    NetFacilitiesAuthenticationRequired,
    NetFacilitiesUnexpectedResponse,
    NetFacilitiesUnavailable,
)


FIXTURE = (
    Path(__file__).parent / "fixtures" / "netfacilities_work_order_sanitized.html"
).read_bytes()


class FakeResponse:
    def __init__(
        self,
        *,
        status=200,
        url="https://system.netfacilities.com/tools/viewworkorders/12345678",
        headers=None,
        body=FIXTURE,
    ):
        self.status = status
        self.url = url
        self.headers = headers or {"content-type": "text/html; charset=utf-8"}
        self._body = body

    async def body(self):
        return self._body


class FakeRequestContext:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


class FakeStandaloneRequestContext(FakeRequestContext):
    def __init__(self, response):
        super().__init__(response)
        self.disposed = 0

    async def dispose(self):
        self.disposed += 1


class FakeBrowserContext:
    def __init__(self, response, *, pages=None):
        self.request = FakeRequestContext(response)
        self.storage_state_calls = []
        self.pages = pages or []

    async def storage_state(self, **kwargs):
        self.storage_state_calls.append(kwargs)
        return {"cookies": [], "origins": []}

    async def new_page(self):
        page = FakePage()
        self.pages.append(page)
        return page


class FakePage:
    def __init__(self, url="about:blank"):
        self.url = url
        self.goto_calls = []

    async def goto(self, url, **kwargs):
        self.goto_calls.append((url, kwargs))
        self.url = url


def _client(response):
    context = FakeBrowserContext(response)
    client = NetFacilitiesClient(
        profile_dir=Path("unused-in-offline-test"),
        headless=True,
        _context=context,
    )
    return client, context


def test_get_work_order_uses_only_the_allowlisted_read_request():
    client, context = _client(FakeResponse())

    parsed = asyncio.run(client.get_work_order("12345678"))

    assert parsed.work_order_number == "12345678"
    assert len(context.request.calls) == 1
    url, options = context.request.calls[0]
    assert url == "https://system.netfacilities.com/tools/viewworkorders/12345678"
    assert options["headers"] == {"Accept": "text/html"}
    assert options["max_redirects"] == 0
    assert options["fail_on_status_code"] is False


def test_diagnostic_reuses_one_allowlisted_read_and_returns_only_structural_facts():
    client, context = _client(FakeResponse())

    parsed, diagnostics = asyncio.run(
        client.get_work_order_with_diagnostics("12345678")
    )

    assert parsed.work_order_number == "12345678"
    assert diagnostics.expected_id_count == 1
    assert diagnostics.expected_id_has_text is True
    assert len(context.request.calls) == 1


def test_persists_playwright_storage_state_inside_the_protected_profile():
    client, context = _client(FakeResponse())

    asyncio.run(client.persist_authentication_state())

    assert context.storage_state_calls == [
        {
            "path": str(Path("unused-in-offline-test") / STORAGE_STATE_FILENAME),
            "indexed_db": True,
        }
    ]


def test_in_app_authentication_opens_only_the_allowlisted_site():
    client, context = _client(FakeResponse())

    asyncio.run(client.open_authentication_page())

    assert len(context.pages) == 1
    assert context.pages[0].goto_calls[0][0] == BASE_URL


def test_in_app_authentication_rejects_confirmation_on_login_page():
    client, context = _client(FakeResponse())
    context.pages.append(
        FakePage("https://system.netfacilities.com/Account/loginfrm")
    )

    with pytest.raises(NetFacilitiesAuthenticationRequired):
        asyncio.run(client.verify_authentication_page())


def test_in_app_authentication_accepts_allowlisted_authenticated_popup():
    client, context = _client(FakeResponse())
    context.pages.extend(
        [
            FakePage("https://system.netfacilities.com/Account/loginfrm"),
            FakePage("https://system.netfacilities.com/tools"),
        ]
    )

    asyncio.run(client.verify_authentication_page())


def test_windows_selector_loop_fails_closed_before_playwright_start(
    tmp_path, monkeypatch
):
    class PlaywrightMustNotStart:
        def start(self):
            raise AssertionError("Playwright started under an incompatible event loop")

    monkeypatch.setattr(client_module.sys, "platform", "win32")
    monkeypatch.setattr(
        client_module,
        "async_playwright",
        lambda: PlaywrightMustNotStart(),
    )
    client = NetFacilitiesClient(profile_dir=tmp_path, headless=False)

    async def enter_client():
        await client.__aenter__()

    with pytest.raises(NetFacilitiesUnavailable, match="without auto-reload"):
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            runner.run(enter_client())


def test_request_only_saved_state_never_launches_a_browser(tmp_path, monkeypatch):
    storage_state = tmp_path / STORAGE_STATE_FILENAME
    storage_state.write_text('{"cookies": [], "origins": []}', encoding="utf-8")
    request_context = FakeStandaloneRequestContext(FakeResponse())

    class FakeRequestFactory:
        def __init__(self):
            self.calls = []

        async def new_context(self, **kwargs):
            self.calls.append(kwargs)
            return request_context

    class FakePlaywright:
        def __init__(self):
            self.request = FakeRequestFactory()
            self.stopped = 0

        @property
        def chromium(self):
            raise AssertionError("request-only enrichment launched a browser")

        async def stop(self):
            self.stopped += 1

    runtime = FakePlaywright()

    class FakeStarter:
        async def start(self):
            return runtime

    monkeypatch.setattr(client_module.sys, "platform", "linux")
    monkeypatch.setattr(client_module, "async_playwright", lambda: FakeStarter())
    client = NetFacilitiesClient(
        profile_dir=None,
        storage_state_path=storage_state,
        headless=True,
        use_saved_state=True,
        request_only=True,
    )

    async def exercise():
        async with client:
            parsed = await client.get_work_order("12345678")
            assert parsed.work_order_number == "12345678"

    asyncio.run(exercise())

    assert runtime.request.calls == [
        {"storage_state": str(storage_state), "timeout": 30_000}
    ]
    assert len(request_context.calls) == 1
    assert request_context.disposed == 1
    assert runtime.stopped == 1


def test_login_redirect_is_authentication_required():
    client, _ = _client(
        FakeResponse(
            status=302,
            headers={"location": "/Account/loginfrm?ReturnUrl=%2ftools"},
        )
    )

    with pytest.raises(NetFacilitiesAuthenticationRequired):
        asyncio.run(client.get_work_order("12345678"))


def test_rejects_non_html_response():
    client, _ = _client(
        FakeResponse(headers={"content-type": "application/json"}, body=b"{}")
    )

    with pytest.raises(NetFacilitiesUnexpectedResponse, match="not HTML"):
        asyncio.run(client.get_work_order("12345678"))


def test_rejects_response_from_an_unexpected_host():
    client, _ = _client(
        FakeResponse(
            url="https://example.com/tools/viewworkorders/12345678",
        )
    )

    with pytest.raises(NetFacilitiesUnexpectedResponse, match="unexpected host"):
        asyncio.run(client.get_work_order("12345678"))


def test_rejects_declared_oversized_response_before_reading_body():
    client, _ = _client(
        FakeResponse(
            headers={
                "content-type": "text/html",
                "content-length": str(MAX_RESPONSE_BYTES + 1),
            }
        )
    )

    with pytest.raises(NetFacilitiesUnexpectedResponse, match="size limit"):
        asyncio.run(client.get_work_order("12345678"))


def test_rejects_actual_oversized_response():
    client, _ = _client(
        FakeResponse(body=b"x" * (MAX_RESPONSE_BYTES + 1)),
    )

    with pytest.raises(NetFacilitiesUnexpectedResponse, match="size limit"):
        asyncio.run(client.get_work_order("12345678"))


def test_stage1_dependencies_are_runtime_pinned_without_dev_duplicates():
    backend = Path(__file__).resolve().parent.parent
    runtime = (backend / "requirements.txt").read_text(encoding="utf-8")
    development = (backend / "requirements-dev.txt").read_text(encoding="utf-8")

    assert "playwright==1.62.0" in runtime
    assert "beautifulsoup4==4.15.0" in runtime
    assert "playwright==" not in development
    assert "beautifulsoup4==" not in development
