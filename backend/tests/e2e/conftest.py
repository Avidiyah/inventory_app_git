"""Fixtures for the real-browser suite.

The server runs in a THREAD, not a subprocess: no fork assumptions, so this
behaves identically on Windows and on the Linux runner, and a traceback from
app code lands in the pytest output instead of a lost stdout pipe.
"""

import os
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
import uvicorn
from sqlalchemy.orm import Session

from app.database import engine
from app.main import app
from tests.e2e import _seed
from tests.e2e._availability import require_e2e_environment

# Console messages that are expected and carry no signal. Keep this list
# SHORT and give every entry a reason -- it is the only thing standing
# between a real CSP violation and a green run.
EXPECTED_CONSOLE_ERRORS = (
    # No favicon is served; Chromium reports the 404 on every page load.
    "favicon.ico",
    # The shell probes for an existing session before the login form is even
    # shown. A fresh browser has no cookie, so the 401 is the expected answer.
    # Matched on the URL, not on "401", so a 401 anywhere else still fails.
    "/auth/me",
)


def is_expected_console_error(text: str) -> bool:
    return any(fragment in text for fragment in EXPECTED_CONSOLE_ERRORS)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="session")
def base_url():
    require_e2e_environment()
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.monotonic() + 30
    while not server.started:
        if time.monotonic() > deadline:
            server.should_exit = True
            raise RuntimeError("uvicorn did not start within 30s")
        time.sleep(0.05)

    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


@pytest.fixture(scope="session")
def seeded(base_url):
    """Session-scoped and COMMITTED. A browser is a separate connection, so
    the transaction-rollback pattern in tests/conftest.py cannot reach it."""
    session = Session(bind=engine)
    try:
        _seed.sweep_debris(session)
        seed = _seed.build(session)
    except Exception:
        session.close()
        raise

    try:
        yield seed
    finally:
        try:
            _seed.destroy(session, seed)
        finally:
            session.close()


@pytest.fixture
def console_errors(page):
    """Every console error and uncaught exception the page produced.

    This is the assertion that makes CSP violations visible: Chromium reports
    a blocked inline style as a console error, and jsdom cannot report one at
    all -- which is the entire reason this layer exists.
    """
    collected = []

    def _on_console(message):
        if message.type != "error":
            return
        # Chromium's text for a failed request names the status but not the
        # URL ("Failed to load resource: ... 401"). Without the URL the
        # allowlist could only match on the status, which would hide every
        # other 401 on the site.
        url = (message.location or {}).get("url") or ""
        collected.append(f"{message.text} [{url}]" if url else message.text)

    page.on("console", _on_console)
    page.on("pageerror", lambda error: collected.append(str(error)))
    yield collected
    unexpected = [text for text in collected if not is_expected_console_error(text)]
    assert not unexpected, "browser console errors:\n" + "\n".join(unexpected)


@pytest.fixture
def login_as(page, base_url):
    def _login(username: str):
        page.goto(base_url)
        page.fill("#login-username", username)
        page.fill("#login-password", _seed.SEED_PASSWORD)
        page.click("#login-btn")
        page.wait_for_selector("#login-screen", state="hidden", timeout=15000)
        return page

    return _login


@pytest.fixture
def owner_page(login_as, console_errors, seeded):
    return login_as(seeded.owner_username)
