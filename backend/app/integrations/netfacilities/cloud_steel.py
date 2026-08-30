"""Steel-backed implementation of `CloudBrowserProvider` (spec D1, D3, D4).

Only this module imports the Steel SDK or opens a CDP connection -- every
other cloud-auth module depends on `cloud_contracts.CloudBrowserProvider`,
so swapping vendors later is contained here.

One CDP connection is opened per login ceremony and reused for every poll
until `close_login_session` (spec §4: some cloud-browser platforms end the
remote session when the CDP socket disconnects, so this never reconnects
mid-ceremony). `_connect_over_cdp` and `_create_steel_client` are separated
into module-level functions purely so tests can monkeypatch the vendor
boundary without touching the adapter's own state machine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
from typing import TYPE_CHECKING

from .errors import NetFacilitiesAuthenticationRequired, NetFacilitiesUnavailable

if TYPE_CHECKING:  # pragma: no cover - import cycle / laziness guard for type checkers only
    from .client import NetFacilitiesClient

CSV_SUFFIX = ".csv"
PARTIAL_SUFFIX = ".crdownload"
# Steel's documented download directory. The listing returns paths carrying
# a `/files/` prefix that must be stripped before interpolation -- see
# `_relative`.
DOWNLOAD_PATH = "/files"
FILES_PREFIX = "/files/"

logger = logging.getLogger(__name__)


def _relative(path: str) -> str:
    """Steel's Files API rejects any leading `/` in the download path.

    `files.list()` returns `/files/`-prefixed absolute paths and
    `files.download()` interpolates its argument into
    `/v1/sessions/{id}/files/{path}` with `/` percent-encoded, so a leading
    slash survives encoding and reaches the server as `%2F`. That is the
    400 this repairs. Interior separators are fine -- Steel accepts nested
    relative paths -- so only the prefix comes off.
    """
    if path.startswith(FILES_PREFIX):
        return path[len(FILES_PREFIX):]
    return path.lstrip("/")


def _create_steel_client(api_key: str):
    from steel import AsyncSteel

    return AsyncSteel(steel_api_key=api_key)


async def _connect_over_cdp(websocket_url: str, api_key: str):
    # Lazy: this module must stay importable (spec D11, and the repo-wide
    # `test_boundary_modules_remain_lazy_without_concrete_dependencies`
    # invariant) on a host with NetFacilities disabled and Playwright not
    # installed -- mirrors `factory.py`'s lazy `from .client import
    # NetFacilitiesClient` for the same reason.
    from playwright.async_api import async_playwright

    playwright = await async_playwright().start()
    browser = await playwright.chromium.connect_over_cdp(f"{websocket_url}&apiKey={api_key}")
    return playwright, browser


@dataclass
class _SteelLoginSession:
    session_id: str
    live_view_url: str
    _playwright: object
    _browser: object
    _client: NetFacilitiesClient
    _seen_files: set[str] = field(default_factory=set)
    # Filenames Playwright's `download` event reported (E2). The event is
    # the trigger; the bytes still come from the Files API. Whether it fires
    # at all over `connect_over_cdp` is unverified (spec 3) -- the safety-net
    # poll is what makes that an optimisation rather than a dependency.
    download_events: list[str] = field(default_factory=list)


class SteelCloudBrowserProvider:
    """One `AsyncSteel` client, reused across every session this process opens."""

    def __init__(self, *, api_key: str) -> None:
        self._api_key = api_key
        self._client = _create_steel_client(api_key)

    async def open_login_session(self) -> _SteelLoginSession:
        from .client import NetFacilitiesClient

        try:
            steel_session = await self._client.sessions.create()
        except Exception as exc:  # vendor SDK's exception hierarchy, reclassified
            raise NetFacilitiesUnavailable(
                "Could not open a NetFacilities cloud browser session."
            ) from exc

        playwright, browser = await _connect_over_cdp(
            steel_session.websocket_url, self._api_key
        )
        context = browser.contexts[0]
        # Browser-level, not page-level: the behavior must outlive any one
        # page, and creating a page here left a stray blank tab in the live
        # view the user is looking at. A ceremony that cannot capture
        # downloads is not a working ceremony, so this no longer swallows.
        try:
            cdp_session = await browser.new_browser_cdp_session()
            await cdp_session.send(
                "Browser.setDownloadBehavior",
                {"behavior": "allow", "downloadPath": DOWNLOAD_PATH, "eventsEnabled": True},
            )
        except Exception as exc:
            logger.error("netfacilities.cloud_download_behavior_setup_failed")
            raise NetFacilitiesUnavailable(
                "Could not prepare the NetFacilities cloud browser for downloads."
            ) from exc

        # The sign-in ceremony never reads a work order, so rendering is moot here.
        client = NetFacilitiesClient(headless=True, _context=context)
        await client.open_authentication_page()

        session = _SteelLoginSession(
            session_id=steel_session.id,
            # `debug_url`, not `session_viewer_url` -- see CloudLoginSession's
            # docstring for why. Confirmed against a real session 2026-08-28.
            live_view_url=steel_session.debug_url,
            _playwright=playwright,
            _browser=browser,
            _client=client,
        )

        # Recorded for every page open now and opened later, so an export
        # clicked from any tab of the live view counts. The recording is
        # what lets `poll_downloaded_csv` log which capture path won
        # (listener or poll) and settle spec 3's open question from
        # production logs rather than argument.
        def _record(download) -> None:
            session.download_events.append(download.suggested_filename)

        def _watch(page) -> None:
            page.on("download", _record)

        for existing in context.pages:
            _watch(existing)
        context.on("page", _watch)
        return session

    async def poll_signed_in(self, session: _SteelLoginSession) -> str | None:
        try:
            await session._client.verify_authentication_page()
            await session._client.prime_session()
        except NetFacilitiesAuthenticationRequired:
            return None
        context = session._browser.contexts[0]
        state = await context.storage_state()
        return json.dumps(state)

    async def poll_downloaded_csv(
        self, session: _SteelLoginSession
    ) -> tuple[str, bytes] | None:
        listing = await self._client.sessions.files.list(session.session_id)
        for entry in listing.data:
            path = entry.path
            if path in session._seen_files:
                continue
            # A `.crdownload` is Chrome mid-write and a zero-byte entry is
            # an export that has not flushed; capturing either would import
            # half a file.
            if path.casefold().endswith(PARTIAL_SUFFIX):
                continue
            if not path.casefold().endswith(CSV_SUFFIX):
                continue
            if getattr(entry, "size", None) == 0:
                continue
            relative = _relative(path)
            response = await self._client.sessions.files.download(
                relative, session_id=session.session_id
            )
            content = await response.read()
            # Recorded only after a successful read: marking it before the
            # download made one transient vendor failure permanent.
            session._seen_files.add(path)
            logger.info(
                "netfacilities.cloud_csv_capture",
                extra={
                    "fields": {
                        "capture_path": "listener" if session.download_events else "poll",
                    }
                },
            )
            return relative.rsplit("/", 1)[-1], content
        return None

    async def close_login_session(self, session: _SteelLoginSession) -> None:
        await session._browser.close()
        await self._client.sessions.release(session.session_id)

    async def open_replay_context(
        self,
        storage_state: str,
        *,
        render_document: bool,
        render_settle_ms: int,
    ):
        """Open a fresh, short-lived session and replay saved storage_state
        into it (spec D5). Task 8 wraps the returned context."""

        try:
            steel_session = await self._client.sessions.create()
        except Exception as exc:
            raise NetFacilitiesUnavailable(
                "Could not open a NetFacilities cloud browser session for enrichment."
            ) from exc
        playwright, browser = await _connect_over_cdp(
            steel_session.websocket_url, self._api_key
        )
        context = await browser.new_context(storage_state=json.loads(storage_state))
        return _SteelEnrichmentContext(
            client=self,
            steel_session_id=steel_session.id,
            playwright=playwright,
            browser=browser,
            context=context,
            render_document=render_document,
            render_settle_ms=render_settle_ms,
        )


@dataclass
class _SteelEnrichmentContext:
    """Implements `NetFacilitiesClientContextProtocol` for one reconnected job."""

    client: "SteelCloudBrowserProvider"
    steel_session_id: str
    playwright: object
    browser: object
    context: object
    render_document: bool
    render_settle_ms: int
    _wrapped: "NetFacilitiesClient | None" = None

    async def __aenter__(self) -> "NetFacilitiesClient":
        from .client import NetFacilitiesClient

        self._wrapped = NetFacilitiesClient(
            headless=True,
            _context=self.context,
            render_document=self.render_document,
            render_settle_ms=self.render_settle_ms,
        )
        return self._wrapped

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        try:
            await self.context.close()
            await self.browser.close()
        finally:
            await self.client._client.sessions.release(self.steel_session_id)
