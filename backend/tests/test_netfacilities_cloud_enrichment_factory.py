"""Offline test for the reconnect-per-job cloud enrichment client factory (D5)."""

from __future__ import annotations

import asyncio

from cryptography.fernet import Fernet

from app.integrations.netfacilities.cloud_config import NetFacilitiesCloudConfig
from app.integrations.netfacilities.factory import (
    create_netfacilities_cloud_enrichment_client,
)
from app.services import netfacilities_cloud_crypto as crypto


def test_decrypts_and_delegates_to_the_provider(monkeypatch):
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY", key)
    token = crypto.encrypt_storage_state('{"cookies": []}')

    captured = {}

    class FakeContext:
        async def __aenter__(self):
            return "fake-client"

        async def __aexit__(self, *args):
            return None

    class FakeProvider:
        def __init__(self, *, api_key):
            captured["api_key"] = api_key

        async def open_replay_context(self, storage_state):
            captured["storage_state"] = storage_state
            return FakeContext()

    # `factory.py`'s implementation imports SteelCloudBrowserProvider lazily,
    # inside the function body, specifically so this patch on its source
    # module -- not on `factory`'s own namespace, which never binds the name
    # at module level -- takes effect on the next call.
    monkeypatch.setattr(
        "app.integrations.netfacilities.cloud_steel.SteelCloudBrowserProvider", FakeProvider
    )

    config = NetFacilitiesCloudConfig(enabled=True, steel_api_key="test-key")
    context = create_netfacilities_cloud_enrichment_client(config, token)

    async def _enter_and_exit():
        async with context as client:
            return client

    client = asyncio.run(_enter_and_exit())

    assert client == "fake-client"
    assert captured["api_key"] == "test-key"
    assert captured["storage_state"] == '{"cookies": []}'
