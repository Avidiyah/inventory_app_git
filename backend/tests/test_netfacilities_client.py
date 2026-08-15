"""Offline contract tests for the read-only NetFacilities Playwright client."""

import asyncio
from pathlib import Path

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

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
    def __init__(self, response, *, pages=None, rendered_html=None):
        self.response = response
        self.request = FakeRequestContext(response)
        self.storage_state_calls = []
        self.pages = pages or []
        self.closed = 0
        self.rendered_html = rendered_html
        self.redirect_to = None

    async def storage_state(self, **kwargs):
        self.storage_state_calls.append(kwargs)
        return {"cookies": [], "origins": []}

    async def new_page(self):
        page = FakePage(
            response=self.response,
            rendered_html=self.rendered_html,
            redirect_to=self.redirect_to,
        )
        self.pages.append(page)
        return page

    async def close(self):
        self.closed += 1


class FakeNavigationRequest:
    def __init__(self, url, *, resource_type="document", navigation=True):
        self.url = url
        self.method = "GET"
        self.resource_type = resource_type
        self._navigation = navigation

    def is_navigation_request(self):
        return self._navigation


class FakeRoute:
    def __init__(self, request):
        self.request = request
        self.action = None
        self.abort_code = None

    async def continue_(self):
        self.action = "continued"

    async def abort(self, code):
        self.action = "aborted"
        self.abort_code = code


class FakePage:
    def __init__(self, url="about:blank", response=None, rendered_html=None,
                 redirect_to=None):
        self.url = url
        self.response = response
        self.rendered_html = rendered_html
        self.redirect_to = redirect_to
        self.goto_calls = []
        self.route_calls = []
        self.waited_for = []
        self.listeners = []
        self._route_handler = None
        self.closed = 0

    def on(self, event, handler):
        self.listeners.append(event)

    async def route(self, pattern, handler):
        self.route_calls.append((pattern, handler))
        self._route_handler = handler

    async def goto(self, url, **kwargs):
        self.goto_calls.append((url, kwargs))
        self.url = url
        if self._route_handler is not None:
            document_route = FakeRoute(FakeNavigationRequest(url))
            await self._route_handler(document_route)
            self.route_calls.append(document_route)
            for probe in (
                FakeNavigationRequest(
                    "https://system.netfacilities.com/bundles/scripts",
                    resource_type="script",
                    navigation=False,
                ),
                FakeNavigationRequest(
                    "https://cdn.example.com/tracker.js",
                    resource_type="script",
                    navigation=False,
                ),
                FakeNavigationRequest(
                    "https://system.netfacilities.com/logo.png",
                    resource_type="image",
                    navigation=False,
                ),
            ):
                probe_route = FakeRoute(probe)
                await self._route_handler(probe_route)
                self.route_calls.append(probe_route)
            if document_route.action != "continued":
                return None
        return self.response

    async def wait_for_selector(self, selector, **kwargs):
        self.waited_for.append((selector, kwargs))
        if self.redirect_to is not None:
            # Simulate first-party JavaScript navigating away while we wait.
            self.url = self.redirect_to
            raise PlaywrightTimeoutError("selector never attached")
        if self.rendered_html is None or selector.strip("#") not in self.rendered_html:
            raise PlaywrightTimeoutError("selector never attached")
        return object()

    async def content(self):
        return self.rendered_html or ""

    async def close(self):
        self.closed += 1


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


def test_saved_state_uses_one_browser_document_and_aborts_every_subresource():
    context = FakeBrowserContext(FakeResponse())
    client = NetFacilitiesClient(
        profile_dir=None,
        storage_state_path=Path("unused-saved-state"),
        headless=True,
        use_saved_state=True,
        _context=context,
    )

    parsed = asyncio.run(client.get_work_order("12345678"))

    assert parsed.priority == "Normal"
    assert context.request.calls == []
    assert len(context.pages) == 1
    page = context.pages[0]
    assert page.goto_calls == [
        (
            "https://system.netfacilities.com/tools/viewworkorders/12345678",
            {"wait_until": "commit", "timeout": 30_000},
        )
    ]
    assert page.route_calls[0][0] == "**/*"
    document_route, *subresource_routes = page.route_calls[1:]
    assert document_route.action == "continued"
    # Kill switch off: nothing but the one document is allowed, not even
    # same-origin scripts.
    assert [route.action for route in subresource_routes] == ["aborted"] * 3
    assert {route.abort_code for route in subresource_routes} == {"blockedbyclient"}
    assert page.waited_for == []
    assert page.closed == 1


RENDERED_HTML = (
    "<html><body><div class='wo_Id'><h3>12345678</h3></div>"
    "<div class='wo_statusdiv'><h3>Open</h3></div>"
    "<div><h2>Task/Procedure</h2><p>Type</p><p>Fix the pump</p></div>"
    "<div><h2>Location</h2><p>Site A</p></div>"
    "<div><h2>General Information</h2>"
    "<p><span class='p-gern'>Priority Level:</span>"
    "<span id='priority-level'>Normal</span></p></div>"
    "</body></html>"
)

# What NetFacilities actually puts on the wire: a complete work order whose
# Priority row exists only inside an inline script until JavaScript runs.
RAW_HTML_WITHOUT_PRIORITY = (
    "<html><body><div class='wo_Id'><h3>12345678</h3></div>"
    "<div class='wo_statusdiv'><h3>Open</h3></div>"
    "<div><h2>Task/Procedure</h2><p>Type</p><p>Fix the pump</p></div>"
    "<div><h2>Location</h2><p>Site A</p></div>"
    "<div><h2>General Information</h2>"
    "<p><span class='p-gern'>WO Type:</span>Corrective</p></div>"
    "<script>var woPriority = 'Normal';</script>"
    "</body></html>"
).encode("utf-8")


def _rendering_client(response, rendered_html=RENDERED_HTML):
    context = FakeBrowserContext(response, rendered_html=rendered_html)
    client = NetFacilitiesClient(
        profile_dir=None,
        storage_state_path=Path("unused-saved-state"),
        headless=True,
        use_saved_state=True,
        render_document=True,
        _context=context,
    )
    return client, context


def test_rendered_mode_parses_priority_that_only_exists_after_javascript():
    client, context = _rendering_client(
        FakeResponse(body=RAW_HTML_WITHOUT_PRIORITY)
    )

    parsed = asyncio.run(client.get_work_order("12345678"))

    assert parsed.priority == "Normal"
    page = context.pages[0]
    assert page.goto_calls[0][1]["wait_until"] == "domcontentloaded"
    assert page.waited_for[0][0] == "#priority-level"
    assert page.closed == 1


def test_rendered_mode_allows_only_same_origin_get_subresources():
    client, context = _rendering_client(FakeResponse())

    asyncio.run(client.get_work_order("12345678"))

    document, same_origin_script, cross_origin_script, image = (
        context.pages[0].route_calls[1:]
    )
    assert document.action == "continued"
    assert same_origin_script.action == "continued"
    assert cross_origin_script.action == "aborted"
    assert image.action == "aborted"


def test_rendered_mode_keeps_the_integration_read_only():
    client, context = _rendering_client(FakeResponse())
    asyncio.run(client.get_work_order("12345678"))
    handler = context.pages[0]._route_handler

    write_request = FakeNavigationRequest(
        "https://system.netfacilities.com/tools/save",
        resource_type="xhr",
        navigation=False,
    )
    write_request.method = "POST"
    route = FakeRoute(write_request)
    asyncio.run(handler(route))

    assert route.action == "aborted"
    assert route.abort_code == "blockedbyclient"


def test_missing_priority_selector_is_not_an_error():
    # A work order with genuinely no priority must still parse.
    blank = RENDERED_HTML.replace(
        "<p><span class='p-gern'>Priority Level:</span>"
        "<span id='priority-level'>Normal</span></p>",
        "",
    )
    client, _ = _rendering_client(FakeResponse(), rendered_html=blank)

    parsed = asyncio.run(client.get_work_order("12345678"))

    assert parsed.priority is None
    assert parsed.work_order_number == "12345678"


def test_client_side_redirect_to_login_fails_closed():
    """JavaScript can now navigate; a login page must not be parsed as a work order."""

    context = FakeBrowserContext(FakeResponse(), rendered_html=RENDERED_HTML)
    context.redirect_to = "https://system.netfacilities.com/account/login"
    client = NetFacilitiesClient(
        profile_dir=None,
        storage_state_path=Path("unused-saved-state"),
        headless=True,
        use_saved_state=True,
        render_document=True,
        _context=context,
    )

    with pytest.raises(NetFacilitiesAuthenticationRequired):
        asyncio.run(client.get_work_order("12345678"))


def test_rendered_document_is_bounded():
    client, _ = _rendering_client(
        FakeResponse(),
        rendered_html="<html>" + "x" * (client_module.MAX_RENDERED_DOCUMENT_BYTES),
    )

    with pytest.raises(NetFacilitiesUnexpectedResponse, match="size limit"):
        asyncio.run(client.get_work_order("12345678"))


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


def test_saved_state_browser_runtime_disables_page_execution(tmp_path, monkeypatch):
    storage_state = tmp_path / STORAGE_STATE_FILENAME
    storage_state.write_text('{"cookies": [], "origins": []}', encoding="utf-8")
    context = FakeBrowserContext(FakeResponse())

    class FakeBrowser:
        def __init__(self):
            self.context_calls = []
            self.closed = 0

        async def new_context(self, **kwargs):
            self.context_calls.append(kwargs)
            return context

        async def close(self):
            self.closed += 1

    class FakeChromium:
        def __init__(self, browser):
            self.browser = browser
            self.launch_calls = []

        async def launch(self, **kwargs):
            self.launch_calls.append(kwargs)
            return self.browser

    class FakePlaywright:
        def __init__(self, chromium):
            self.chromium = chromium
            self.stopped = 0

        async def stop(self):
            self.stopped += 1

    browser = FakeBrowser()
    chromium = FakeChromium(browser)
    runtime = FakePlaywright(chromium)

    class FakeStarter:
        async def start(self):
            return runtime

    monkeypatch.setattr(client_module.sys, "platform", "linux")
    monkeypatch.setattr(client_module, "async_playwright", lambda: FakeStarter())
    client = NetFacilitiesClient(
        profile_dir=None,
        storage_state_path=storage_state,
        headless=True,
        browser_channel=None,
        use_saved_state=True,
        request_only=False,
    )

    async def exercise():
        async with client:
            parsed = await client.get_work_order("12345678")
            assert parsed.priority == "Normal"

    asyncio.run(exercise())

    assert chromium.launch_calls == [{"channel": None, "headless": True}]
    assert browser.context_calls == [
        {
            "storage_state": str(storage_state),
            "accept_downloads": False,
            "java_script_enabled": False,
            "service_workers": "block",
        }
    ]
    assert context.closed == 1
    assert browser.closed == 1
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


def test_production_image_installs_only_the_configured_bundled_browser():
    backend = Path(__file__).resolve().parent.parent
    dockerfile = (backend / "Dockerfile").read_text(encoding="utf-8")

    assert "PLAYWRIGHT_BROWSERS_PATH=/ms-playwright" in dockerfile
    assert "NETFACILITIES_BROWSER_CHANNEL=bundled-chromium" in dockerfile
    assert "playwright install --with-deps chromium" in dockerfile
