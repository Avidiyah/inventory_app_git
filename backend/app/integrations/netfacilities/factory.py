"""Lazy construction of the local-only NetFacilities browser client."""

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

    if not config.enabled or config.profile_dir is None:
        raise NetFacilitiesUnavailable(
            "NetFacilities enrichment is disabled on this host."
        )
    try:
        from .client import NetFacilitiesClient
    except ModuleNotFoundError as exc:
        raise NetFacilitiesUnavailable(
            "NetFacilities local browser dependencies are unavailable."
        ) from exc

    return NetFacilitiesClient(
        profile_dir=config.profile_dir,
        headless=headless,
        browser_channel=config.playwright_channel,
        timeout_ms=config.request_timeout_ms,
        use_saved_state=use_saved_state,
    )


def create_netfacilities_authentication_client(
    config: NetFacilitiesConfig,
) -> NetFacilitiesAuthenticationContextProtocol:
    """Create the headed client used by the local in-app sign-in ceremony."""

    return create_netfacilities_client(
        config,
        headless=False,
        use_saved_state=False,
    )
