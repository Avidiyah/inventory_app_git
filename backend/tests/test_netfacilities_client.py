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


class FakeBrowserContext:
    def __init__(self, response, *, pages=None, rendered_html=None):
        self.response = response
        self.request = FakeRequestContext(response)
        self.pages = pages or []
        self.closed = 0
        self.rendered_html = rendered_html
        self.redirect_to = None
        self.handlers = {}

    def on(self, event, handler):
        self.handlers[event] = handler

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
        self.handlers = {}
        self._route_handler = None
        self.closed = 0

    def on(self, event, handler):
        self.listeners.append(event)
        self.handlers[event] = handler

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
    client = NetFacilitiesClient(headless=True, _context=context)
    return client, context


def test_a_client_without_a_context_cannot_be_entered():
    """The Steel cloud session is the only way to get a working client."""

    client = NetFacilitiesClient(headless=True)

    with pytest.raises(NetFacilitiesUnavailable, match="existing browser context"):
        asyncio.run(client.__aenter__())


def test_get_work_order_uses_only_the_allowlisted_read_request():
    client, context = _client(FakeResponse())

    parsed = asyncio.run(client.get_work_order("12345678"))

    assert parsed.work_order_number == "12345678"
    # One priming GET, then the one allowlisted work-order read.
    assert len(context.request.calls) == 2
    prime_url, _prime_options = context.request.calls[0]
    assert prime_url == "https://system.netfacilities.com/myhome"
    url, options = context.request.calls[1]
    assert url == "https://system.netfacilities.com/tools/viewworkorders/12345678"
    assert options["headers"] == {"Accept": "text/html"}
    assert options["max_redirects"] == 0
    assert options["fail_on_status_code"] is False


def test_diagnostic_reuses_one_allowlisted_read_and_returns_only_structural_facts():
    client, context = _client(FakeResponse())

    parsed, diagnostics, retrieval, raw_diagnostics = asyncio.run(
        client.get_work_order_with_diagnostics("12345678")
    )

    assert parsed.work_order_number == "12345678"
    assert diagnostics.expected_id_count == 1
    assert diagnostics.expected_id_has_text is True
    # The priming GET plus one read; the diagnostic never re-fetches the document.
    assert len(context.request.calls) == 2
    # A raw read has only one view, so there is nothing to compare against.
    assert retrieval.rendered is False
    assert raw_diagnostics is None


def _document(*, priority_row: bool) -> bytes:
    """A parseable work order, with or without the Priority Level row."""

    priority = (
        "<p><span class='p-gern'>Priority Level:</span>"
        "<span id='priority-level'>Normal</span></p>"
        if priority_row
        else ""
    )
    return (
        "<html><body><div class='wo_Id'><h3>12345678</h3></div>"
        "<div class='wo_statusdiv'><h3>Open</h3></div>"
        "<div><h2>Task/Procedure</h2><p>Type</p><p>Fix the pump</p></div>"
        "<div><h2>Location</h2><p>Site A</p></div>"
        "<div><h2>General Information</h2>"
        "<p><span class='p-gern'>WO Type:</span>Corrective</p>"
        f"{priority}</div></body></html>"
    ).encode("utf-8")


# What an unprimed session receives: a complete work order whose General
# Information block silently omits the Priority Level row.
TRIMMED_DOCUMENT = _document(priority_row=False)
PRIMED_DOCUMENT = _document(priority_row=True)


class FakeSequencedRequestContext(FakeRequestContext):
    """Serve a scripted sequence of responses so a re-read can differ."""

    def __init__(self, responses):
        super().__init__(None)
        self._responses = list(responses)

    async def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        index = min(len(self.calls) - 1, len(self._responses) - 1)
        return self._responses[index]


def _sequenced_client(bodies):
    context = FakeBrowserContext(FakeResponse())
    context.request = FakeSequencedRequestContext(
        [FakeResponse(body=body) for body in bodies]
    )
    client = NetFacilitiesClient(headless=True, _context=context)
    return client, context


def test_session_is_primed_once_and_reused_across_work_orders():
    client, context = _sequenced_client(
        [PRIMED_DOCUMENT, PRIMED_DOCUMENT, PRIMED_DOCUMENT]
    )

    first = asyncio.run(client.get_work_order("12345678"))
    second = asyncio.run(client.get_work_order("12345678"))

    assert first.priority == "Normal"
    assert second.priority == "Normal"
    # One priming GET covers both reads; a batch pays it once, not per row.
    assert [url for url, _ in context.request.calls] == [
        "https://system.netfacilities.com/myhome",
        "https://system.netfacilities.com/tools/viewworkorders/12345678",
        "https://system.netfacilities.com/tools/viewworkorders/12345678",
    ]


def test_trimmed_document_reprimes_the_session_and_reads_again():
    client, context = _sequenced_client(
        [PRIMED_DOCUMENT, TRIMMED_DOCUMENT, PRIMED_DOCUMENT, PRIMED_DOCUMENT]
    )

    parsed = asyncio.run(client.get_work_order("12345678"))

    # A session that went stale mid-batch recovers instead of importing a blank.
    assert parsed.priority == "Normal"
    assert [url for url, _ in context.request.calls] == [
        "https://system.netfacilities.com/myhome",
        "https://system.netfacilities.com/tools/viewworkorders/12345678",
        "https://system.netfacilities.com/myhome",
        "https://system.netfacilities.com/tools/viewworkorders/12345678",
    ]


def test_persistently_trimmed_document_retries_only_once():
    client, context = _sequenced_client([TRIMMED_DOCUMENT])

    parsed = asyncio.run(client.get_work_order("12345678"))

    # A work order with no priority is legal, so this must settle, not loop.
    assert parsed.priority is None
    assert len(context.request.calls) == 4


def test_priming_redirected_to_login_is_authentication_required():
    context = FakeBrowserContext(FakeResponse())
    context.request = FakeRequestContext(
        FakeResponse(status=302, headers={"location": "/Account/loginfrm"})
    )
    client = NetFacilitiesClient(headless=True, _context=context)

    with pytest.raises(NetFacilitiesAuthenticationRequired):
        asyncio.run(client.get_work_order("12345678"))

    # The work order is never requested with an unauthenticated session.
    assert len(context.request.calls) == 1


def test_unrendered_reads_never_open_a_page():
    """Priority is server-rendered, so the default read needs no page at all."""

    client, context = _client(FakeResponse())

    asyncio.run(client.get_work_order("12345678"))

    assert context.pages == []


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
        headless=True,
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
        headless=True,
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
    assert "playwright install --with-deps chromium" in dockerfile


def test_prime_session_always_probes_the_server_and_leaves_it_primed():
    client, context = _client(FakeResponse())

    async def exercise():
        await client.prime_session()
        await client.prime_session()
        await client.get_work_order("12345678")

    asyncio.run(exercise())
    urls = [call[0] for call in context.request.calls]
    assert urls == [
        f"{BASE_URL}/myhome",
        f"{BASE_URL}/myhome",
        f"{BASE_URL}/tools/viewworkorders/12345678",
    ]
