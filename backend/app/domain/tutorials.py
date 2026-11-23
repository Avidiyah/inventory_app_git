"""Tutorial progress rules (0b spec 5.1, 5.2). Pure; no database, no FastAPI."""

import re

from app.domain.errors import InvalidTutorialKeyError

KEY_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{0,79}$")
MAX_ROWS_PER_USER = 500


def validate_key(key: str) -> str:
    """Return `key` if it is a legal script key, else raise."""
    if not KEY_RE.fullmatch(key):
        raise InvalidTutorialKeyError("Invalid tutorial key.")
    return key
