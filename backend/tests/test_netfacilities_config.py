"""NetFacilities configuration stays strict, lazy, and production-safe."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

from app.integrations.netfacilities.config import (
    DEFAULT_AUTH_TIMEOUT_SECONDS,
    DEFAULT_BATCH_TIMEOUT_SECONDS,
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    DEFAULT_SESSION_TIMEOUT_SECONDS,
    NetFacilitiesConfig,
    STORAGE_STATE_FILENAME,
    _repository_root,
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
    assert config.storage_state_path is None
    assert not config.interactive_authentication_available


@pytest.mark.parametrize("value", ["1", "yes", "enabled", "maybe"])
def test_feature_flag_rejects_ambiguous_values(value):
    with pytest.raises(NetFacilitiesUnavailable, match="either true or false"):
        load_netfacilities_config({"NETFACILITIES_ENABLED": value}, platform="win32")


def test_linux_capability_requires_an_absolute_external_storage_state(tmp_path):
    repository_root = tmp_path / "repository"
    with pytest.raises(NetFacilitiesUnavailable, match="required on Linux"):
        load_netfacilities_config(
            {"NETFACILITIES_ENABLED": "true"},
            platform="linux",
            repository_root=repository_root,
        )

    with pytest.raises(NetFacilitiesUnavailable, match="absolute path"):
        load_netfacilities_config(
            {
                "NETFACILITIES_ENABLED": "true",
                "NETFACILITIES_STORAGE_STATE_PATH": "relative/state.json",
            },
            platform="linux",
            repository_root=repository_root,
        )

    with pytest.raises(NetFacilitiesUnavailable, match="outside the repository"):
        load_netfacilities_config(
            {
                "NETFACILITIES_ENABLED": "true",
                "NETFACILITIES_STORAGE_STATE_PATH": str(
                    repository_root / "state.json"
                ),
            },
            platform="linux",
            repository_root=repository_root,
        )


def test_linux_capability_uses_hosted_saved_state_without_interactive_auth(tmp_path):
    repository_root = tmp_path / "repository"
    storage_state = tmp_path / "secrets" / "netfacilities-state.json"
    storage_state.parent.mkdir()
    storage_state.write_text('{"cookies": [], "origins": []}', encoding="utf-8")

    config = load_netfacilities_config(
        {
            "NETFACILITIES_ENABLED": "true",
            "NETFACILITIES_STORAGE_STATE_PATH": str(storage_state),
        },
        platform="linux",
        repository_root=repository_root,
    )

    assert config.enabled
    assert config.profile_dir is None
    assert config.storage_state_path == storage_state.resolve(strict=False)
    assert config.has_saved_authentication
    assert not config.interactive_authentication_available


def _hosted_environment(tmp_path, **overrides):
    storage_state = tmp_path / "secrets" / "netfacilities-state.json"
    storage_state.parent.mkdir(exist_ok=True)
    storage_state.write_text('{"cookies": [], "origins": []}', encoding="utf-8")
    return {
        "NETFACILITIES_ENABLED": "true",
        "NETFACILITIES_STORAGE_STATE_PATH": str(storage_state),
        **overrides,
    }


def test_raw_document_retrieval_is_the_hosted_default(tmp_path):
    config = load_netfacilities_config(
        _hosted_environment(tmp_path),
        platform="linux",
        repository_root=tmp_path / "repository",
    )

    # Priority is server-rendered into the primed document, so the batch pays no
    # settle wait and runs no JavaScript.
    assert config.render_document is False
    assert config.render_settle_ms == 5_000


def test_rendered_document_retrieval_can_be_enabled_without_a_redeploy(tmp_path):
    config = load_netfacilities_config(
        _hosted_environment(tmp_path, NETFACILITIES_RENDER_DOCUMENT="true"),
        platform="linux",
        repository_root=tmp_path / "repository",
    )

    assert config.render_document is True


@pytest.mark.parametrize("value", ["1", "yes", "enabled", "maybe"])
def test_rendered_document_flag_rejects_ambiguous_values(tmp_path, value):
    with pytest.raises(NetFacilitiesUnavailable, match="either true or false"):
        load_netfacilities_config(
            _hosted_environment(tmp_path, NETFACILITIES_RENDER_DOCUMENT=value),
            platform="linux",
            repository_root=tmp_path / "repository",
        )


def test_render_settle_seconds_is_bounded_and_configurable(tmp_path):
    config = load_netfacilities_config(
        _hosted_environment(tmp_path, NETFACILITIES_RENDER_SETTLE_SECONDS="8"),
        platform="linux",
        repository_root=tmp_path / "repository",
    )
    assert config.render_settle_ms == 8_000

    with pytest.raises(NetFacilitiesUnavailable, match="positive whole number"):
        load_netfacilities_config(
            _hosted_environment(tmp_path, NETFACILITIES_RENDER_SETTLE_SECONDS="0"),
            platform="linux",
            repository_root=tmp_path / "repository",
        )


def test_repository_root_supports_checkout_and_production_image_layouts(tmp_path):
    checkout_module = (
        tmp_path
        / "inventory-app"
        / "backend"
        / "app"
        / "integrations"
        / "netfacilities"
        / "config.py"
    )
    image_module = (
        tmp_path
        / "image"
        / "app"
        / "integrations"
        / "netfacilities"
        / "config.py"
    )

    assert _repository_root(checkout_module) == tmp_path / "inventory-app"
    assert _repository_root(image_module) == tmp_path / "image"


def test_production_image_defaults_enable_hosted_capability():
    backend = Path(__file__).resolve().parents[1]
    dockerfile = (backend / "Dockerfile").read_text(encoding="utf-8")

    # A Render deploy hook rebuilds the service image but does not apply new
    # render.yaml environment declarations to an existing service. These image
    # defaults keep the deployed capability on even before a Blueprint sync.
    assert "NETFACILITIES_ENABLED=true" in dockerfile
    assert (
        "NETFACILITIES_STORAGE_STATE_PATH="
        "/etc/secrets/netfacilities-storage-state.json"
    ) in dockerfile


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
    assert config.interactive_authentication_available

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


def test_hosted_factory_uses_bundled_browser_without_interactive_authentication(
    tmp_path,
):
    storage_state = tmp_path / STORAGE_STATE_FILENAME
    storage_state.write_text('{"cookies": [], "origins": []}', encoding="utf-8")
    config = NetFacilitiesConfig(
        enabled=True,
        profile_dir=None,
        browser_channel="bundled-chromium",
        request_timeout_seconds=30,
        auth_timeout_seconds=900,
        batch_timeout_seconds=1_800,
        storage_state_file=storage_state,
        interactive_authentication_available=False,
    )

    client = create_netfacilities_client(
        config,
        headless=True,
        use_saved_state=True,
    )

    assert client.request_only is False
    assert client.browser_channel is None
    # Priming, not rendering, is what puts Priority in the document.
    assert client.render_document is False
    assert client.render_settle_ms == 5_000


def test_hosted_factory_honours_the_rendered_document_kill_switch(tmp_path):
    storage_state = tmp_path / STORAGE_STATE_FILENAME
    storage_state.write_text('{"cookies": [], "origins": []}', encoding="utf-8")
    config = NetFacilitiesConfig(
        enabled=True,
        profile_dir=None,
        browser_channel="bundled-chromium",
        request_timeout_seconds=30,
        auth_timeout_seconds=900,
        batch_timeout_seconds=1_800,
        storage_state_file=storage_state,
        interactive_authentication_available=False,
        render_document=False,
    )

    client = create_netfacilities_client(config, headless=True, use_saved_state=True)

    assert client.render_document is False


def test_boundary_modules_remain_lazy_without_concrete_dependencies():
    backend = Path(__file__).resolve().parents[1]
    script = r'''
import builtins
real_import = builtins.__import__
def guarded_import(name, *args, **kwargs):
    if name == "playwright" or name.startswith("playwright.") or name == "bs4" or name.startswith("bs4."):
        raise AssertionError(f"concrete dependency imported: {name}")
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


def _windows_env(profile):
    return {
        "NETFACILITIES_ENABLED": "true",
        "NETFACILITIES_PROFILE_DIR": str(profile),
    }


def test_windows_download_dir_defaults_to_home_downloads_when_present(
    tmp_path, monkeypatch
):
    home = tmp_path / "home"
    (home / "Downloads").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: home)
    profile = tmp_path / "profile"

    config = load_netfacilities_config(_windows_env(profile), platform="win32")

    assert config.download_dir == (home / "Downloads").resolve()
    assert config.session_timeout_seconds == DEFAULT_SESSION_TIMEOUT_SECONDS


def test_windows_download_dir_falls_back_inside_the_profile(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    profile = tmp_path / "profile"

    config = load_netfacilities_config(_windows_env(profile), platform="win32")

    assert config.download_dir == profile.resolve() / "downloads"


def test_explicit_download_dir_and_session_timeout_are_honored(tmp_path):
    profile = tmp_path / "profile"
    downloads = tmp_path / "exports"
    env = {
        **_windows_env(profile),
        "NETFACILITIES_DOWNLOAD_DIR": str(downloads),
        "NETFACILITIES_SESSION_TIMEOUT_SECONDS": "600",
    }

    config = load_netfacilities_config(env, platform="win32")

    assert config.download_dir == downloads.resolve()
    assert config.session_timeout_seconds == 600


@pytest.mark.parametrize("value", ["relative/dir", "0", "-5", "soon"])
def test_download_dir_and_session_timeout_reject_bad_values(tmp_path, value):
    profile = tmp_path / "profile"
    if value == "relative/dir":
        env = {**_windows_env(profile), "NETFACILITIES_DOWNLOAD_DIR": value}
    else:
        env = {**_windows_env(profile), "NETFACILITIES_SESSION_TIMEOUT_SECONDS": value}

    with pytest.raises(NetFacilitiesUnavailable):
        load_netfacilities_config(env, platform="win32")


def test_download_dir_may_not_live_inside_the_repository(tmp_path):
    repository = tmp_path / "repo"
    profile = tmp_path / "profile"
    env = {
        **_windows_env(profile),
        "NETFACILITIES_DOWNLOAD_DIR": str(repository / "downloads"),
    }

    with pytest.raises(NetFacilitiesUnavailable, match="outside the repository"):
        load_netfacilities_config(env, platform="win32", repository_root=repository)


def test_disabled_and_hosted_configs_have_no_download_dir(tmp_path):
    disabled = load_netfacilities_config({}, platform="win32")
    hosted = load_netfacilities_config(
        {
            "NETFACILITIES_ENABLED": "true",
            "NETFACILITIES_STORAGE_STATE_PATH": str(tmp_path / "state.json"),
        },
        platform="linux",
    )

    assert disabled.download_dir is None
    assert hosted.download_dir is None
    assert hosted.session_timeout_seconds == DEFAULT_SESSION_TIMEOUT_SECONDS
