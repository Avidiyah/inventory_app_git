"""Fail-closed configuration for local and hosted NetFacilities enrichment."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os
from pathlib import Path
import sys

from .errors import NetFacilitiesUnavailable


def _repository_root(module_file: Path) -> Path:
    """Locate the protected source tree in a checkout or production image."""

    application_root = module_file.resolve(strict=False).parents[3]
    if application_root.name == "backend":
        return application_root.parent
    return application_root


REPOSITORY_ROOT = _repository_root(Path(__file__))
DEFAULT_BROWSER_CHANNEL = "chrome"
ALLOWED_BROWSER_CHANNELS = frozenset({"chrome", "msedge", "bundled-chromium"})
DEFAULT_REQUEST_TIMEOUT_SECONDS = 30
DEFAULT_AUTH_TIMEOUT_SECONDS = 900
DEFAULT_BATCH_TIMEOUT_SECONDS = 1_800
DEFAULT_RENDER_SETTLE_SECONDS = 5
DEFAULT_SESSION_TIMEOUT_SECONDS = 7_200
DOWNLOADS_FALLBACK_DIRNAME = "downloads"
STORAGE_STATE_FILENAME = "playwright-storage-state.json"


@dataclass(frozen=True, slots=True)
class NetFacilitiesConfig:
    """Validated capability settings with no browser or network side effects."""

    enabled: bool
    profile_dir: Path | None
    browser_channel: str
    request_timeout_seconds: int
    auth_timeout_seconds: int
    batch_timeout_seconds: int
    storage_state_file: Path | None = None
    interactive_authentication_available: bool = True
    render_document: bool = False
    render_settle_seconds: int = DEFAULT_RENDER_SETTLE_SECONDS
    # Idle limit for a signed-in live window (spec D1). Pending sign-in keeps
    # using auth_timeout_seconds.
    session_timeout_seconds: int = DEFAULT_SESSION_TIMEOUT_SECONDS
    # Where a download the operator triggers in the live window is saved (spec
    # D3). None when disabled or hosted: Linux never opens a window.
    download_dir: Path | None = None

    @property
    def render_settle_ms(self) -> int:
        """How long a rendered document may settle before it is serialized."""

        return self.render_settle_seconds * 1_000

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

        if self.storage_state_file is not None:
            return self.storage_state_file
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
    integration settings. An attempted enablement is strict: malformed or unsafe
    configuration becomes one secret-safe ``unavailable`` failure. Windows uses a
    dedicated interactive profile; Linux/Render uses a separately provisioned saved
    authentication file and never attempts headed sign-in.
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
            interactive_authentication_available=False,
        )

    current_platform = sys.platform if platform is None else platform
    if current_platform == "win32":
        profile_dir = _profile_dir(
            values.get("NETFACILITIES_PROFILE_DIR"),
            repository_root=repository_root,
        )
        storage_state_file = None
        interactive_authentication_available = True
        download_dir: Path | None = _download_dir(
            values.get("NETFACILITIES_DOWNLOAD_DIR"),
            profile_dir=profile_dir,
            repository_root=repository_root,
        )
    elif current_platform == "linux":
        profile_dir = None
        storage_state_file = _storage_state_file(
            values.get("NETFACILITIES_STORAGE_STATE_PATH"),
            repository_root=repository_root,
        )
        interactive_authentication_available = False
        download_dir = None
    else:
        raise NetFacilitiesUnavailable(
            "NetFacilities enrichment is supported only on Windows or Linux hosts."
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
        storage_state_file=storage_state_file,
        interactive_authentication_available=interactive_authentication_available,
        # Priority is server-rendered, so the primed raw response already carries it
        # and the batch needs no JavaScript. Rendering stays available behind this
        # flag for diagnosis, but costs a settle wait on every row when enabled.
        render_document=_flag(
            values.get("NETFACILITIES_RENDER_DOCUMENT"),
            name="NETFACILITIES_RENDER_DOCUMENT",
            default=False,
        ),
        render_settle_seconds=_positive_seconds(
            values,
            "NETFACILITIES_RENDER_SETTLE_SECONDS",
            DEFAULT_RENDER_SETTLE_SECONDS,
        ),
        session_timeout_seconds=_positive_seconds(
            values,
            "NETFACILITIES_SESSION_TIMEOUT_SECONDS",
            DEFAULT_SESSION_TIMEOUT_SECONDS,
        ),
        download_dir=download_dir,
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


def _flag(raw: str | None, *, name: str, default: bool) -> bool:
    """Parse an optional strict boolean, keeping unset values at the safe default."""

    if raw is None or not raw.strip():
        return default
    normalized = raw.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise NetFacilitiesUnavailable(f"{name} must be either true or false.")


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


def _download_dir(
    raw: str | None,
    *,
    profile_dir: Path,
    repository_root: Path,
) -> Path:
    """Resolve where the live window's downloads are saved.

    Unset picks the operator's own Downloads folder when it exists, because that
    is where they will look for the CSV they just exported; otherwise a folder
    inside the protected profile. An explicit value obeys the same three checks
    as NETFACILITIES_PROFILE_DIR: absolute, outside the repository, a directory.
    """

    if raw is None or not raw.strip():
        home_downloads = Path.home() / "Downloads"
        if home_downloads.is_dir():
            return home_downloads.resolve(strict=False)
        return profile_dir / DOWNLOADS_FALLBACK_DIRNAME
    expanded = Path(raw.strip()).expanduser()
    if not expanded.is_absolute():
        raise NetFacilitiesUnavailable(
            "NETFACILITIES_DOWNLOAD_DIR must be an absolute path outside the repository."
        )

    path = expanded.resolve(strict=False)
    root = repository_root.resolve(strict=False)
    try:
        path.relative_to(root)
    except ValueError:
        pass
    else:
        raise NetFacilitiesUnavailable(
            "NETFACILITIES_DOWNLOAD_DIR must be outside the repository."
        )
    if path.exists() and not path.is_dir():
        raise NetFacilitiesUnavailable(
            "NETFACILITIES_DOWNLOAD_DIR must refer to a directory."
        )
    return path


def _storage_state_file(raw: str | None, *, repository_root: Path) -> Path:
    if raw is None or not raw.strip():
        raise NetFacilitiesUnavailable(
            "NETFACILITIES_STORAGE_STATE_PATH is required on Linux when "
            "NetFacilities is enabled."
        )
    expanded = Path(raw.strip()).expanduser()
    if not expanded.is_absolute():
        raise NetFacilitiesUnavailable(
            "NETFACILITIES_STORAGE_STATE_PATH must be an absolute path outside "
            "the repository."
        )

    path = expanded.resolve(strict=False)
    root = repository_root.resolve(strict=False)
    try:
        path.relative_to(root)
    except ValueError:
        pass
    else:
        raise NetFacilitiesUnavailable(
            "NETFACILITIES_STORAGE_STATE_PATH must be outside the repository."
        )
    if path.exists() and not path.is_file():
        raise NetFacilitiesUnavailable(
            "NETFACILITIES_STORAGE_STATE_PATH must refer to a file."
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
