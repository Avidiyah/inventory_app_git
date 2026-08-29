"""Fail-closed configuration for NetFacilities enrichment."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os

from .errors import NetFacilitiesUnavailable

DEFAULT_REQUEST_TIMEOUT_SECONDS = 30
DEFAULT_BATCH_TIMEOUT_SECONDS = 1_800
DEFAULT_RENDER_SETTLE_SECONDS = 5


@dataclass(frozen=True, slots=True)
class NetFacilitiesConfig:
    """Validated capability settings with no browser or network side effects."""

    enabled: bool
    request_timeout_seconds: int
    batch_timeout_seconds: int
    render_document: bool = False
    render_settle_seconds: int = DEFAULT_RENDER_SETTLE_SECONDS

    @property
    def render_settle_ms(self) -> int:
        """How long a rendered document may settle before it is serialized."""

        return self.render_settle_seconds * 1_000

    @property
    def request_timeout_ms(self) -> int:
        return self.request_timeout_seconds * 1_000


def load_netfacilities_config(
    environ: Mapping[str, str] | None = None,
) -> NetFacilitiesConfig:
    """Read configuration without importing or starting the browser runtime.

    Missing or explicit ``false`` keeps the capability disabled and ignores all
    integration settings. An attempted enablement is strict: malformed
    configuration becomes one secret-safe ``unavailable`` failure.
    """

    values = os.environ if environ is None else environ
    enabled = _enabled(values.get("NETFACILITIES_ENABLED"))
    if not enabled:
        return NetFacilitiesConfig(
            enabled=False,
            request_timeout_seconds=DEFAULT_REQUEST_TIMEOUT_SECONDS,
            batch_timeout_seconds=DEFAULT_BATCH_TIMEOUT_SECONDS,
        )

    return NetFacilitiesConfig(
        enabled=True,
        request_timeout_seconds=_positive_seconds(
            values,
            "NETFACILITIES_REQUEST_TIMEOUT_SECONDS",
            DEFAULT_REQUEST_TIMEOUT_SECONDS,
        ),
        batch_timeout_seconds=_positive_seconds(
            values,
            "NETFACILITIES_BATCH_TIMEOUT_SECONDS",
            DEFAULT_BATCH_TIMEOUT_SECONDS,
        ),
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
