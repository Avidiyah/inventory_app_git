# Frontend Test Harness — P3 (E2E Smoke Layer) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A thin real-browser layer over the real app and a real database, catching what jsdom structurally cannot — CSP violations, the service worker, real fetch, real rendering.

**Architecture:** A new `backend/tests/e2e/` package driven by pytest-playwright. A session-scoped uvicorn server runs the real app in a background thread on a free port; a session-scoped fixture seeds committed data through existing service functions and deletes it by tracked id afterwards. Tests navigate as a logged-in owner and assert both DOM landmarks and an empty browser console. A new `e2e` pytest marker, deselected by default, keeps the existing backend suite and CI job untouched.

**Tech Stack:** pytest, pytest-playwright, Playwright Chromium, uvicorn, SQLAlchemy, FastAPI.

**Spec:** `docs/superpowers/specs/2026-09-10-frontend-test-harness-design.md`
**Roadmap:** `docs/superpowers/plans/2026-09-10-frontend-test-harness-roadmap.md` (P3)
**Depends on:** P0 (merged). Not on P1 or P2 — this layer shares no code with the Vitest suite. P2 is planned but unimplemented; both must land before P4, in either order.

## Global Constraints

- **Tests and CI only.** No changes to any file under `backend/app/` or `backend/static/`. If a test cannot be written without changing production code, stop and raise it.
- **The dev database is the target.** Decided deliberately: E2E runs against `DATABASE_URL` (locally the dev Postgres on port 8801). Seeded rows commit and are visible in the running app until teardown. Every safeguard in Task 3 exists because of this.
- **Every seeded record carries the run prefix** `E2E-<8 hex>` in its username / barcode / work-order number. No seeded row is created without it.
- **Skip locally, fail in CI.** Unreachable database or missing Chromium skips the suite locally and raises under `CI=true` — the same rule and the same reasoning as `backend/tests/_db_availability.py`.
- **`playwright==1.62.0` is pinned in `backend/requirements.txt` and stays there.** It is a runtime dependency (NetFacilities cloud auth). Installing `pytest-playwright` must not move it.
- **Runtime budget: under ~3 minutes in CI.** If exceeded, cut journeys from `test_work_orders.py` — never entries from the smoke table.
- Commit messages end with `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.

## File Structure

| File | Responsibility |
| --- | --- |
| `backend/pytest.ini` (create) | Registers the `e2e` marker and deselects it by default |
| `backend/requirements-dev.txt` (modify) | Adds `pytest-playwright` |
| `backend/tests/e2e/__init__.py` (create) | Package marker |
| `backend/tests/e2e/_availability.py` (create) | Skip-local / raise-in-CI guard for DB and browser |
| `backend/tests/e2e/_seed.py` (create) | Seed construction and teardown, isolated from fixture plumbing |
| `backend/tests/e2e/conftest.py` (create) | Live server, seed, login and console-guard fixtures |
| `backend/tests/e2e/test_availability.py` (create) | Unit tests for the guard and the seed contract — run without a browser |
| `backend/tests/e2e/test_smoke.py` (create) | Every `SHELL_PARTS` page renders with a clean console |
| `backend/tests/e2e/test_work_orders.py` (create) | Two work-order journeys |
| `.github/workflows/ci.yml` (modify) | New `e2e` job; added to `deploy`'s `needs` |
| `docs/current-state.md`, `docs/open-work.md` (modify) | Record the layer |

---

### Task 1: Marker, dependency and package skeleton

**Files:**
- Create: `backend/pytest.ini`, `backend/tests/e2e/__init__.py`
- Modify: `backend/requirements-dev.txt`

**Interfaces:**
- Produces: the `e2e` marker, deselected by default. Every later test module declares `pytestmark = pytest.mark.e2e`.

- [ ] **Step 1: Create `backend/pytest.ini`**

```ini
[pytest]
# E2E is opt-in. `pytest` and the `backend` CI job stay exactly as they were:
# fast, no browser, no committed rows in anyone's dev database. The `e2e` job
# passes `-m e2e` on the command line, and pytest honours the last -m it sees.
addopts = -m "not e2e"
markers =
    e2e: real-browser test; needs Postgres, a built Chromium, and commits data
```

- [ ] **Step 2: Confirm the default suite is unchanged**

Run: `cd backend && python -m pytest -q`
Expected: the same pass/skip counts as before this task. A deselection message means the marker expression is wrong.

- [ ] **Step 3: Add the dependency**

Append to `backend/requirements-dev.txt`:

```
# Playwright's pytest plugin. `playwright` itself is a RUNTIME pin in
# requirements.txt (1.62.0, NetFacilities cloud auth); this must not move it.
# Step 4 asserts that it did not.
pytest-playwright==0.7.2
```

- [ ] **Step 4: Install and assert the runtime pin held**

Run:
```bash
cd backend && python -m pip install -r requirements-dev.txt
python -c "import playwright; print(playwright.__version__)"
```
Expected: `1.62.0`. If pip resolved a different version, or refused with a conflict, pick the highest `pytest-playwright` whose dependency range admits 1.62.0 and update the pin and this step. Do not relax the runtime pin.

- [ ] **Step 5: Install the browser**

Run: `cd backend && python -m playwright install chromium`
Expected: Chromium downloads, or reports it is already present. On Windows this is the one manual prerequisite for running E2E locally.

- [ ] **Step 6: Create the package marker**

`backend/tests/e2e/__init__.py`:

```python
"""Real-browser end-to-end tests. Opt in with `pytest -m e2e`."""
```

- [ ] **Step 7: Commit**

```bash
git add backend/pytest.ini backend/requirements-dev.txt backend/tests/e2e/__init__.py
git commit -m "add an opt-in e2e marker and the playwright pytest plugin"
```

---

### Task 2: Availability guard

**Files:**
- Create: `backend/tests/e2e/_availability.py`
- Test: `backend/tests/e2e/test_availability.py`

**Interfaces:**
- Produces: `unavailable(reason: str) -> NoReturn` and `require_e2e_environment() -> None`. The latter is called once, by the session-scoped server fixture in Task 4.

- [ ] **Step 1: Write the failing tests**

`backend/tests/e2e/test_availability.py`:

```python
"""Unit tests for the E2E guard. Deliberately NOT marked `e2e`: they run in
the ordinary backend job, which is what keeps the guard covered even though
the suite it protects is deselected there."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest

from tests.e2e import _availability


def test_missing_browser_skips_outside_ci(monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    with pytest.raises(Exception) as caught:
        _availability.unavailable("chromium is not installed")
    assert caught.typename == "Skipped"


def test_missing_browser_is_an_error_in_ci(monkeypatch):
    monkeypatch.setenv("CI", "true")
    with pytest.raises(RuntimeError, match="chromium is not installed"):
        _availability.unavailable("chromium is not installed")
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/e2e/test_availability.py -v`
Expected: FAIL — `ModuleNotFoundError: tests.e2e._availability`.

- [ ] **Step 3: Implement the guard**

`backend/tests/e2e/_availability.py`:

```python
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
```

- [ ] **Step 4: Run to verify the tests pass**

Run: `cd backend && python -m pytest tests/e2e/test_availability.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/e2e/_availability.py backend/tests/e2e/test_availability.py
git commit -m "skip e2e without postgres or chromium, and fail loudly in ci"
```

---

### Task 3: Seed data with a run prefix, tracked teardown and a debris sweep

**Files:**
- Create: `backend/tests/e2e/_seed.py`
- Modify: `backend/tests/e2e/test_availability.py`

**Interfaces:**
- Produces:
  - `RUN_PREFIX: str` — `f"E2E-{uuid.uuid4().hex[:8]}"`, evaluated once at import.
  - `SEED_PASSWORD: str` — the plaintext every seeded user shares.
  - `Seed` — dataclass with `prefix`, `owner_username`, `work_order_number`, `item_barcode`, all `str`.
  - `sweep_debris(db: Session) -> int` — deletes rows left by crashed earlier runs (any `E2E-` prefix); returns the row count removed.
  - `build(db: Session) -> Seed`
  - `destroy(db: Session, seed: Seed) -> None`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/e2e/test_availability.py`:

```python
def test_seed_names_all_carry_the_run_prefix():
    """Teardown finds rows by prefix. A record without one is a row that
    survives the run inside a real dev database."""
    from tests.e2e import _seed

    seed = _seed.Seed(
        prefix="E2E-abcd1234",
        owner_username="E2E-abcd1234-owner",
        work_order_number="E2E-abcd1234-WO",
        item_barcode="E2E-abcd1234-ITEM",
    )
    for value in (seed.owner_username, seed.work_order_number, seed.item_barcode):
        assert value.startswith(seed.prefix)
    assert _seed.RUN_PREFIX.startswith("E2E-")
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/e2e/test_availability.py -v`
Expected: FAIL — `ModuleNotFoundError: tests.e2e._seed`.

- [ ] **Step 3: Implement the seed module**

`backend/tests/e2e/_seed.py`:

```python
"""Committed seed data for the E2E suite, and its removal.

These rows go into the database `DATABASE_URL` points at -- locally the
developer's own dev Postgres, by decision. They are therefore visible in the
running app for the length of a session. Three safeguards make that
acceptable:

1. Every record carries `RUN_PREFIX` in the column a human reads.
2. Teardown deletes by prefix, children before parents.
3. `sweep_debris` removes anything a crashed earlier run left behind, before
   a new one starts, so debris cannot accumulate.
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Item, LaborSession, User, WorkOrder
from app.services import auth as auth_service
from app.services import items as items_service
from app.services import work_orders as wo_service

RUN_PREFIX = f"E2E-{uuid.uuid4().hex[:8]}"
SEED_PASSWORD = "e2e-password-1"


@dataclass
class Seed:
    prefix: str
    owner_username: str
    work_order_number: str
    item_barcode: str


def _purge(db: Session, pattern: str) -> int:
    """Delete every row whose human-readable column matches `pattern`.
    Labor sessions first: they carry the FK to work orders."""
    work_order_ids = db.scalars(
        select(WorkOrder.id).where(WorkOrder.number.like(pattern))
    ).all()
    removed = 0
    if work_order_ids:
        removed += (
            db.execute(
                delete(LaborSession).where(
                    LaborSession.work_order_id.in_(work_order_ids)
                )
            ).rowcount
            or 0
        )
        removed += (
            db.execute(delete(WorkOrder).where(WorkOrder.id.in_(work_order_ids))).rowcount
            or 0
        )
    removed += db.execute(delete(Item).where(Item.barcode.like(pattern))).rowcount or 0
    removed += db.execute(delete(User).where(User.username.like(pattern))).rowcount or 0
    db.commit()
    return removed


def sweep_debris(db: Session) -> int:
    """Remove what any earlier E2E run left behind."""
    return _purge(db, "E2E-%")


def build(db: Session) -> Seed:
    """Create one owner, one item and one `created` work order."""
    seed = Seed(
        prefix=RUN_PREFIX,
        owner_username=f"{RUN_PREFIX}-owner",
        work_order_number=f"{RUN_PREFIX}-WO",
        item_barcode=f"{RUN_PREFIX}-ITEM",
    )

    owner = User(
        username=seed.owner_username,
        first_name="Eetoo",
        last_name="Ee",
        password_hash=auth_service.hash_password(SEED_PASSWORD),
        role="owner",
    )
    db.add(owner)
    db.commit()

    items_service.create_item(
        db,
        barcode=seed.item_barcode,
        name=f"{RUN_PREFIX} widget",
        quantity=Decimal("5"),
        location=f"{RUN_PREFIX}-shelf",
    )

    # `get_or_create_work_order` is the only path that brings a work order into
    # existence (see its docstring). With no assignee it starts `created`,
    # which is the status the Task 6 journey transitions out of.
    wo_service.get_or_create_work_order(
        db,
        number=seed.work_order_number,
        community=f"{RUN_PREFIX} community",
        description=f"{RUN_PREFIX} smoke work order",
        created_by_id=owner.id,
    )
    return seed


def destroy(db: Session, seed: Seed) -> None:
    """Remove exactly what `build` created, plus anything the run attached to
    it -- a labor session, for one: the Task 6 journey starts a clock."""
    _purge(db, f"{seed.prefix}%")
```

- [ ] **Step 4: Verify the model names against the real schema**

Run: `cd backend && python -c "from app.models import Item, LaborSession, User, WorkOrder; print('ok')"`
Expected: `ok`. If `LaborSession` carries a different class name or a different FK attribute in `app/models.py`, use the real ones here and in Task 6 — do not add an alias.

- [ ] **Step 5: Run to verify the test passes**

Run: `cd backend && python -m pytest tests/e2e/test_availability.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/tests/e2e/_seed.py backend/tests/e2e/test_availability.py
git commit -m "seed e2e data behind a run prefix with tracked teardown"
```

---

### Task 4: Live server, seed, login and console fixtures

**Files:**
- Create: `backend/tests/e2e/conftest.py`
- Test: `backend/tests/e2e/test_smoke.py` (first test only; Task 5 fills it out)

**Interfaces:**
- Consumes: `_availability.require_e2e_environment`; `_seed.build` / `destroy` / `sweep_debris` / `SEED_PASSWORD`.
- Produces:
  - `base_url` (session) — `str`, `http://127.0.0.1:<port>`, with the app running.
  - `seeded` (session) — the `Seed` dataclass.
  - `console_errors` (function) — the live `list[str]`, asserted empty at teardown.
  - `login_as` (function) — `login_as(username: str) -> Page`.
  - `owner_page` (function) — a `Page` signed in as the seeded owner, with the console guard attached.
  - `is_expected_console_error(text: str) -> bool` — the allowlist predicate.

- [ ] **Step 1: Write the failing test**

`backend/tests/e2e/test_smoke.py`:

```python
"""Every page in the shell, in a real browser, with a clean console."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest

pytestmark = pytest.mark.e2e


def test_the_shell_is_served(owner_page, seeded):
    """The whole fixture chain in one assertion: server up, database seeded,
    login succeeded, console clean."""
    assert owner_page.locator("#login-screen").is_hidden()
    assert owner_page.locator("#user-hub-page").is_visible()
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python -m pytest tests/e2e/test_smoke.py -m e2e -v`
Expected: FAIL — `fixture 'owner_page' not found`.

- [ ] **Step 3: Implement the fixtures**

`backend/tests/e2e/conftest.py`:

```python
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
        if message.type == "error":
            collected.append(message.text)

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
```

- [ ] **Step 4: Run to verify the test passes**

Run: `cd backend && python -m pytest tests/e2e/test_smoke.py -m e2e -v`
Expected: 1 passed. A failure on `#user-hub-page` means the post-login landing page differs — read `backend/static/main.js` for the page it opens and fix the assertion, not the app.

- [ ] **Step 5: Confirm the database is clean afterwards**

Run:
```bash
cd backend && python -c "
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.database import engine
from app.models import Item, User, WorkOrder
s = Session(bind=engine)
for model, column in ((User, User.username), (Item, Item.barcode), (WorkOrder, WorkOrder.number)):
    print(model.__name__, s.scalar(select(func.count()).select_from(model).where(column.like('E2E-%'))))
"
```
Expected: `0` for all three. A non-zero count means teardown is not reaching something — fix `_seed` before going further. This is the check that protects the dev database.

- [ ] **Step 6: Commit**

```bash
git add backend/tests/e2e/conftest.py backend/tests/e2e/test_smoke.py
git commit -m "run the real app in-thread for a signed-in browser session"
```

---

### Task 5: The smoke table over every shell page

**Files:**
- Modify: `backend/tests/e2e/test_smoke.py`

**Interfaces:**
- Consumes: `owner_page` from Task 4; `app.main.SHELL_PARTS`.
- Produces: nothing later tasks import.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/e2e/test_smoke.py`:

```python
from app.main import SHELL_PARTS

# One landmark per page: an element that exists only once the page's module
# has rendered, so a blank page fails rather than passing on its container.
# `integrations-import-section` ships with a `hidden` attribute and is
# unhidden for Admin+ only, so asserting it visible also proves role gating ran.
PAGE_LANDMARKS = {
    "user-hub": "#hub-tabpanel-dashboard",
    "create-item": "#create-item-section",
    "saved-items": "#items-table",
    "create-user": "#create-user-section",
    "saved-users": "#users-table",
    "transaction": "#txn-scango-section",
    "mass-stage": "#mass-stage-list-section",
    "work-orders": "#work-orders-list-section",
    "user-requests": "#user-requests-section",
    "low-stock": "#low-stock-section",
    "admin-review": "#admin-review-queue-section",
    "tools": "#tool-custody-section",
    "history": "#history-section",
    "integrations": "#integrations-import-section",
}

PAGE_NAMES = [
    part.removeprefix("pages/").removesuffix(".html")
    for part in SHELL_PARTS
    if part.startswith("pages/")
]


def test_every_shell_page_has_a_landmark():
    """A new fragment added to SHELL_PARTS joins this suite automatically.
    Without this check it would join it silently and never be visited."""
    assert sorted(PAGE_NAMES) == sorted(PAGE_LANDMARKS)


@pytest.mark.parametrize("page_name", PAGE_NAMES)
def test_page_renders_with_a_clean_console(owner_page, page_name):
    owner_page.click(f'[data-page="{page_name}"]')
    owner_page.wait_for_selector(f"#{page_name}-page", state="visible", timeout=15000)
    owner_page.wait_for_selector(PAGE_LANDMARKS[page_name], state="visible", timeout=15000)
```

- [ ] **Step 2: Run to see which pages are real**

Run: `cd backend && python -m pytest tests/e2e/test_smoke.py -m e2e -v`
Expected: some parametrised cases fail at first. Two legitimate causes, fixed differently:
- **A wrong landmark selector** — fix the entry in `PAGE_LANDMARKS`.
- **A real console error, including a CSP violation** — a genuine finding. File it in `docs/open-work.md` and add the exact fragment to `EXPECTED_CONSOLE_ERRORS` with the open-work id in the comment. Never delete the assertion.

- [ ] **Step 3: Iterate until green**

Run: `cd backend && python -m pytest tests/e2e/test_smoke.py -m e2e -v`
Expected: 16 passed — 14 pages, the landmark completeness check, and the Task 4 shell test.

- [ ] **Step 4: Check the clock**

Run: `cd backend && python -m pytest tests/e2e/test_smoke.py -m e2e --durations=5`
Expected: comfortably under 3 minutes. `owner_page` logs in once per test; if that dominates the total, note it here and revisit only if CI breaches the budget.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/e2e/test_smoke.py
git commit -m "visit every shell page in a real browser and assert a clean console"
```

---

### Task 6: Work-order journeys

**Files:**
- Create: `backend/tests/e2e/test_work_orders.py`

**Interfaces:**
- Consumes: `owner_page`, `seeded`, `base_url`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/e2e/test_work_orders.py`:

```python
"""Two journeys through the work-order surface, end to end.

Deliberately thin. Exhaustive behaviour coverage is P2's jsdom suite; what
these two add is the real network, the real service worker, the real
`history.pushState` deep link, and a real status write reaching Postgres.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest

pytestmark = pytest.mark.e2e


def test_a_deep_linked_card_renders_on_its_own(owner_page, seeded, base_url):
    owner_page.goto(f"{base_url}/workorder_card/{seeded.work_order_number}")
    owner_page.wait_for_selector("#work-orders-page", state="visible", timeout=15000)
    card = owner_page.locator(".wo-card", has_text=seeded.work_order_number)
    card.wait_for(state="visible", timeout=15000)
    assert card.locator(".wo-status-created").count() == 1


def test_beginning_work_moves_the_badge_to_in_progress(owner_page, seeded, base_url):
    owner_page.goto(f"{base_url}/workorder_card/{seeded.work_order_number}")
    card = owner_page.locator(".wo-card", has_text=seeded.work_order_number)
    card.wait_for(state="visible", timeout=15000)

    # The only status control on a `created` card for a Supervisor+ viewer.
    # The transition to in_progress is a side effect of starting the clock --
    # see the comment above `statusActions` in views/workOrders.js.
    card.locator('[data-action="start-tracking-wo"]').click()

    card.locator(".wo-status-in_progress").wait_for(state="visible", timeout=15000)
    assert card.locator(".wo-status-created").count() == 0
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && python -m pytest tests/e2e/test_work_orders.py -m e2e -v`
Expected: FAIL on the card selector if `.wo-card` is not the real class.

- [ ] **Step 3: Correct the selectors against the source**

Run: `cd backend && grep -n "wo-card\|workOrderCardClass" static/views/workOrders.js | head`
Use the real card class, and the real solo-card container if the deep link renders into one. Adjust the test only; change nothing under `static/`.

- [ ] **Step 4: Run to verify they pass**

Run: `cd backend && python -m pytest tests/e2e/test_work_orders.py -m e2e -v`
Expected: 2 passed.

- [ ] **Step 5: Confirm teardown still clears the labor session**

Run the count command from Task 4 Step 5.
Expected: `0` for all three. The second journey opened a labor session; a non-zero work-order count means `_purge` is not deleting its children.

- [ ] **Step 6: Commit**

```bash
git add backend/tests/e2e/test_work_orders.py
git commit -m "drive a deep-linked card and a real status change end to end"
```

---

### Task 7: CI job

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Add the job**

Insert after the `frontend` job and before `deploy`:

```yaml
  e2e:
    name: End-to-end (browser)
    runs-on: ubuntu-latest

    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_USER: inventory
          POSTGRES_PASSWORD: inventory
          POSTGRES_DB: inventory_test
        ports:
          - 5432:5432
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5

    env:
      DATABASE_URL: postgresql://inventory:inventory@localhost:5432/inventory_test
      # Turns the e2e availability guard's skip into an error.
      CI: "true"

    defaults:
      run:
        working-directory: backend

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
          cache-dependency-path: backend/requirements-dev.txt

      - name: Install native zbar
        run: sudo apt-get update && sudo apt-get install -y libzbar0

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements-dev.txt

      # --with-deps pulls the shared libraries headless Chromium needs on a
      # bare runner. Without it the browser installs and then fails to launch.
      - name: Install Chromium
        run: python -m playwright install --with-deps chromium

      - name: Run migrations
        run: alembic upgrade head

      # -m e2e overrides the `-m "not e2e"` in pytest.ini: the command line
      # beats addopts, and pytest honours the last -m it is given.
      - name: Run end-to-end suite
        run: python -m pytest -q -m e2e
```

- [ ] **Step 2: Gate the deploy on it**

In the `deploy` job, change `needs: [backend, static, frontend]` to `needs: [backend, static, frontend, e2e]`, and update the comment above it so it names the e2e job alongside the others.

- [ ] **Step 3: Validate the workflow parses**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml')); print('ok')"`
Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "gate deploys on the end-to-end browser suite"
```

---

### Task 8: The success check, and the docs

**Files:**
- Modify: `docs/current-state.md`, `docs/open-work.md`

- [ ] **Step 1: Break CSP deliberately**

Add `style="color: red"` to any element in `backend/static/pages/history.html`.

- [ ] **Step 2: Confirm the suite catches it**

Run: `cd backend && python -m pytest tests/e2e/test_smoke.py -m e2e -k history -v`
Expected: FAIL, with a `Refused to apply inline style` message in the console-errors assertion output. If it passes, the console listener is not wired to the right event — fix Task 4's `console_errors` fixture before going on. This is the check the whole phase exists to satisfy.

- [ ] **Step 3: Revert the break**

Run: `git checkout -- backend/static/pages/history.html`
Then re-run the Step 2 command and confirm it passes.

- [ ] **Step 4: Update the docs**

In `docs/current-state.md`, record the E2E layer in the testing section: what it covers, how to run it (`python -m pytest -m e2e` from `backend/`, after `python -m playwright install chromium`), and that it commits `E2E-`-prefixed rows to `DATABASE_URL` and removes them afterwards.

In `docs/open-work.md`, add any console error or CSP violation Task 5 uncovered. Do **not** remove the "no frontend tests" line — that is P7's.

Respect each file's word budget; if the addition breaches one, delete something stale in the same edit.

- [ ] **Step 5: Full local verification**

Run:
```bash
cd backend && python -m pytest -q          # default suite, e2e deselected
cd backend && python -m pytest -q -m e2e   # the new layer
cd .. && npm test                          # the vitest suite, unchanged
```
Expected: all three green.

- [ ] **Step 6: Commit**

```bash
git add docs/current-state.md docs/open-work.md
git commit -m "document the end-to-end layer and how to run it"
```

---

## Notes for the executor

- **The dev database is real.** While a session runs, `E2E-` rows are visible in the app. If a run is killed, the next one sweeps the debris; a manual sweep is the same `delete ... like 'E2E-%'` that `_seed.sweep_debris` performs.
- **A failing smoke page is usually a finding, not a broken test.** Console errors and CSP violations are exactly what this layer was built to surface. File before you allowlist, and never delete the assertion.
- **`playwright==1.62.0` in `requirements.txt` is a runtime pin.** If dependency resolution wants to move it, stop and raise it.
- **Roadmap deviation, decided here.** The roadmap named `backend/tests/e2e/{conftest.py,test_smoke.py,test_work_orders.py}`. This plan adds `_availability.py`, `_seed.py` and `test_availability.py`: the guard and the seed carry real logic, and folding them into `conftest.py` would leave both untested and that file well over 200 lines.
- **Roles.** The roadmap's "a `page` fixture logged in per role" is served by `login_as`, which takes any seeded username. Only the owner is seeded, because every smoke page is visible to an owner and role gating is P2's dimension, not this layer's. A second role gets a second `User` row in `_seed.build` and a second fixture — three lines each, when a journey needs one.
