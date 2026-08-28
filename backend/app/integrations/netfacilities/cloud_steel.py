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
DOWNLOAD_PATH = "/downloads"

logger = logging.getLogger(__name__)


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
    session_viewer_url: str
    _playwright: object
    _browser: object
    _client: NetFacilitiesClient
    _seen_files: set[str] = field(default_factory=set)


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
        try:
            cdp_session = await context.new_cdp_session(await context.new_page())
            await cdp_session.send(
                "Browser.setDownloadBehavior",
                {"behavior": "allow", "downloadPath": DOWNLOAD_PATH, "eventsEnabled": True},
            )
        except Exception:
            logger.error("netfacilities.cloud_download_behavior_setup_failed")

        client = NetFacilitiesClient(profile_dir=None, headless=True, _context=context)
        await client.open_authentication_page()

        return _SteelLoginSession(
            session_id=steel_session.id,
            session_viewer_url=steel_session.session_viewer_url,
            _playwright=playwright,
            _browser=browser,
            _client=client,
        )

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
            if not path.casefold().endswith(CSV_SUFFIX):
                continue
            if path in session._seen_files:
                continue
            session._seen_files.add(path)
            response = await self._client.sessions.files.download(
                path, session_id=session.session_id
            )
            content = await response.read()
            return path.rsplit("/", 1)[-1], content
        return None

    async def close_login_session(self, session: _SteelLoginSession) -> None:
        await session._browser.close()
        await self._client.sessions.release(session.session_id)

    async def open_replay_context(self, storage_state: str):
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
        )


@dataclass
class _SteelEnrichmentContext:
    """Implements `NetFacilitiesClientContextProtocol` for one reconnected job."""

    client: "SteelCloudBrowserProvider"
    steel_session_id: str
    playwright: object
    browser: object
    context: object
    _wrapped: "NetFacilitiesClient | None" = None

    async def __aenter__(self) -> "NetFacilitiesClient":
        from .client import NetFacilitiesClient

        self._wrapped = NetFacilitiesClient(
            profile_dir=None, headless=True, _context=self.context
        )
        return self._wrapped

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        try:
            await self.context.close()
            await self.browser.close()
        finally:
            await self.client._client.sessions.release(self.steel_session_id)
