"""Lazy construction of local or hosted NetFacilities clients."""

from __future__ import annotations

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
