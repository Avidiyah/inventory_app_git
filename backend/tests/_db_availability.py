"""What to do when the test database cannot be reached.

Local: skip, so the pure tests still run without Postgres.
CI: raise, because a skipped DB suite there is a false green.
"""

import os
from typing import NoReturn

import pytest


def _running_in_ci() -> bool:
    # Same idiom as SQL_ECHO in app/database.py:48 -- an explicit "true",
    # not mere presence. GitHub Actions sets CI=true on every runner.
    return os.getenv("CI", "").strip().lower() == "true"


def handle_unreachable_database(exc: Exception) -> NoReturn:
    if _running_in_ci():
        raise RuntimeError(
            f"Database unreachable in CI: {exc}\n"
            "CI must run the full suite against a real Postgres. Skipping "
            "here would report success over the pure tests while the 244 "
            "db-fixture tests silently vanished. Check the postgres service "
            "container and DATABASE_URL in .github/workflows/ci.yml."
        ) from exc

    pytest.skip(f"database unreachable: {exc}")
