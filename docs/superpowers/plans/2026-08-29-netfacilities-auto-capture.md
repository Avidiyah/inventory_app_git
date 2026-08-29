# NetFacilities Auto-Capture → Import → Enrich Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the broken CSV capture path, then turn one click of *Download CSV* in the Steel live view into an unattended import → enrichment → push chain.

**Architecture:** Two phases separated by a production gate. Phase 1 is a
handful of lines in the Steel adapter and the poll loop — path
normalization, a guarded loop, retryable `_seen_files` — plus the test
fakes whose absence let the bug ship. It is deployed and proven before
Phase 2 exists. Phase 2 adds one shared `_capture_and_dispatch` function
in `netfacilities_cloud_auth.py` that both the automatic trigger and the
manual button call, so the two paths cannot drift, plus a Playwright
`download` listener as a latency optimisation over a still-present
safety-net poll.

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy / Playwright (async) /
`steel-sdk==0.19.0` / pytest (no `pytest-asyncio` — every async exercise is
wrapped in a plain `def test_...(): asyncio.run(...)`) / vanilla-JS
frontend under `backend/static`.

**Spec:** `docs/superpowers/specs/2026-08-29-netfacilities-auto-capture-design.md`

---

## Global Constraints

- **Role gate is unchanged: TechFM OA+** (`roles.ROLE_TECHFM_OA`). E1.
- **No `pytest-asyncio`.** Async tests are `def test_x(): asyncio.run(_exercise())`.
- **`cloud_steel.py` is the only module allowed to import the Steel SDK or
  Playwright,** and both imports stay lazy — the repo-wide
  `test_boundary_modules_remain_lazy_without_concrete_dependencies`
  invariant must keep passing.
- **Never hold `self._lock` across a provider, import, or enrichment
  call.** The existing loops copy `provider`/`cloud_session` out under the
  lock and release it before awaiting. Import takes seconds; holding the
  lock would block `latest()` and the whole status endpoint.
- **Timings (E12), all env-configurable via `cloud_config.py`'s
  `_positive_seconds` helper:** signed-in ceremony deadline **600 s**;
  safety-net capture poll **5 s**; enrichment collision retry cap **120 s**.
- **CSP forbids inline `style=` attributes.** Frontend changes use classes
  or CSSOM, never a `style=` string.
- **`docs/notification-events.md` is the single trigger table.** Any push
  added here adds rows there in the same commit. Event-name constants live
  in `backend/app/domain/notifications.py`.
- **`run_csv_import` is not refactored** (E11). Two live routes depend on it.

---

## Review findings folded into this plan

The spec is sound and its diagnosis checks out against the code — I
verified `DOWNLOAD_PATH = "/downloads"` at `cloud_steel.py:28`, the
verbatim `path` passed to `download()` at `cloud_steel.py:127`,
`_seen_files.add` before the download at `:126`, the unguarded
`poll_downloaded_csv` call at `netfacilities_cloud_auth.py:192`, the
`except asyncio.CancelledError`-only handler at `:177`, and the deadline-free
`while True` at `:181`. `FakeSteelClient` (test file, `:86`) genuinely has
no `files` resource and `FakeContext` (`:38`) genuinely has no `new_page`
or `new_cdp_session` — so the existing tests exercise the `except
Exception` branch of the download-behavior setup, exactly as §6 claims.

Six things the spec asserts but does not fully specify. Each has a task
below.

1. **Timings are hardcoded in the spec; the house pattern is env-driven.**
   Every other cloud timing is a `NetFacilitiesCloudConfig` field parsed by
   `_positive_seconds`. Task 5 makes all three E12 values config fields
   rather than module constants.
2. **The frontend already auto-enriches after a cloud import.**
   `afterWorkOrderImport` (`workOrders.js:2306-2325`) calls
   `runNetFacilitiesEnrichment()` whenever the user has a saved session.
   Once the chain owns enrichment (E8), that client call double-fires.
   E5 keeps it from corrupting anything — the second `jobs.start()` returns
   `created=False` — but it burns the chain's 120 s retry cap and narrates a
   phantom queue. Task 10 removes the client-side call for the cloud path.
3. **Nothing marks a capture consumed.** §4.5 says the manual button is
   hidden "unless a capture is sitting unconsumed", but §4.2 never clears
   `ceremony.captured_csv` or `last_download_filename`. Task 6 adds an
   explicit `capture_consumed` flag; the button keys off it.
4. **New snapshot fields must also be added to the Pydantic schema.**
   §4.2 records the import result and job id on the snapshot and §4.5 has
   the poll carry them, but `NetFacilitiesCloudSessionStatus`
   (`schemas/netfacilities.py:71`) is a closed model — undeclared fields
   never reach the browser. Task 9 adds them in both places.
5. **`_resolve_cloud_enrichment_context` is not a pure move.** It takes a
   `User` ORM object but only ever reads `user.id`. The chain holds a
   `user_id: UUID` and no `User`. Task 7 moves it *and* changes the
   parameter to `user_id: UUID`, updating the one router call site.
6. **Moving `setDownloadBehavior` to a browser-level CDP session also
   removes the stray blank page** that `context.new_page()` currently
   creates. That page is what a signed-in user may be looking at in the
   live view. Task 3 sequences the CDP setup *before*
   `client.open_authentication_page()` so the ceremony's only page is the
   NetFacilities sign-in page.

One thing I am deliberately not changing: §3's open question about whether
`page.on("download")` fires over `connect_over_cdp`. E3's safety-net poll
makes the answer optional, and Task 8 logs which path won so production
settles it.

---

## File Structure

**Phase 1**

| File | Responsibility |
| --- | --- |
| `backend/app/integrations/netfacilities/cloud_steel.py` | `_relative()` normalization, `/files`, retryable `_seen_files`, zero-byte/`.crdownload` skip, browser-level CDP download behavior |
| `backend/tests/test_netfacilities_cloud_steel.py` | `FakeFilesResource`, `FakeContext.new_page`/`new_cdp_session`, `FakeBrowser.new_browser_cdp_session`, normalization + capture tests |
| `backend/app/services/netfacilities_cloud_auth.py` | guard the capture loop so a vendor error cannot kill it |
| `backend/tests/test_netfacilities_cloud_auth.py` | provider-error-does-not-kill-the-loop test |

**Phase 2**

| File | Responsibility |
| --- | --- |
| `backend/app/integrations/netfacilities/cloud_config.py` | three new timing fields |
| `backend/app/integrations/netfacilities/cloud_steel.py` | `download` listener recording capture events |
| `backend/app/services/netfacilities_cloud_enrichment.py` | **new** — `resolve_cloud_enrichment_context(config, db, user_id)`, moved out of the router |
| `backend/app/services/netfacilities_cloud_auth.py` | `_capture_and_dispatch`, ceremony expiry, consumption flag, push |
| `backend/app/domain/notifications.py` | two new event constants + message text |
| `backend/app/services/notifications.py` | `notify_netfacilities_chain_finished` |
| `backend/app/routers/netfacilities.py` | manual button route delegates to the shared chain |
| `backend/app/schemas/netfacilities.py` | new status fields |
| `backend/static/views/workOrders.js` | chain narration, button gating, stop double-enriching |
| `docs/notification-events.md`, `docs/open-work.md` | registry + backlog |

---

# PHASE 1 — Unblock capture

Ships and deploys on its own. After it, exports stop vanishing and the
existing manual Import button works. **Do not start Phase 2 until Phase 1
has run in production and a real export has been captured** — that is the
spec's §3a gate, and it is what keeps a chain bug from being mistaken for
a capture bug.

---

### Task 1: `_relative()` path normalization (D-A)

**Files:**
- Modify: `backend/app/integrations/netfacilities/cloud_steel.py:27-28` (constants), new module-level function
- Test: `backend/tests/test_netfacilities_cloud_steel.py`

**Interfaces:**
- Produces: `cloud_steel._relative(path: str) -> str` — strips a leading
  `/files/` prefix, then any remaining leading `/`. Used by Task 2.
- Produces: `cloud_steel.DOWNLOAD_PATH == "/files"`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_netfacilities_cloud_steel.py`:

```python
def test_relative_strips_the_files_prefix_the_listing_returns():
    # Steel's listing returns `/files/`-prefixed paths and its download
    # endpoint rejects any leading slash -- the 400 that shipped.
    assert cloud_steel._relative("/files/export.csv") == "export.csv"


def test_relative_strips_a_bare_leading_slash():
    assert cloud_steel._relative("/downloads/export.csv") == "downloads/export.csv"


def test_relative_leaves_an_already_relative_path_alone():
    assert cloud_steel._relative("files/export.csv") == "files/export.csv"
    assert cloud_steel._relative("export.csv") == "export.csv"


def test_relative_keeps_interior_separators():
    # Steel accepts nested relative paths; only the leading slash is fatal.
    assert cloud_steel._relative("/files/a/b/export.csv") == "a/b/export.csv"


def test_download_path_is_steels_documented_directory():
    assert cloud_steel.DOWNLOAD_PATH == "/files"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest backend/tests/test_netfacilities_cloud_steel.py -k relative -v`
Expected: FAIL — `AttributeError: module ... has no attribute '_relative'`.

- [ ] **Step 3: Write the implementation**

In `cloud_steel.py`, replace the `DOWNLOAD_PATH` constant and add the helper
just below it:

```python
CSV_SUFFIX = ".csv"
# Steel's documented download directory. The listing returns paths carrying
# a `/files/` prefix that must be stripped before interpolation -- see
# `_relative`.
DOWNLOAD_PATH = "/files"
FILES_PREFIX = "/files/"


def _relative(path: str) -> str:
    """Steel's Files API rejects any leading `/` in the download path.

    `files.list()` returns `/files/`-prefixed absolute paths and
    `files.download()` interpolates its argument into
    `/v1/sessions/{id}/files/{path}` with `/` percent-encoded, so a leading
    slash survives encoding and reaches the server as `%2F`. That is the
    400 this repairs. Interior separators are fine -- Steel accepts nested
    relative paths -- so only the prefix comes off.
    """
    if path.startswith(FILES_PREFIX):
        return path[len(FILES_PREFIX):]
    return path.lstrip("/")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest backend/tests/test_netfacilities_cloud_steel.py -v`
Expected: PASS, all tests in the file.

- [ ] **Step 5: Commit**

```bash
git add backend/app/integrations/netfacilities/cloud_steel.py backend/tests/test_netfacilities_cloud_steel.py
git commit -m "fix(netfacilities): normalize Steel file paths before download (D-A)"
```

---

### Task 2: `poll_downloaded_csv` — retryable, half-write-safe, normalized

**Files:**
- Modify: `backend/app/integrations/netfacilities/cloud_steel.py:116-132`
- Test: `backend/tests/test_netfacilities_cloud_steel.py`

**Interfaces:**
- Consumes: `_relative()` from Task 1.
- Produces: `poll_downloaded_csv(session) -> tuple[str, bytes] | None`,
  signature unchanged; now skips zero-byte and `.crdownload` entries and
  only records a path in `_seen_files` after a successful read.

- [ ] **Step 1: Write the failing tests**

The existing `FakeSteelClient` has no `files` resource at all — that gap is
why D-A shipped. Add the fake first, then the tests, in
`backend/tests/test_netfacilities_cloud_steel.py`:

```python
class FakeFileEntry:
    def __init__(self, path, size=128):
        self.path = path
        self.size = size


class FakeFileListing:
    def __init__(self, data):
        self.data = data


class FakeDownloadResponse:
    def __init__(self, content):
        self._content = content

    async def read(self):
        return self._content


class FakeFilesResource:
    """Mirrors Steel's real shape: listing returns `/files/`-prefixed
    absolute paths, download takes a *relative* one and 400s otherwise."""

    def __init__(self):
        self.entries = []
        self.requested_paths = []
        self.contents = {}
        self.fail_next_download = False

    async def list(self, _session_id):
        return FakeFileListing(list(self.entries))

    async def download(self, path, *, session_id):  # noqa: ARG002
        self.requested_paths.append(path)
        if path.startswith("/"):
            raise AssertionError(
                "Steel rejects a leading '/' in the download path (400)."
            )
        if self.fail_next_download:
            self.fail_next_download = False
            raise RuntimeError("transient vendor failure")
        return FakeDownloadResponse(self.contents.get(path, b"col\n1\n"))


def _provider_with_files(monkeypatch):
    provider, fake_client = _provider(monkeypatch)
    fake_client.sessions.files = FakeFilesResource()
    context = FakeContext(pages=[FakePage("https://system.netfacilities.com/myhome")])
    browser = FakeBrowser(context)
    monkeypatch.setattr(
        cloud_steel, "_connect_over_cdp", lambda *_args, **_kwargs: _resolved((None, browser))
    )
    return provider, fake_client


def test_poll_downloaded_csv_strips_the_listed_prefix_before_downloading(monkeypatch):
    provider, fake_client = _provider_with_files(monkeypatch)
    files = fake_client.sessions.files
    files.entries = [FakeFileEntry("/files/work-orders.csv")]
    files.contents["work-orders.csv"] = b"NUMBER\n1001\n"

    async def _exercise():
        session = await provider.open_login_session()
        return await provider.poll_downloaded_csv(session)

    found = asyncio.run(_exercise())

    assert found == ("work-orders.csv", b"NUMBER\n1001\n")
    assert files.requested_paths == ["work-orders.csv"]


def test_poll_downloaded_csv_skips_zero_byte_and_partial_entries(monkeypatch):
    provider, fake_client = _provider_with_files(monkeypatch)
    files = fake_client.sessions.files
    files.entries = [
        FakeFileEntry("/files/half.csv", size=0),
        FakeFileEntry("/files/still-writing.csv.crdownload"),
        FakeFileEntry("/files/done.csv"),
    ]

    async def _exercise():
        session = await provider.open_login_session()
        return await provider.poll_downloaded_csv(session)

    filename, _content = asyncio.run(_exercise())

    assert filename == "done.csv"
    assert files.requested_paths == ["done.csv"]


def test_a_failed_download_is_retried_on_the_next_poll(monkeypatch):
    provider, fake_client = _provider_with_files(monkeypatch)
    files = fake_client.sessions.files
    files.entries = [FakeFileEntry("/files/work-orders.csv")]
    files.fail_next_download = True

    async def _exercise():
        session = await provider.open_login_session()
        try:
            await provider.poll_downloaded_csv(session)
        except RuntimeError:
            pass
        return await provider.poll_downloaded_csv(session)

    found = asyncio.run(_exercise())

    # Blacklisting before the read is what made a transient failure permanent.
    assert found is not None
    assert files.requested_paths == ["work-orders.csv", "work-orders.csv"]


def test_an_already_captured_file_is_not_captured_twice(monkeypatch):
    provider, fake_client = _provider_with_files(monkeypatch)
    fake_client.sessions.files.entries = [FakeFileEntry("/files/work-orders.csv")]

    async def _exercise():
        session = await provider.open_login_session()
        first = await provider.poll_downloaded_csv(session)
        second = await provider.poll_downloaded_csv(session)
        return first, second

    first, second = asyncio.run(_exercise())

    assert first is not None
    assert second is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest backend/tests/test_netfacilities_cloud_steel.py -k poll_downloaded -v`
Expected: FAIL — `AssertionError: Steel rejects a leading '/'` on the first
test, and failures on the skip/retry tests.

- [ ] **Step 3: Write the implementation**

Replace `poll_downloaded_csv` in `cloud_steel.py`:

```python
    async def poll_downloaded_csv(
        self, session: _SteelLoginSession
    ) -> tuple[str, bytes] | None:
        listing = await self._client.sessions.files.list(session.session_id)
        for entry in listing.data:
            path = entry.path
            if path in session._seen_files:
                continue
            # A `.crdownload` is Chrome mid-write and a zero-byte entry is
            # an export that has not flushed; capturing either would import
            # half a file.
            if path.casefold().endswith(PARTIAL_SUFFIX):
                continue
            if not path.casefold().endswith(CSV_SUFFIX):
                continue
            if getattr(entry, "size", None) == 0:
                continue
            relative = _relative(path)
            response = await self._client.sessions.files.download(
                relative, session_id=session.session_id
            )
            content = await response.read()
            # Recorded only after a successful read: marking it before the
            # download made one transient vendor failure permanent.
            session._seen_files.add(path)
            return relative.rsplit("/", 1)[-1], content
        return None
```

And add the constant beside `CSV_SUFFIX`:

```python
PARTIAL_SUFFIX = ".crdownload"
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest backend/tests/test_netfacilities_cloud_steel.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/integrations/netfacilities/cloud_steel.py backend/tests/test_netfacilities_cloud_steel.py
git commit -m "fix(netfacilities): make CSV capture retryable and half-write safe"
```

---

### Task 3: Download behavior at the browser level, failing loudly

**Files:**
- Modify: `backend/app/integrations/netfacilities/cloud_steel.py:82-94`
- Test: `backend/tests/test_netfacilities_cloud_steel.py`

**Interfaces:**
- Produces: `open_login_session` raises `NetFacilitiesUnavailable` when
  `Browser.setDownloadBehavior` fails, instead of logging and continuing.
- Produces: `FakeContext.new_page`, `FakeContext.new_cdp_session`,
  `FakeBrowser.new_browser_cdp_session`, `FakeCdpSession` — the surfaces
  Task 8's tests also use.

- [ ] **Step 1: Write the failing tests**

First give the fakes the surface they lack — their absence is why every
existing test silently ran the `except Exception` branch. Edit
`FakeContext` and `FakeBrowser` in
`backend/tests/test_netfacilities_cloud_steel.py`:

```python
class FakeCdpSession:
    def __init__(self, *, fail=False):
        self.sent = []
        self._fail = fail

    async def send(self, method, params=None):
        if self._fail:
            raise RuntimeError("CDP refused setDownloadBehavior")
        self.sent.append((method, params))
        return {}


class FakeContext:
    def __init__(self, *, pages=None, state=None):
        self.pages = pages or []
        self._state = state or {"cookies": []}
        self.closed = False
        self.request = FakeRequestContext()
        self.created_pages = []
        self.handlers = {}

    async def storage_state(self):
        return self._state

    def on(self, event, handler):
        self.handlers[event] = handler

    async def new_page(self):
        page = FakePage("about:blank")
        self.created_pages.append(page)
        self.pages.append(page)
        return page


class FakeBrowser:
    def __init__(self, context, *, cdp_fails=False):
        self.contexts = [context]
        self.closed = False
        self.cdp_session = FakeCdpSession(fail=cdp_fails)

    async def new_browser_cdp_session(self):
        return self.cdp_session

    async def close(self):
        self.closed = True
```

`FakePage` also needs the `on` hook Task 8 uses; add it now so the fake has
one shape:

```python
class FakePage:
    def __init__(self, url):
        self.url = url
        self.handlers = {}

    def on(self, event, handler):
        self.handlers[event] = handler

    async def goto(self, *_args, **_kwargs):
        return None
```

Then the tests:

```python
def test_download_behavior_is_set_on_a_browser_level_cdp_session(monkeypatch):
    provider, _fake_client = _provider(monkeypatch)
    context = FakeContext(pages=[FakePage("https://system.netfacilities.com/account/login")])
    browser = FakeBrowser(context)
    monkeypatch.setattr(
        cloud_steel, "_connect_over_cdp", lambda *_args, **_kwargs: _resolved((None, browser))
    )

    asyncio.run(provider.open_login_session())

    method, params = browser.cdp_session.sent[0]
    assert method == "Browser.setDownloadBehavior"
    assert params["downloadPath"] == "/files"
    assert params["eventsEnabled"] is True
    # No stray blank page: the ceremony's only page is the sign-in page the
    # user is looking at in the live view.
    assert context.created_pages == []


def test_a_ceremony_that_cannot_capture_downloads_fails_to_open(monkeypatch):
    provider, _fake_client = _provider(monkeypatch)
    context = FakeContext(pages=[FakePage("https://system.netfacilities.com/account/login")])
    browser = FakeBrowser(context, cdp_fails=True)
    monkeypatch.setattr(
        cloud_steel, "_connect_over_cdp", lambda *_args, **_kwargs: _resolved((None, browser))
    )

    try:
        asyncio.run(provider.open_login_session())
    except NetFacilitiesUnavailable:
        return
    raise AssertionError("expected NetFacilitiesUnavailable")
```

Add the import at the top of the test file:

```python
from app.integrations.netfacilities.errors import NetFacilitiesUnavailable
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest backend/tests/test_netfacilities_cloud_steel.py -k download_behavior -v`
Expected: FAIL — the first on `browser.cdp_session.sent` being empty (the
adapter still uses `context.new_cdp_session`), the second on no exception
being raised.

- [ ] **Step 3: Write the implementation**

In `open_login_session`, replace the `try`/`except` block:

```python
        context = browser.contexts[0]
        # Browser-level, not page-level: the behavior must outlive any one
        # page, and creating a page here left a stray blank tab in the live
        # view the user is looking at. A ceremony that cannot capture
        # downloads is not a working ceremony, so this no longer swallows.
        try:
            cdp_session = await browser.new_browser_cdp_session()
            await cdp_session.send(
                "Browser.setDownloadBehavior",
                {"behavior": "allow", "downloadPath": DOWNLOAD_PATH, "eventsEnabled": True},
            )
        except Exception as exc:
            logger.error("netfacilities.cloud_download_behavior_setup_failed")
            raise NetFacilitiesUnavailable(
                "Could not prepare the NetFacilities cloud browser for downloads."
            ) from exc
```

- [ ] **Step 4: Run the full adapter and coordinator suites**

Run: `python -m pytest backend/tests/test_netfacilities_cloud_steel.py backend/tests/test_netfacilities_cloud_auth.py backend/tests/test_netfacilities_cloud_routes.py -v`
Expected: PASS. The four pre-existing adapter tests now exercise the real
CDP path rather than the `except` branch.

- [ ] **Step 5: Commit**

```bash
git add backend/app/integrations/netfacilities/cloud_steel.py backend/tests/test_netfacilities_cloud_steel.py
git commit -m "fix(netfacilities): set download behavior browser-wide and fail loudly"
```

---

### Task 4: A vendor error must not kill the capture loop (D-B)

**Files:**
- Modify: `backend/app/services/netfacilities_cloud_auth.py:180-209`
- Test: `backend/tests/test_netfacilities_cloud_auth.py`

**Interfaces:**
- Produces: `_poll_for_csv` survives any exception from
  `provider.poll_downloaded_csv` and keeps polling.

- [ ] **Step 1: Write the failing test**

Give the existing `FakeCloudBrowserProvider` a way to fail once, then assert
the loop recovers. In `backend/tests/test_netfacilities_cloud_auth.py`, add
to `FakeCloudBrowserProvider.__init__`:

```python
        self.csv_poll_calls = 0
        self.raise_on_csv_poll = 0
```

and replace `poll_downloaded_csv`:

```python
    async def poll_downloaded_csv(self, session):
        self.csv_poll_calls += 1
        if self.csv_poll_calls <= self.raise_on_csv_poll:
            raise RuntimeError("Error code: 400 - Bad Request")
        return self.csv_to_return
```

Then the test:

```python
def test_a_provider_error_does_not_kill_the_capture_loop(db):
    # The shipped bug: one BadRequestError unwound the whole poll task and
    # nothing ever polled again for the life of the process.
    provider = FakeCloudBrowserProvider()
    provider.raise_on_csv_poll = 1
    provider.csv_to_return = ("work-orders.csv", b"NUMBER\n1001\n")
    coordinator = NetFacilitiesCloudAuthenticationCoordinator(
        provider_factory=lambda _config: provider,
        session_factory=_session_factory(db),
        poll_seconds=0.01,
    )
    user_id = uuid.uuid4()

    async def _exercise():
        await coordinator.start(user_id, _config())
        for _ in range(60):
            await asyncio.sleep(0.01)
            if coordinator.captured_csv_bytes(user_id) is not None:
                break
        return coordinator.captured_csv_bytes(user_id)

    captured = asyncio.run(_exercise())

    assert provider.csv_poll_calls >= 2
    assert captured == ("work-orders.csv", b"NUMBER\n1001\n")
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest backend/tests/test_netfacilities_cloud_auth.py -k capture_loop -v`
Expected: FAIL — `captured is None`; the `RuntimeError` unwound the task.

- [ ] **Step 3: Write the implementation**

In `netfacilities_cloud_auth.py`, wrap the provider call inside
`_poll_for_csv`:

```python
            try:
                found = await provider.poll_downloaded_csv(cloud_session)
            except asyncio.CancelledError:
                raise
            except Exception:
                # A vendor error is a bad poll, not a dead ceremony. The
                # shipped 400 unwound this task and left the user parked in
                # `signed_in` with nothing ever polling again (D-B).
                logger.exception(
                    "netfacilities.cloud_csv_poll_failed",
                    extra={"fields": {"user_id": str(user_id)}},
                )
                continue
            if found is None:
                continue
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest backend/tests/test_netfacilities_cloud_auth.py -v`
Expected: PASS.

- [ ] **Step 5: Run the whole backend suite, then commit**

Run: `python -m pytest backend/tests -q`
Expected: PASS, no regressions.

```bash
git add backend/app/services/netfacilities_cloud_auth.py backend/tests/test_netfacilities_cloud_auth.py
git commit -m "fix(netfacilities): a vendor error no longer kills the capture loop (D-B)"
```

---

## ⛔ PRODUCTION GATE — do not proceed past this line

Phase 1 merges and deploys. Before any Phase 2 task begins, confirm in
production that a real *Download CSV* click produces a
`netfacilities.cloud_csv_captured` log line and that the manual **Import
downloaded CSV** button imports it. Record the result in
`docs/open-work.md`.

If capture still fails after Phase 1, **stop and re-diagnose** — Phase 2
built on an unproven capture path is exactly the confusion §3a exists to
prevent.

---

# PHASE 2 — The unattended chain

---

### Task 5: Configurable chain timings (E12)

**Files:**
- Modify: `backend/app/integrations/netfacilities/cloud_config.py:35-42, 73-82`
- Test: `backend/tests/test_netfacilities_cloud_config.py`

**Interfaces:**
- Produces: `NetFacilitiesCloudConfig.signed_in_timeout_seconds` (default
  `600`), `.capture_poll_seconds` (default `5`),
  `.enrichment_retry_seconds` (default `120`) — read by Tasks 6 and 8.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_netfacilities_cloud_config.py`, matching the
file's existing `load_netfacilities_cloud_config` call convention:

```python
def test_chain_timings_default_to_the_spec_values():
    config = _load({})

    assert config.signed_in_timeout_seconds == 600
    assert config.capture_poll_seconds == 5
    assert config.enrichment_retry_seconds == 120


def test_chain_timings_are_env_overridable():
    config = _load(
        {
            "NETFACILITIES_CLOUD_SIGNED_IN_TIMEOUT_SECONDS": "300",
            "NETFACILITIES_CLOUD_CAPTURE_POLL_SECONDS": "2",
            "NETFACILITIES_CLOUD_ENRICHMENT_RETRY_SECONDS": "45",
        }
    )

    assert config.signed_in_timeout_seconds == 300
    assert config.capture_poll_seconds == 2
    assert config.enrichment_retry_seconds == 45
```

If the file has no `_load` helper, write one that mirrors how its existing
tests build a settings mapping and call
`load_netfacilities_cloud_config` — read the file first and follow it
rather than inventing a second convention.

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest backend/tests/test_netfacilities_cloud_config.py -k chain_timings -v`
Expected: FAIL — `AttributeError: 'NetFacilitiesCloudConfig' object has no attribute 'signed_in_timeout_seconds'`.

- [ ] **Step 3: Write the implementation**

Add the defaults beside the existing ones in `cloud_config.py`:

```python
# The signed-in half of the ceremony gets its own deadline, under Steel's
# own 15-minute session cap: without one, nothing but an explicit Cancel or
# a process restart ever ended a signed-in ceremony, and the session stayed
# billed (D-C).
DEFAULT_SIGNED_IN_TIMEOUT_SECONDS = 600
# The listener is primary; this is the safety net, so it can be slower than
# the 3 s the capture poll used to run at (E3, E12).
DEFAULT_CAPTURE_POLL_SECONDS = 5
DEFAULT_ENRICHMENT_RETRY_SECONDS = 120
```

Add the fields to the dataclass:

```python
    signed_in_timeout_seconds: int = DEFAULT_SIGNED_IN_TIMEOUT_SECONDS
    capture_poll_seconds: int = DEFAULT_CAPTURE_POLL_SECONDS
    enrichment_retry_seconds: int = DEFAULT_ENRICHMENT_RETRY_SECONDS
```

And parse them alongside the existing two:

```python
        signed_in_timeout_seconds=_positive_seconds(
            values,
            "NETFACILITIES_CLOUD_SIGNED_IN_TIMEOUT_SECONDS",
            DEFAULT_SIGNED_IN_TIMEOUT_SECONDS,
        ),
        capture_poll_seconds=_positive_seconds(
            values,
            "NETFACILITIES_CLOUD_CAPTURE_POLL_SECONDS",
            DEFAULT_CAPTURE_POLL_SECONDS,
        ),
        enrichment_retry_seconds=_positive_seconds(
            values,
            "NETFACILITIES_CLOUD_ENRICHMENT_RETRY_SECONDS",
            DEFAULT_ENRICHMENT_RETRY_SECONDS,
        ),
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest backend/tests/test_netfacilities_cloud_config.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/integrations/netfacilities/cloud_config.py backend/tests/test_netfacilities_cloud_config.py
git commit -m "feat(netfacilities): make the chain timings configurable"
```

---

### Task 6: Ceremony expiry and the consumption flag (D-C, E7)

**Files:**
- Modify: `backend/app/services/netfacilities_cloud_auth.py` — `_Ceremony`,
  `NetFacilitiesCloudAuthenticationSnapshot`, `_poll_for_csv`, `_timeout`
- Test: `backend/tests/test_netfacilities_cloud_auth.py`

**Interfaces:**
- Consumes: `config.signed_in_timeout_seconds`, `config.capture_poll_seconds`
  from Task 5.
- Produces: `_Ceremony.capture_consumed: bool` and
  `NetFacilitiesCloudAuthenticationSnapshot.capture_consumed: bool`,
  read by Tasks 8, 9, 10.
- Produces: a signed-in ceremony past its deadline reaches state
  `timed_out` with `failure="timed_out"` and its Steel session released.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_signed_in_ceremony_expires_and_releases_the_session(db):
    # Observed in production: signed_in for 18 minutes against a session
    # Steel had already reaped, still billed, still advertising a dead
    # live-view URL (D-C).
    provider = FakeCloudBrowserProvider()
    coordinator = NetFacilitiesCloudAuthenticationCoordinator(
        provider_factory=lambda _config: provider,
        session_factory=_session_factory(db),
        poll_seconds=0.01,
    )
    user_id = uuid.uuid4()

    async def _exercise():
        await coordinator.start(user_id, _config(signed_in_timeout_seconds=1, capture_poll_seconds=1))
        for _ in range(300):
            await asyncio.sleep(0.01)
            snapshot = await coordinator.latest(user_id)
            if snapshot.state == "timed_out":
                break
        return await coordinator.latest(user_id)

    snapshot = asyncio.run(_exercise())

    assert snapshot.state == "timed_out"
    assert snapshot.failure == "timed_out"
    assert provider.closed_sessions == ["sess-1"]


def test_an_unconsumed_capture_is_reported_as_unconsumed(db):
    provider = FakeCloudBrowserProvider()
    provider.csv_to_return = ("work-orders.csv", b"NUMBER\n1001\n")
    coordinator = NetFacilitiesCloudAuthenticationCoordinator(
        provider_factory=lambda _config: provider,
        session_factory=_session_factory(db),
        poll_seconds=0.01,
    )
    user_id = uuid.uuid4()

    async def _exercise():
        await coordinator.start(user_id, _config(capture_poll_seconds=1))
        for _ in range(60):
            await asyncio.sleep(0.01)
            if coordinator.captured_csv_bytes(user_id) is not None:
                break
        return await coordinator.latest(user_id)

    snapshot = asyncio.run(_exercise())

    assert snapshot.last_download_filename == "work-orders.csv"
    assert snapshot.capture_consumed is False
```

Extend `_config` in the test file so the new keys are settable:

```python
def _config(**overrides):
    settings = {
        "enabled": True,
        "steel_api_key": "test-key",
        "login_timeout_seconds": 60,
        "signed_in_timeout_seconds": 600,
        "capture_poll_seconds": 5,
        "enrichment_retry_seconds": 120,
    }
    settings.update(overrides)
    return NetFacilitiesCloudConfig(**settings)
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest backend/tests/test_netfacilities_cloud_auth.py -k "expires or unconsumed" -v`
Expected: FAIL — no `capture_consumed` attribute; the ceremony never leaves
`signed_in`.

- [ ] **Step 3: Write the implementation**

Add to the snapshot dataclass:

```python
    capture_consumed: bool = False
```

Add to `_Ceremony`:

```python
    capture_consumed: bool = False
```

Thread `config` through to the capture loop and give it a deadline. In
`_poll_until_signed_in`, change the call site:

```python
                await self._poll_for_csv(user_id, attempt_id, config)
                return
```

and replace `_poll_for_csv`'s signature and loop head:

```python
    async def _poll_for_csv(
        self, user_id: UUID, attempt_id: UUID, config: NetFacilitiesCloudConfig
    ) -> None:
        loop = asyncio.get_running_loop()
        # A signed-in ceremony without a deadline is what left a released
        # Steel session advertised as live for 18 minutes (D-C, E7).
        deadline = loop.time() + config.signed_in_timeout_seconds
        while loop.time() < deadline:
            await asyncio.sleep(config.capture_poll_seconds)
            ...
        await self._timeout(user_id, attempt_id)
```

`_timeout` already closes the session and sets `state="timed_out"`, and it
already re-checks `attempt_id` under the lock — it needs no change.

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest backend/tests/test_netfacilities_cloud_auth.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/netfacilities_cloud_auth.py backend/tests/test_netfacilities_cloud_auth.py
git commit -m "fix(netfacilities): give a signed-in ceremony a deadline (D-C)"
```

---

### Task 7: Move the enrichment-context resolver to the service layer

**Files:**
- Create: `backend/app/services/netfacilities_cloud_enrichment.py`
- Modify: `backend/app/routers/netfacilities.py:117-119, 139-165`
- Test: `backend/tests/test_netfacilities_cloud_enrichment_factory.py`

**Interfaces:**
- Produces: `resolve_cloud_enrichment_context(config: NetFacilitiesConfig,
  db: Session, user_id: UUID) -> tuple[NetFacilitiesClientContextProtocol
  | None, float | None]`. Note the third parameter: the router passed a
  `User` but only read `user.id`, and the chain holds a bare `UUID`.
  Consumed by Task 8.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_netfacilities_cloud_enrichment_factory.py`:

```python
def test_resolve_returns_nothing_for_a_user_with_no_saved_session(db):
    from app.services.netfacilities_cloud_enrichment import (
        resolve_cloud_enrichment_context,
    )

    context, seconds = resolve_cloud_enrichment_context(
        _netfacilities_config(), db, uuid.uuid4()
    )

    assert context is None
    assert seconds is None
```

Build `_netfacilities_config()` the way the file's existing tests build a
`NetFacilitiesConfig` — read it first and reuse that helper if one exists.

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest backend/tests/test_netfacilities_cloud_enrichment_factory.py -k resolve -v`
Expected: FAIL — `ModuleNotFoundError: app.services.netfacilities_cloud_enrichment`.

- [ ] **Step 3: Write the implementation**

Create `backend/app/services/netfacilities_cloud_enrichment.py`:

```python
"""Resolving one user's saved cloud session into an enrichment context.

Lifted out of `routers/netfacilities.py` because the unattended capture
chain needs it too, and the two must not drift. Takes a `user_id` rather
than a `User`: it only ever read `user.id`, and the chain has no ORM user
to hand it.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.integrations.netfacilities.cloud_config import load_netfacilities_cloud_config
from app.integrations.netfacilities.config import NetFacilitiesConfig


def resolve_cloud_enrichment_context(
    config: NetFacilitiesConfig,
    db: Session,
    user_id: UUID,
):
    """The user's own cloud session, ready to reconnect, and the batch
    deadline it must respect (spec §4), or `(None, None)` if they have none
    or theirs has expired (spec D10)."""

    cloud_config = load_netfacilities_cloud_config(config)
    if not cloud_config.enabled:
        return None, None
    from app.integrations.netfacilities.factory import (
        create_netfacilities_cloud_enrichment_client,
    )
    from app.models import NetFacilitiesCloudSession

    row = db.query(NetFacilitiesCloudSession).filter_by(user_id=user_id).one_or_none()
    if row is None or row.expires_at is not None:
        return None, None
    context = create_netfacilities_cloud_enrichment_client(
        cloud_config,
        row.storage_state.encode("ascii"),
        render_document=config.render_document,
        render_settle_ms=config.render_settle_ms,
    )
    return context, cloud_config.batch_session_seconds
```

Delete `_resolve_cloud_enrichment_context` from
`routers/netfacilities.py`, import the new function, and update the one
call site in `start_netfacilities_enrichment`:

```python
        cloud_context, cloud_batch_seconds = resolve_cloud_enrichment_context(
            config, db, user.id
        )
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest backend/tests/test_netfacilities_cloud_enrichment_factory.py backend/tests/test_netfacilities_cloud_routes.py -v`
Expected: PASS — the enrich route still behaves identically.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/netfacilities_cloud_enrichment.py backend/app/routers/netfacilities.py backend/tests/test_netfacilities_cloud_enrichment_factory.py
git commit -m "refactor(netfacilities): move the enrichment-context resolver to services"
```

---

### Task 8: The chain — `_capture_and_dispatch` (E4, E5, E6, E11)

The largest task, and deliberately one task: the import, the conditional
close, and the enrichment retry are a single decision tree, and a reviewer
cannot sensibly approve the close without the import that gates it.

**Files:**
- Modify: `backend/app/services/netfacilities_cloud_auth.py`
- Test: `backend/tests/test_netfacilities_cloud_auth.py`

**Interfaces:**
- Consumes: `resolve_cloud_enrichment_context` (Task 7),
  `config.enrichment_retry_seconds` (Task 5), `capture_consumed` (Task 6).
- Produces: `NetFacilitiesCloudAuthenticationCoordinator.dispatch_capture(
  user_id: UUID) -> NetFacilitiesCloudAuthenticationSnapshot` — the single
  entry point both the automatic trigger and the manual route (Task 9) call.
- Produces: snapshot fields `import_created: int | None`,
  `import_error: str | None`, `enrichment_job_id: UUID | None`,
  `chain_stage: str | None` (`"importing"`, `"imported"`, `"enriching"`,
  `"done"`, `"failed"`).
- Produces: the coordinator gains constructor kwargs
  `import_runner` and `notifier`, defaulting to the real ones, so tests
  substitute them without patching module globals.

- [ ] **Step 1: Write the failing tests**

```python
class FakeImportRunner:
    def __init__(self):
        self.calls = []
        self.raise_domain_error = False

    def __call__(self, db, background, *, data, user_id):  # noqa: ARG002
        self.calls.append((data, user_id))
        if self.raise_domain_error:
            raise DomainError("That file is not a NetFacilities export.")
        return {"created": 3, "supervisors_matched": 1}


class FakeJobs:
    def __init__(self, busy_times=0):
        self.starts = 0
        self.busy_times = busy_times
        self.job_id = uuid.uuid4()

    async def start(self, _config, **_kwargs):
        self.starts += 1
        created = self.starts > self.busy_times
        return _FakeJobSnapshot(self.job_id), created


def test_the_chain_imports_closes_and_enriches(db):
    importer, jobs, notifier = FakeImportRunner(), FakeJobs(), FakeNotifier()
    provider = FakeCloudBrowserProvider()
    provider.csv_to_return = ("work-orders.csv", b"NUMBER\n1001\n")
    coordinator = _coordinator(db, provider, importer, jobs, notifier)
    user_id = uuid.uuid4()

    snapshot = asyncio.run(_run_chain(coordinator, user_id))

    assert importer.calls == [(b"NUMBER\n1001\n", user_id)]
    assert provider.closed_sessions == ["sess-1"]      # E6, success path
    assert jobs.starts == 1
    assert snapshot.state == "closed"
    assert snapshot.import_created == 3
    assert snapshot.enrichment_job_id == jobs.job_id
    assert snapshot.capture_consumed is True
    assert notifier.sent[0]["ok"] is True


def test_a_failed_import_keeps_the_session_open_and_skips_enrichment(db):
    importer, jobs, notifier = FakeImportRunner(), FakeJobs(), FakeNotifier()
    importer.raise_domain_error = True
    provider = FakeCloudBrowserProvider()
    provider.csv_to_return = ("wrong.csv", b"nope\n")
    coordinator = _coordinator(db, provider, importer, jobs, notifier)
    user_id = uuid.uuid4()

    snapshot = asyncio.run(_run_chain(coordinator, user_id))

    # E6: the user re-exports the right file without repeating the ceremony.
    assert provider.closed_sessions == []
    assert snapshot.state == "signed_in"
    assert jobs.starts == 0
    assert snapshot.import_error
    assert snapshot.chain_stage == "failed"
    # Capture retained so the manual button can retry it.
    assert coordinator.captured_csv_bytes(user_id) is not None
    assert notifier.sent[0]["ok"] is False
    assert notifier.sent[0]["stage"] == "import"


def test_enrichment_retries_while_a_batch_is_running(db):
    importer, notifier = FakeImportRunner(), FakeNotifier()
    jobs = FakeJobs(busy_times=2)          # E5: created=False twice, then true
    provider = FakeCloudBrowserProvider()
    provider.csv_to_return = ("work-orders.csv", b"NUMBER\n1001\n")
    coordinator = _coordinator(db, provider, importer, jobs, notifier)
    user_id = uuid.uuid4()

    snapshot = asyncio.run(_run_chain(coordinator, user_id))

    assert jobs.starts == 3
    assert snapshot.enrichment_job_id == jobs.job_id


def test_enrichment_giving_up_leaves_the_import_standing(db):
    importer, notifier = FakeImportRunner(), FakeNotifier()
    jobs = FakeJobs(busy_times=10_000)     # never free
    provider = FakeCloudBrowserProvider()
    provider.csv_to_return = ("work-orders.csv", b"NUMBER\n1001\n")
    coordinator = _coordinator(
        db, provider, importer, jobs, notifier, enrichment_retry_seconds=1
    )
    user_id = uuid.uuid4()

    snapshot = asyncio.run(_run_chain(coordinator, user_id))

    assert snapshot.import_created == 3
    assert snapshot.enrichment_job_id is None
    assert notifier.sent[0]["stage"] == "enrichment"
```

Write the three helpers beside them, in the same file:

```python
class FakeNotifier:
    def __init__(self):
        self.sent = []

    def __call__(self, *, user_id, ok, stage, created, job_id):
        self.sent.append(
            {"user_id": user_id, "ok": ok, "stage": stage, "created": created, "job_id": job_id}
        )


class _FakeJobSnapshot:
    def __init__(self, job_id):
        self.job_id = job_id


def _coordinator(db, provider, importer, jobs, notifier, **config_overrides):
    return NetFacilitiesCloudAuthenticationCoordinator(
        provider_factory=lambda _config: provider,
        session_factory=_session_factory(db),
        poll_seconds=0.01,
        import_runner=importer,
        job_coordinator=jobs,
        notifier=notifier,
    )


async def _run_chain(coordinator, user_id, **config_overrides):
    await coordinator.start(user_id, _config(capture_poll_seconds=1, **config_overrides))
    for _ in range(400):
        await asyncio.sleep(0.01)
        snapshot = await coordinator.latest(user_id)
        if snapshot.chain_stage in {"done", "failed"}:
            break
    return await coordinator.latest(user_id)
```

Add the imports the tests need:

```python
from app.domain.errors import DomainError
```

(Confirm that module path against `routers/work_orders.py`'s own
`DomainError` import before writing it.)

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest backend/tests/test_netfacilities_cloud_auth.py -k chain -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'import_runner'`.

- [ ] **Step 3: Write the implementation**

Add the snapshot fields:

```python
    import_created: int | None = None
    import_error: str | None = None
    enrichment_job_id: UUID | None = None
    chain_stage: ChainStage | None = None
```

with the alias beside the existing ones:

```python
ChainStage: TypeAlias = Literal["importing", "imported", "enriching", "done", "failed"]
```

Add the injectable collaborators to `__init__` — real defaults, so
production wiring is unchanged and tests substitute without patching:

```python
    def __init__(
        self,
        *,
        provider_factory: ProviderFactory,
        session_factory: SessionFactory = SessionLocal,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
        import_runner: Callable[..., dict] | None = None,
        job_coordinator: object | None = None,
        notifier: Callable[..., None] | None = None,
    ) -> None:
        ...
        self._import_runner = import_runner
        self._job_coordinator = job_coordinator
        self._notifier = notifier
```

`None` means "resolve the real one lazily" — importing
`routers.work_orders` at module scope from a service would invert the
dependency and risk a cycle:

```python
    def _resolve_import_runner(self):
        if self._import_runner is not None:
            return self._import_runner
        from app.routers.work_orders import run_csv_import
        from app.models import User

        def _run(db, background, *, data, user_id):
            user = db.query(User).filter_by(id=user_id).one()
            result = run_csv_import(db, background, data=data, user=user)
            return result.model_dump()

        return _run
```

Replace the capture branch of `_poll_for_csv` so it records the capture and
then dispatches, and add the chain itself:

```python
    async def dispatch_capture(
        self, user_id: UUID
    ) -> NetFacilitiesCloudAuthenticationSnapshot:
        """Import a captured CSV, close the session, start enrichment, notify.

        The one function both the automatic trigger and the manual Import
        button run (E8), so the two paths cannot drift.
        """
        async with self._lock:
            ceremony = self._ceremonies.get(user_id)
            if ceremony is None or ceremony.captured_csv is None:
                raise NetFacilitiesError("No captured NetFacilities CSV to import.")
            attempt_id = ceremony.snapshot.attempt_id
            _filename, data = ceremony.captured_csv
            provider, cloud_session = ceremony.provider, ceremony.cloud_session
            config = ceremony.config
            ceremony.snapshot = replace(ceremony.snapshot, chain_stage="importing")

        # E11: no request scope here, so the chain opens its own Session and
        # its own BackgroundTasks, then awaits the tasks itself so the
        # supervisor notification `run_csv_import` queues still fires.
        # `import_work_orders` is synchronous -- off the event loop it goes.
        background = BackgroundTasks()
        db = self._session_factory()
        summary, import_error = None, None
        try:
            summary = await asyncio.to_thread(
                self._resolve_import_runner(), db, background, data=data, user_id=user_id
            )
        except DomainError as exc:
            import_error = str(exc)
        except Exception as exc:  # noqa: BLE001 - reported, never raised into the loop
            logger.exception("netfacilities.cloud_import_failed")
            import_error = str(exc)
        finally:
            db.close()
        if summary is not None:
            await background()

        if import_error is not None:
            # E6: a wrong or malformed CSV keeps the session open so the user
            # can re-export immediately. The E7 deadline still bounds it, so
            # a kept-open session cannot leak.
            return await self._finish_chain(
                user_id, attempt_id, stage="failed", failed_stage="import",
                import_error=import_error,
            )

        async with self._lock:
            ceremony = self._ceremonies.get(user_id)
            if ceremony is not None and ceremony.snapshot.attempt_id == attempt_id:
                ceremony.capture_consumed = True
                ceremony.snapshot = replace(
                    ceremony.snapshot,
                    chain_stage="imported",
                    capture_consumed=True,
                    import_created=summary.get("created"),
                )

        # E6 success path: close before enriching, so the ceremony's session
        # and enrichment's own short-lived replay session never overlap.
        await self._close(user_id, attempt_id, provider, cloud_session)

        job_id = await self._start_enrichment(user_id, attempt_id, config)
        if job_id is None:
            return await self._finish_chain(
                user_id, attempt_id, stage="done", failed_stage="enrichment",
                created=summary.get("created"),
            )
        return await self._finish_chain(
            user_id, attempt_id, stage="done", created=summary.get("created"),
            job_id=job_id,
        )

    async def _start_enrichment(
        self, user_id: UUID, attempt_id: UUID, config: NetFacilitiesCloudConfig
    ) -> UUID | None:
        """E5: a running batch is a queue, not a loss. Retry under the cap."""

        from app.integrations.netfacilities.config import load_netfacilities_config
        from app.services.netfacilities_cloud_enrichment import (
            resolve_cloud_enrichment_context,
        )

        loop = asyncio.get_running_loop()
        deadline = loop.time() + config.enrichment_retry_seconds
        jobs = self._job_coordinator
        if jobs is None:
            from app.services.netfacilities_jobs import coordinator as jobs
        while True:
            db = self._session_factory()
            try:
                enrichment_config = load_netfacilities_config()
                context, batch_seconds = resolve_cloud_enrichment_context(
                    enrichment_config, db, user_id
                )
            finally:
                db.close()
            if context is None:
                return None
            snapshot, created = await jobs.start(
                enrichment_config,
                cloud_client_context=context,
                cloud_user_id=user_id,
                cloud_batch_session_seconds=batch_seconds,
            )
            if created:
                return snapshot.job_id
            if loop.time() >= deadline:
                logger.info(
                    "netfacilities.cloud_enrichment_still_busy",
                    extra={"fields": {"user_id": str(user_id)}},
                )
                return None
            await asyncio.sleep(min(5, config.enrichment_retry_seconds))
```

Write `_close` and `_finish_chain` as small private helpers on the same
class: `_close` calls `provider.close_login_session` inside a
`try`/`except Exception: logger.exception(...)` and moves the snapshot to
`state="closed"`, `finished_at=_now()`; `_finish_chain` takes the lock,
`replace()`s the snapshot with the stage, counts, error and job id, calls
`self._notifier` (or Task 9's real one) off the loop with
`asyncio.to_thread`, and returns the snapshot.

Finally, store `config` on `_Ceremony` in `start()` so the chain can read
its timings without a second parameter, and have `_poll_for_csv` call
`await self.dispatch_capture(user_id)` immediately after recording the
capture, wrapped so a chain failure logs and lets the loop continue.

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest backend/tests/test_netfacilities_cloud_auth.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/netfacilities_cloud_auth.py backend/tests/test_netfacilities_cloud_auth.py
git commit -m "feat(netfacilities): auto-import and enrich a captured CSV"
```

---

### Task 9: Push on both outcomes, and the manual button on the same chain (E8, E10)

**Files:**
- Modify: `backend/app/domain/notifications.py:30-40, 67-101`
- Modify: `backend/app/services/notifications.py`
- Modify: `backend/app/routers/netfacilities.py:307-327`
- Modify: `backend/app/schemas/netfacilities.py:71-87`
- Modify: `docs/notification-events.md`
- Test: `backend/tests/test_netfacilities_cloud_routes.py`

**Interfaces:**
- Consumes: `dispatch_capture` (Task 8).
- Produces: `EVENT_NETFACILITIES_IMPORT_FINISHED = "netfacilities.import_finished"`
  and `EVENT_NETFACILITIES_IMPORT_FAILED = "netfacilities.import_failed"`.
- Produces: `notifications.notify_netfacilities_chain_finished(*, user_id,
  ok, stage, created, job_id) -> None` — synchronous, opens its own
  session via the existing `_deliver`, so the chain can call it from a
  thread with no `BackgroundTasks`.
- Produces: the manual route becomes `async def` returning
  `NetFacilitiesCloudSessionStatus`, not `WorkOrderImportResult`.

- [ ] **Step 1: Write the failing test**

```python
def test_the_manual_import_button_runs_the_whole_chain(client, techfm_oa_headers, monkeypatch):
    # E8: whether capture was automatic or the user clicked the fallback,
    # behavior is identical -- import *and* enrichment.
    calls = []

    async def _dispatch(user_id):
        calls.append(user_id)
        return _snapshot_with(state="closed", chain_stage="done", import_created=3)

    monkeypatch.setattr(
        netfacilities_router.cloud_authentication_coordinator,
        "dispatch_capture",
        _dispatch,
    )

    response = client.post(
        "/integrations/netfacilities/cloud/downloads/import", headers=techfm_oa_headers
    )

    assert response.status_code == 200
    assert len(calls) == 1
    assert response.json()["import_created"] == 3
    assert response.json()["chain_stage"] == "done"
```

Build `_snapshot_with` and reuse the file's existing client/auth fixtures —
read `test_netfacilities_cloud_routes.py` first and follow its conventions
rather than introducing new ones. Test through the real `TestClient`, not
by calling the handler directly: this repo's pinned FastAPI/Pydantic has
bitten direct-handler tests before.

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest backend/tests/test_netfacilities_cloud_routes.py -k manual_import -v`
Expected: FAIL — the route still calls `run_csv_import` directly and
returns a `WorkOrderImportResult` with no `chain_stage`.

- [ ] **Step 3: Write the implementation**

Add the two event constants to `domain/notifications.py`, in the existing
`EVENT_*` block, in `ALL_EVENTS`, and in the message map:

```python
    EVENT_NETFACILITIES_IMPORT_FINISHED: (
        "NetFacilities import finished",
        "{count} new work orders imported. Task/Symptom and Priority are filling in now.",
    ),
    EVENT_NETFACILITIES_IMPORT_FAILED: (
        "NetFacilities import needs you",
        "The {stage} step did not finish. Open Work Orders to see what to do next.",
    ),
```

Locked-screen text names a count and a stage and nothing else — the same
rule the rest of the table follows.

Add the service function to `services/notifications.py`, beside the others:

```python
def notify_netfacilities_chain_finished(
    *,
    user_id: uuid.UUID,
    ok: bool,
    stage: str,
    created: int | None,
    job_id: uuid.UUID | None,  # noqa: ARG001 - recorded on the snapshot, not in the text
) -> None:
    """The unattended chain's only channel to a user who closed the tab.

    Synchronous and session-opening, unlike every other notifier here: the
    chain has no request and no `BackgroundTasks`, so there is nothing to
    queue behind.
    """
    if not push_service.is_configured():
        return
    event = (
        policy.EVENT_NETFACILITIES_IMPORT_FINISHED
        if ok
        else policy.EVENT_NETFACILITIES_IMPORT_FAILED
    )
    title, body = policy.build_message(event, count=created or 0, stage=stage)
    _deliver([user_id], title, body)
```

Confirm `build_message`'s keyword handling accepts `count` and `stage`
before writing this — read it and extend it the way the existing `count`
event does, rather than assuming.

Wire it as the coordinator's default `notifier` in Task 8's
`_finish_chain`.

Add the four fields to `NetFacilitiesCloudSessionStatus` — a closed
Pydantic model drops anything undeclared, so the frontend would otherwise
never see them:

```python
    capture_consumed: bool = False
    import_created: int | None = None
    import_error: str | None = None
    enrichment_job_id: UUID | None = None
    chain_stage: Literal[
        "importing", "imported", "enriching", "done", "failed"
    ] | None = None
```

and carry them in `_cloud_status_response`.

Replace the manual route:

```python
@router.post(
    "/cloud/downloads/import",
    response_model=NetFacilitiesCloudSessionStatus,
    responses={**_forbidden(), 409: {"description": "No CSV has been captured yet."}},
)
async def import_netfacilities_cloud_download(
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    cloud_auth: NetFacilitiesCloudAuthenticationCoordinator = Depends(
        get_netfacilities_cloud_authentication_coordinator
    ),
) -> NetFacilitiesCloudSessionStatus:
    """The fallback for a capture the chain did not consume. Runs the same
    chain the automatic trigger does (E8) -- import *and* enrichment -- so
    the two cannot drift."""

    try:
        snapshot = await cloud_auth.dispatch_capture(user.id)
    except NetFacilitiesError as exc:
        raise HTTPException(
            status_code=409,
            detail="No CSV has been exported through the NetFacilities cloud window yet.",
        ) from exc
    return _cloud_status_response(snapshot)
```

Add the two rows to `docs/notification-events.md`'s "Who is told" table and
its text section, in the same commit.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest backend/tests/test_netfacilities_cloud_routes.py backend/tests/test_netfacilities_cloud_auth.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/domain/notifications.py backend/app/services/notifications.py backend/app/routers/netfacilities.py backend/app/schemas/netfacilities.py backend/tests/test_netfacilities_cloud_routes.py docs/notification-events.md
git commit -m "feat(netfacilities): notify on chain completion and share one chain"
```

---

### Task 10: The `download` listener (E2, E3, §3)

**Files:**
- Modify: `backend/app/integrations/netfacilities/cloud_steel.py` — `open_login_session`, `_SteelLoginSession`
- Test: `backend/tests/test_netfacilities_cloud_steel.py`

**Interfaces:**
- Consumes: `FakeContext.new_page`, `FakePage.on` (Task 3).
- Produces: `_SteelLoginSession.download_events: list[str]` and
  `poll_downloaded_csv` logging `capture_path=listener|poll` so production
  answers §3's open question.

This task is a latency optimisation on a proven path, and it is last on
purpose: if the listener never fires over `connect_over_cdp`, everything
above still works and this gets deleted in a follow-up.

- [ ] **Step 1: Write the failing test**

```python
def test_a_download_event_is_recorded_for_pages_open_and_pages_created(monkeypatch):
    provider, _fake_client = _provider(monkeypatch)
    page = FakePage("https://system.netfacilities.com/account/login")
    context = FakeContext(pages=[page])
    browser = FakeBrowser(context)
    monkeypatch.setattr(
        cloud_steel, "_connect_over_cdp", lambda *_args, **_kwargs: _resolved((None, browser))
    )

    async def _exercise():
        session = await provider.open_login_session()
        # The live view's own export click, as Playwright would report it.
        page.handlers["download"](FakeDownload("work-orders.csv"))
        return session

    session = asyncio.run(_exercise())

    assert "page" in context.handlers            # pages opened later are covered too
    assert session.download_events == ["work-orders.csv"]
```

with the fake beside the others:

```python
class FakeDownload:
    def __init__(self, suggested_filename):
        self.suggested_filename = suggested_filename
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest backend/tests/test_netfacilities_cloud_steel.py -k download_event -v`
Expected: FAIL — `KeyError: 'download'`; no handler is attached.

- [ ] **Step 3: Write the implementation**

Add the field to `_SteelLoginSession`:

```python
    download_events: list[str] = field(default_factory=list)
```

and, in `open_login_session` after the CDP setup and before returning,
attach the listeners. Build the session object first so the closure has
something to record onto:

```python
        session = _SteelLoginSession(
            session_id=steel_session.id,
            live_view_url=steel_session.debug_url,
            _playwright=playwright,
            _browser=browser,
            _client=client,
        )

        # The listener is the trigger; the bytes still come from the Files
        # API, which is Steel's own documented retrieval path (E2). Whether
        # this fires at all over `connect_over_cdp` is unverified -- the
        # safety-net poll (E3) is what makes that acceptable, and the
        # `capture_path` log line is what settles it in production.
        def _record(download) -> None:
            session.download_events.append(download.suggested_filename)

        def _watch(page) -> None:
            page.on("download", _record)

        for existing in context.pages:
            _watch(existing)
        context.on("page", _watch)
        return session
```

Then, in `poll_downloaded_csv`, log which path won when a capture succeeds:

```python
            logger.info(
                "netfacilities.cloud_csv_capture",
                extra={
                    "fields": {
                        "capture_path": "listener" if session.download_events else "poll",
                    }
                },
            )
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest backend/tests/test_netfacilities_cloud_steel.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/integrations/netfacilities/cloud_steel.py backend/tests/test_netfacilities_cloud_steel.py
git commit -m "feat(netfacilities): record download events and log the capture path"
```

---

### Task 11: Frontend narration and the double-enrich fix (§4.5)

**Files:**
- Modify: `backend/static/views/workOrders.js:2192-2242` (control gating and
  status text), `:2306-2325` (`afterWorkOrderImport`), `:2271-2282`
  (`importNetFacilitiesCloudDownload`)
- Modify: `backend/static/api.js` — the cloud-import call's return shape

**Interfaces:**
- Consumes: `capture_consumed`, `chain_stage`, `import_created`,
  `import_error`, `enrichment_job_id` from Task 9's schema.

- [ ] **Step 1: Gate the manual button on an *unconsumed* capture**

In `updateNetFacilitiesCloudControls`, replace the `hasCsv` line:

```js
  // E8: the fallback appears only when a capture is sitting unconsumed --
  // the chain normally consumes it before the next poll lands.
  const hasUnconsumedCsv = signedIn
    && Boolean(cloudStatus.last_download_filename)
    && !cloudStatus.capture_consumed;
```

and use `hasUnconsumedCsv` for
`netFacilitiesCloudImportDownloadBtn.hidden`.

- [ ] **Step 2: Narrate the chain**

In the same function's status block, ahead of the existing `signedIn`
branch:

```js
    } else if (cloudStatus && cloudStatus.chain_stage === "importing") {
      setMessage(netFacilitiesStatus, `Importing ${cloudStatus.last_download_filename}…`, "");
    } else if (cloudStatus && cloudStatus.chain_stage === "imported") {
      setMessage(netFacilitiesStatus, `Imported ${cloudStatus.import_created} work orders. Starting Task/Symptom and Priority…`, "success");
    } else if (cloudStatus && cloudStatus.chain_stage === "done") {
      setMessage(netFacilitiesStatus, `Imported ${cloudStatus.import_created} work orders${cloudStatus.enrichment_job_id ? " · enrichment running" : " · enrichment is busy, click Enrich when it frees up"}.`, "success");
    } else if (cloudStatus && cloudStatus.chain_stage === "failed") {
      setMessage(netFacilitiesStatus, `${cloudStatus.import_error || "That import did not finish."} You are still signed in — export the right CSV in the NetFacilities window and it will import automatically.`, "error");
```

The `signed_in` + `chain_stage === null` branch's copy also changes: the
user no longer clicks anything after exporting.

```js
        setMessage(netFacilitiesStatus, "NetFacilities is open and logged in. Export the work-order CSV in that window — it imports and enriches on its own.", "success");
```

Poll while a chain is running, not only while awaiting sign-in — extend
`shouldPoll`:

```js
  const chainRunning = Boolean(cloudStatus && ["importing", "imported", "enriching"].includes(cloudStatus.chain_stage));
  const shouldPoll = available && (awaitingSignIn || signedIn || chainRunning);
```

- [ ] **Step 3: Stop the client double-enriching**

`afterWorkOrderImport` currently calls `runNetFacilitiesEnrichment()` for
any user with a saved session. The chain now owns enrichment, so that call
must fire only for the *uploaded-file* path. Give it a flag:

```js
// `chainOwnsEnrichment` is true for the cloud path, where the server's
// capture chain starts enrichment itself (E8). Enriching again here would
// collide with that job, burn the chain's retry budget, and narrate a
// queue that is really our own duplicate.
async function afterWorkOrderImport(r, { chainOwnsEnrichment = false } = {}) {
```

and guard the tail:

```js
  if (
    !chainOwnsEnrichment
    && capability
    && capability.available
    && (capability.has_saved_session || (cloudStatus && cloudStatus.state === "signed_in"))
  ) {
    await runNetFacilitiesEnrichment();
  }
```

- [ ] **Step 4: Point the manual button at the new response shape**

The route now returns a session status, not a `WorkOrderImportResult`:

```js
async function importNetFacilitiesCloudDownload() {
  if (netFacilitiesCloudImportDownloadBtn) netFacilitiesCloudImportDownloadBtn.disabled = true;
  setMessage(importMessage, "Importing…", "");
  try {
    const status = await apiImportNetFacilitiesCloudDownload();
    if (status.chain_stage === "failed") {
      setMessage(importMessage, status.import_error || "Could not import the downloaded CSV.", "error");
    } else {
      // The same chain the automatic path runs (E8): the list and the
      // enrichment job are already in motion server-side.
      await afterWorkOrderImport(
        { created: status.import_created, supervisors_matched: 0 },
        { chainOwnsEnrichment: true },
      );
    }
  } catch (err) {
    setMessage(importMessage, friendlyError(err, "Could not import the downloaded CSV."), "error");
  } finally {
    if (netFacilitiesCloudImportDownloadBtn) netFacilitiesCloudImportDownloadBtn.disabled = false;
    await refreshNetFacilitiesCloudSession();
  }
}
```

- [ ] **Step 5: Verify in the app, then commit**

Run the backend suite: `python -m pytest backend/tests -q` — expected PASS.

Then hand off for manual validation rather than auto-running the preview
server: sign in through the cloud window, export a CSV, and watch the
status line walk *captured → importing → imported → done* with no clicks,
the Import button never appearing, and one enrichment job — not two —
starting.

```bash
git add backend/static/views/workOrders.js backend/static/api.js
git commit -m "feat(netfacilities): narrate the capture chain and stop double-enriching"
```

---

### Task 12: Documentation

**Files:**
- Modify: `docs/current-state.md`, `docs/endpoint-map.md`, `docs/open-work.md`
- Modify: `docs/superpowers/specs/2026-08-29-netfacilities-auto-capture-design.md` (status line)

- [ ] **Step 1: Update the endpoint map**

`POST /integrations/netfacilities/cloud/downloads/import` now returns
`NetFacilitiesCloudSessionStatus` and runs the whole chain. Correct its row.

- [ ] **Step 2: Update current-state**

Describe the shipped behavior: export in the cloud window → automatic
import → automatic enrichment → push. Name the three new env vars from
Task 5.

- [ ] **Step 3: Update open-work**

Record the two follow-ups the spec names as known gaps: vendor-side session
health checking (§4.4), and deleting the `download` listener if production
logs show `capture_path=poll` every time (§3).

- [ ] **Step 4: Flip the spec's status line**

`Status: **designed 2026-08-29, not yet implemented.**` becomes
`Status: **implemented <date>.**` with the plan path beside it.

- [ ] **Step 5: Commit**

```bash
git add docs
git commit -m "docs(netfacilities): record the shipped auto-capture chain"
```

---

## Self-review

**Spec coverage.** §1 D-A → Tasks 1–2. D-B → Task 4. D-C → Task 6. E1 → no
task, unchanged by construction. E2/E3 → Task 10. E4 → Task 8. E5 → Task 8
(`_start_enrichment`). E6 → Task 8, both branches tested. E7 → Tasks 5–6.
E8 → Task 9 (route) + Task 11 (gating). E9 → no task, unchanged. E10 →
Task 9. E11 → Task 8. E12 → Task 5. §3a phasing → the production gate.
§4.1 → Tasks 1, 2, 3, 10. §4.2 → Task 8. §4.3 → Task 7. §4.4 → Task 6.
§4.5 → Task 11. §4.6 → Task 9. §5's five failure rows → Tasks 3, 4, 6, 8.
§6's eleven test bullets → Tasks 1, 2, 3, 4, 6, 8, 9.

Two §6 bullets are covered indirectly and worth naming: "the manual button
runs the same chain" is asserted in Task 9 by the route calling
`dispatch_capture`, which Task 8's tests exercise end to end — the shared
function is the assertion. "Push fires on both outcomes with the failing
stage named" is asserted in Task 8 against `FakeNotifier`, with Task 9
covering the wiring to the real notifier.

**Placeholders.** Three steps deliberately say "read the file first and
follow its conventions" — Task 5's `_load`, Task 7's `_netfacilities_config`,
Task 9's client fixtures — because inventing a second fixture convention in
a suite that already has one is a worse outcome than the instruction. Every
other step carries the code it needs. Task 8 describes `_close` and
`_finish_chain` in prose rather than code; they are four-line lock-and-
`replace()` helpers in the exact shape of the existing `_timeout`, and the
task's tests pin their behavior.

**Type consistency.** `capture_consumed` is a `bool` on `_Ceremony`, the
snapshot dataclass, and the Pydantic schema. `chain_stage` uses the same
five string values in `ChainStage`, the schema `Literal`, and the JS
comparisons. `dispatch_capture` returns a snapshot in Task 8 and the route
in Task 9 passes exactly that to `_cloud_status_response`.
`resolve_cloud_enrichment_context` takes `user_id: UUID` in Task 7 and is
called with `user.id` (router) and `user_id` (chain).
