"""Local capability configuration stays strict, lazy, and production-safe."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

from app.integrations.netfacilities.config import (
    DEFAULT_AUTH_TIMEOUT_SECONDS,
    DEFAULT_BATCH_TIMEOUT_SECONDS,
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    NetFacilitiesConfig,
    STORAGE_STATE_FILENAME,
    load_netfacilities_config,
)
from app.integrations.netfacilities.errors import NetFacilitiesUnavailable
from app.integrations.netfacilities.factory import create_netfacilities_client


def test_capability_defaults_to_disabled_without_local_paths():
    config = load_netfacilities_config({}, platform="win32")

    assert not config.enabled
    assert config.profile_dir is None
    assert config.browser_channel == "chrome"
    assert config.request_timeout_seconds == DEFAULT_REQUEST_TIMEOUT_SECONDS
    assert config.auth_timeout_seconds == DEFAULT_AUTH_TIMEOUT_SECONDS
    assert config.batch_timeout_seconds == DEFAULT_BATCH_TIMEOUT_SECONDS


@pytest.mark.parametrize("value", ["1", "yes", "enabled", "maybe"])
def test_feature_flag_rejects_ambiguous_values(value):
    with pytest.raises(NetFacilitiesUnavailable, match="either true or false"):
        load_netfacilities_config({"NETFACILITIES_ENABLED": value}, platform="win32")


def test_enabled_capability_requires_local_windows():
    with pytest.raises(NetFacilitiesUnavailable, match="local Windows host"):
        load_netfacilities_config(
            {
                "NETFACILITIES_ENABLED": "true",
                "NETFACILITIES_PROFILE_DIR": "/secure/netfacilities",
            },
            platform="linux",
        )


def test_enabled_capability_requires_an_absolute_external_profile(tmp_path):
    with pytest.raises(NetFacilitiesUnavailable, match="required"):
        load_netfacilities_config({"NETFACILITIES_ENABLED": "true"}, platform="win32")

    with pytest.raises(NetFacilitiesUnavailable, match="absolute path"):
        load_netfacilities_config(
            {
                "NETFACILITIES_ENABLED": "true",
                "NETFACILITIES_PROFILE_DIR": "relative/profile",
            },
            platform="win32",
        )

    repository_root = tmp_path / "repository"
    with pytest.raises(NetFacilitiesUnavailable, match="outside the repository"):
        load_netfacilities_config(
            {
                "NETFACILITIES_ENABLED": "true",
                "NETFACILITIES_PROFILE_DIR": str(repository_root / "profile"),
            },
            platform="win32",
            repository_root=repository_root,
        )


def test_external_profile_may_be_created_later_but_cannot_be_a_file(tmp_path):
    repository_root = tmp_path / "repository"
    external_profile = tmp_path / "protected" / "profile"
    config = load_netfacilities_config(
        {
            "NETFACILITIES_ENABLED": "true",
            "NETFACILITIES_PROFILE_DIR": str(external_profile),
        },
        platform="win32",
        repository_root=repository_root,
    )
    assert config.profile_dir == external_profile.resolve(strict=False)
    assert config.storage_state_path == external_profile / STORAGE_STATE_FILENAME
    assert not config.has_saved_authentication
    assert not external_profile.exists()

    external_profile.mkdir(parents=True)
    config.storage_state_path.write_text("test-only", encoding="utf-8")
    assert config.has_saved_authentication

    profile_file = tmp_path / "profile-file"
    profile_file.write_text("not a profile", encoding="utf-8")
    with pytest.raises(NetFacilitiesUnavailable, match="directory"):
        load_netfacilities_config(
            {
                "NETFACILITIES_ENABLED": "true",
                "NETFACILITIES_PROFILE_DIR": str(profile_file),
            },
            platform="win32",
            repository_root=repository_root,
        )


@pytest.mark.parametrize(
    ("setting", "value"),
    [
        ("NETFACILITIES_REQUEST_TIMEOUT_SECONDS", "0"),
        ("NETFACILITIES_AUTH_TIMEOUT_SECONDS", "-1"),
        ("NETFACILITIES_BATCH_TIMEOUT_SECONDS", "forever"),
    ],
)
def test_enabled_capability_rejects_unbounded_timeouts(tmp_path, setting, value):
    with pytest.raises(NetFacilitiesUnavailable, match="positive whole number"):
        load_netfacilities_config(
            {
                "NETFACILITIES_ENABLED": "true",
                "NETFACILITIES_PROFILE_DIR": str(tmp_path / "profile"),
                setting: value,
            },
            platform="win32",
            repository_root=tmp_path / "repository",
        )


def test_browser_channel_is_allowlisted_and_bundled_maps_to_none(tmp_path):
    base = {
        "NETFACILITIES_ENABLED": "true",
        "NETFACILITIES_PROFILE_DIR": str(tmp_path / "profile"),
    }
    with pytest.raises(NetFacilitiesUnavailable, match="approved browser channel"):
        load_netfacilities_config(
            {**base, "NETFACILITIES_BROWSER_CHANNEL": "firefox"},
            platform="win32",
            repository_root=tmp_path / "repository",
        )

    config = load_netfacilities_config(
        {**base, "NETFACILITIES_BROWSER_CHANNEL": "bundled-chromium"},
        platform="win32",
        repository_root=tmp_path / "repository",
    )
    assert config.playwright_channel is None


def test_factory_refuses_disabled_capability():
    config = NetFacilitiesConfig(
        enabled=False,
        profile_dir=None,
        browser_channel="chrome",
        request_timeout_seconds=30,
        auth_timeout_seconds=900,
        batch_timeout_seconds=1_800,
    )
    with pytest.raises(NetFacilitiesUnavailable, match="disabled"):
        create_netfacilities_client(config, headless=True, use_saved_state=True)


def test_boundary_modules_import_without_local_browser_dependencies():
    backend = Path(__file__).resolve().parents[1]
    script = r'''
import builtins
real_import = builtins.__import__
def guarded_import(name, *args, **kwargs):
    if name == "playwright" or name.startswith("playwright.") or name == "bs4" or name.startswith("bs4."):
        raise AssertionError(f"local dependency imported: {name}")
    return real_import(name, *args, **kwargs)
builtins.__import__ = guarded_import
from app.integrations.netfacilities import config, contracts, factory
from app.services import netfacilities as enrichment_service
assert "app.integrations.netfacilities.client" not in sys.modules
import app.main
assert "app.integrations.netfacilities.client" not in sys.modules
'''
    # Keep the subprocess isolated from any concrete-client imports performed by
    # other tests in this pytest process.
    result = subprocess.run(
        [sys.executable, "-c", "import sys\n" + script],
        cwd=backend,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
