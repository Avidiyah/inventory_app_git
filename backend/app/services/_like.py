"""Escaped substring pattern for `Column.like(pattern, escape=...)`.

Shared by the history and work-order search filters so a `%` or `_` typed by
a user matches itself rather than acting as a LIKE wildcard.
"""

from typing import Optional

# Backslash is the LIKE escape character passed to SQLAlchemy. Escape the
# escape char first, then the two LIKE wildcards.
LIKE_ESCAPE = "\\"


def like_pattern(value: Optional[str]) -> Optional[tuple[str, str]]:
    """`("%<escaped value>%", LIKE_ESCAPE)` for a case-sensitive substring
    match, or `None` when `value` is None, empty, or whitespace-only (no
    filter should be applied at all)."""
    if value is None:
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    escaped = (
        trimmed.replace(LIKE_ESCAPE, LIKE_ESCAPE * 2)
        .replace("%", LIKE_ESCAPE + "%")
        .replace("_", LIKE_ESCAPE + "_")
    )
    return f"%{escaped}%", LIKE_ESCAPE
