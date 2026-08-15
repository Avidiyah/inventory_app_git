"""Dependency-free validation shared by the parser, client, and app service."""

from __future__ import annotations

import re

from .errors import NetFacilitiesInvalidWorkOrderNumber


WORK_ORDER_NUMBER_RE = re.compile(r"^[1-9][0-9]{0,19}$")


def validate_work_order_number(value: str) -> str:
    """Normalize a numeric work-order number before it reaches a source URL."""

    normalized = value.strip()
    if not WORK_ORDER_NUMBER_RE.fullmatch(normalized):
        raise NetFacilitiesInvalidWorkOrderNumber(
            "Work-order number must contain 1-20 digits and cannot start with zero."
        )
    return normalized
