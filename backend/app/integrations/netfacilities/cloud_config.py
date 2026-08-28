"""Fail-closed configuration for the per-user NetFacilities cloud-auth path.

Additive to `app.integrations.netfacilities.config` (spec §2): this feature
requires a paid third-party account and a database encryption key, so it
must default fully off, independently of the existing `NETFACILITIES_ENABLED`
capability. Safe to call even when the base capability is disabled -- it
always reports `enabled=False` in that case, never raises.

The encryption-key check validates the Fernet key's shape directly (rather
than delegating to `netfacilities_cloud_crypto.is_configured()`, which reads
the real `os.environ`) so this function never has a side effect on process
environment state -- important because callers pass a synthetic `environ`
mapping in tests.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os

from cryptography.fernet import Fernet

from .config import NetFacilitiesConfig
from .errors import NetFacilitiesUnavailable

# Steel's session cap is 15 minutes (spec §1, §4); both defaults leave margin
# for the ceremony/job to notice expiry and close cleanly rather than being
# cut off mid-request.
DEFAULT_LOGIN_TIMEOUT_SECONDS = 840
DEFAULT_BATCH_SESSION_SECONDS = 840


@dataclass(frozen=True, slots=True)
class NetFacilitiesCloudConfig:
    """Validated cloud-auth capability settings with no network side effects."""

    enabled: bool
    steel_api_key: str | None = None
    login_timeout_seconds: int = DEFAULT_LOGIN_TIMEOUT_SECONDS
    batch_session_seconds: int = DEFAULT_BATCH_SESSION_SECONDS


def load_netfacilities_cloud_config(
    base: NetFacilitiesConfig,
    environ: Mapping[str, str] | None = None,
) -> NetFacilitiesCloudConfig:
    """Read cloud-auth configuration. Disabled unless every prerequisite holds:
    the base capability, the feature flag, a Steel API key, and a working
    encryption key (spec D9)."""

    values = os.environ if environ is None else environ
    if not base.enabled:
        return NetFacilitiesCloudConfig(enabled=False)
    if not _enabled(values.get("NETFACILITIES_CLOUD_AUTH_ENABLED")):
        return NetFacilitiesCloudConfig(enabled=False)

    api_key = values.get("STEEL_API_KEY", "").strip()
    if not api_key:
        return NetFacilitiesCloudConfig(enabled=False)

    encryption_key = values.get("NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY", "").strip()
    if not encryption_key:
        return NetFacilitiesCloudConfig(enabled=False)
    try:
        Fernet(encryption_key.encode("ascii"))
    except ValueError:
        return NetFacilitiesCloudConfig(enabled=False)

    return NetFacilitiesCloudConfig(
        enabled=True,
        steel_api_key=api_key,
        login_timeout_seconds=_positive_seconds(
            values,
            "NETFACILITIES_CLOUD_LOGIN_TIMEOUT_SECONDS",
            DEFAULT_LOGIN_TIMEOUT_SECONDS,
        ),
        batch_session_seconds=_positive_seconds(
            values,
            "NETFACILITIES_CLOUD_BATCH_SESSION_SECONDS",
            DEFAULT_BATCH_SESSION_SECONDS,
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
        "NETFACILITIES_CLOUD_AUTH_ENABLED must be either true or false."
    )


def _positive_seconds(values: Mapping[str, str], name: str, default: int) -> int:
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
