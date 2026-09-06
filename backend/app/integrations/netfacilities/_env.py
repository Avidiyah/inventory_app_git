"""Strict environment-value parsers shared by the NetFacilities config modules.

Both `config.py` (base capability) and `cloud_config.py` (per-user cloud auth)
fail closed on malformed values; the rules live here once so the two cannot
drift.
"""

from __future__ import annotations

from collections.abc import Mapping

from .errors import NetFacilitiesUnavailable


def strict_bool(raw: str | None, *, name: str, default: bool = False) -> bool:
    """`true`/`false` (case-insensitive, trimmed); unset or blank -> `default`."""

    if raw is None or not raw.strip():
        return default
    normalized = raw.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise NetFacilitiesUnavailable(f"{name} must be either true or false.")


def positive_seconds(values: Mapping[str, str], name: str, default: int) -> int:
    """A positive whole number of seconds from `values[name]`, else `default`."""

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
