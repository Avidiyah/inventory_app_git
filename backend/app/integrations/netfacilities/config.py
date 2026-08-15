"""Fail-closed local configuration for the NetFacilities capability."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os
from pathlib import Path
import sys

from .errors import NetFacilitiesUnavailable


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_BROWSER_CHANNEL = "chrome"
ALLOWED_BROWSER_CHANNELS = frozenset({"chrome", "msedge", "bundled-chromium"})
DEFAULT_REQUEST_TIMEOUT_SECONDS = 30
DEFAULT_AUTH_TIMEOUT_SECONDS = 900
DEFAULT_BATCH_TIMEOUT_SECONDS = 1_800
STORAGE_STATE_FILENAME = "playwright-storage-state.json"


@dataclass(frozen=True, slots=True)
class NetFacilitiesConfig:
    """Validated local capability settings with no browser side effects."""

    enabled: bool
    profile_dir: Path | None
    browser_channel: str
    request_timeout_seconds: int
    auth_timeout_seconds: int
    batch_timeout_seconds: int

    @property
    def playwright_channel(self) -> str | None:
        """Translate the operator-facing bundled-browser name for Playwright."""

        return None if self.browser_channel == "bundled-chromium" else self.browser_channel

    @property
    def request_timeout_ms(self) -> int:
        return self.request_timeout_seconds * 1_000

    @property
    def storage_state_path(self) -> Path | None:
        """Protected saved-login state, without importing Playwright."""

        if self.profile_dir is None:
            return None
        return self.profile_dir / STORAGE_STATE_FILENAME

    @property
    def has_saved_authentication(self) -> bool:
        """Whether an in-app or CLI manual sign-in has saved browser state."""

        path = self.storage_state_path
        return path is not None and path.is_file()


def load_netfacilities_config(
    environ: Mapping[str, str] | None = None,
    *,
    platform: str | None = None,
    repository_root: Path = REPOSITORY_ROOT,
) -> NetFacilitiesConfig:
    """Read configuration without importing or starting the browser runtime.

    Missing or explicit ``false`` keeps the capability disabled and ignores all
    local-only settings.  An attempted enablement is strict: malformed or unsafe
    configuration becomes one secret-safe ``unavailable`` failure.
    """

    values = os.environ if environ is None else environ
    enabled = _enabled(values.get("NETFACILITIES_ENABLED"))
    if not enabled:
        return NetFacilitiesConfig(
            enabled=False,
            profile_dir=None,
            browser_channel=DEFAULT_BROWSER_CHANNEL,
            request_timeout_seconds=DEFAULT_REQUEST_TIMEOUT_SECONDS,
            auth_timeout_seconds=DEFAULT_AUTH_TIMEOUT_SECONDS,
            batch_timeout_seconds=DEFAULT_BATCH_TIMEOUT_SECONDS,
        )

    current_platform = sys.platform if platform is None else platform
    if current_platform != "win32":
        raise NetFacilitiesUnavailable(
            "NetFacilities enrichment is available only on the configured local Windows host."
        )

    profile_dir = _profile_dir(
        values.get("NETFACILITIES_PROFILE_DIR"),
        repository_root=repository_root,
    )
    browser_channel = values.get(
        "NETFACILITIES_BROWSER_CHANNEL",
        DEFAULT_BROWSER_CHANNEL,
    ).strip().lower()
    if browser_channel not in ALLOWED_BROWSER_CHANNELS:
        raise NetFacilitiesUnavailable(
            "NETFACILITIES_BROWSER_CHANNEL must select an approved browser channel."
        )

    return NetFacilitiesConfig(
        enabled=True,
        profile_dir=profile_dir,
        browser_channel=browser_channel,
        request_timeout_seconds=_positive_seconds(
            values,
            "NETFACILITIES_REQUEST_TIMEOUT_SECONDS",
            DEFAULT_REQUEST_TIMEOUT_SECONDS,
        ),
        auth_timeout_seconds=_positive_seconds(
            values,
            "NETFACILITIES_AUTH_TIMEOUT_SECONDS",
            DEFAULT_AUTH_TIMEOUT_SECONDS,
        ),
        batch_timeout_seconds=_positive_seconds(
            values,
            "NETFACILITIES_BATCH_TIMEOUT_SECONDS",
            DEFAULT_BATCH_TIMEOUT_SECONDS,
        ),
    )


def _enabled(raw: str | None) -> bool:
    if raw is None or not raw.strip():
        return False
    normalized = raw.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise NetFacilitiesUnavailable(
        "NETFACILITIES_ENABLED must be either true or false."
    )


def _profile_dir(raw: str | None, *, repository_root: Path) -> Path:
    if raw is None or not raw.strip():
        raise NetFacilitiesUnavailable(
            "NETFACILITIES_PROFILE_DIR is required when NetFacilities is enabled."
        )
    expanded = Path(raw.strip()).expanduser()
    if not expanded.is_absolute():
        raise NetFacilitiesUnavailable(
            "NETFACILITIES_PROFILE_DIR must be an absolute path outside the repository."
        )

    path = expanded.resolve(strict=False)
    root = repository_root.resolve(strict=False)
    try:
        path.relative_to(root)
    except ValueError:
        pass
    else:
        raise NetFacilitiesUnavailable(
            "NETFACILITIES_PROFILE_DIR must be outside the repository."
        )
    if path.exists() and not path.is_dir():
        raise NetFacilitiesUnavailable(
            "NETFACILITIES_PROFILE_DIR must refer to a directory."
        )
    return path


def _positive_seconds(
    values: Mapping[str, str],
    name: str,
    default: int,
) -> int:
    raw = values.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        seconds = int(raw)
    except ValueError as exc:
        raise NetFacilitiesUnavailable(f"{name} must be a positive whole number.") from exc
    if seconds <= 0:
        raise NetFacilitiesUnavailable(f"{name} must be a positive whole number.")
    return seconds
