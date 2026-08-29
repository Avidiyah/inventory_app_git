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
