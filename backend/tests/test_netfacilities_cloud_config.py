"""Offline tests for cloud-auth configuration (spec D1, §4)."""

from __future__ import annotations

from cryptography.fernet import Fernet

from app.integrations.netfacilities.cloud_config import load_netfacilities_cloud_config
from app.integrations.netfacilities.config import NetFacilitiesConfig


VALID_KEY = Fernet.generate_key().decode("ascii")
ENABLED_BASE = NetFacilitiesConfig(
    enabled=True,
    request_timeout_seconds=30,
    batch_timeout_seconds=1_800,
)
DISABLED_BASE = NetFacilitiesConfig(
    enabled=False,
    request_timeout_seconds=30,
    batch_timeout_seconds=1_800,
)


def _environ(**overrides):
    base = {
        "NETFACILITIES_CLOUD_AUTH_ENABLED": "true",
        "STEEL_API_KEY": "test-key",
        "NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY": VALID_KEY,
    }
    base.update(overrides)
    return base


def test_disabled_when_base_capability_off():
    config = load_netfacilities_cloud_config(DISABLED_BASE, _environ())
    assert config.enabled is False


def test_disabled_when_flag_unset():
    config = load_netfacilities_cloud_config(
        ENABLED_BASE, _environ(NETFACILITIES_CLOUD_AUTH_ENABLED="")
    )
    assert config.enabled is False


def test_disabled_when_steel_api_key_missing():
    config = load_netfacilities_cloud_config(ENABLED_BASE, _environ(STEEL_API_KEY=""))
    assert config.enabled is False


def test_disabled_when_encryption_key_missing():
    config = load_netfacilities_cloud_config(
        ENABLED_BASE, _environ(NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY="")
    )
    assert config.enabled is False


def test_enabled_with_every_prerequisite():
    config = load_netfacilities_cloud_config(ENABLED_BASE, _environ())
    assert config.enabled is True
    assert config.steel_api_key == "test-key"
    assert config.login_timeout_seconds == 840


def test_custom_login_timeout():
    config = load_netfacilities_cloud_config(
        ENABLED_BASE,
        _environ(NETFACILITIES_CLOUD_LOGIN_TIMEOUT_SECONDS="300"),
    )
    assert config.login_timeout_seconds == 300


def test_chain_timings_default_to_the_spec_values():
    # E12: signed-in deadline 10 min (under Steel's 15-minute cap), safety-net
    # poll 5 s (slower than the old 3 s -- the listener is primary), and a
    # 2-minute cap on retrying a busy enrichment coordinator.
    config = load_netfacilities_cloud_config(ENABLED_BASE, _environ())

    assert config.signed_in_timeout_seconds == 600
    assert config.capture_poll_seconds == 5
    assert config.enrichment_retry_seconds == 120


def test_chain_timings_are_env_overridable():
    config = load_netfacilities_cloud_config(
        ENABLED_BASE,
        _environ(
            NETFACILITIES_CLOUD_SIGNED_IN_TIMEOUT_SECONDS="300",
            NETFACILITIES_CLOUD_CAPTURE_POLL_SECONDS="2",
            NETFACILITIES_CLOUD_ENRICHMENT_RETRY_SECONDS="45",
        ),
    )

    assert config.signed_in_timeout_seconds == 300
    assert config.capture_poll_seconds == 2
    assert config.enrichment_retry_seconds == 45
