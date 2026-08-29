"""Lazy construction of hosted NetFacilities clients."""

from __future__ import annotations

from .cloud_config import NetFacilitiesCloudConfig
from .contracts import NetFacilitiesClientContextProtocol
from .errors import NetFacilitiesUnavailable


def create_netfacilities_cloud_enrichment_client(
    config: NetFacilitiesCloudConfig,
    encrypted_storage_state: bytes,
) -> NetFacilitiesClientContextProtocol:
    """Reconnect to a fresh, short-lived Steel session and replay a user's
    saved storage_state() for one enrichment job (spec D5, verified by the
    Task 1 manual spike). A context whose `__aenter__` returns a client with
    `get_work_order` -- exactly the shape `NetFacilitiesJobCoordinator`
    already expects."""

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
    `create_netfacilities_cloud_enrichment_client` itself is sync."""

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
