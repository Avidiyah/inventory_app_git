"""Configuration is fail-closed and free of browser or filesystem side effects."""

from app.integrations.netfacilities.config import (
    DEFAULT_BATCH_TIMEOUT_SECONDS,
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    load_netfacilities_config,
)
from app.integrations.netfacilities.errors import NetFacilitiesUnavailable
import pytest


def test_disabled_by_default():
    config = load_netfacilities_config({})
    assert config.enabled is False
    assert config.request_timeout_seconds == DEFAULT_REQUEST_TIMEOUT_SECONDS
    assert config.batch_timeout_seconds == DEFAULT_BATCH_TIMEOUT_SECONDS


def test_enabled_reads_timeouts():
    config = load_netfacilities_config(
        {
            "NETFACILITIES_ENABLED": "true",
            "NETFACILITIES_REQUEST_TIMEOUT_SECONDS": "45",
            "NETFACILITIES_BATCH_TIMEOUT_SECONDS": "900",
        }
    )
    assert config.enabled is True
    assert config.request_timeout_seconds == 45
    assert config.request_timeout_ms == 45_000
    assert config.batch_timeout_seconds == 900


def test_invalid_enabled_flag_raises():
    with pytest.raises(NetFacilitiesUnavailable):
        load_netfacilities_config({"NETFACILITIES_ENABLED": "sure"})


def test_non_positive_timeout_raises():
    with pytest.raises(NetFacilitiesUnavailable):
        load_netfacilities_config(
            {"NETFACILITIES_ENABLED": "true", "NETFACILITIES_BATCH_TIMEOUT_SECONDS": "0"}
        )


def test_render_document_flag_and_settle_seconds():
    config = load_netfacilities_config(
        {
            "NETFACILITIES_ENABLED": "true",
            "NETFACILITIES_RENDER_DOCUMENT": "true",
            "NETFACILITIES_RENDER_SETTLE_SECONDS": "9",
        }
    )
    assert config.render_document is True
    assert config.render_settle_seconds == 9
    assert config.render_settle_ms == 9_000


def test_invalid_render_document_flag_raises():
    with pytest.raises(NetFacilitiesUnavailable):
        load_netfacilities_config(
            {"NETFACILITIES_ENABLED": "true", "NETFACILITIES_RENDER_DOCUMENT": "maybe"}
        )
