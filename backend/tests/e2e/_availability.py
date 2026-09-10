"""What to do when the E2E prerequisites are missing.

Same rule as `tests/_db_availability.py`: skip locally so a contributor
without Postgres or a built Chromium still gets the rest of the suite;
raise under CI, where a skipped E2E suite is a false green over the one
layer that can see CSP violations.
"""

import os
from typing import NoReturn

import pytest
from playwright.sync_api import sync_playwright
from sqlalchemy.exc import OperationalError

from app.database import engine


def _running_in_ci() -> bool:
    # Same idiom as tests/_db_availability.py: an explicit "true", not mere
    # presence. GitHub Actions sets CI=true on every runner.
    return os.getenv("CI", "").strip().lower() == "true"


def unavailable(reason: str) -> NoReturn:
    if _running_in_ci():
        raise RuntimeError(
            f"E2E prerequisite missing in CI: {reason}\n"
            "The e2e job must run the browser suite for real. Check the "
            "postgres service, DATABASE_URL, and the `playwright install "
            "--with-deps chromium` step in .github/workflows/ci.yml."
        )
    pytest.skip(f"e2e unavailable: {reason}")


def require_e2e_environment() -> None:
    """Skip or raise unless a database and a built Chromium are both here."""
    try:
        engine.connect().close()
    except OperationalError as exc:  # pragma: no cover - environment-dependent
        unavailable(f"database unreachable: {exc}")

    try:
        with sync_playwright() as play:
            browser = play.chromium.launch()
            browser.close()
    except Exception as exc:  # pragma: no cover - environment-dependent
        unavailable(
            f"chromium is not installed or failed to launch: {exc}. "
            "Run `python -m playwright install chromium` from backend/."
        )
