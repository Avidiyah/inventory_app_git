"""Lazy construction of local or hosted NetFacilities clients."""

from __future__ import annotations

from .cloud_config import NetFacilitiesCloudConfig
from .config import NetFacilitiesConfig
from .contracts import (
    NetFacilitiesAuthenticationContextProtocol,
    NetFacilitiesClientContextProtocol,
)
from .errors import NetFacilitiesUnavailable


def create_netfacilities_client(
    config: NetFacilitiesConfig,
    *,
    headless: bool,
    use_saved_state: bool,
) -> NetFacilitiesClientContextProtocol:
    """Create the concrete client only after safe enablement is established."""

    if not config.enabled or config.storage_state_path is None:
        raise NetFacilitiesUnavailable(
            "NetFacilities enrichment is disabled on this host."
        )
    try:
        from .client import NetFacilitiesClient
    except ModuleNotFoundError as exc:
        raise NetFacilitiesUnavailable(
            "NetFacilities integration dependencies are unavailable."
        ) from exc

    return NetFacilitiesClient(
        profile_dir=config.profile_dir,
        storage_state_path=config.storage_state_path,
        headless=headless,
        browser_channel=config.playwright_channel,
        timeout_ms=config.request_timeout_ms,
        use_saved_state=use_saved_state,
        # NetFacilities ships Priority inside an inline script and inserts it into the
        # DOM on load. Owner DevTools verification on 2026-08-15 found it absent from
        # the Network response body and from every XHR, and present only in Elements,
        # so no request-shaped change can recover it: the document must be rendered.
        # NETFACILITIES_RENDER_DOCUMENT=false reverts to the raw read via a restart.
        request_only=False,
        render_document=config.render_document,
        render_settle_ms=config.render_settle_ms,
    )


def create_netfacilities_authentication_client(
    config: NetFacilitiesConfig,
) -> NetFacilitiesAuthenticationContextProtocol:
    """Create the headed client used by the local in-app sign-in ceremony."""

    if not config.interactive_authentication_available or config.profile_dir is None:
        raise NetFacilitiesUnavailable(
            "Interactive NetFacilities sign-in is unavailable on this host."
        )

    return create_netfacilities_client(
        config,
        headless=False,
        use_saved_state=False,
    )


def create_netfacilities_cloud_enrichment_client(
    config: NetFacilitiesCloudConfig,
    encrypted_storage_state: bytes,
) -> NetFacilitiesClientContextProtocol:
    """Reconnect to a fresh, short-lived Steel session and replay a user's
    saved storage_state() for one enrichment job (spec D5, verified by the
    Task 1 manual spike). A context whose `__aenter__` returns a client with
    `get_work_order` -- exactly the shape `NetFacilitiesJobCoordinator`
    already expects from `create_netfacilities_client`."""

    from app.services import netfacilities_cloud_crypto as crypto

    from .cloud_steel import SteelCloudBrowserProvider

    if not config.enabled or config.steel_api_key is None:
        raise NetFacilitiesUnavailable(
            "NetFacilities cloud enrichment is disabled on this host."
        )
    storage_state = crypto.decrypt_storage_state(encrypted_storage_state)
    provider = SteelCloudBrowserProvider(api_key=config.steel_api_key)
    return _CloudEnrichmentContextAdapter(provider, storage_state)


class _CloudEnrichmentContextAdapter:
    """Defers `open_replay_context` (async) until `__aenter__`, since
    `create_netfacilities_cloud_enrichment_client` itself is sync -- matching
    every other factory function in this module."""

    def __init__(self, provider, storage_state: str) -> None:
        self._provider = provider
        self._storage_state = storage_state
        self._inner = None

    async def __aenter__(self):
        self._inner = await self._provider.open_replay_context(self._storage_state)
        return await self._inner.__aenter__()

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        if self._inner is not None:
            await self._inner.__aexit__(exc_type, exc, traceback)
