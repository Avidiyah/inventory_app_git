"""Offline test for the reconnect-per-job cloud enrichment client factory (D5)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import uuid

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

        async def open_replay_context(
            self, storage_state, *, render_document, render_settle_ms
        ):
            captured["storage_state"] = storage_state
            captured["render_document"] = render_document
            captured["render_settle_ms"] = render_settle_ms
            return FakeContext()

    # `factory.py`'s implementation imports SteelCloudBrowserProvider lazily,
    # inside the function body, specifically so this patch on its source
    # module -- not on `factory`'s own namespace, which never binds the name
    # at module level -- takes effect on the next call.
    monkeypatch.setattr(
        "app.integrations.netfacilities.cloud_steel.SteelCloudBrowserProvider", FakeProvider
    )

    config = NetFacilitiesCloudConfig(enabled=True, steel_api_key="test-key")
    context = create_netfacilities_cloud_enrichment_client(
        config,
        token,
        render_document=True,
        render_settle_ms=5_000,
    )

    async def _enter_and_exit():
        async with context as client:
            return client

    client = asyncio.run(_enter_and_exit())

    assert client == "fake-client"
    assert captured["api_key"] == "test-key"
    assert captured["storage_state"] == '{"cookies": []}'
    # NETFACILITIES_RENDER_DOCUMENT reaches the only client that still exists.
    assert captured["render_document"] is True
    assert captured["render_settle_ms"] == 5_000


# --- resolve_cloud_enrichment_context ------------------------------------
#
# Lifted out of the router so the unattended capture chain can call it with a
# bare `user_id` (spec §4.3). These run against the real `db` fixture: the
# rule under test is "whose row, and is it still live", which a fake session
# cannot exercise honestly.


def _netfacilities_config():
    from app.integrations.netfacilities.config import NetFacilitiesConfig

    return NetFacilitiesConfig(
        enabled=True,
        request_timeout_seconds=30,
        batch_timeout_seconds=1_800,
    )


def _cloud_env(monkeypatch):
    monkeypatch.setenv("NETFACILITIES_CLOUD_AUTH_ENABLED", "true")
    monkeypatch.setenv("STEEL_API_KEY", "test-key")
    monkeypatch.setenv(
        "NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY", Fernet.generate_key().decode()
    )


def _user(db):
    from app.models import User

    user = User(
        username=f"oa-{uuid.uuid4().hex[:8]}",
        first_name="Test",
        last_name="User",
        password_hash="x",
        role="techfm_oa",
    )
    db.add(user)
    db.commit()
    return user


def test_resolve_returns_nothing_for_a_user_with_no_saved_session(db, monkeypatch):
    from app.services.netfacilities_cloud_enrichment import (
        resolve_cloud_enrichment_context,
    )

    _cloud_env(monkeypatch)

    context, seconds = resolve_cloud_enrichment_context(
        _netfacilities_config(), db, uuid.uuid4()
    )

    assert context is None
    assert seconds is None


def test_resolve_returns_the_users_own_session_and_the_batch_cap(db, monkeypatch):
    from app.models import NetFacilitiesCloudSession
    from app.services.netfacilities_cloud_enrichment import (
        resolve_cloud_enrichment_context,
    )

    _cloud_env(monkeypatch)
    user = _user(db)
    token = crypto.encrypt_storage_state('{"cookies": []}').decode("ascii")
    db.add(
        NetFacilitiesCloudSession(
            user_id=user.id,
            storage_state=token,
            signed_in_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    class FakeProvider:
        def __init__(self, *, api_key):
            self.api_key = api_key

    monkeypatch.setattr(
        "app.integrations.netfacilities.cloud_steel.SteelCloudBrowserProvider", FakeProvider
    )

    context, seconds = resolve_cloud_enrichment_context(
        _netfacilities_config(), db, user.id
    )

    assert context is not None
    # Default batch cap (spec §4): 840 s, margin under Steel's 15-minute cap.
    assert seconds == 840


def test_resolve_treats_an_expired_session_as_absent(db, monkeypatch):
    """Spec D10: a row the router expired after `authentication_required`
    must not be replayed into another job."""

    from app.models import NetFacilitiesCloudSession
    from app.services.netfacilities_cloud_enrichment import (
        resolve_cloud_enrichment_context,
    )

    _cloud_env(monkeypatch)
    user = _user(db)
    token = crypto.encrypt_storage_state('{"cookies": []}').decode("ascii")
    db.add(
        NetFacilitiesCloudSession(
            user_id=user.id,
            storage_state=token,
            signed_in_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    context, seconds = resolve_cloud_enrichment_context(
        _netfacilities_config(), db, user.id
    )

    assert context is None
    assert seconds is None
