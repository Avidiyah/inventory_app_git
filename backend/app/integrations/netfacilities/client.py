"""Authenticated, read-only Playwright client for NetFacilities Stage 1."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any
from urllib.parse import urlsplit

from playwright.async_api import (
    BrowserContext,
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)

from .errors import (
    NetFacilitiesAuthenticationRequired,
    NetFacilitiesPermissionDenied,
    NetFacilitiesUnexpectedResponse,
    NetFacilitiesUnavailable,
    NetFacilitiesWorkOrderNotFound,
)
from .config import STORAGE_STATE_FILENAME
from .parser import (
    ParsedWorkOrder,
    PriorityMarkupDiagnostics,
    inspect_priority_markup,
    parse_work_order_html,
)
from .validation import validate_work_order_number


BASE_URL = "https://system.netfacilities.com"
LOGIN_PATH_PREFIX = "/account/login"
MAX_RESPONSE_BYTES = 2_000_000
REQUEST_TIMEOUT_MS = 30_000

# A rendered document is larger than its wire response, so it carries its own bound.
MAX_RENDERED_DOCUMENT_BYTES = 4_000_000
DEFAULT_RENDER_SETTLE_MS = 5_000
PRIORITY_SELECTOR = "#priority-level"
# First-party scripts build the Priority row; nothing else is needed to read text.
RENDER_ALLOWED_RESOURCE_TYPES = frozenset({"script", "xhr", "fetch"})


@dataclass(frozen=True, slots=True)
class DocumentRetrieval:
    """One navigation's raw and rendered views plus secret-safe telemetry.

    Only counts and booleans accompany the markup: this record is the source of the
    Render diagnostic's output and must never carry source values.
    """

    body: bytes
    raw_body: bytes | None
    rendered: bool
    priority_selector_appeared: bool | None
    subresources_allowed: int
    subresources_blocked: int
    console_errors: int
    raw_byte_count: int
    rendered_byte_count: int | None


class NetFacilitiesClient:
    """Own a browser or request context and perform one allowlisted read request."""

    def __init__(
        self,
        *,
        profile_dir: Path | None,
        storage_state_path: Path | None = None,
        headless: bool,
        browser_channel: str | None = "chrome",
        timeout_ms: int = REQUEST_TIMEOUT_MS,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
        use_saved_state: bool = False,
        request_only: bool = False,
        render_document: bool = False,
        render_settle_ms: int = DEFAULT_RENDER_SETTLE_MS,
        _context: BrowserContext | Any | None = None,
    ) -> None:
        self.profile_dir = profile_dir
        self.headless = headless
        self.browser_channel = browser_channel
        self.timeout_ms = timeout_ms
        self.max_response_bytes = max_response_bytes
        self.use_saved_state = use_saved_state
        self.request_only = request_only
        self.render_document = render_document
        self.render_settle_ms = render_settle_ms
        self.storage_state_path = storage_state_path or (
            profile_dir / STORAGE_STATE_FILENAME if profile_dir is not None else None
        )
        self._context = _context
        self._request_context: Any | None = None
        self._browser: Any | None = None
        self._playwright: Any | None = None
        self._owns_context = _context is None

    async def __aenter__(self) -> "NetFacilitiesClient":
        if self._context is not None:
            return self
        _require_subprocess_capable_event_loop()
        try:
            self._playwright = await async_playwright().start()
            if self.use_saved_state:
                if self.storage_state_path is None or not self.storage_state_path.is_file():
                    raise NetFacilitiesAuthenticationRequired(
                        "No saved NetFacilities authentication state; sign in first."
                    )
                if self.request_only:
                    self._request_context = await self._playwright.request.new_context(
                        storage_state=str(self.storage_state_path),
                        timeout=self.timeout_ms,
                    )
                else:
                    self._browser = await self._playwright.chromium.launch(
                        channel=self.browser_channel,
                        headless=self.headless,
                    )
                    self._context = await self._browser.new_context(
                        storage_state=str(self.storage_state_path),
                        accept_downloads=False,
                        java_script_enabled=self.render_document,
                        service_workers="block",
                    )
            else:
                if self.profile_dir is None:
                    raise NetFacilitiesUnavailable(
                        "Interactive NetFacilities sign-in requires a dedicated profile."
                    )
                self._context = await self._playwright.chromium.launch_persistent_context(
                    user_data_dir=str(self.profile_dir),
                    channel=self.browser_channel,
                    headless=self.headless,
                    accept_downloads=False,
                )
        except NetFacilitiesAuthenticationRequired:
            await self._stop_runtime()
            raise
        except PlaywrightError as exc:
            await self._stop_runtime()
            if self.use_saved_state:
                raise NetFacilitiesAuthenticationRequired(
                    "Saved NetFacilities authentication state could not be loaded; "
                    "sign in again."
                ) from exc
            raise NetFacilitiesUnavailable(
                "Could not start the dedicated browser. Verify the browser channel "
                "and that no other process is using this profile."
            ) from exc
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        try:
            if self._owns_context and self._context is not None:
                await self._context.close()
        finally:
            if self._owns_context:
                self._context = None
            await self._stop_runtime()

    async def authenticate_interactively(self) -> None:
        """Open the dedicated profile and let the authorized user sign in manually."""

        await self.open_authentication_page()
        await asyncio.to_thread(
            input,
            "Complete NetFacilities login in the dedicated browser, then press Enter here: ",
        )
        await self.verify_authentication_page()

    async def open_authentication_page(self) -> None:
        """Open the allowlisted sign-in site without collecting credentials."""

        context = self._require_context()
        page = context.pages[0] if context.pages else await context.new_page()
        try:
            await page.goto(
                BASE_URL,
                wait_until="domcontentloaded",
                timeout=self.timeout_ms,
            )
        except (PlaywrightError, PlaywrightTimeoutError) as exc:
            raise NetFacilitiesUnavailable(
                "Could not open the NetFacilities authentication page."
            ) from exc

    async def verify_authentication_page(self) -> None:
        """Confirm the headed browser reached an allowlisted non-login page."""

        context = self._require_context()
        if not context.pages:
            raise NetFacilitiesAuthenticationRequired(
                "The dedicated browser has no authenticated NetFacilities page."
            )
        if any(
            _is_allowed_host(page.url) and not _is_login_url(page.url)
            for page in reversed(context.pages)
        ):
            return
        raise NetFacilitiesAuthenticationRequired(
            "The dedicated browser is not on an authenticated NetFacilities page."
        )

    async def persist_authentication_state(self) -> None:
        """Save cookies and browser storage, including session cookies, before close."""

        if self.storage_state_path is None:
            raise NetFacilitiesUnavailable(
                "NetFacilities authentication state has no configured destination."
            )
        context = self._require_context()
        try:
            await context.storage_state(
                path=str(self.storage_state_path),
                indexed_db=True,
            )
        except PlaywrightError as exc:
            raise NetFacilitiesUnavailable(
                "Authenticated NetFacilities state could not be saved."
            ) from exc

    async def get_work_order(self, work_order_number: str) -> ParsedWorkOrder:
        """Retrieve and parse one work order without executing document actions."""

        number, retrieval = await self._get_work_order_document(work_order_number)
        return parse_work_order_html(retrieval.body, expected_work_order_number=number)

    async def get_work_order_with_diagnostics(
        self,
        work_order_number: str,
    ) -> tuple[
        ParsedWorkOrder,
        PriorityMarkupDiagnostics,
        DocumentRetrieval,
        PriorityMarkupDiagnostics | None,
    ]:
        """Retrieve once and classify both views of that single navigation.

        Returns the parsed work order, the parsed document's Priority facts, the
        retrieval telemetry, and -- when rendering produced a second view -- the same
        facts for the raw wire response, so the two can be compared directly.
        """

        number, retrieval = await self._get_work_order_document(work_order_number)
        work_order = parse_work_order_html(
            retrieval.body, expected_work_order_number=number
        )
        raw_markup = (
            inspect_priority_markup(retrieval.raw_body)
            if retrieval.raw_body is not None
            else None
        )
        return (
            work_order,
            inspect_priority_markup(retrieval.body),
            retrieval,
            raw_markup,
        )

    async def _get_work_order_document(
        self,
        work_order_number: str,
    ) -> tuple[str, DocumentRetrieval]:
        """Perform the single allowlisted read and return its bounded document."""

        number = validate_work_order_number(work_order_number)
        expected_path = f"/tools/viewworkorders/{number}"
        url = f"{BASE_URL}{expected_path}"

        if self.use_saved_state and self._request_context is None:
            retrieval = await self._navigate_to_work_order_document(
                url,
                expected_path=expected_path,
            )
        else:
            raw = await self._request_work_order_document(
                url,
                expected_path=expected_path,
            )
            retrieval = _unrendered_retrieval(raw)
        return number, retrieval

    async def _request_work_order_document(
        self,
        url: str,
        *,
        expected_path: str,
    ) -> bytes:
        """Read through APIRequestContext for the local proof-of-concept fallback."""

        request_context = self._request_context
        if request_context is None:
            request_context = self._require_context().request

        try:
            response = await request_context.get(
                url,
                headers={"Accept": "text/html"},
                fail_on_status_code=False,
                max_redirects=0,
                timeout=self.timeout_ms,
            )
        except (PlaywrightError, PlaywrightTimeoutError) as exc:
            raise NetFacilitiesUnavailable(
                "NetFacilities did not complete the read-only work-order request."
            ) from exc

        self._validate_response_metadata(response, expected_path)
        return await self._read_bounded_body(response)

    async def _navigate_to_work_order_document(
        self,
        url: str,
        *,
        expected_path: str,
    ) -> DocumentRetrieval:
        """Perform one document GET and return both views of that navigation.

        With rendering disabled this is the original isolated read: one document,
        every other request aborted. With rendering enabled, same-origin ``GET``
        scripts and XHR are additionally allowed so first-party JavaScript can build
        the Priority row, and the serialized DOM becomes the parsed document. The
        integration stays read-only either way: no non-``GET`` route is continued.
        """

        page = await self._require_context().new_page()
        route_state = {
            "document_continued": False,
            "login_redirect_blocked": False,
            "subresources_allowed": 0,
            "subresources_blocked": 0,
            "console_errors": 0,
        }

        def count_console_error(message: Any) -> None:
            # Count only. Console text can echo source values and is never read.
            if getattr(message, "type", None) == "error":
                route_state["console_errors"] += 1

        def count_page_error(_error: Any) -> None:
            route_state["console_errors"] += 1

        async def allow_only_expected_document(route: Any) -> None:
            request = route.request
            is_expected_document = (
                not route_state["document_continued"]
                and request.method == "GET"
                and request.url == url
                and request.resource_type == "document"
                and request.is_navigation_request()
            )
            if is_expected_document:
                route_state["document_continued"] = True
                await route.continue_()
                return
            if request.is_navigation_request():
                if _is_login_url(request.url):
                    route_state["login_redirect_blocked"] = True
                await route.abort("blockedbyclient")
                return
            if (
                self.render_document
                and request.method == "GET"
                and request.resource_type in RENDER_ALLOWED_RESOURCE_TYPES
                and _is_allowed_host(request.url)
            ):
                route_state["subresources_allowed"] += 1
                await route.continue_()
                return
            route_state["subresources_blocked"] += 1
            await route.abort("blockedbyclient")

        try:
            if self.render_document:
                page.on("console", count_console_error)
                page.on("pageerror", count_page_error)
            await page.route("**/*", allow_only_expected_document)
            try:
                response = await page.goto(
                    url,
                    wait_until="domcontentloaded" if self.render_document else "commit",
                    timeout=self.timeout_ms,
                )
            except (PlaywrightError, PlaywrightTimeoutError) as exc:
                if route_state["login_redirect_blocked"]:
                    raise NetFacilitiesAuthenticationRequired(
                        "NetFacilities session is not authenticated; sign in again."
                    ) from exc
                raise NetFacilitiesUnavailable(
                    "NetFacilities did not complete the isolated browser document request."
                ) from exc
            if response is None:
                raise NetFacilitiesUnexpectedResponse(
                    "NetFacilities browser navigation returned no document response."
                )
            self._validate_response_metadata(response, expected_path)
            raw_body = await self._read_bounded_body(response)
            if not self.render_document:
                return _unrendered_retrieval(
                    raw_body,
                    subresources_blocked=route_state["subresources_blocked"],
                )
            return await self._read_rendered_document(
                page,
                expected_path=expected_path,
                raw_body=raw_body,
                route_state=route_state,
            )
        finally:
            await page.close()

    async def _read_rendered_document(
        self,
        page: Any,
        *,
        expected_path: str,
        raw_body: bytes,
        route_state: dict[str, Any],
    ) -> DocumentRetrieval:
        """Let first-party scripts populate the DOM, then serialize it once."""

        try:
            await page.wait_for_selector(
                PRIORITY_SELECTOR,
                state="attached",
                timeout=self.render_settle_ms,
            )
            selector_appeared = True
        except PlaywrightTimeoutError:
            # A work order with no priority is a normal outcome, not a failure.
            selector_appeared = False

        # Check where the page ended up before serializing: JavaScript can navigate.
        if _is_login_url(page.url):
            raise NetFacilitiesAuthenticationRequired(
                "NetFacilities session is not authenticated; sign in again."
            )
        if urlsplit(page.url).path.rstrip("/") != expected_path:
            raise NetFacilitiesUnexpectedResponse(
                "NetFacilities navigated away from the requested work order."
            )

        try:
            markup = await page.content()
        except PlaywrightError as exc:
            raise NetFacilitiesUnavailable(
                "NetFacilities rendered work-order document could not be read."
            ) from exc

        body = markup.encode("utf-8")
        if len(body) > MAX_RENDERED_DOCUMENT_BYTES:
            raise NetFacilitiesUnexpectedResponse(
                "NetFacilities rendered work-order document exceeds the Stage 1 size limit."
            )
        return DocumentRetrieval(
            body=body,
            raw_body=raw_body,
            rendered=True,
            priority_selector_appeared=selector_appeared,
            subresources_allowed=route_state["subresources_allowed"],
            subresources_blocked=route_state["subresources_blocked"],
            console_errors=route_state["console_errors"],
            raw_byte_count=len(raw_body),
            rendered_byte_count=len(body),
        )

    async def _read_bounded_body(self, response: Any) -> bytes:
        """Read one already-validated response under the shared size bound."""

        try:
            body = await response.body()
        except PlaywrightError as exc:
            raise NetFacilitiesUnavailable(
                "NetFacilities work-order response could not be read."
            ) from exc
        if len(body) > self.max_response_bytes:
            raise NetFacilitiesUnexpectedResponse(
                "NetFacilities work-order response exceeds the Stage 1 size limit."
            )
        return body

    def _validate_response_metadata(self, response: Any, expected_path: str) -> None:
        status = response.status
        headers = {key.casefold(): value for key, value in response.headers.items()}

        if status in {301, 302, 303, 307, 308}:
            location = headers.get("location", "")
            if _is_login_url(location):
                raise NetFacilitiesAuthenticationRequired(
                    "NetFacilities session is not authenticated; sign in again."
                )
            raise NetFacilitiesUnexpectedResponse(
                "NetFacilities returned an unexpected redirect."
            )
        if status == 401:
            raise NetFacilitiesAuthenticationRequired(
                "NetFacilities session is not authenticated; sign in again."
            )
        if status == 403:
            raise NetFacilitiesPermissionDenied(
                "The authenticated NetFacilities account cannot view this work order."
            )
        if status == 404:
            raise NetFacilitiesWorkOrderNotFound(
                "NetFacilities did not find the requested work order."
            )
        if status != 200:
            raise NetFacilitiesUnexpectedResponse(
                f"NetFacilities returned unexpected status {status}."
            )

        parsed_url = urlsplit(response.url)
        if parsed_url.scheme != "https" or parsed_url.hostname != "system.netfacilities.com":
            raise NetFacilitiesUnexpectedResponse(
                "NetFacilities returned a response from an unexpected host."
            )
        if parsed_url.path.rstrip("/") != expected_path:
            if _is_login_url(response.url):
                raise NetFacilitiesAuthenticationRequired(
                    "NetFacilities session is not authenticated; sign in again."
                )
            raise NetFacilitiesUnexpectedResponse(
                "NetFacilities returned an unexpected response path."
            )

        content_type = headers.get("content-type", "")
        if not content_type.casefold().startswith("text/html"):
            raise NetFacilitiesUnexpectedResponse(
                "NetFacilities work-order response is not HTML."
            )

        content_length = headers.get("content-length")
        if content_length:
            try:
                declared_length = int(content_length)
            except ValueError as exc:
                raise NetFacilitiesUnexpectedResponse(
                    "NetFacilities returned an invalid Content-Length header."
                ) from exc
            if declared_length > self.max_response_bytes:
                raise NetFacilitiesUnexpectedResponse(
                    "NetFacilities work-order response exceeds the Stage 1 size limit."
                )

    def _require_context(self) -> BrowserContext | Any:
        if self._context is None:
            raise RuntimeError("NetFacilitiesClient must be used as an async context manager.")
        return self._context

    async def _stop_playwright(self) -> None:
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    async def _stop_runtime(self) -> None:
        try:
            try:
                if self._request_context is not None:
                    await self._request_context.dispose()
                    self._request_context = None
            finally:
                if self._browser is not None:
                    await self._browser.close()
                    self._browser = None
        finally:
            await self._stop_playwright()


def _unrendered_retrieval(
    body: bytes,
    *,
    subresources_blocked: int = 0,
) -> DocumentRetrieval:
    """Wrap a raw wire response, which has no second view to compare against."""

    return DocumentRetrieval(
        body=body,
        raw_body=None,
        rendered=False,
        priority_selector_appeared=None,
        subresources_allowed=0,
        subresources_blocked=subresources_blocked,
        console_errors=0,
        raw_byte_count=len(body),
        rendered_byte_count=None,
    )


def _is_allowed_host(url: str) -> bool:
    parsed = urlsplit(url)
    return parsed.scheme == "https" and parsed.hostname == "system.netfacilities.com"


def _is_login_url(url: str) -> bool:
    parsed = urlsplit(url)
    return parsed.path.casefold().startswith(LOGIN_PATH_PREFIX)


def _require_subprocess_capable_event_loop() -> None:
    """Reject the Windows selector loop before Playwright starts its driver."""

    if sys.platform == "win32" and isinstance(
        asyncio.get_running_loop(), asyncio.SelectorEventLoop
    ):
        raise NetFacilitiesUnavailable(
            "The NetFacilities browser requires a subprocess-capable Windows event "
            "loop. Restart Uvicorn without auto-reload or multiple workers."
        )
