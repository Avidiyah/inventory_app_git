# NetFacilities Live Session — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to
> implement this plan task-by-task. (This repo's `CLAUDE.md` forbids subagents, so
> superpowers:subagent-driven-development does **not** apply here.) Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the dedicated NetFacilities window open after login, save the CSV
the operator exports from it under its real name in their Downloads folder, let
enrichment run through that same signed-in window, and add a one-click import of
the captured CSV.

**Architecture:** The authentication coordinator (`services/netfacilities_auth.py`)
becomes a *session* coordinator with a new non-terminal `signed_in` state, an
auto-confirm poller, an idle timeout, download recording, and a borrow API. The
job coordinator accepts a borrowed client and skips the profile gate when it has
one. The Playwright client gains download capture, a context-closed hook, and a
public `prime_session`. One new route imports the captured CSV through the same
function `POST /work-orders/import` uses. Frontend changes are confined to the
Integrations card's wiring in `views/workOrders.js`.

**Tech Stack:** FastAPI + Pydantic (pinned versions in `backend/requirements.txt`),
Playwright 1.62 async API, pytest with offline fakes, vanilla ES modules with no
build step.

**Spec:** `docs/superpowers/specs/2026-08-28-netfacilities-live-session-design.md`
— read it first; every task below cites its decisions (D1–D10) and constraints
(§3).

---

## Global Constraints

- **No subagents** (`CLAUDE.md`). Do the research inline with Read/Grep/Glob.
- **Branch first.** Before Task 1: `git checkout -b netfacilities-live-session`
  from an up-to-date `main` (`git fetch origin; git status` — local main often
  lags remote). **Never merge to `main` or push without the owner's explicit
  go-ahead: a green CI run on `main` deploys to production.**
- **Commit after every task.** Plain commit messages, **no `Co-Authored-By`
  trailer** (the user-level `CLAUDE.md` forbids it and no attribution is
  configured).
- **Run commands from `backend/`.** Every pytest/compile command below is written
  as `cd C:/Users/mcclu/Desktop/inventory_app_git/backend; ./venv/Scripts/python.exe …`
  — the absolute `cd` is idempotent in both PowerShell and Git Bash. `import app`
  only resolves with `backend/` as the working directory. The five
  `tests/test_netfacilities_*.py` files, `tests/test_route_role_gates.py`, and
  `tests/test_netfacilities_config.py` need **no database**; the full suite does.
- **Do not start the app server.** The owner validates in the browser manually
  (spec §11). After every JS edit run
  `node --check C:/Users/mcclu/Desktop/inventory_app_git/backend/static/views/workOrders.js`
  (and the other edited JS file).
- **Secret-safety (D7):** no route response, snapshot, or log line may contain a
  filesystem path, cookie, header, HTML, or source field value. Download
  **filenames** are allowed in responses; directories are not.
- **No live NetFacilities request in any test (D10).**
- **Files under 500 lines** where you create or substantially rewrite one.
  `client.py` (679) and `workOrders.js` (2525) are pre-existing exceptions; do
  not restructure them.
- **Read a file before editing it.** Line numbers in this plan are from commit
  `2858221`; re-locate by content if they have drifted.
- When a step says "replace function X", replace the whole `def`/`function`
  body from its signature to the next top-level definition.

---

## File map

| File | Change |
|---|---|
| `backend/app/integrations/netfacilities/config.py` | `session_timeout_seconds`, `download_dir`, `_download_dir()` |
| `backend/app/integrations/netfacilities/contracts.py` | auth-client protocol gains `prime_session`, `capture_downloads`, `on_context_closed`, and `get_work_order` |
| `backend/app/integrations/netfacilities/client.py` | `accept_downloads=True` (headed), download capture, context-closed hook, `prime_session`, `wait_for_downloads`, `_unique_download_path` |
| `backend/app/services/netfacilities_live_session.py` | **new** — `LiveSessionClientContext` |
| `backend/app/services/netfacilities_auth.py` | **rewritten** — `signed_in`/`closed` states, auto-confirm, idle timeout, downloads, borrow |
| `backend/app/services/netfacilities_jobs.py` | `live_client_context`, `source` |
| `backend/app/lifespan.py` | shutdown order: jobs before auth |
| `backend/app/schemas/netfacilities.py` | new states/fields/`source` |
| `backend/app/routers/netfacilities.py` | session precedence, cancel 409, enrich borrows, new `downloads/import` route |
| `backend/app/routers/work_orders.py` | extract `run_csv_import` |
| `backend/app/routers/_uploads.py` | `read_file_capped` |
| `backend/static/api.js` | `apiImportNetFacilitiesDownload` |
| `backend/static/pages/integrations.html` | button labels, new button |
| `backend/static/views/workOrders.js` | Integrations card wiring |
| `backend/static/tips.js` | copy for `integrations.netfacilities` |
| `backend/tests/test_netfacilities_config.py` | +5 tests |
| `backend/tests/test_netfacilities_client.py` | fakes store handlers; +7 tests |
| `backend/tests/test_netfacilities_auth.py` | fakes extended; tests rewritten/added |
| `backend/tests/test_netfacilities_jobs.py` | +3 tests |
| `backend/tests/test_netfacilities_routes.py` | fakes extended; +8 tests; 3 existing updated |
| `backend/tests/test_route_role_gates.py` | new endpoint in the NetFacilities parametrize list |
| `docs/current-state.md`, `docs/endpoint-map.md`, `docs/project-summary.md`, `docs/open-work.md` | reconciled |

## Locked interfaces (every task depends on these)

```python
# config.py
DEFAULT_SESSION_TIMEOUT_SECONDS = 7_200
NetFacilitiesConfig.session_timeout_seconds: int            # default DEFAULT_SESSION_TIMEOUT_SECONDS
NetFacilitiesConfig.download_dir: Path | None               # default None

# client.py  (NetFacilitiesClient)
def capture_downloads(self, destination: Path, on_saved: Callable[[Path], Awaitable[None]]) -> None
def on_context_closed(self, callback: Callable[[], None]) -> None
async def prime_session(self) -> None
async def wait_for_downloads(self) -> None
def _unique_download_path(directory: Path, suggested_filename: str) -> Path   # module-level

# services/netfacilities_live_session.py
class LiveSessionClientContext:
    def __init__(self, coordinator: "NetFacilitiesAuthenticationCoordinator") -> None
    async def __aenter__(self) -> NetFacilitiesClientProtocol      # -> coordinator.borrow_started()
    async def __aexit__(self, exc_type, exc, traceback) -> None    # -> coordinator.borrow_finished()

# services/netfacilities_auth.py
AuthenticationState = Literal["starting","awaiting_confirmation","confirming","signed_in","closed","failed","cancelled","timed_out"]
PENDING_STATES = frozenset({"starting","awaiting_confirmation","confirming"})
NetFacilitiesAuthenticationSnapshot(..., signed_in_at, last_download_filename, last_download_at)
NetFacilitiesAuthenticationCoordinator(*, client_factory, profile_gate,
    auto_confirm_poll_seconds=1.0, auto_confirm_retry_seconds=5.0, timeout_retry_seconds=60.0)
    async def start(config) -> (snapshot, created)      # returns live session unchanged if pending or signed in
    async def confirm() -> snapshot                     # -> state "signed_in", window stays open
    async def cancel() -> snapshot                      # pending -> "cancelled"; signed_in -> "closed"; 409 while borrowed
    async def shutdown() -> None
    async def latest() -> snapshot | None
    def captured_csv_path() -> Path | None              # sync, lock-free
    async def borrow_live_client() -> LiveSessionClientContext | None
    async def borrow_started() -> client                # raises NetFacilitiesAuthenticationRequired if not signed in
    async def borrow_finished() -> None

# services/netfacilities_jobs.py
JobSource = Literal["live_session", "saved_state"]
NetFacilitiesJobSnapshot.source: JobSource | None
NetFacilitiesJobCoordinator.start(config, *, live_client_context=None) -> (snapshot, created)

# routers/work_orders.py
def run_csv_import(db: Session, background: BackgroundTasks, *, data: bytes, user: User) -> WorkOrderImportResult

# routers/_uploads.py
def read_file_capped(path: Path, *, limit: int, what: str) -> bytes

# routers/netfacilities.py
POST /integrations/netfacilities/downloads/import  -> handler name `import_netfacilities_download`

# static/api.js
export async function apiImportNetFacilitiesDownload()
# static/pages/integrations.html
<button id="wo-netfacilities-import-download-btn" …>Import downloaded CSV</button>
```

---

### Task 1: Configuration — session timeout and download directory

**Files:**
- Modify: `backend/app/integrations/netfacilities/config.py`
- Test: `backend/tests/test_netfacilities_config.py`

**Interfaces:**
- Produces: `DEFAULT_SESSION_TIMEOUT_SECONDS`, `NetFacilitiesConfig.session_timeout_seconds`, `NetFacilitiesConfig.download_dir`, `_download_dir()`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_netfacilities_config.py`. Also extend the existing
import block at the top of the file to include `DEFAULT_SESSION_TIMEOUT_SECONDS`
(add it to the `from app.integrations.netfacilities.config import (...)` list).

```python
def _windows_env(profile):
    return {
        "NETFACILITIES_ENABLED": "true",
        "NETFACILITIES_PROFILE_DIR": str(profile),
    }


def test_windows_download_dir_defaults_to_home_downloads_when_present(
    tmp_path, monkeypatch
):
    home = tmp_path / "home"
    (home / "Downloads").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: home)
    profile = tmp_path / "profile"

    config = load_netfacilities_config(_windows_env(profile), platform="win32")

    assert config.download_dir == (home / "Downloads").resolve()
    assert config.session_timeout_seconds == DEFAULT_SESSION_TIMEOUT_SECONDS


def test_windows_download_dir_falls_back_inside_the_profile(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    profile = tmp_path / "profile"

    config = load_netfacilities_config(_windows_env(profile), platform="win32")

    assert config.download_dir == profile.resolve() / "downloads"


def test_explicit_download_dir_and_session_timeout_are_honored(tmp_path):
    profile = tmp_path / "profile"
    downloads = tmp_path / "exports"
    env = {
        **_windows_env(profile),
        "NETFACILITIES_DOWNLOAD_DIR": str(downloads),
        "NETFACILITIES_SESSION_TIMEOUT_SECONDS": "600",
    }

    config = load_netfacilities_config(env, platform="win32")

    assert config.download_dir == downloads.resolve()
    assert config.session_timeout_seconds == 600


@pytest.mark.parametrize("value", ["relative/dir", "0", "-5", "soon"])
def test_download_dir_and_session_timeout_reject_bad_values(tmp_path, value):
    profile = tmp_path / "profile"
    if value == "relative/dir":
        env = {**_windows_env(profile), "NETFACILITIES_DOWNLOAD_DIR": value}
    else:
        env = {**_windows_env(profile), "NETFACILITIES_SESSION_TIMEOUT_SECONDS": value}

    with pytest.raises(NetFacilitiesUnavailable):
        load_netfacilities_config(env, platform="win32")


def test_download_dir_may_not_live_inside_the_repository(tmp_path):
    repository = tmp_path / "repo"
    profile = tmp_path / "profile"
    env = {
        **_windows_env(profile),
        "NETFACILITIES_DOWNLOAD_DIR": str(repository / "downloads"),
    }

    with pytest.raises(NetFacilitiesUnavailable, match="outside the repository"):
        load_netfacilities_config(env, platform="win32", repository_root=repository)


def test_disabled_and_hosted_configs_have_no_download_dir(tmp_path):
    disabled = load_netfacilities_config({}, platform="win32")
    hosted = load_netfacilities_config(
        {
            "NETFACILITIES_ENABLED": "true",
            "NETFACILITIES_STORAGE_STATE_PATH": str(tmp_path / "state.json"),
        },
        platform="linux",
    )

    assert disabled.download_dir is None
    assert hosted.download_dir is None
    assert hosted.session_timeout_seconds == DEFAULT_SESSION_TIMEOUT_SECONDS
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd C:/Users/mcclu/Desktop/inventory_app_git/backend; ./venv/Scripts/python.exe -m pytest tests/test_netfacilities_config.py -q`
Expected: ImportError on `DEFAULT_SESSION_TIMEOUT_SECONDS` (collection fails).

- [ ] **Step 3: Implement the config**

In `backend/app/integrations/netfacilities/config.py`:

1. After `DEFAULT_RENDER_SETTLE_SECONDS = 5` add:

```python
DEFAULT_SESSION_TIMEOUT_SECONDS = 7_200
DOWNLOADS_FALLBACK_DIRNAME = "downloads"
```

2. Add two fields at the **end** of the `NetFacilitiesConfig` dataclass (after
   `render_settle_seconds`):

```python
    # Idle limit for a signed-in live window (spec D1). Pending sign-in keeps
    # using auth_timeout_seconds.
    session_timeout_seconds: int = DEFAULT_SESSION_TIMEOUT_SECONDS
    # Where a download the operator triggers in the live window is saved (spec
    # D3). None when disabled or hosted: Linux never opens a window.
    download_dir: Path | None = None
```

3. In `load_netfacilities_config`, in the `if current_platform == "win32":`
   branch, after `interactive_authentication_available = True` add:

```python
        download_dir: Path | None = _download_dir(
            values.get("NETFACILITIES_DOWNLOAD_DIR"),
            profile_dir=profile_dir,
            repository_root=repository_root,
        )
```

   and in the `elif current_platform == "linux":` branch, after
   `interactive_authentication_available = False` add:

```python
        download_dir = None
```

4. In the final `return NetFacilitiesConfig(` call add, after
   `render_settle_seconds=...,`:

```python
        session_timeout_seconds=_positive_seconds(
            values,
            "NETFACILITIES_SESSION_TIMEOUT_SECONDS",
            DEFAULT_SESSION_TIMEOUT_SECONDS,
        ),
        download_dir=download_dir,
```

5. Add this helper after `_profile_dir`:

```python
def _download_dir(
    raw: str | None,
    *,
    profile_dir: Path,
    repository_root: Path,
) -> Path:
    """Resolve where the live window's downloads are saved.

    Unset picks the operator's own Downloads folder when it exists, because that
    is where they will look for the CSV they just exported; otherwise a folder
    inside the protected profile. An explicit value obeys the same three checks
    as NETFACILITIES_PROFILE_DIR: absolute, outside the repository, a directory.
    """

    if raw is None or not raw.strip():
        home_downloads = Path.home() / "Downloads"
        if home_downloads.is_dir():
            return home_downloads.resolve(strict=False)
        return profile_dir / DOWNLOADS_FALLBACK_DIRNAME
    expanded = Path(raw.strip()).expanduser()
    if not expanded.is_absolute():
        raise NetFacilitiesUnavailable(
            "NETFACILITIES_DOWNLOAD_DIR must be an absolute path outside the repository."
        )

    path = expanded.resolve(strict=False)
    root = repository_root.resolve(strict=False)
    try:
        path.relative_to(root)
    except ValueError:
        pass
    else:
        raise NetFacilitiesUnavailable(
            "NETFACILITIES_DOWNLOAD_DIR must be outside the repository."
        )
    if path.exists() and not path.is_dir():
        raise NetFacilitiesUnavailable(
            "NETFACILITIES_DOWNLOAD_DIR must refer to a directory."
        )
    return path
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd C:/Users/mcclu/Desktop/inventory_app_git/backend; ./venv/Scripts/python.exe -m pytest tests/test_netfacilities_config.py -q`
Expected: all pass (existing tests untouched: new fields have defaults).

- [ ] **Step 5: Commit**

```bash
cd C:/Users/mcclu/Desktop/inventory_app_git; git add backend/app/integrations/netfacilities/config.py backend/tests/test_netfacilities_config.py; git commit -m "feat(netfacilities): session timeout and download directory settings (IMP-039)"
```

---

### Task 2: Client — accept downloads, capture them, report window close, public priming

**Files:**
- Modify: `backend/app/integrations/netfacilities/contracts.py`
- Modify: `backend/app/integrations/netfacilities/client.py`
- Test: `backend/tests/test_netfacilities_client.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `capture_downloads`, `on_context_closed`, `prime_session`,
  `wait_for_downloads`, `_unique_download_path`; the extended
  `NetFacilitiesAuthenticationClientProtocol`.

- [ ] **Step 1: Extend the test fakes**

In `backend/tests/test_netfacilities_client.py`:

1. Change the playwright import to
   `from playwright.async_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError`.
2. In `FakeBrowserContext.__init__` add `self.handlers = {}` and add the method:

```python
    def on(self, event, handler):
        self.handlers[event] = handler
```

3. In `FakePage.__init__` add `self.handlers = {}` and change `on` to:

```python
    def on(self, event, handler):
        self.listeners.append(event)
        self.handlers[event] = handler
```

4. Add after `FakePage`:

```python
class FakeDownload:
    def __init__(self, suggested_filename, *, save_error=None):
        self.suggested_filename = suggested_filename
        self.save_error = save_error
        self.saved_to = None

    async def save_as(self, path):
        if self.save_error is not None:
            raise self.save_error
        self.saved_to = Path(path)
        self.saved_to.write_text("WORK ORDER\n", encoding="utf-8")


def _persistent_runtime(monkeypatch, context):
    """Fake Playwright whose chromium launches the given persistent context."""

    class FakeChromium:
        def __init__(self):
            self.persistent_calls = []

        async def launch_persistent_context(self, **kwargs):
            self.persistent_calls.append(kwargs)
            return context

    class FakePlaywright:
        def __init__(self, chromium):
            self.chromium = chromium
            self.stopped = 0

        async def stop(self):
            self.stopped += 1

    chromium = FakeChromium()
    runtime = FakePlaywright(chromium)

    class FakeStarter:
        async def start(self):
            return runtime

    monkeypatch.setattr(client_module.sys, "platform", "linux")
    monkeypatch.setattr(client_module, "async_playwright", lambda: FakeStarter())
    return chromium, runtime
```

- [ ] **Step 2: Write the failing tests**

Append to `backend/tests/test_netfacilities_client.py`:

```python
def test_interactive_profile_accepts_downloads(tmp_path, monkeypatch):
    context = FakeBrowserContext(FakeResponse())
    chromium, runtime = _persistent_runtime(monkeypatch, context)
    client = NetFacilitiesClient(
        profile_dir=tmp_path, headless=False, browser_channel="chrome"
    )

    async def exercise():
        async with client:
            pass

    asyncio.run(exercise())
    assert chromium.persistent_calls == [
        {
            "user_data_dir": str(tmp_path),
            "channel": "chrome",
            "headless": False,
            "accept_downloads": True,
        }
    ]
    assert context.closed == 1
    assert runtime.stopped == 1


def test_context_closed_by_the_operator_is_reported_and_not_closed_again(
    tmp_path, monkeypatch
):
    context = FakeBrowserContext(FakeResponse())
    _chromium, runtime = _persistent_runtime(monkeypatch, context)
    client = NetFacilitiesClient(
        profile_dir=tmp_path, headless=False, browser_channel="chrome"
    )
    seen = []

    async def exercise():
        async with client:
            client.on_context_closed(lambda: seen.append("closed"))
            context.handlers["close"](context)

    asyncio.run(exercise())
    assert seen == ["closed"]
    assert context.closed == 0
    assert runtime.stopped == 1


def test_capture_downloads_saves_under_the_suggested_name_and_reports_the_path(
    tmp_path,
):
    client, context = _client(FakeResponse())
    page = FakePage("https://system.netfacilities.com/myhome")
    context.pages.append(page)
    saved = []

    async def on_saved(path):
        saved.append(path)

    async def exercise():
        client.capture_downloads(tmp_path / "downloads", on_saved)
        page.handlers["download"](FakeDownload("WorkOrders.csv"))
        await client.wait_for_downloads()
        page.handlers["download"](FakeDownload("WorkOrders.csv"))
        await client.wait_for_downloads()

    asyncio.run(exercise())
    assert saved == [
        tmp_path / "downloads" / "WorkOrders.csv",
        tmp_path / "downloads" / "WorkOrders (1).csv",
    ]
    assert all(path.is_file() for path in saved)
    assert "page" in context.handlers


def test_capture_downloads_attaches_to_pages_opened_later(tmp_path):
    client, context = _client(FakeResponse())

    async def on_saved(_path):
        return None

    async def exercise():
        client.capture_downloads(tmp_path, on_saved)
        later = FakePage("https://system.netfacilities.com/tools/viewworkorders")
        context.handlers["page"](later)
        assert "download" in later.handlers

    asyncio.run(exercise())


def test_download_save_failure_is_swallowed_and_never_reported(tmp_path):
    client, context = _client(FakeResponse())
    page = FakePage("https://system.netfacilities.com/myhome")
    context.pages.append(page)
    saved = []

    async def on_saved(path):
        saved.append(path)

    async def exercise():
        client.capture_downloads(tmp_path, on_saved)
        page.handlers["download"](
            FakeDownload("x.csv", save_error=PlaywrightError("disk"))
        )
        await client.wait_for_downloads()

    asyncio.run(exercise())
    assert saved == []


def test_prime_session_always_probes_the_server_and_leaves_it_primed():
    client, context = _client(FakeResponse())

    async def exercise():
        await client.prime_session()
        await client.prime_session()
        await client.get_work_order("12345678")

    asyncio.run(exercise())
    urls = [call[0] for call in context.request.calls]
    assert urls == [
        f"{BASE_URL}/myhome",
        f"{BASE_URL}/myhome",
        f"{BASE_URL}/tools/viewworkorders/12345678",
    ]


def test_unique_download_path_strips_directories_and_numbers_duplicates(tmp_path):
    (tmp_path / "export.csv").write_text("", encoding="utf-8")
    (tmp_path / "export (1).csv").write_text("", encoding="utf-8")

    assert (
        client_module._unique_download_path(tmp_path, "../export.csv")
        == tmp_path / "export (2).csv"
    )
    assert client_module._unique_download_path(tmp_path, "") == tmp_path / "download"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd C:/Users/mcclu/Desktop/inventory_app_git/backend; ./venv/Scripts/python.exe -m pytest tests/test_netfacilities_client.py -q`
Expected: the 7 new tests fail (`AttributeError: ... has no attribute 'capture_downloads'`, assertion on `accept_downloads`, etc.); all pre-existing tests still pass.

- [ ] **Step 4: Extend the contract**

In `backend/app/integrations/netfacilities/contracts.py`:

1. Change the imports to:

```python
from collections.abc import Awaitable, Callable
from pathlib import Path
from types import TracebackType
from typing import Protocol
```

2. Replace `NetFacilitiesAuthenticationClientProtocol` with:

```python
class NetFacilitiesAuthenticationClientProtocol(NetFacilitiesClientProtocol, Protocol):
    """Headed-browser actions for the in-app sign-in and the live session.

    The same client reads work orders once signed in, which is why this extends
    the read protocol: enrichment borrows it instead of launching a second
    browser (spec D4).
    """

    async def open_authentication_page(self) -> None: ...

    async def verify_authentication_page(self) -> None: ...

    async def prime_session(self) -> None: ...

    async def persist_authentication_state(self) -> None: ...

    def capture_downloads(
        self,
        destination: Path,
        on_saved: Callable[[Path], Awaitable[None]],
    ) -> None: ...

    def on_context_closed(self, callback: Callable[[], None]) -> None: ...
```

- [ ] **Step 5: Implement the client changes**

In `backend/app/integrations/netfacilities/client.py`:

1. Imports: add `from collections.abc import Awaitable, Callable` and
   `import logging`; after the constants add
   `logger = logging.getLogger(__name__)`.

2. In `__init__` (after `self._session_primed = False`) add:

```python
        self._context_closed = False
        self._download_tasks: set[asyncio.Task[None]] = set()
```

3. In `__aenter__`, the headed launch (currently `accept_downloads=False` inside
   `launch_persistent_context(...)`) becomes `accept_downloads=True`. **Leave the
   saved-state `new_context(... accept_downloads=False ...)` alone.**

4. Replace `__aexit__` with:

```python
    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        try:
            try:
                await asyncio.wait_for(
                    self.wait_for_downloads(), timeout=self.timeout_ms / 1_000
                )
            except TimeoutError:
                logger.error("netfacilities.download_wait_timed_out")
            if (
                self._owns_context
                and self._context is not None
                and not self._context_closed
            ):
                await self._context.close()
        finally:
            if self._owns_context:
                self._context = None
            await self._stop_runtime()
```

5. After `persist_authentication_state` add:

```python
    async def prime_session(self) -> None:
        """Verify the session against the server and leave it primed.

        ``confirm`` uses this as the authoritative "are we signed in" probe (spec
        §3.4); a URL check alone can be fooled by the instant before a redirect.
        The successful probe also primes the session, so the enrichment that
        follows pays no extra request.
        """

        self._session_primed = False
        await self._ensure_session_primed()

    def on_context_closed(self, callback: Callable[[], None]) -> None:
        """Run ``callback`` once if the operator closes the dedicated window."""

        context = self._require_context()

        def handle_close(_context: Any) -> None:
            self._context_closed = True
            callback()

        context.on("close", handle_close)

    def capture_downloads(
        self,
        destination: Path,
        on_saved: Callable[[Path], Awaitable[None]],
    ) -> None:
        """Save every download the operator triggers under its suggested name.

        Playwright never writes a download to the OS Downloads folder on its own
        (spec §3.1), so each one is saved explicitly. Attaches to the pages that
        exist now and to every page the context opens later.
        """

        context = self._require_context()

        def attach(page: Any) -> None:
            def handle_download(download: Any) -> None:
                task = asyncio.get_running_loop().create_task(
                    self._save_download(download, destination, on_saved)
                )
                self._download_tasks.add(task)
                task.add_done_callback(self._download_tasks.discard)

            page.on("download", handle_download)

        for page in context.pages:
            attach(page)
        context.on("page", attach)

    async def wait_for_downloads(self) -> None:
        """Await in-flight saves so a close never truncates a file."""

        pending = [task for task in self._download_tasks if not task.done()]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def _save_download(
        self,
        download: Any,
        destination: Path,
        on_saved: Callable[[Path], Awaitable[None]],
    ) -> None:
        try:
            destination.mkdir(parents=True, exist_ok=True)
            target = _unique_download_path(destination, download.suggested_filename)
            await download.save_as(str(target))
        except (OSError, PlaywrightError) as exc:
            # The exception class is the only thing logged: a message could
            # echo the filename's directory, which never leaves this process.
            logger.error(
                "netfacilities.download_save_failed",
                extra={"fields": {"exc_type": type(exc).__name__}},
            )
            return
        await on_saved(target)
```

6. After `_unrendered_retrieval` (module level) add:

```python
def _unique_download_path(directory: Path, suggested_filename: str) -> Path:
    """Keep the vendor's filename, minus any path, and never overwrite."""

    name = Path(suggested_filename or "").name or "download"
    candidate = directory / name
    stem, suffix = candidate.stem, candidate.suffix
    counter = 1
    while candidate.exists():
        candidate = directory / f"{stem} ({counter}){suffix}"
        counter += 1
    return candidate
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd C:/Users/mcclu/Desktop/inventory_app_git/backend; ./venv/Scripts/python.exe -m pytest tests/test_netfacilities_client.py tests/test_netfacilities_poc.py tests/test_netfacilities_diagnostic.py -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
cd C:/Users/mcclu/Desktop/inventory_app_git; git add backend/app/integrations/netfacilities/contracts.py backend/app/integrations/netfacilities/client.py backend/tests/test_netfacilities_client.py; git commit -m "feat(netfacilities): headed client saves downloads, reports window close, exposes priming (IMP-039)"
```

---

### Task 3: Session coordinator — signed-in state, auto-confirm, idle timeout, downloads, borrow

**Files:**
- Create: `backend/app/services/netfacilities_live_session.py`
- Rewrite: `backend/app/services/netfacilities_auth.py`
- Test: `backend/tests/test_netfacilities_auth.py`

**Interfaces:**
- Consumes: Task 1 config fields; Task 2 client methods and protocol.
- Produces: everything under `services/netfacilities_auth.py` and
  `services/netfacilities_live_session.py` in the locked-interfaces block.

- [ ] **Step 1: Extend the test fakes and helpers**

In `backend/tests/test_netfacilities_auth.py` replace the imports, the two fake
classes, and `_config` with:

```python
"""Offline tests for the in-app NetFacilities live session lifecycle."""

from __future__ import annotations

import asyncio

import pytest

from app.integrations.netfacilities.config import NetFacilitiesConfig
from app.integrations.netfacilities.errors import (
    NetFacilitiesAuthenticationRequired,
    NetFacilitiesOperationInProgress,
    NetFacilitiesUnavailable,
    NetFacilitiesUnexpectedResponse,
)
from app.services.netfacilities import NetFacilitiesEnrichmentSummary
from app.services.netfacilities_auth import NetFacilitiesAuthenticationCoordinator
from app.services.netfacilities_jobs import NetFacilitiesJobCoordinator
from app.services.netfacilities_operations import NetFacilitiesOperationGate


class FakeAuthenticationClient:
    def __init__(self, *, verify_error=None, prime_error=None):
        self.verify_error = verify_error
        self.prime_error = prime_error
        self.opened = 0
        self.verified = 0
        self.primed = 0
        self.persisted = 0
        self.download_destination = None
        self.on_saved = None
        self.close_callback = None
        self.work_orders_requested = []

    async def open_authentication_page(self):
        self.opened += 1

    async def verify_authentication_page(self):
        self.verified += 1
        if self.verify_error is not None:
            raise self.verify_error

    async def prime_session(self):
        self.primed += 1
        if self.prime_error is not None:
            raise self.prime_error

    async def persist_authentication_state(self):
        self.persisted += 1

    def capture_downloads(self, destination, on_saved):
        self.download_destination = destination
        self.on_saved = on_saved

    def on_context_closed(self, callback):
        self.close_callback = callback

    async def get_work_order(self, work_order_number):
        self.work_orders_requested.append(work_order_number)
        return object()


class FakeAuthenticationContext:
    def __init__(self, client=None):
        self.client = client or FakeAuthenticationClient()
        self.entered = 0
        self.exited = 0

    async def __aenter__(self):
        self.entered += 1
        return self.client

    async def __aexit__(self, *_args):
        self.exited += 1


class FakeEnrichmentContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *_args):
        return None


def _config(tmp_path, *, timeout=900, session_timeout=7_200, authenticated=False):
    profile = tmp_path / "profile"
    profile.mkdir(exist_ok=True)
    config = NetFacilitiesConfig(
        enabled=True,
        profile_dir=profile,
        browser_channel="chrome",
        request_timeout_seconds=30,
        auth_timeout_seconds=timeout,
        batch_timeout_seconds=1_800,
        session_timeout_seconds=session_timeout,
        download_dir=tmp_path / "downloads",
    )
    if authenticated:
        config.storage_state_path.write_text("sanitized-test-state", encoding="utf-8")
    return config


def _coordinator(context, gate=None, **overrides):
    """A coordinator whose auto-confirm poller is effectively off unless a test
    opts in with ``auto_confirm_poll_seconds``."""

    settings = {"auto_confirm_poll_seconds": 60.0}
    settings.update(overrides)
    return NetFacilitiesAuthenticationCoordinator(
        client_factory=lambda _config: context,
        profile_gate=gate or NetFacilitiesOperationGate(),
        **settings,
    )


async def _wait_for_state(coordinator, state, *, attempts=300):
    for _ in range(attempts):
        latest = await coordinator.latest()
        if latest is not None and latest.state == state:
            return latest
        await asyncio.sleep(0.002)
    raise AssertionError(f"coordinator never reached {state!r}")
```

- [ ] **Step 2: Replace the tests**

Delete every existing `def test_*` in the file **except**
`test_duplicate_start_returns_same_pending_attempt`,
`test_cancel_closes_browser_without_persisting_state`,
`test_client_factory_failure_releases_profile_gate`,
`test_abandoned_sign_in_times_out_and_releases_profile`,
`test_enrichment_cannot_start_while_sign_in_owns_profile`, and the trailing
`_completed_summary` helper. In each of those five kept tests, replace the
`NetFacilitiesAuthenticationCoordinator(client_factory=lambda _config: context, profile_gate=gate)`
/ `profile_gate=NetFacilitiesOperationGate()` construction with
`_coordinator(context, gate)` (or `_coordinator(context)` where no gate variable
exists); in `test_client_factory_failure_releases_profile_gate` keep the
`client_factory=unavailable` construction as it is but add
`auto_confirm_poll_seconds=60.0`. In
`test_enrichment_cannot_start_while_sign_in_owns_profile` keep `authentication =
NetFacilitiesAuthenticationCoordinator(client_factory=lambda _config:
FakeAuthenticationContext(), profile_gate=gate, auto_confirm_poll_seconds=60.0)`.

Then add these tests:

```python
def test_start_and_confirm_keep_the_window_open_and_signed_in(tmp_path):
    gate = NetFacilitiesOperationGate()
    context = FakeAuthenticationContext()
    coordinator = _coordinator(context, gate)

    async def exercise():
        config = _config(tmp_path)
        started, created = await coordinator.start(config)
        assert created
        assert started.state == "awaiting_confirmation"
        assert context.client.download_destination == config.download_dir
        assert context.client.close_callback is not None

        signed_in = await coordinator.confirm()
        assert signed_in.attempt_id == started.attempt_id
        assert signed_in.state == "signed_in"
        assert signed_in.signed_in_at is not None
        assert signed_in.finished_at is None
        assert await gate.active_kind() == "authentication"
        assert context.exited == 0

        closed = await coordinator.cancel()
        assert closed.state == "closed"
        assert closed.failure is None
        assert closed.finished_at is not None
        assert await gate.active_kind() is None

    asyncio.run(exercise())
    assert context.entered == 1
    assert context.exited == 1
    assert context.client.verified == 1
    assert context.client.primed == 1
    assert context.client.persisted == 1


def test_manual_confirm_probe_failure_keeps_the_window_open(tmp_path):
    client = FakeAuthenticationClient(
        verify_error=NetFacilitiesAuthenticationRequired("still on login")
    )
    context = FakeAuthenticationContext(client)
    coordinator = _coordinator(context)

    async def exercise():
        await coordinator.start(_config(tmp_path))
        with pytest.raises(NetFacilitiesAuthenticationRequired):
            await coordinator.confirm()
        assert (await coordinator.latest()).state == "awaiting_confirmation"
        assert context.exited == 0

        client.verify_error = None
        client.prime_error = NetFacilitiesUnexpectedResponse("vendor returned 503")
        with pytest.raises(NetFacilitiesUnexpectedResponse):
            await coordinator.confirm()
        assert (await coordinator.latest()).state == "awaiting_confirmation"
        assert client.persisted == 0
        assert context.exited == 0

        client.prime_error = None
        assert (await coordinator.confirm()).state == "signed_in"
        await coordinator.cancel()

    asyncio.run(exercise())
    assert context.exited == 1
    assert client.persisted == 1


def test_sign_in_is_confirmed_automatically_once_a_page_leaves_the_login_screen(
    tmp_path,
):
    client = FakeAuthenticationClient(
        verify_error=NetFacilitiesAuthenticationRequired("still on login")
    )
    context = FakeAuthenticationContext(client)
    coordinator = _coordinator(
        context, auto_confirm_poll_seconds=0.001, auto_confirm_retry_seconds=0.001
    )

    async def exercise():
        await coordinator.start(_config(tmp_path))
        await asyncio.sleep(0.01)
        assert (await coordinator.latest()).state == "awaiting_confirmation"
        assert client.persisted == 0

        client.verify_error = None
        signed_in = await _wait_for_state(coordinator, "signed_in")
        assert signed_in.signed_in_at is not None
        assert client.primed == 1
        assert client.persisted == 1
        assert context.exited == 0
        await coordinator.cancel()

    asyncio.run(exercise())


def test_auto_confirm_stays_pending_until_the_server_probe_succeeds(tmp_path):
    client = FakeAuthenticationClient(
        prime_error=NetFacilitiesAuthenticationRequired("cookies not set yet")
    )
    context = FakeAuthenticationContext(client)
    coordinator = _coordinator(
        context, auto_confirm_poll_seconds=0.001, auto_confirm_retry_seconds=0.001
    )

    async def exercise():
        await coordinator.start(_config(tmp_path))
        for _ in range(300):
            if client.primed >= 2:
                break
            await asyncio.sleep(0.002)
        assert client.primed >= 2
        assert (await coordinator.latest()).state == "awaiting_confirmation"
        assert client.persisted == 0
        assert context.exited == 0

        client.prime_error = None
        await _wait_for_state(coordinator, "signed_in")
        await coordinator.cancel()

    asyncio.run(exercise())


def test_start_while_signed_in_returns_the_live_session_unchanged(tmp_path):
    context = FakeAuthenticationContext()
    coordinator = _coordinator(context)

    async def exercise():
        first, _created = await coordinator.start(_config(tmp_path))
        await coordinator.confirm()
        again, created = await coordinator.start(_config(tmp_path))
        assert not created
        assert again.attempt_id == first.attempt_id
        assert again.state == "signed_in"
        await coordinator.cancel()

    asyncio.run(exercise())
    assert context.entered == 1


def test_borrow_hands_out_the_live_client_and_blocks_cancel_until_returned(tmp_path):
    context = FakeAuthenticationContext()
    coordinator = _coordinator(context)

    async def exercise():
        assert await coordinator.borrow_live_client() is None
        await coordinator.start(_config(tmp_path))
        assert await coordinator.borrow_live_client() is None
        await coordinator.confirm()

        borrowed = await coordinator.borrow_live_client()
        assert borrowed is not None
        async with borrowed as client:
            assert client is context.client
            with pytest.raises(NetFacilitiesOperationInProgress):
                await coordinator.cancel()
            assert (await coordinator.latest()).state == "signed_in"
            assert context.exited == 0
        assert (await coordinator.cancel()).state == "closed"

    asyncio.run(exercise())
    assert context.exited == 1


def test_borrowing_after_the_window_closed_is_authentication_required(tmp_path):
    context = FakeAuthenticationContext()
    coordinator = _coordinator(context)

    async def exercise():
        await coordinator.start(_config(tmp_path))
        await coordinator.confirm()
        borrowed = await coordinator.borrow_live_client()
        await coordinator.cancel()
        with pytest.raises(NetFacilitiesAuthenticationRequired):
            async with borrowed:
                pass

    asyncio.run(exercise())


def test_window_closed_by_the_operator_ends_the_session_and_releases_the_profile(
    tmp_path,
):
    gate = NetFacilitiesOperationGate()
    context = FakeAuthenticationContext()
    coordinator = _coordinator(context, gate)

    async def exercise():
        await coordinator.start(_config(tmp_path))
        await coordinator.confirm()
        context.client.close_callback()
        closed = await _wait_for_state(coordinator, "closed")
        assert closed.failure is None
        assert await gate.active_kind() is None

    asyncio.run(exercise())
    assert context.exited == 1


def test_window_closed_before_sign_in_is_recorded_as_cancelled(tmp_path):
    gate = NetFacilitiesOperationGate()
    context = FakeAuthenticationContext()
    coordinator = _coordinator(context, gate)

    async def exercise():
        await coordinator.start(_config(tmp_path))
        context.client.close_callback()
        cancelled = await _wait_for_state(coordinator, "cancelled")
        assert cancelled.failure == "cancelled"
        assert await gate.active_kind() is None

    asyncio.run(exercise())
    assert context.exited == 1


def test_csv_download_is_recorded_by_name_and_other_files_are_ignored(tmp_path):
    context = FakeAuthenticationContext()
    coordinator = _coordinator(context)
    downloads = tmp_path / "downloads"

    async def exercise():
        await coordinator.start(_config(tmp_path))
        await coordinator.confirm()

        await context.client.on_saved(downloads / "report.pdf")
        assert (await coordinator.latest()).last_download_filename is None
        assert coordinator.captured_csv_path() is None

        await context.client.on_saved(downloads / "WorkOrders.CSV")
        latest = await coordinator.latest()
        assert latest.state == "signed_in"
        assert latest.last_download_filename == "WorkOrders.CSV"
        assert latest.last_download_at is not None
        assert coordinator.captured_csv_path() == downloads / "WorkOrders.CSV"

        closed = await coordinator.cancel()
        assert closed.last_download_filename == "WorkOrders.CSV"
        assert coordinator.captured_csv_path() == downloads / "WorkOrders.CSV"

        await coordinator.start(_config(tmp_path))
        assert (await coordinator.latest()).last_download_filename is None
        assert coordinator.captured_csv_path() is None
        await coordinator.cancel()

    asyncio.run(exercise())


def test_signed_in_session_times_out_when_idle(tmp_path):
    gate = NetFacilitiesOperationGate()
    context = FakeAuthenticationContext()
    coordinator = _coordinator(context, gate)

    async def exercise():
        await coordinator.start(_config(tmp_path, session_timeout=0.001))
        await coordinator.confirm()
        timed_out = await _wait_for_state(coordinator, "timed_out")
        assert timed_out.failure == "timed_out"
        assert await gate.active_kind() is None

    asyncio.run(exercise())
    assert context.exited == 1


def test_session_timeout_waits_while_enrichment_borrows_the_window(tmp_path):
    context = FakeAuthenticationContext()
    coordinator = _coordinator(context, timeout_retry_seconds=0.001)

    async def exercise():
        await coordinator.start(_config(tmp_path, session_timeout=0.001))
        await coordinator.confirm()
        borrowed = await coordinator.borrow_live_client()
        async with borrowed:
            await asyncio.sleep(0.02)
            assert (await coordinator.latest()).state == "signed_in"
            assert context.exited == 0
        await _wait_for_state(coordinator, "timed_out")

    asyncio.run(exercise())
    assert context.exited == 1


def test_shutdown_closes_a_signed_in_window(tmp_path):
    gate = NetFacilitiesOperationGate()
    context = FakeAuthenticationContext()
    coordinator = _coordinator(context, gate)

    async def exercise():
        await coordinator.start(_config(tmp_path))
        await coordinator.confirm()
        await coordinator.shutdown()
        assert (await coordinator.latest()).state == "closed"
        assert await gate.active_kind() is None

    asyncio.run(exercise())
    assert context.exited == 1
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd C:/Users/mcclu/Desktop/inventory_app_git/backend; ./venv/Scripts/python.exe -m pytest tests/test_netfacilities_auth.py -q`
Expected: failures (`TypeError: unexpected keyword argument 'session_timeout_seconds'` is fixed by Task 1, so expect `unexpected keyword argument 'auto_confirm_poll_seconds'` and attribute errors).

- [ ] **Step 4: Create the live-session module**

Create `backend/app/services/netfacilities_live_session.py`:

```python
"""Borrow the signed-in NetFacilities window for one enrichment job.

Layer: services. The job coordinator treats this exactly like the headless
client context it launches itself -- ``async with`` yields a client with
``get_work_order`` -- except that leaving the block hands the window back
instead of closing it (spec D4, D8). The coordinator refuses to close the
window while it is borrowed.
"""

from __future__ import annotations

from types import TracebackType
from typing import TYPE_CHECKING

from app.integrations.netfacilities.contracts import NetFacilitiesClientProtocol

if TYPE_CHECKING:  # pragma: no cover - import cycle guard for type checkers only
    from app.services.netfacilities_auth import (
        NetFacilitiesAuthenticationCoordinator,
    )


class LiveSessionClientContext:
    """Enter to borrow the live client; exit to return it. Never closes it."""

    def __init__(self, coordinator: "NetFacilitiesAuthenticationCoordinator") -> None:
        self._coordinator = coordinator

    async def __aenter__(self) -> NetFacilitiesClientProtocol:
        return await self._coordinator.borrow_started()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._coordinator.borrow_finished()
```

- [ ] **Step 5: Rewrite the coordinator**

Replace the entire contents of `backend/app/services/netfacilities_auth.py` with:

```python
"""Process-local lifecycle for the in-app NetFacilities live session.

One headed browser per process. ``start`` opens it on the sign-in page.
``confirm`` -- called automatically once a page leaves the login screen, or by
the operator -- verifies the session against the server, saves the storage
state for the headless fallback, and leaves the window **open**: the operator
exports the work-order CSV from it, and enrichment borrows the same signed-in
session instead of launching a second browser. ``cancel`` closes the window in
any state; the window closing on its own, the idle timeout, and application
shutdown do the same. Spec: docs/superpowers/specs/2026-08-28-netfacilities-
live-session-design.md.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import logging
from pathlib import Path
from typing import Literal, TypeAlias
from uuid import UUID, uuid4

from app.integrations.netfacilities.config import NetFacilitiesConfig
from app.integrations.netfacilities.contracts import (
    NetFacilitiesAuthenticationClientProtocol,
    NetFacilitiesAuthenticationContextProtocol,
)
from app.integrations.netfacilities.errors import (
    NetFacilitiesAuthenticationNotPending,
    NetFacilitiesAuthenticationRequired,
    NetFacilitiesError,
    NetFacilitiesOperationInProgress,
    NetFacilitiesUnexpectedResponse,
)
from app.integrations.netfacilities.factory import (
    create_netfacilities_authentication_client,
)
from app.services.netfacilities_live_session import LiveSessionClientContext
from app.services.netfacilities_operations import (
    NetFacilitiesOperationGate,
    operation_gate,
)


logger = logging.getLogger(__name__)

AuthenticationState: TypeAlias = Literal[
    "starting",
    "awaiting_confirmation",
    "confirming",
    "signed_in",
    "closed",
    "failed",
    "cancelled",
    "timed_out",
]
AuthenticationFailure: TypeAlias = Literal["unavailable", "cancelled", "timed_out"]
AuthenticationClientFactory: TypeAlias = Callable[
    [NetFacilitiesConfig], NetFacilitiesAuthenticationContextProtocol
]

# "Pending" is the window being open before anyone is signed in. ``signed_in``
# is deliberately not in this set: it is live, not pending, and not terminal.
PENDING_STATES: frozenset[str] = frozenset(
    {"starting", "awaiting_confirmation", "confirming"}
)
AUTO_CONFIRM_POLL_SECONDS = 1.0
AUTO_CONFIRM_RETRY_SECONDS = 5.0
TIMEOUT_RETRY_SECONDS = 60.0
CSV_SUFFIX = ".csv"


@dataclass(frozen=True, slots=True)
class NetFacilitiesAuthenticationSnapshot:
    """Secret-free state safe to return to an administrator.

    ``last_download_filename`` is a bare filename. The directory is
    configuration the operator already knows and never travels in a response.
    """

    attempt_id: UUID
    state: AuthenticationState
    started_at: datetime
    finished_at: datetime | None = None
    failure: AuthenticationFailure | None = None
    signed_in_at: datetime | None = None
    last_download_filename: str | None = None
    last_download_at: datetime | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


class NetFacilitiesAuthenticationCoordinator:
    """Own one headed browser from sign-in through the end of the live session."""

    def __init__(
        self,
        *,
        client_factory: AuthenticationClientFactory = (
            create_netfacilities_authentication_client
        ),
        profile_gate: NetFacilitiesOperationGate = operation_gate,
        auto_confirm_poll_seconds: float = AUTO_CONFIRM_POLL_SECONDS,
        auto_confirm_retry_seconds: float = AUTO_CONFIRM_RETRY_SECONDS,
        timeout_retry_seconds: float = TIMEOUT_RETRY_SECONDS,
    ) -> None:
        self._client_factory = client_factory
        self._profile_gate = profile_gate
        self._auto_confirm_poll_seconds = auto_confirm_poll_seconds
        self._auto_confirm_retry_seconds = auto_confirm_retry_seconds
        self._timeout_retry_seconds = timeout_retry_seconds
        self._lock = asyncio.Lock()
        self._latest: NetFacilitiesAuthenticationSnapshot | None = None
        self._lease: UUID | None = None
        self._context: NetFacilitiesAuthenticationContextProtocol | None = None
        self._client: NetFacilitiesAuthenticationClientProtocol | None = None
        self._timeout_task: asyncio.Task[None] | None = None
        self._auto_confirm_task: asyncio.Task[None] | None = None
        self._background_tasks: set[asyncio.Task[None]] = set()
        self._session_timeout_seconds: float = 0
        self._borrow_count = 0
        self._last_download_path: Path | None = None

    # ------------------------------------------------------------------ reads

    async def latest(self) -> NetFacilitiesAuthenticationSnapshot | None:
        async with self._lock:
            return self._latest

    def captured_csv_path(self) -> Path | None:
        """The most recent CSV exported through the live window, if any.

        Read without the lock on purpose: the route that consumes it is a sync
        handler (the import is one long transaction) and a single attribute read
        of a ``Path | None`` is atomic. The path never leaves the server.
        """

        return self._last_download_path

    async def borrow_live_client(self) -> LiveSessionClientContext | None:
        """A context that lends the signed-in client to one job, or None."""

        async with self._lock:
            if not self._signed_in_locked() or self._client is None:
                return None
            return LiveSessionClientContext(self)

    async def borrow_started(self) -> NetFacilitiesAuthenticationClientProtocol:
        async with self._lock:
            if not self._signed_in_locked() or self._client is None:
                raise NetFacilitiesAuthenticationRequired(
                    "The NetFacilities window is no longer signed in."
                )
            self._borrow_count += 1
            return self._client

    async def borrow_finished(self) -> None:
        async with self._lock:
            self._borrow_count = max(0, self._borrow_count - 1)

    # --------------------------------------------------------------- commands

    async def start(
        self,
        config: NetFacilitiesConfig,
    ) -> tuple[NetFacilitiesAuthenticationSnapshot, bool]:
        """Open the headed browser, or return the window that is already open."""

        async with self._lock:
            if self._active_locked() or self._signed_in_locked():
                if self._latest is None:  # defensive type narrowing
                    raise RuntimeError("active authentication has no snapshot")
                return self._latest, False

            lease = await self._profile_gate.acquire("authentication")
            attempt = NetFacilitiesAuthenticationSnapshot(
                attempt_id=uuid4(),
                state="starting",
                started_at=_now(),
            )
            self._latest = attempt
            self._lease = lease
            self._last_download_path = None
            self._session_timeout_seconds = config.session_timeout_seconds
            try:
                context = self._client_factory(config)
                self._context = context
                client = await context.__aenter__()
                self._client = client
                await client.open_authentication_page()
                if config.download_dir is not None:
                    client.capture_downloads(config.download_dir, self._record_download)
                client.on_context_closed(
                    lambda: self._schedule_context_closed(attempt.attempt_id)
                )
            except BaseException as exc:
                await self._terminal_failure_locked(attempt, exc)
                raise

            waiting = replace(attempt, state="awaiting_confirmation")
            self._latest = waiting
            self._timeout_task = asyncio.create_task(
                self._expire_after(attempt.attempt_id, config.auth_timeout_seconds),
                name=f"netfacilities-auth-timeout-{attempt.attempt_id}",
            )
            self._auto_confirm_task = asyncio.create_task(
                self._auto_confirm(attempt.attempt_id),
                name=f"netfacilities-auto-confirm-{attempt.attempt_id}",
            )
            logger.info(
                "netfacilities.authentication_started",
                extra={"fields": {"operation_id": str(attempt.attempt_id)}},
            )
            return waiting, True

    async def confirm(self) -> NetFacilitiesAuthenticationSnapshot:
        """Verify the sign-in against the server, save state, keep the window open."""

        async with self._lock:
            attempt = self._require_active_locked()
            client = self._client
            if client is None:  # defensive invariant
                raise RuntimeError("active NetFacilities authentication has no client")
            self._latest = replace(attempt, state="confirming")
            try:
                await client.verify_authentication_page()
                await client.prime_session()
                await client.persist_authentication_state()
            except (NetFacilitiesAuthenticationRequired, NetFacilitiesUnexpectedResponse):
                # Not signed in yet, or the server hiccupped: stay pending with
                # the window open so the operator or the poller can try again.
                self._latest = attempt
                raise
            except BaseException as exc:
                await self._terminal_failure_locked(attempt, exc)
                raise

            signed_in = replace(attempt, state="signed_in", signed_in_at=_now())
            self._latest = signed_in
            self._cancel_task(self._timeout_task)
            self._timeout_task = asyncio.create_task(
                self._expire_after(attempt.attempt_id, self._session_timeout_seconds),
                name=f"netfacilities-session-timeout-{attempt.attempt_id}",
            )
            self._cancel_task(self._auto_confirm_task)
            self._auto_confirm_task = None
            logger.info(
                "netfacilities.authentication_completed",
                extra={"fields": {"operation_id": str(attempt.attempt_id)}},
            )
            return signed_in

    async def cancel(self) -> NetFacilitiesAuthenticationSnapshot:
        """Close the window: abandon a pending sign-in or end the live session."""

        async with self._lock:
            if self._borrow_count > 0:
                raise NetFacilitiesOperationInProgress(
                    "Enrichment is still using the NetFacilities window."
                )
            if self._signed_in_locked():
                current = self._latest
                if current is None:  # defensive type narrowing
                    raise RuntimeError("signed-in session has no snapshot")
                finished = replace(current, state="closed", finished_at=_now())
                event = "netfacilities.session_closed"
            else:
                attempt = self._require_active_locked()
                finished = replace(
                    attempt,
                    state="cancelled",
                    finished_at=_now(),
                    failure="cancelled",
                )
                event = "netfacilities.authentication_cancelled"
            self._latest = finished
            await self._close_locked()
            logger.info(
                event,
                extra={"fields": {"operation_id": str(finished.attempt_id)}},
            )
            return finished

    async def shutdown(self) -> None:
        """Close a pending or live window during application shutdown."""

        async with self._lock:
            current = self._latest
            if current is None:
                return
            if self._signed_in_locked():
                self._latest = replace(current, state="closed", finished_at=_now())
            elif self._active_locked():
                self._latest = replace(
                    current,
                    state="cancelled",
                    finished_at=_now(),
                    failure="cancelled",
                )
            else:
                return
            await self._close_locked()

    # -------------------------------------------------------------- internals

    def _active_locked(self) -> bool:
        return self._latest is not None and self._latest.state in PENDING_STATES

    def _signed_in_locked(self) -> bool:
        return self._latest is not None and self._latest.state == "signed_in"

    def _require_active_locked(self) -> NetFacilitiesAuthenticationSnapshot:
        if not self._active_locked() or self._latest is None:
            raise NetFacilitiesAuthenticationNotPending(
                "No NetFacilities sign-in is waiting for confirmation."
            )
        return self._latest

    @staticmethod
    def _cancel_task(task: asyncio.Task[None] | None) -> None:
        if task is not None and task is not asyncio.current_task():
            task.cancel()

    async def _record_download(self, path: Path) -> None:
        """Remember the CSV the operator exported. Other downloads are saved
        by the client but not surfaced (spec D3)."""

        async with self._lock:
            current = self._latest
            if current is None or not (self._active_locked() or self._signed_in_locked()):
                return
            if path.suffix.casefold() != CSV_SUFFIX:
                return
            self._last_download_path = path
            self._latest = replace(
                current,
                last_download_filename=path.name,
                last_download_at=_now(),
            )
            attempt_id = current.attempt_id
        logger.info(
            "netfacilities.csv_captured",
            extra={"fields": {"operation_id": str(attempt_id)}},
        )

    def _schedule_context_closed(self, attempt_id: UUID) -> None:
        task = asyncio.get_running_loop().create_task(
            self._handle_context_closed(attempt_id),
            name=f"netfacilities-window-closed-{attempt_id}",
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _handle_context_closed(self, attempt_id: UUID) -> None:
        async with self._lock:
            current = self._latest
            if current is None or current.attempt_id != attempt_id:
                return
            if self._signed_in_locked():
                self._latest = replace(current, state="closed", finished_at=_now())
            elif self._active_locked():
                self._latest = replace(
                    current,
                    state="cancelled",
                    finished_at=_now(),
                    failure="cancelled",
                )
            else:
                return
            await self._close_locked()
            logger.info(
                "netfacilities.window_closed",
                extra={"fields": {"operation_id": str(attempt_id)}},
            )

    async def _auto_confirm(self, attempt_id: UUID) -> None:
        """Confirm on the operator's behalf once a page leaves the login screen.

        The local URL check is the cheap gate; ``confirm`` still performs the
        server probe, so a false local positive only costs one request (spec
        §3.4, D2).
        """

        try:
            while True:
                await asyncio.sleep(self._auto_confirm_poll_seconds)
                async with self._lock:
                    current = self._latest
                    if (
                        current is None
                        or current.attempt_id != attempt_id
                        or current.state != "awaiting_confirmation"
                    ):
                        return
                    client = self._client
                if client is None:
                    return
                try:
                    await client.verify_authentication_page()
                except NetFacilitiesAuthenticationRequired:
                    continue
                try:
                    await self.confirm()
                    return
                except (NetFacilitiesAuthenticationRequired, NetFacilitiesUnexpectedResponse):
                    await asyncio.sleep(self._auto_confirm_retry_seconds)
                except NetFacilitiesError:
                    return
        except asyncio.CancelledError:
            pass

    async def _expire_after(self, attempt_id: UUID, seconds: float) -> None:
        """Close the window when a pending sign-in or an idle session outlives
        its limit. A borrowed window is re-checked instead of closed."""

        try:
            await asyncio.sleep(seconds)
            while True:
                async with self._lock:
                    current = self._latest
                    if (
                        current is None
                        or current.attempt_id != attempt_id
                        or not (self._active_locked() or self._signed_in_locked())
                    ):
                        return
                    if self._borrow_count == 0:
                        was_signed_in = self._signed_in_locked()
                        self._latest = replace(
                            current,
                            state="timed_out",
                            finished_at=_now(),
                            failure="timed_out",
                        )
                        await self._close_locked()
                        logger.info(
                            "netfacilities.session_timed_out"
                            if was_signed_in
                            else "netfacilities.authentication_timed_out",
                            extra={"fields": {"operation_id": str(attempt_id)}},
                        )
                        return
                await asyncio.sleep(self._timeout_retry_seconds)
        except asyncio.CancelledError:
            pass

    async def _terminal_failure_locked(
        self,
        attempt: NetFacilitiesAuthenticationSnapshot,
        exc: BaseException,
    ) -> None:
        self._latest = replace(
            attempt,
            state="failed",
            finished_at=_now(),
            failure="unavailable",
        )
        logger.error(
            "netfacilities.authentication_failed",
            extra={
                "fields": {
                    "operation_id": str(attempt.attempt_id),
                    "failure": (
                        "expected" if isinstance(exc, NetFacilitiesError) else "unexpected"
                    ),
                    "exc_type": type(exc).__name__,
                }
            },
        )
        await self._close_locked()

    async def _close_locked(self) -> None:
        timeout_task = self._timeout_task
        self._timeout_task = None
        self._cancel_task(timeout_task)
        auto_confirm_task = self._auto_confirm_task
        self._auto_confirm_task = None
        self._cancel_task(auto_confirm_task)

        context = self._context
        lease = self._lease
        self._context = None
        self._client = None
        self._lease = None
        try:
            if context is not None:
                await context.__aexit__(None, None, None)
        except Exception as exc:
            logger.error(
                "netfacilities.authentication_close_failed",
                extra={"fields": {"exc_type": type(exc).__name__}},
            )
        finally:
            if lease is not None:
                await self._profile_gate.release(lease)


authentication_coordinator = NetFacilitiesAuthenticationCoordinator()
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd C:/Users/mcclu/Desktop/inventory_app_git/backend; ./venv/Scripts/python.exe -m pytest tests/test_netfacilities_auth.py -q`
Expected: all pass. If `test_auto_confirm_stays_pending_until_the_server_probe_succeeds` is flaky, raise its `range(300)` loop bound — do not lengthen the sleeps.

Then confirm nothing else broke at this layer:
Run: `cd C:/Users/mcclu/Desktop/inventory_app_git/backend; ./venv/Scripts/python.exe -m pytest tests/test_netfacilities_jobs.py tests/test_netfacilities_routes.py -q`
Expected: **`test_netfacilities_routes.py` has exactly one failure** —
`test_authentication_routes_return_only_safe_attempt_state` constructs a snapshot
with `state="authenticated"`, which the dataclass still accepts but the Pydantic
schema will reject once Task 5 updates it; leave it for Task 5. Everything in
`test_netfacilities_jobs.py` passes.

- [ ] **Step 7: Line count and compile check**

Run: `cd C:/Users/mcclu/Desktop/inventory_app_git/backend; ./venv/Scripts/python.exe -m compileall -q app; (Get-Content app/services/netfacilities_auth.py | Measure-Object -Line).Lines`
(In Git Bash use `wc -l app/services/netfacilities_auth.py` instead of the PowerShell measure.)
Expected: compile clean; the coordinator is under 500 lines.

- [ ] **Step 8: Commit**

```bash
cd C:/Users/mcclu/Desktop/inventory_app_git; git add backend/app/services/netfacilities_live_session.py backend/app/services/netfacilities_auth.py backend/tests/test_netfacilities_auth.py; git commit -m "feat(netfacilities): live session keeps the window open, auto-confirms, records the exported CSV (IMP-039)"
```

---

### Task 4: Job coordinator borrows the live window; lifespan closes jobs before the window

**Files:**
- Modify: `backend/app/services/netfacilities_jobs.py`
- Modify: `backend/app/lifespan.py`
- Test: `backend/tests/test_netfacilities_jobs.py`

**Interfaces:**
- Consumes: `LiveSessionClientContext` (any object with `__aenter__`/`__aexit__` yielding a client).
- Produces: `JobSource`, `NetFacilitiesJobSnapshot.source`, `start(config, *, live_client_context=None)`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_netfacilities_jobs.py`:

```python
class FakeLiveContext:
    def __init__(self, *, enter_error=None):
        self.enter_error = enter_error
        self.entered = 0
        self.exited = 0
        self.client = object()

    async def __aenter__(self):
        self.entered += 1
        if self.enter_error is not None:
            raise self.enter_error
        return self.client

    async def __aexit__(self, *_args):
        self.exited += 1


class RefusingGate:
    async def acquire(self, kind):
        raise AssertionError(f"live-session job must not take the {kind} lease")

    async def release(self, _lease):
        raise AssertionError("live-session job has nothing to release")

    async def active_kind(self):
        return None


def _must_not_launch(_config):
    raise AssertionError("a live-session job must not launch a browser")


async def _never_called(**_kwargs):
    raise AssertionError("enrichment must not run without a client")


def test_live_session_job_borrows_the_client_and_skips_the_profile_gate(tmp_path):
    live = FakeLiveContext()
    captured = {}

    async def enrich(**kwargs):
        captured.update(kwargs)
        return NetFacilitiesEnrichmentSummary(
            candidates=1, requests_attempted=1, fetched=1
        )

    coordinator = NetFacilitiesJobCoordinator(
        session_factory=lambda: None,
        client_factory=_must_not_launch,
        enrichment_runner=enrich,
        profile_gate=RefusingGate(),
    )

    async def exercise():
        started, created = await coordinator.start(
            _config(tmp_path, authenticated=False),
            live_client_context=live,
        )
        assert created
        assert started.source == "live_session"
        finished = await _wait_for_terminal(coordinator, started.job_id)
        assert finished.state == "completed"
        assert finished.source == "live_session"

    asyncio.run(exercise())
    assert live.entered == 1
    assert live.exited == 1
    assert captured["client"] is live.client


def test_saved_state_job_reports_its_source(tmp_path):
    context = FakeClientContext()

    async def enrich(**_kwargs):
        return NetFacilitiesEnrichmentSummary()

    coordinator = NetFacilitiesJobCoordinator(
        client_factory=lambda _config: context,
        enrichment_runner=enrich,
    )

    async def exercise():
        started, _created = await coordinator.start(_config(tmp_path))
        finished = await _wait_for_terminal(coordinator, started.job_id)
        assert started.source == "saved_state"
        assert finished.source == "saved_state"

    asyncio.run(exercise())


def test_live_session_that_lost_authentication_ends_authentication_required(
    tmp_path,
):
    live = FakeLiveContext(
        enter_error=NetFacilitiesAuthenticationRequired("window closed")
    )
    coordinator = NetFacilitiesJobCoordinator(
        client_factory=_must_not_launch,
        enrichment_runner=_never_called,
        profile_gate=RefusingGate(),
    )

    async def exercise():
        started, _created = await coordinator.start(
            _config(tmp_path, authenticated=False),
            live_client_context=live,
        )
        finished = await _wait_for_terminal(coordinator, started.job_id)
        assert finished.state == "authentication_required"
        assert finished.failure == "authentication_required"
        assert finished.source == "live_session"

    asyncio.run(exercise())
    assert live.entered == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd C:/Users/mcclu/Desktop/inventory_app_git/backend; ./venv/Scripts/python.exe -m pytest tests/test_netfacilities_jobs.py -q`
Expected: 3 failures (`unexpected keyword argument 'live_client_context'`, `source` attribute missing).

- [ ] **Step 3: Implement the job coordinator changes**

In `backend/app/services/netfacilities_jobs.py`:

1. After the `FailureClass` alias add:

```python
JobSource: TypeAlias = Literal["live_session", "saved_state"]
```

2. Add a field at the end of `NetFacilitiesJobSnapshot`:

```python
    source: JobSource | None = None
```

3. Replace `start` with:

```python
    async def start(
        self,
        config: NetFacilitiesConfig,
        *,
        live_client_context: NetFacilitiesClientContextProtocol | None = None,
    ) -> tuple[NetFacilitiesJobSnapshot, bool]:
        """Start a batch, or return the currently active batch unchanged.

        With ``live_client_context`` the job reads through the operator's open,
        signed-in window: no saved-state file is needed and no profile lease is
        taken, because the live session already holds it (spec D4, D8).
        """

        if not config.enabled:
            raise NetFacilitiesAuthenticationRequired(
                "NetFacilities enrichment is not enabled on this host."
            )
        if live_client_context is None and not config.has_saved_authentication:
            raise NetFacilitiesAuthenticationRequired(
                "Sign in to NetFacilities before enrichment."
            )

        async with self._lock:
            if self._task is not None and not self._task.done():
                if self._latest is None:  # defensive invariant
                    raise RuntimeError("active NetFacilities task has no job state")
                return self._latest, False

            source: JobSource = (
                "live_session" if live_client_context is not None else "saved_state"
            )
            lease = None
            if live_client_context is None:
                lease = await self._profile_gate.acquire("enrichment")
            job = NetFacilitiesJobSnapshot(job_id=uuid4(), state="queued", source=source)
            self._latest = job
            self._lease = lease
            try:
                self._task = asyncio.create_task(
                    self._run(job.job_id, config, live_client_context, source),
                    name=f"netfacilities-enrichment-{job.job_id}",
                )
            except BaseException:
                self._lease = None
                if lease is not None:
                    await self._profile_gate.release(lease)
                raise
            return job, True
```

   **Note:** the saved-state `self._client_factory(config)` call stays inside
   `_run`'s `try` block (next item). `create_netfacilities_client` raises
   `NetFacilitiesUnavailable` synchronously when the Playwright dependency is
   missing, and `_run` is where that becomes a `failed` / `unavailable` job
   instead of an unhandled exception out of `start`.

4. Change the `_run` signature and its first lines to:

```python
    async def _run(
        self,
        job_id: UUID,
        config: NetFacilitiesConfig,
        live_client_context: NetFacilitiesClientContextProtocol | None,
        source: JobSource,
    ) -> None:
        started_at = datetime.now(timezone.utc)
        started_clock = asyncio.get_running_loop().time()
        await self._set(
            NetFacilitiesJobSnapshot(
                job_id=job_id,
                state="running",
                started_at=started_at,
                source=source,
            )
        )
```

   and replace the line `async with self._client_factory(config) as client:`
   (the first statement inside `try:`) with:

```python
            client_context = (
                live_client_context
                if live_client_context is not None
                else self._client_factory(config)
            )
            async with client_context as client:
```

   (keep the `summary = await self._enrichment_runner(...)` call nested under it
   exactly as it is).

5. Every `await self._finish(job_id, started_at, ...)` call inside `_run` gains
   `source=source,` as a keyword argument (there are five). Add the parameter to
   `_finish` and pass it through:

```python
    async def _finish(
        self,
        job_id: UUID,
        started_at: datetime,
        *,
        state: JobState,
        failure: FailureClass | None,
        source: JobSource,
        summary: NetFacilitiesEnrichmentSummary | None = None,
    ) -> None:
        await self._set(
            NetFacilitiesJobSnapshot(
                job_id=job_id,
                state=state,
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                failure=failure,
                summary=summary,
                source=source,
            )
        )
```

- [ ] **Step 4: Swap the lifespan shutdown order**

In `backend/app/lifespan.py` the `finally:` block becomes:

```python
    finally:
        # Jobs first: a running job may be borrowing the live window, and
        # closing the window under it would turn a clean cancel into a browser
        # error (spec D8).
        await netfacilities_jobs.shutdown()
        await netfacilities_authentication.shutdown()
        await stop_dispatch()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd C:/Users/mcclu/Desktop/inventory_app_git/backend; ./venv/Scripts/python.exe -m pytest tests/test_netfacilities_jobs.py tests/test_netfacilities_auth.py -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
cd C:/Users/mcclu/Desktop/inventory_app_git; git add backend/app/services/netfacilities_jobs.py backend/app/lifespan.py backend/tests/test_netfacilities_jobs.py; git commit -m "feat(netfacilities): enrichment borrows the live window and reports its source (IMP-039)"
```

---

### Task 5: Schemas and router — `signed_in`, cancel-while-borrowed, enrich-prefers-live

**Files:**
- Modify: `backend/app/schemas/netfacilities.py`
- Modify: `backend/app/routers/netfacilities.py`
- Test: `backend/tests/test_netfacilities_routes.py`

**Interfaces:**
- Consumes: Task 3 coordinator API, Task 4 `source`.
- Produces: the API described in spec §6 except the new import route (Task 6).

- [ ] **Step 1: Extend the route-test fakes and fix the stale test**

In `backend/tests/test_netfacilities_routes.py`:

1. Change `from datetime import datetime, timezone` to
   `from datetime import datetime, timedelta, timezone`, and change the errors import to:

```python
from app.integrations.netfacilities.errors import (
    NetFacilitiesAuthenticationRequired,
    NetFacilitiesOperationInProgress,
)
```

2. Replace `FakeJobs.start` with:

```python
    async def start(self, _config, *, live_client_context=None):
        self.live_client_context = live_client_context
        if self.start_error is not None:
            raise self.start_error
        return self.snapshot, True
```

   and add `self.live_client_context = None` to `FakeJobs.__init__`.

3. Replace `FakeAuthentication` with:

```python
class FakeAuthentication:
    def __init__(
        self,
        snapshot=None,
        *,
        confirm_error=None,
        cancel_error=None,
        live=None,
        csv_path=None,
    ):
        self.snapshot = snapshot
        self.confirm_error = confirm_error
        self.cancel_error = cancel_error
        self.live = live
        self.csv_path = csv_path

    async def latest(self):
        return self.snapshot

    async def start(self, _config):
        return self.snapshot, True

    async def confirm(self):
        if self.confirm_error is not None:
            raise self.confirm_error
        return self.snapshot

    async def cancel(self):
        if self.cancel_error is not None:
            raise self.cancel_error
        return self.snapshot

    async def borrow_live_client(self):
        return self.live

    def captured_csv_path(self):
        return self.csv_path
```

4. After `_authentication_snapshot` add:

```python
def _signed_in_snapshot(*, filename=None, signed_in_at=None):
    now = datetime.now(timezone.utc)
    return NetFacilitiesAuthenticationSnapshot(
        attempt_id=uuid4(),
        state="signed_in",
        started_at=now,
        signed_in_at=signed_in_at or now,
        last_download_filename=filename,
        last_download_at=now if filename else None,
    )
```

5. In `test_authentication_routes_return_only_safe_attempt_state` change
   `_authentication_snapshot(state="authenticated")` to
   `_signed_in_snapshot()` (rename the local variable to `signed_in`) and the
   assertion to `assert confirmed.state == "signed_in"`.

6. Every call to `router.start_netfacilities_enrichment(` in this file (there are
   two: in `test_start_translates_missing_authentication_to_recoverable_409` and
   `test_job_response_contains_approved_progress_and_counts_but_no_source_values`)
   gains the keyword argument `authentication=FakeAuthentication(),`.

- [ ] **Step 2: Write the failing tests**

Append:

```python
def test_session_reports_the_live_window_and_its_captured_csv(tmp_path, monkeypatch):
    config = _config(tmp_path, authenticated=False)
    monkeypatch.setattr(router, "load_netfacilities_config", lambda: config)

    result = asyncio.run(
        router.netfacilities_session(
            _user=SimpleNamespace(),
            jobs=FakeJobs(),
            authentication=FakeAuthentication(
                _signed_in_snapshot(filename="WorkOrders.csv")
            ),
        )
    )

    assert result.state == "signed_in"
    assert result.latest_authentication.state == "signed_in"
    assert result.latest_authentication.signed_in_at is not None
    assert result.latest_authentication.last_download_filename == "WorkOrders.csv"
    assert "profile" not in result.model_dump()


def test_session_reports_expired_when_a_live_job_lost_authentication(
    tmp_path, monkeypatch
):
    # Saved state exists too, so this must still be "expired", never "ready".
    config = _config(tmp_path)
    monkeypatch.setattr(router, "load_netfacilities_config", lambda: config)
    signed_in_at = datetime.now(timezone.utc)
    job = NetFacilitiesJobSnapshot(
        job_id=uuid4(),
        state="authentication_required",
        started_at=signed_in_at,
        finished_at=signed_in_at + timedelta(seconds=5),
        failure="authentication_required",
        source="live_session",
    )

    result = asyncio.run(
        router.netfacilities_session(
            _user=SimpleNamespace(),
            jobs=FakeJobs(job),
            authentication=FakeAuthentication(
                _signed_in_snapshot(signed_in_at=signed_in_at)
            ),
        )
    )

    assert result.state == "expired"
    assert "Close it and log in again" in result.message


def test_session_ignores_an_authentication_failure_from_before_this_sign_in(
    tmp_path, monkeypatch
):
    config = _config(tmp_path, authenticated=False)
    monkeypatch.setattr(router, "load_netfacilities_config", lambda: config)
    signed_in_at = datetime.now(timezone.utc)
    job = NetFacilitiesJobSnapshot(
        job_id=uuid4(),
        state="authentication_required",
        started_at=signed_in_at - timedelta(minutes=10),
        finished_at=signed_in_at - timedelta(minutes=9),
        failure="authentication_required",
        source="live_session",
    )

    result = asyncio.run(
        router.netfacilities_session(
            _user=SimpleNamespace(),
            jobs=FakeJobs(job),
            authentication=FakeAuthentication(
                _signed_in_snapshot(signed_in_at=signed_in_at)
            ),
        )
    )

    assert result.state == "signed_in"


def test_enrich_hands_the_live_window_to_the_job(tmp_path, monkeypatch):
    config = _config(tmp_path, authenticated=False)
    monkeypatch.setattr(router, "load_netfacilities_config", lambda: config)
    snapshot = NetFacilitiesJobSnapshot(
        job_id=uuid4(), state="queued", source="live_session"
    )
    jobs = FakeJobs(snapshot=snapshot)
    live = object()

    response = asyncio.run(
        router.start_netfacilities_enrichment(
            _user=SimpleNamespace(),
            jobs=jobs,
            authentication=FakeAuthentication(live=live),
        )
    )

    assert jobs.live_client_context is live
    assert response.source == "live_session"


def test_cancel_is_refused_while_enrichment_borrows_the_window():
    authentication = FakeAuthentication(
        _signed_in_snapshot(),
        cancel_error=NetFacilitiesOperationInProgress("busy"),
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            router.cancel_netfacilities_authentication(
                _user=SimpleNamespace(),
                authentication=authentication,
            )
        )

    assert exc.value.status_code == 409
    assert "still using" in exc.value.detail


def test_cancel_reports_a_closed_live_session():
    closed = NetFacilitiesAuthenticationSnapshot(
        attempt_id=uuid4(),
        state="closed",
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
        signed_in_at=datetime.now(timezone.utc),
    )

    result = asyncio.run(
        router.cancel_netfacilities_authentication(
            _user=SimpleNamespace(),
            authentication=FakeAuthentication(closed),
        )
    )

    assert result.state == "closed"
    assert result.failure is None
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd C:/Users/mcclu/Desktop/inventory_app_git/backend; ./venv/Scripts/python.exe -m pytest tests/test_netfacilities_routes.py -q`
Expected: the 6 new tests and `test_authentication_routes_return_only_safe_attempt_state` fail (Pydantic literal errors, `TypeError` on the new `authentication` argument).

- [ ] **Step 4: Update the schemas**

In `backend/app/schemas/netfacilities.py`:

1. Add after `NetFacilitiesJobState`:

```python
NetFacilitiesJobSource = Literal["live_session", "saved_state"]
```

2. Add to `NetFacilitiesEnrichmentJob`, after `counts`:

```python
    # Which session read the source: the operator's open window or the saved
    # storage-state file. Lets the card say which one it is using.
    source: NetFacilitiesJobSource | None = None
```

3. Replace `NetFacilitiesAuthenticationAttempt` with:

```python
class NetFacilitiesAuthenticationAttempt(BaseModel):
    """Process-local headed sign-in / live-session state.

    ``last_download_filename`` is a bare filename -- never a directory or path;
    the operator already knows where their Downloads folder is.
    """

    attempt_id: UUID
    state: Literal[
        "starting",
        "awaiting_confirmation",
        "confirming",
        "signed_in",
        "closed",
        "failed",
        "cancelled",
        "timed_out",
    ]
    started_at: datetime
    finished_at: datetime | None = None
    failure: Literal["unavailable", "cancelled", "timed_out"] | None = None
    signed_in_at: datetime | None = None
    last_download_filename: str | None = None
    last_download_at: datetime | None = None
```

4. In `NetFacilitiesCapability.state` add `"signed_in",` after `"authenticating",`.

- [ ] **Step 5: Update the router**

In `backend/app/routers/netfacilities.py`:

1. Extend the auth-service import to also bring `PENDING_STATES`:

```python
from app.services.netfacilities_auth import (
    PENDING_STATES,
    NetFacilitiesAuthenticationCoordinator,
    NetFacilitiesAuthenticationSnapshot,
    authentication_coordinator,
)
```

2. Replace `_job_response` and `_authentication_response` with:

```python
def _job_response(snapshot: NetFacilitiesJobSnapshot) -> NetFacilitiesEnrichmentJob:
    counts = None
    if snapshot.summary is not None:
        counts = NetFacilitiesEnrichmentCounts(**asdict(snapshot.summary))
    return NetFacilitiesEnrichmentJob(
        job_id=snapshot.job_id,
        state=snapshot.state,
        started_at=snapshot.started_at,
        finished_at=snapshot.finished_at,
        current_work_order_number=snapshot.current_work_order_number,
        failure=snapshot.failure,
        counts=counts,
        source=snapshot.source,
    )


def _authentication_response(
    snapshot: NetFacilitiesAuthenticationSnapshot,
) -> NetFacilitiesAuthenticationAttempt:
    return NetFacilitiesAuthenticationAttempt(
        attempt_id=snapshot.attempt_id,
        state=snapshot.state,
        started_at=snapshot.started_at,
        finished_at=snapshot.finished_at,
        failure=snapshot.failure,
        signed_in_at=snapshot.signed_in_at,
        last_download_filename=snapshot.last_download_filename,
        last_download_at=snapshot.last_download_at,
    )


def _live_session_lost_authentication(
    session: NetFacilitiesAuthenticationSnapshot,
    job: NetFacilitiesJobSnapshot | None,
) -> bool:
    """A job that borrowed *this* window and was told to sign in again."""

    return (
        job is not None
        and job.state == "authentication_required"
        and job.source == "live_session"
        and job.finished_at is not None
        and session.signed_in_at is not None
        and job.finished_at >= session.signed_in_at
    )
```

3. Replace the body of `netfacilities_session` (keep the decorator and
   signature) with:

```python
    """Report safe sign-in, capability, and latest-job state."""

    try:
        config = load_netfacilities_config()
    except NetFacilitiesUnavailable:
        return NetFacilitiesCapability(
            available=False,
            state="unavailable",
            message="NetFacilities enrichment is unavailable on this host.",
        )
    if not config.enabled:
        return NetFacilitiesCapability(
            available=False,
            state="unavailable",
            message="NetFacilities enrichment is disabled on this host.",
        )

    latest = await jobs.latest()
    latest_authentication = await authentication.latest()
    latest_response = _job_response(latest) if latest is not None else None
    authentication_response = (
        _authentication_response(latest_authentication)
        if latest_authentication is not None
        else None
    )

    def capability(state: str, message: str) -> NetFacilitiesCapability:
        return NetFacilitiesCapability(
            available=True,
            interactive_authentication_available=(
                config.interactive_authentication_available
            ),
            state=state,
            message=message,
            latest_job=latest_response,
            latest_authentication=authentication_response,
        )

    if latest is not None and latest.state in {"queued", "running"}:
        return capability(
            "running", "NetFacilities is seeking Task/Symptom and Priority data."
        )
    if (
        latest_authentication is not None
        and latest_authentication.state in PENDING_STATES
    ):
        return capability(
            "authenticating",
            "Complete NetFacilities sign-in in the opened browser, then confirm "
            "it here.",
        )
    if latest_authentication is not None and latest_authentication.state == "signed_in":
        if _live_session_lost_authentication(latest_authentication, latest):
            return capability(
                "expired",
                "Your NetFacilities window is no longer logged in. Close it and "
                "log in again.",
            )
        return capability(
            "signed_in",
            "NetFacilities is open and logged in. Export the work-order CSV in "
            "that window; it is saved to your Downloads folder and can be "
            "imported from here.",
        )
    if not config.has_saved_authentication:
        message = (
            "Sign in to NetFacilities before enrichment."
            if config.interactive_authentication_available
            else (
                "Saved NetFacilities authentication is missing; update the Render "
                "secret file."
            )
        )
        return capability("not_authenticated", message)
    if (
        latest is not None
        and latest.state == "authentication_required"
        and not _saved_state_refreshed_after(config, latest)
    ):
        message = (
            "NetFacilities authentication expired; sign in again."
            if config.interactive_authentication_available
            else (
                "NetFacilities authentication expired; refresh the Render secret "
                "file and redeploy."
            )
        )
        return capability("expired", message)
    return capability(
        "ready", "Saved NetFacilities authentication is ready for enrichment."
    )
```

4. In `cancel_netfacilities_authentication`: change the docstring to
   `"""Close the dedicated window: a pending sign-in or the live session."""`,
   update the `409` description in the decorator to
   `"No NetFacilities window is open, or enrichment is still using it."`, and
   add this `except` **before** the existing `NetFacilitiesAuthenticationNotPending`
   one:

```python
    except NetFacilitiesOperationInProgress as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Enrichment is still using the NetFacilities window; wait for it "
                "to finish."
            ),
        ) from exc
```

5. In `start_netfacilities_enrichment`: add the parameter

```python
    authentication: NetFacilitiesAuthenticationCoordinator = Depends(
        get_netfacilities_authentication_coordinator
    ),
```

   change the docstring to `"""Start one batch through the open window if there is one, else the saved state."""`,
   and replace `snapshot, _created = await jobs.start(config)` with:

```python
        live = await authentication.borrow_live_client()
        snapshot, _created = await jobs.start(config, live_client_context=live)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd C:/Users/mcclu/Desktop/inventory_app_git/backend; ./venv/Scripts/python.exe -m pytest tests/test_netfacilities_routes.py tests/test_route_role_gates.py -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
cd C:/Users/mcclu/Desktop/inventory_app_git; git add backend/app/schemas/netfacilities.py backend/app/routers/netfacilities.py backend/tests/test_netfacilities_routes.py; git commit -m "feat(netfacilities): signed_in capability state, cancel closes the live window, enrich prefers it (IMP-039)"
```

---

### Task 6: One-click import of the captured CSV

**Files:**
- Modify: `backend/app/routers/_uploads.py`
- Modify: `backend/app/routers/work_orders.py:596-656`
- Modify: `backend/app/routers/netfacilities.py`
- Test: `backend/tests/test_netfacilities_routes.py`, `backend/tests/test_route_role_gates.py`

**Interfaces:**
- Consumes: `captured_csv_path()` (Task 3).
- Produces: `run_csv_import`, `read_file_capped`, route handler `import_netfacilities_download`.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_route_role_gates.py`, add
`"import_netfacilities_download",` to the parametrize list of
`test_netfacilities_routes_require_techfm_oa_and_document_403` (after
`"get_netfacilities_enrichment",`).

Append to `backend/tests/test_netfacilities_routes.py` (add
`from fastapi import BackgroundTasks, HTTPException` in place of the existing
`from fastapi import HTTPException`, and
`from app.schemas.work_orders import WorkOrderImportResult` to the imports):

```python
def _import_result(**overrides):
    values = {
        "total": 1,
        "created": 1,
        "opened": 0,
        "closed": 0,
        "supervisors_matched": 0,
        "supervisors_unmatched": 1,
        "skipped": 0,
    }
    values.update(overrides)
    return WorkOrderImportResult(**values)


def test_import_download_returns_409_without_a_captured_csv():
    with pytest.raises(HTTPException) as exc:
        router.import_netfacilities_download(
            background=BackgroundTasks(),
            user=SimpleNamespace(id=uuid4()),
            db=object(),
            authentication=FakeAuthentication(),
        )

    assert exc.value.status_code == 409
    assert "Import from CSV" in exc.value.detail


def test_import_download_runs_the_shared_import_pipeline(tmp_path, monkeypatch):
    csv_path = tmp_path / "WorkOrders.csv"
    csv_path.write_bytes(b"WORK ORDER\n12345678\n")
    received = {}

    def fake_run_csv_import(db, background, *, data, user):
        received.update(db=db, background=background, data=data, user=user)
        return _import_result()

    monkeypatch.setattr(router, "run_csv_import", fake_run_csv_import)
    db = object()
    background = BackgroundTasks()
    user = SimpleNamespace(id=uuid4())

    result = router.import_netfacilities_download(
        background=background,
        user=user,
        db=db,
        authentication=FakeAuthentication(csv_path=csv_path),
    )

    assert result.created == 1
    assert received == {
        "db": db,
        "background": background,
        "data": b"WORK ORDER\n12345678\n",
        "user": user,
    }


def test_import_download_reports_a_missing_file_as_409(tmp_path):
    with pytest.raises(HTTPException) as exc:
        router.import_netfacilities_download(
            background=BackgroundTasks(),
            user=SimpleNamespace(id=uuid4()),
            db=object(),
            authentication=FakeAuthentication(csv_path=tmp_path / "gone.csv"),
        )

    assert exc.value.status_code == 409
    assert "no longer where it was saved" in exc.value.detail
    assert str(tmp_path) not in exc.value.detail


def test_import_download_refuses_an_oversized_file(tmp_path, monkeypatch):
    csv_path = tmp_path / "huge.csv"
    csv_path.write_bytes(b"x")
    monkeypatch.setattr(router, "MAX_CSV_UPLOAD_BYTES", 0)

    with pytest.raises(HTTPException) as exc:
        router.import_netfacilities_download(
            background=BackgroundTasks(),
            user=SimpleNamespace(id=uuid4()),
            db=object(),
            authentication=FakeAuthentication(csv_path=csv_path),
        )

    assert exc.value.status_code == 413
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd C:/Users/mcclu/Desktop/inventory_app_git/backend; ./venv/Scripts/python.exe -m pytest tests/test_netfacilities_routes.py tests/test_route_role_gates.py -q`
Expected: the 4 new route tests fail with `AttributeError: module ... has no attribute 'import_netfacilities_download'`; the role-gate test fails with `route 'import_netfacilities_download' not found`.

- [ ] **Step 3: Add the bounded file read**

In `backend/app/routers/_uploads.py`:

1. In the module docstring, change "The two upload routes (`POST /barcodes/decode`,
   `POST /work-orders/import`) are its only callers" to "The two upload routes
   (`POST /barcodes/decode`, `POST /work-orders/import`) and the one on-host
   file route (`POST /integrations/netfacilities/downloads/import`) are its only
   callers".
2. Add `from pathlib import Path` to the imports.
3. Append:

```python
def read_file_capped(path: Path, *, limit: int, what: str) -> bytes:
    """Bounded read of a file already on this host.

    The CSV the live NetFacilities window saved is imported from disk rather
    than uploaded, so it bypasses the multipart parser -- and would bypass the
    cap too, unless it is applied here. Same limit, same 413, same log line as
    the upload routes. ``OSError`` (missing, unreadable) propagates: the caller
    decides what a vanished file means.
    """

    size = path.stat().st_size
    if size > limit:
        _log_rejection(what, limit=limit, size=size)
        raise _too_large(what, limit)
    with path.open("rb") as handle:
        return handle.read(limit)
```

- [ ] **Step 4: Extract the import pipeline**

In `backend/app/routers/work_orders.py`, immediately **above** the
`@router.post("/import", ...)` decorator add:

```python
def run_csv_import(
    db: Session,
    background: BackgroundTasks,
    *,
    data: bytes,
    user: User,
) -> WorkOrderImportResult:
    """Run one CSV import end to end.

    The idempotent service call, the two realtime invalidations, and the
    batched supervisor notification, in that order. Shared by
    `POST /work-orders/import` (an upload) and
    `POST /integrations/netfacilities/downloads/import` (the CSV the live
    NetFacilities window saved) so the two can never drift -- an import route
    that called only the service would silently drop the push (spec §3.6).
    """
    try:
        summary = wo_service.import_work_orders(db, csv_bytes=data, user=user)
        _emit_review_queue_changed(None)
        _emit_status_changed(None)
    except DomainError as exc:
        raise to_http(exc)
    # Popped rather than passed through: the routing map exists to address a
    # notification and is not part of the API contract, and
    # `WorkOrderImportResult` would have to grow a field to carry it.
    routing = summary.pop("supervisor_routing", {})
    if routing:
        _notify(
            notifications_service.notify_supervisors_assigned_bulk,
            db,
            background,
            routing=routing,
            actor_id=user.id,
        )
    return WorkOrderImportResult(**summary)
```

Then replace the body of `import_work_orders` **after its docstring** (from
`data = read_capped(...)` to `return WorkOrderImportResult(**summary)`) with:

```python
    data = read_capped(file, limit=MAX_CSV_UPLOAD_BYTES, what="CSV file")
    return run_csv_import(db, background, data=data, user=user)
```

- [ ] **Step 5: Add the route**

In `backend/app/routers/netfacilities.py`:

1. Add imports:

```python
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.routers._uploads import MAX_CSV_UPLOAD_BYTES, read_file_capped
from app.routers.work_orders import run_csv_import
from app.schemas.work_orders import WorkOrderImportResult
```

   (merge the `fastapi` line with the existing one).

2. Append at the end of the file:

```python
@router.post(
    "/downloads/import",
    response_model=WorkOrderImportResult,
    responses={
        **_forbidden(),
        409: {
            "description": (
                "No CSV has been exported through the live NetFacilities window, "
                "or the file is gone."
            )
        },
        413: {"description": "CSV exceeds the upload size cap."},
    },
)
def import_netfacilities_download(
    background: BackgroundTasks,
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    db: Session = Depends(get_db),
    authentication: NetFacilitiesAuthenticationCoordinator = Depends(
        get_netfacilities_authentication_coordinator
    ),
) -> WorkOrderImportResult:
    """Import the CSV the operator most recently exported through the live
    NetFacilities window (spec D5).

    One click instead of a file chooser, through exactly the pipeline
    `POST /work-orders/import` uses. The file's location stays on the server;
    the operator only ever sees its name. Deliberately `def`, not `async def`,
    for the same reason as the upload route: the import is one long
    synchronous transaction and belongs in the threadpool.
    """

    path = authentication.captured_csv_path()
    if path is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "No CSV has been exported through the NetFacilities window yet. "
                "Export it there, or use Import from CSV…."
            ),
        )
    try:
        data = read_file_capped(path, limit=MAX_CSV_UPLOAD_BYTES, what="CSV file")
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "The exported CSV is no longer where it was saved. Export it "
                "again, or use Import from CSV…."
            ),
        ) from exc
    return run_csv_import(db, background, data=data, user=user)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd C:/Users/mcclu/Desktop/inventory_app_git/backend; ./venv/Scripts/python.exe -m pytest tests/test_netfacilities_routes.py tests/test_route_role_gates.py tests/test_netfacilities_auth.py tests/test_netfacilities_jobs.py tests/test_netfacilities_client.py tests/test_netfacilities_config.py -q`
Expected: all pass. Then run the import-related suites that need the DB only if `DATABASE_URL` is reachable (they skip otherwise):
`./venv/Scripts/python.exe -m pytest tests -q -k "import" `
Expected: pass or skip; no failures.

- [ ] **Step 7: Commit**

```bash
cd C:/Users/mcclu/Desktop/inventory_app_git; git add backend/app/routers/_uploads.py backend/app/routers/work_orders.py backend/app/routers/netfacilities.py backend/tests/test_netfacilities_routes.py backend/tests/test_route_role_gates.py; git commit -m "feat(netfacilities): import the CSV captured from the live window in one click (IMP-039)"
```

---

### Task 7: Frontend — Integrations card follows the live session

**Files:**
- Modify: `backend/static/api.js:548-585`
- Modify: `backend/static/pages/integrations.html:22-45`
- Modify: `backend/static/views/workOrders.js` (element consts near line 91-111; NetFacilities section 2068-2300; `handleImport` 2311-2338)
- Modify: `backend/static/tips.js:256-259`

**Interfaces:**
- Consumes: Task 5/6 API shapes.
- Produces: nothing downstream; manual validation per spec §11.

- [ ] **Step 1: API wrapper**

In `backend/static/api.js`, after `apiGetNetFacilitiesEnrichment` add:

```js
// Import the CSV the live NetFacilities window saved (Admin+). The server
// reads it from disk; the browser never sees a path.
export async function apiImportNetFacilitiesDownload() {
  return parseResponse(await fetch(
    "/integrations/netfacilities/downloads/import",
    { method: "POST", credentials: "include" },
  ));
}
```

- [ ] **Step 2: Markup**

In `backend/static/pages/integrations.html`:

- `Sign in to NetFacilities` → `Log in to NetFacilities` (the sign-in button text).
- `Cancel sign-in` → `Close NetFacilities`.
- Directly after the `wo-import-btn` button line add:

```html
                        <button id="wo-netfacilities-import-download-btn" type="button" hidden>Import downloaded CSV</button>
```

- [ ] **Step 3: Tooltip copy**

In `backend/static/tips.js` replace the `text` of `"integrations.netfacilities"` with:

```js
    text: "Log in to NetFacilities opens a window that stays open. Export the work-order CSV there; it lands in your Downloads folder and Import downloaded CSV brings it in, then Task/Symptom and Priority fill in through the same window. Import from CSV still accepts any file you already have. For Client exports the billing sheet with totals and receipts, scoped by the dropdown beside it.",
```

- [ ] **Step 4: workOrders.js — imports, elements, state**

1. In the `import { ... } from "../api.js"` block that already lists
   `apiStartNetFacilitiesEnrichment`, add `apiImportNetFacilitiesDownload,`.
2. After `const netFacilitiesOpenBtn = ...` add:

```js
const netFacilitiesImportDownloadBtn = document.getElementById("wo-netfacilities-import-download-btn");
```

3. After `let netFacilitiesPollingJobId = null;` add:

```js
let netFacilitiesSessionPolling = false;
```

4. After the `NETFACILITIES_ACTIVE_AUTH_STATES` constant add:

```js
// Capability states in which the card keeps refreshing on its own, so that
// auto-confirm, a saved CSV, and a closed window show up without a click.
const NETFACILITIES_LIVE_STATES = new Set(["authenticating", "signed_in"]);
const NETFACILITIES_SESSION_POLL_MS = 3000;
```

- [ ] **Step 5: workOrders.js — replace `updateNetFacilitiesControls`**

```js
function updateNetFacilitiesControls(capability) {
  const authentication = capability && capability.latest_authentication;
  const authActive = Boolean(
    authentication && NETFACILITIES_ACTIVE_AUTH_STATES.has(authentication.state),
  );
  // "Window open" is read from the attempt, not the capability, so that an
  // `expired` capability with the window still open (a live job lost auth)
  // offers Close instead of a second Log in.
  const windowSignedIn = Boolean(authentication && authentication.state === "signed_in");
  const windowOpen = authActive || windowSignedIn;
  const signedIn = Boolean(capability && capability.state === "signed_in");
  const available = Boolean(capability && capability.available);
  const interactiveAuthentication = Boolean(
    capability && capability.interactive_authentication_available,
  );
  const enrichmentRunning = Boolean(capability && capability.state === "running");
  const hasCsv = Boolean(authentication && authentication.last_download_filename);

  if (netFacilitiesSignInBtn) {
    const hide = !available || !interactiveAuthentication || windowOpen || enrichmentRunning;
    netFacilitiesSignInBtn.hidden = hide;
    netFacilitiesSignInBtn.disabled = hide;
    netFacilitiesSignInBtn.textContent = capability && capability.state === "ready"
      ? "Log in again"
      : "Log in to NetFacilities";
  }
  if (netFacilitiesConfirmBtn) {
    netFacilitiesConfirmBtn.hidden = !authActive;
    netFacilitiesConfirmBtn.disabled = !authentication
      || authentication.state !== "awaiting_confirmation";
  }
  if (netFacilitiesCancelBtn) {
    netFacilitiesCancelBtn.hidden = !windowOpen;
    netFacilitiesCancelBtn.disabled = !authentication
      || authentication.state === "confirming"
      || enrichmentRunning;
  }
  if (netFacilitiesImportDownloadBtn) {
    netFacilitiesImportDownloadBtn.hidden = !(signedIn && hasCsv);
    netFacilitiesImportDownloadBtn.disabled = enrichmentRunning
      || Boolean(netFacilitiesPollingJobId);
  }
  if (netFacilitiesEnrichBtn) {
    netFacilitiesEnrichBtn.hidden = !available;
    netFacilitiesEnrichBtn.disabled = !capability
      || !(capability.state === "ready" || signedIn)
      || Boolean(netFacilitiesPollingJobId);
  }
}
```

- [ ] **Step 6: workOrders.js — job description and signed-in rendering**

Replace `netFacilitiesReauthenticationAction` and `renderNetFacilitiesJob` with:

```js
function netFacilitiesReauthenticationAction() {
  return netFacilitiesCapability
    && netFacilitiesCapability.interactive_authentication_available
    ? "Log in again"
    : "Refresh the saved authentication secret and redeploy";
}

// Pure: one job snapshot -> the line the card shows and its message kind.
// Split from the renderer so the signed-in view can prefix a job result to
// its own guidance in a single status line.
function describeNetFacilitiesJob(job) {
  if (job.state === "queued" || job.state === "running") {
    const currentRequest = job.current_work_order_number
      ? ` Currently requesting work order ${job.current_work_order_number}.`
      : "";
    return { text: `Seeking Task/Symptom and Priority in NetFacilities…${currentRequest}`, kind: "" };
  }
  if (job.state === "completed") {
    return { text: `NetFacilities enrichment completed: ${netFacilitiesCountsMessage(job)}.`, kind: "success" };
  }
  if (job.state === "authentication_required") {
    return {
      text: `NetFacilities authentication is missing or expired. ${netFacilitiesReauthenticationAction()}, then click Import Tasks and Priority.`,
      kind: "error",
    };
  }
  if (job.state === "timed_out") {
    return { text: `NetFacilities enrichment timed out with partial results: ${netFacilitiesCountsMessage(job)}.`, kind: "error" };
  }
  if (job.state === "cancelled") {
    return { text: "NetFacilities enrichment stopped when the local app shut down.", kind: "error" };
  }
  return {
    text: "NetFacilities enrichment failed without changing unapproved work-order fields. Try again or log in again.",
    kind: "error",
  };
}

function renderNetFacilitiesJob(job) {
  if (!job || !netFacilitiesStatus) return;
  const described = describeNetFacilitiesJob(job);
  setMessage(netFacilitiesStatus, described.text, described.kind);
}

// The signed-in status line: the latest job's result, if it ran in this
// session, followed by what to do next in the open window.
function renderNetFacilitiesSignedIn(capability) {
  const job = capability.latest_job;
  const authentication = capability.latest_authentication;
  const parts = [];
  let kind = "success";
  const jobFinished = job && job.state !== "queued" && job.state !== "running";
  const jobIsFromThisSession = jobFinished
    && job.finished_at && authentication && authentication.signed_in_at
    && new Date(job.finished_at) >= new Date(authentication.signed_in_at);
  if (jobIsFromThisSession) {
    const described = describeNetFacilitiesJob(job);
    parts.push(described.text);
    kind = described.kind || kind;
  }
  if (authentication && authentication.last_download_filename) {
    parts.push(`Saved ${authentication.last_download_filename} to your Downloads folder. Click Import downloaded CSV to import it and fill in Task/Symptom and Priority.`);
  } else {
    parts.push("NetFacilities is open and logged in. Export the work-order CSV in that window; it is saved to your Downloads folder and can be imported from here.");
  }
  setMessage(netFacilitiesStatus, parts.join(" "), kind);
}
```

- [ ] **Step 7: workOrders.js — replace `refreshNetFacilitiesSession` and add polling**

```js
async function refreshNetFacilitiesSession({ preserveJobResult = false } = {}) {
  if (!isAdminPlus() || !netFacilitiesStatus) return null;
  try {
    const capability = await apiGetNetFacilitiesSession();
    netFacilitiesCapability = capability;
    updateNetFacilitiesControls(capability);
    const job = capability.latest_job;
    const jobActive = job && (job.state === "queued" || job.state === "running");
    if (jobActive) {
      renderNetFacilitiesJob(job);
      void pollNetFacilitiesJob(job.job_id);
    } else if (capability.state === "signed_in") {
      renderNetFacilitiesSignedIn(capability);
    } else if (preserveJobResult && job) {
      renderNetFacilitiesJob(job);
    } else if (capability.state === "authenticating") {
      setMessage(netFacilitiesStatus, "Log in to NetFacilities in the window that opened. This page will notice when you're in.", "");
    } else if (capability.state === "ready") {
      setMessage(netFacilitiesStatus, "Saved NetFacilities login is ready. Choose a downloaded CSV to import it and seek Task/Symptom and Priority, or log in to export a fresh one.", "success");
    } else if (capability.state === "not_authenticated" || capability.state === "expired") {
      setMessage(netFacilitiesStatus, `${capability.message} Then export and import the CSV, or use Import Tasks and Priority to retry existing rows.`, "error");
    } else {
      setMessage(netFacilitiesStatus, `${capability.message} CSV import still works normally.`, "");
    }
    if (NETFACILITIES_LIVE_STATES.has(capability.state)) ensureNetFacilitiesSessionPolling();
    return capability;
  } catch (err) {
    netFacilitiesCapability = null;
    updateNetFacilitiesControls(null);
    setMessage(netFacilitiesStatus, friendlyError(err, "NetFacilities status is unavailable. CSV import still works normally."), "error");
    return null;
  }
}

// Keep the card current while the window is open. One loop at a time; it
// ends on its own when the session leaves the live states. Skips a tick
// while the tab is hidden or the 1-second job poll is already refreshing.
function ensureNetFacilitiesSessionPolling() {
  if (netFacilitiesSessionPolling) return;
  netFacilitiesSessionPolling = true;
  void (async () => {
    try {
      while (netFacilitiesCapability && NETFACILITIES_LIVE_STATES.has(netFacilitiesCapability.state)) {
        await new Promise((resolve) => setTimeout(resolve, NETFACILITIES_SESSION_POLL_MS));
        if (document.hidden || netFacilitiesPollingJobId) continue;
        await refreshNetFacilitiesSession();
      }
    } finally {
      netFacilitiesSessionPolling = false;
    }
  })();
}
```

- [ ] **Step 8: workOrders.js — imports share one tail**

Replace `handleImport` with:

```js
// Everything that follows a successful import, whether the CSV was uploaded
// or captured from the live window: summary, list reload, then enrichment
// through whichever session is available (the open window or saved state).
async function afterWorkOrderImport(r) {
  // Only the new work orders are worth reporting: re-imported numbers keep
  // their own routing, and rows the import passed over changed nothing.
  setMessage(importMessage, importSummary(r), "success");
  // Reset caches so a re-import reflects fresh data, then reload the list.
  usersLoaded = false;
  filterOptionsLoaded = false;
  await loadWorkOrders();
  const capability = await refreshNetFacilitiesSession();
  if (capability && (capability.state === "ready" || capability.state === "signed_in")) {
    await runNetFacilitiesEnrichment();
  }
}

async function handleImport() {
  const file = importFile.files && importFile.files[0];
  if (!file) return;
  setMessage(importMessage, "Importing…", "");
  importBtn.disabled = true;
  try {
    const r = await apiImportWorkOrders(file);
    await afterWorkOrderImport(r);
  } catch (err) {
    setMessage(importMessage, friendlyError(err, "Could not import that file."), "error");
  } finally {
    importBtn.disabled = false;
    importFile.value = "";  // allow re-selecting the same file
  }
}

async function importNetFacilitiesDownload() {
  if (netFacilitiesImportDownloadBtn) netFacilitiesImportDownloadBtn.disabled = true;
  setMessage(importMessage, "Importing…", "");
  try {
    const r = await apiImportNetFacilitiesDownload();
    await afterWorkOrderImport(r);
  } catch (err) {
    setMessage(importMessage, friendlyError(err, "Could not import the downloaded CSV."), "error");
    updateNetFacilitiesControls(netFacilitiesCapability);
  }
}
```

Then, next to the existing `if (importFile) importFile.addEventListener("change", handleImport);` add:

```js
if (netFacilitiesImportDownloadBtn) {
  netFacilitiesImportDownloadBtn.addEventListener("click", importNetFacilitiesDownload);
}
```

- [ ] **Step 9: Syntax check**

Run: `node --check C:/Users/mcclu/Desktop/inventory_app_git/backend/static/views/workOrders.js; node --check C:/Users/mcclu/Desktop/inventory_app_git/backend/static/api.js; node --check C:/Users/mcclu/Desktop/inventory_app_git/backend/static/tips.js`
Expected: no output (clean).

Then grep for leftovers:
`grep -n "Sign in to NetFacilities\|Sign in again\|Cancel sign-in" C:/Users/mcclu/Desktop/inventory_app_git/backend/static/views/workOrders.js C:/Users/mcclu/Desktop/inventory_app_git/backend/static/pages/integrations.html`
Expected: no matches.

- [ ] **Step 10: Commit**

```bash
cd C:/Users/mcclu/Desktop/inventory_app_git; git add backend/static/api.js backend/static/pages/integrations.html backend/static/views/workOrders.js backend/static/tips.js; git commit -m "feat(integrations): NetFacilities card follows the live window and imports the captured CSV (IMP-039)"
```

---

### Task 8: Documentation reconciliation

**Files:**
- Modify: `docs/open-work.md` (insert before `### IMP-037 — Field-help ...`)
- Modify: `docs/current-state.md` (§ NetFacilities enrichment, lines 1672-1836; Task Routing Map row at line 134)
- Modify: `docs/endpoint-map.md` (rows NF1c/NF1d near line 134; flow bullets near 470-490; schema paragraph at 982)
- Modify: `docs/project-summary.md` (lines 29-33, 92-95, 213)

- [ ] **Step 1: Backlog entry**

In `docs/open-work.md`, insert directly above the line
`### IMP-037 — Field-help `?` tooltips — CLOSED`:

```markdown
### IMP-039 — NetFacilities live session — IN PROGRESS

- **Logged** 2026-08-28 · *Integrations / Work Orders* · designed with the owner the same day
- Spec: `docs/superpowers/specs/2026-08-28-netfacilities-live-session-design.md`
- Plan: `docs/superpowers/plans/2026-08-28-netfacilities-live-session.md`

The dedicated NetFacilities window stays open after login (new `signed_in`
state, auto-confirmed once a page leaves the login screen), the CSV the
operator exports from it is saved under its real name in their Downloads
folder, enrichment runs through that same signed-in window instead of a second
headless browser, and `POST /integrations/netfacilities/downloads/import`
imports the captured CSV in one click through the same pipeline as the upload
route. Local Windows only; Render keeps the secret-file path. Manual
acceptance is spec §11 — step 4 doubles as the still-pending live acceptance of
the `/myhome` priming fix.

```

- [ ] **Step 2: `current-state.md` — NetFacilities section**

1. Task Routing Map row (line 134): append to the *last* cell of the
   `| NetFacilities enrichment |` row: ` · **IMP-039 live session:** the headed
   window stays open after login, downloads are saved to the operator's
   Downloads folder, enrichment borrows the open window, and
   `downloads/import` imports the captured CSV`.

2. In the `### NetFacilities enrichment` section, immediately **before** the
   paragraph starting `The TechFM OA and above then uses the existing **Import from CSV…** chooser`,
   insert:

```markdown
#### Live session (IMP-039, 2026-08-28)

On the local Windows host the sign-in ceremony is a **live session**. `POST
/auth/start` opens the dedicated headed Chrome as before; a coordinator task
then polls once a second with a local URL check and, once any page is on the
allowlisted host and off the login path, calls `confirm` on the operator's
behalf. `confirm` runs the server-verified probe (`GET /myhome`, the priming
request), saves `playwright-storage-state.json` for the headless fallback, and
**leaves the window open** in the new `signed_in` state. **I finished signing
in** still calls the same `confirm` as a manual fallback; a probe that fails
keeps the session pending rather than failing it.

The headed context now launches with `accept_downloads=True` and saves every
download the operator triggers under its suggested filename into
`NETFACILITIES_DOWNLOAD_DIR` — default `%USERPROFILE%\Downloads` when that
directory exists, else `<profile>\downloads`; a collision appends ` (1)`,
` (2)`. Only a `.csv` is recorded as the captured CSV; the snapshot and the API
carry its **filename only**, never a path. The app never *initiates* a
download.

`POST /work-orders/enrich` asks the session coordinator for the live client
first. When the window is signed in, the job reads through the persistent
context's `request` API (the same pure-HTTP path priming uses), takes no
profile lease, and reports `source: live_session`; otherwise it runs the
saved-state headless path (`source: saved_state`). While a job borrows the
window, `POST /auth/cancel` is 409 and the idle timeout defers. `POST
/auth/cancel` now also closes a signed-in window (`state: closed`); the
operator closing the window by hand, `NETFACILITIES_SESSION_TIMEOUT_SECONDS`
(default 7200) of idleness, and application shutdown do the same. Shutdown
cancels the job before closing the window.

`POST /downloads/import` imports the captured CSV through
`routers.work_orders.run_csv_import` — the function `POST /work-orders/import`
itself now calls — so both paths emit the same realtime invalidations and the
same batched supervisor push. It is 409 when nothing was captured or the file
is gone, 413 over `MAX_CSV_UPLOAD_BYTES`.

Capability precedence in `GET /session`: `unavailable` → `running` →
`authenticating` → `signed_in` → `not_authenticated` → `expired` → `ready`,
except that a signed-in window whose *own* job (`source: live_session`,
finished after `signed_in_at`) ended `authentication_required` reports
`expired` with *Your NetFacilities window is no longer logged in. Close it and
log in again.* The `authenticated` attempt state no longer exists. Render is
unchanged: no window, secret-file state, `download_dir` is `None`.
```

3. Replace the sentence
   `The application never downloads the vendor CSV or receives NetFacilities credential fields.`
   with
   `The application never initiates a NetFacilities download or receives credential fields; on the local host it saves the CSV the operator exports through the live window.`

4. In the API table (the six `| … | `/integrations/netfacilities/…` |` rows near
   line 1812), change the `auth/cancel` row's behaviour cell to
   `close the dedicated window — a pending sign-in (`cancelled`) or the live session (`closed`); 409 while enrichment borrows it`,
   append ` — prefers the open signed-in window (`source: live_session`), else saved state` to the `work-orders/enrich` row's behaviour cell, and add after the last row:

```markdown
| POST | `/integrations/netfacilities/downloads/import` | techfm_oa+ | import the CSV most recently saved from the live window through the shared `run_csv_import` pipeline; 409 when none was captured or the file is gone, 413 over the CSV cap |
```

5. In the `- **Local Windows:**` bullet near line 1681, after `The app saves
   `playwright-storage-state.json`; the CLI `auth` command is a fallback.` add:
   ` `NETFACILITIES_SESSION_TIMEOUT_SECONDS` and `NETFACILITIES_DOWNLOAD_DIR` (both optional) tune the live session; see *Live session (IMP-039)* below.`

- [ ] **Step 3: `endpoint-map.md`**

1. Row `NF1c` (`/auth/cancel`): change its behaviour text to
   `no DB; closes the dedicated window in any state — `cancelled` when pending, `closed` when signed in — and is 409 while enrichment borrows it`.
2. After row `NF3` add:

```markdown
| NF4 | POST | `/integrations/netfacilities/downloads/import` | techfm_oa+ | `netfacilities.py` → `netfacilities_auth.captured_csv_path` → `_uploads.read_file_capped` → `work_orders.run_csv_import` → `services/work_orders.import_work_orders` | **work_orders** (find-or-create by number), same realtime + push side effects as WO import | `apiImportNetFacilitiesDownload` | `workOrders.js` (Integrations card, **Import downloaded CSV**) |
```

3. In the flow bullets (the one beginning `- On the local Windows host, an Admin may call apiStartNetFacilitiesAuthentication`), replace that bullet with:

```markdown
- On the local Windows host, an Admin calls `apiStartNetFacilitiesAuthentication`
  and completes credentials/CAPTCHA/MFA in the dedicated headed browser. The
  coordinator confirms on its own once a page leaves the login screen
  (`apiConfirmNetFacilitiesAuthentication` remains the manual fallback) and the
  window **stays open** (`state: signed_in`). Downloads the Admin triggers there
  are saved to their Downloads folder; a `.csv` shows up as
  `latest_authentication.last_download_filename`. `apiCancelNetFacilitiesAuthentication`
  closes the window. On Render, interactive sign-in is unavailable and the saved
  state comes from a protected secret file. Authentication and enrichment share
  one process-local operation lease; a job that borrows the live window runs
  under the session's lease. Responses never contain credentials, browser
  storage, paths, or source values.
```

   and in the bullet beginning `- After CSV import succeeds, workOrders.js checks`, change
   `On the configured local Windows host or Render service with ready saved auth state, it calls`
   to
   `When the state is `signed_in` (the open window) or `ready` (saved auth state), it calls`,
   and change `One process-local job snapshots` to
   `One process-local job (`source: live_session` through the open window, else `saved_state`) snapshots`.
   Add after that bullet:

```markdown
- `workOrders.js` (**Import downloaded CSV**) calls `apiImportNetFacilitiesDownload`
  → `POST /integrations/netfacilities/downloads/import`, which imports the CSV the
  live window most recently saved through the same `run_csv_import` the upload
  route uses, then continues into the enrichment flow above.
```

4. In `### NetFacilities (`schemas/netfacilities.py`)`: change `All six routes`
   to `All seven routes`; change the capability literal list to
   `unavailable|not_authenticated|authenticating|signed_in|ready|running|expired`;
   after `**`NetFacilitiesAuthenticationAttempt`** returns only an attempt ID, lifecycle state, timestamps, and a safe failure class.`
   add ` Lifecycle states are `starting|awaiting_confirmation|confirming|signed_in|closed|failed|cancelled|timed_out`; a signed-in attempt also carries `signed_in_at`, and `last_download_filename` / `last_download_at` name the CSV most recently saved from the window (filename only).`;
   after `optional aggregate `counts`` add `, and `source` (`live_session|saved_state`)`.
   Append a paragraph:

```markdown
`POST /downloads/import` has no request body and returns `WorkOrderImportResult`
(the upload route's schema). 409 when no CSV has been captured in this process
or the file has since been removed; 413 over the CSV cap; `DomainError`s map
exactly as on the upload route.
```

- [ ] **Step 4: `project-summary.md`**

1. In the `- **NetFacilities enrichment**` bullet (line 29), after
   `It never creates a work order — CSV import remains the sole create path.`
   add: ` Since IMP-039 the local sign-in is a **live session**: the window
   stays open, the CSV exported from it is saved to the operator's Downloads
   folder, enrichment borrows the open window, and **Import downloaded CSV**
   imports the capture in one click.`
2. Line 92-93: `**79 router operations** across 11 routers (78 HTTP + the `/ws` WebSocket)` → `**80 router operations** across 11 routers (79 HTTP + the `/ws` WebSocket)`; `**82 total**` → `**83 total**`.
3. Line 213: `- 79 router operations across 11 routers, including work-order` → `- 80 router operations across 11 routers, including the NetFacilities `downloads/import` route, work-order`.
4. Under "Capabilities added after the improvement batch include:" append a bullet:

```markdown
- NetFacilities live session (IMP-039): sign-in auto-confirms and keeps the
  headed window open; downloads from it are saved under their real names;
  enrichment runs through the open window (`source: live_session`) with the
  saved-state headless path as fallback; `POST
  /integrations/netfacilities/downloads/import` imports the captured CSV
  through the shared `run_csv_import` pipeline.
```

5. Refresh the test-count baseline: run
   `cd C:/Users/mcclu/Desktop/inventory_app_git/backend; ./venv/Scripts/python.exe -m pytest --collect-only -q | Select-Object -Last 1`
   (Git Bash: `| tail -1`) and replace both `1135 tests` figures (lines 95 and
   198) with the collected number and today's date (2026-08-28).

- [ ] **Step 5: Whitespace check and commit**

Run: `cd C:/Users/mcclu/Desktop/inventory_app_git; git diff --check`
Expected: no output.

```bash
cd C:/Users/mcclu/Desktop/inventory_app_git; git add docs/open-work.md docs/current-state.md docs/endpoint-map.md docs/project-summary.md; git commit -m "docs: record the NetFacilities live session, its route, states, and settings (IMP-039)"
```

---

### Task 9: Final verification and handoff

**Files:** none edited.

- [ ] **Step 1: Offline suites**

Run: `cd C:/Users/mcclu/Desktop/inventory_app_git/backend; ./venv/Scripts/python.exe -m pytest tests/test_netfacilities_auth.py tests/test_netfacilities_jobs.py tests/test_netfacilities_routes.py tests/test_netfacilities_config.py tests/test_netfacilities_client.py tests/test_netfacilities_poc.py tests/test_netfacilities_diagnostic.py tests/test_netfacilities_parser.py tests/test_netfacilities_service.py tests/test_route_role_gates.py tests/test_docs_endpoints.py -q`
Expected: all pass.

- [ ] **Step 2: Whole suite**

Run: `cd C:/Users/mcclu/Desktop/inventory_app_git/backend; ./venv/Scripts/python.exe -m pytest tests -q`
Expected: all pass, or DB-backed tests **skip** if `DATABASE_URL` is unreachable
(the local Postgres on port 8801 must be up for them to run). Report the exact
tail line to the owner either way — CI is the authoritative pass count.

- [ ] **Step 3: Compile and syntax**

Run: `cd C:/Users/mcclu/Desktop/inventory_app_git/backend; ./venv/Scripts/python.exe -m compileall -q app scripts; node --check static/views/workOrders.js; node --check static/api.js; node --check static/tips.js`
Expected: clean.

- [ ] **Step 4: Secret-safety grep**

Run: `cd C:/Users/mcclu/Desktop/inventory_app_git; git grep -n "download_dir\|captured_csv_path\|_last_download_path" -- backend/app/routers backend/app/schemas`
Expected: the only hits are in `routers/netfacilities.py` inside
`import_netfacilities_download` (reading the path) — none in a response model,
`detail=` string, or log call.

- [ ] **Step 5: Handoff — do not merge**

Report to the owner:

1. The branch name and the list of commits (`git log --oneline main..HEAD`).
2. The exact test tail lines from Steps 1–2.
3. Spec §11's eight manual checks, verbatim, as the owner's click-through
   list — the implementer does **not** start the server.
4. That merging `netfacilities-live-session` into `main` deploys to production
   via CI, so it waits for the owner's explicit go-ahead after the manual
   checks.

---

## Self-review (performed while writing this plan)

**Spec coverage.** D1 → Task 3 (`confirm` keeps the window, `cancel`/close
paths). D2 → Task 3 (`_auto_confirm`, manual `confirm` retained). D3 → Task 1
(`download_dir`) + Task 2 (`capture_downloads`, `_unique_download_path`,
`accept_downloads=True`) + Task 3 (`_record_download`, CSV-only). D4 → Task 4
(borrowed context, no gate) + Task 5 (router borrows) + Task 2 protocol
(`get_work_order` on the auth client). D5 → Task 6. D6 → Task 3 (`confirm`
still persists). D7 → snapshot carries filename only; Task 9 Step 4 grep. D8 →
Task 3 (`_borrow_count`, cancel 409, timeout defers) + Task 4 lifespan order.
D9 → Task 7 polling. D10 → each task's tests; no live request. §6 states and
routes → Tasks 5–6. §7 config → Task 1. §9 matrix → Task 7 Step 5. §11/§12 →
Tasks 8–9.

**Placeholder scan.** No TBD/TODO; every code step carries the code.

**Type consistency.** `captured_csv_path()` is sync everywhere (coordinator,
route, fakes). `borrow_live_client()` async, returns `LiveSessionClientContext |
None`; the fake returns `self.live`. `start(config, *, live_client_context=None)`
matches the router call and `FakeJobs.start`. `NetFacilitiesJobSnapshot.source`
is set in `start`, the running snapshot, and `_finish`. Schema literal for the
attempt state matches `AuthenticationState`. The frontend reads
`latest_authentication.signed_in_at` and `last_download_filename`, both present
in `_authentication_response`.
