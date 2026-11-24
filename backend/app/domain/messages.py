"""Pure rules for live messaging (spec
docs/superpowers/specs/2026-11-24-live-messaging-design.md).

No database, no clock: callers pass `now`. The service layer
(`services/messages.py`) owns every query; this module owns the numbers and
the text rules both it and the tests read.
"""

from collections.abc import Iterable
from datetime import datetime, timedelta

from app.domain import roles
from app.domain.errors import InvalidMessageError

MAX_BODY = 2000
MAX_GROUP_NAME = 60
MAX_GROUP_MEMBERS = 30
MIN_GROUP_OTHERS = 2
DIRECT_RETENTION_DAYS = 90
GROUP_QUIET_DAYS = 7
SEARCH_MIN_CHARS = 2
SEARCH_MAX_ROWS = 30
PAGE_SIZE = 50

KIND_DIRECT = "direct"
KIND_GROUP = "group"


def can_start_group(role: str) -> bool:
    """Team Lead (stored `supervisor`) and above may start a group."""
    return roles.role_at_least(role, roles.ROLE_SUPERVISOR)


def can_broadcast(role: str) -> bool:
    """Admin and Owner may send one message to many people as separate direct chats."""
    return roles.role_at_least(role, roles.ROLE_ADMIN)


def direct_key(a, b) -> str:
    """Order-free key for the one direct chat between two users."""
    low, high = sorted((str(a), str(b)))
    return f"{low}:{high}"


def _clean(text, limit: int, what: str) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        raise InvalidMessageError(f"{what} cannot be empty.")
    if len(cleaned) > limit:
        raise InvalidMessageError(f"{what} is longer than {limit} characters.")
    return cleaned


def clean_body(text) -> str:
    return _clean(text, MAX_BODY, "Message")


def clean_group_name(text) -> str:
    return _clean(text, MAX_GROUP_NAME, "Group name")


def unread_people(sender_ids: Iterable) -> int:
    """How many distinct people have unread messages waiting (the badge)."""
    return len({str(s) for s in sender_ids})


def direct_cutoff(now: datetime) -> datetime:
    """Direct messages created before this are swept."""
    return now - timedelta(days=DIRECT_RETENTION_DAYS)


def group_cutoff(now: datetime) -> datetime:
    """A group quiet since before this is swept, messages and all."""
    return now - timedelta(days=GROUP_QUIET_DAYS)
