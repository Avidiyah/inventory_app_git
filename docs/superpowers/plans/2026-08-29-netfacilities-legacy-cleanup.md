# NetFacilities Legacy Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the pre-Steel NetFacilities auth system (shared Render secret-file / local headed sign-in / live-session borrow) now that per-user Steel cloud auth (IMP-040) is the only path anyone uses, and rebuild the Integrations card to show only the cloud flow.

**Architecture:** This is subtractive, not additive. `NetFacilitiesClient` in `client.py` stays — both the old and new systems use it to fetch/parse a work order, and the Steel path constructs it directly with an injected `_context`. Everything that exists only to authenticate that client the *old* way (headed Windows profile, shared Playwright storage-state file, the `/session` + `/auth/*` routes, the `NetFacilitiesAuthenticationCoordinator`, the "saved_state" job fallback, the shared profile lease) is deleted. `NetFacilitiesConfig` is simplified to the handful of settings the cloud path and `NetFacilitiesClient` still read; all platform-branching (Windows vs. Linux), storage-state-file, and interactive-auth settings are removed. The cloud stack (`cloud_config.py`, `cloud_steel.py`, `cloud_contracts.py`, `netfacilities_cloud_auth.py`, `netfacilities_cloud_crypto.py`, `netfacilities_cloud_sessions` table, `/cloud/*` routes) is untouched except where it reads a field being removed from `NetFacilitiesConfig`.

**Tech Stack:** FastAPI, SQLAlchemy, Playwright (via `client.py`), Steel SDK, vanilla JS frontend (`workOrders.js`, `api.js`), pytest.

**Spec:** No new spec — this plan implements the removal agreed in conversation on 2026-08-29 (this repo's chat history is the record; there is no separate spec doc). The systems being replaced were specified in `docs/superpowers/specs/2026-08-28-netfacilities-live-session-design.md` (being retired) and are superseded by `docs/superpowers/specs/2026-08-28-netfacilities-cloud-auth-design.md` (being kept).

## Global Constraints

- Every task must end with `cd backend && python -m pytest` passing (or, for a task that only touches frontend/docs/Render config, the closest applicable check — see that task).
- Never touch `netfacilities_cloud_sessions`, `NetFacilitiesCloudSession`, `cloud_config.py`, `cloud_steel.py`, `cloud_contracts.py`, `netfacilities_cloud_auth.py`, `netfacilities_cloud_crypto.py`, or any `/cloud/*` route/behavior except where a task below explicitly says to edit a specific line in one of those files.
- `NetFacilitiesClient` (`backend/app/integrations/netfacilities/client.py`) keeps its full work-order-fetch/parse behavior (`get_work_order`, `_get_work_order_document`, `_ensure_session_primed`, rendering support) — only the authentication-establishment code paths inside it are removed (Task 3).
- Commit after each task, in the style already used in this repo's `netfacilities:` commits (`feat(netfacilities): ...` / `fix(netfacilities): ...` / `chore(netfacilities): ...`).
- Don't add backwards-compatibility shims (no deprecated-route aliases, no dead feature flags) — this is a hard cutover, not a phased rollout.

---

## Order of operations

Backend must be cut over before frontend, because the frontend cards call backend routes. Delete backend routes first only after the frontend stops calling them (Task 8 removes the JS calls in the same commit range as Task 7 removes the routes — do Task 7 and Task 8 back-to-back before deploying). Tasks 1–6 are backend-internal and safe to land independently. Tasks 9–13 (docs, Render, Dockerfile) can land anytime after Task 8.

1. Simplify `NetFacilitiesConfig` (config.py)
2. Delete the local-auth service layer (`netfacilities_auth.py`, `netfacilities_live_session.py`, `netfacilities_operations.py`)
3. Trim `client.py` to drop the local-auth-only code paths
4. Trim `factory.py` to the cloud-only surface
5. Simplify `netfacilities_jobs.py` to cloud-only
6. Wire `render_document`/`render_settle_ms` into the Steel client (close a gap this cleanup would otherwise widen)
7. Rewrite `routers/netfacilities.py` and `schemas/netfacilities.py` to the cloud-only surface
8. Wire up `main.py`/`lifespan.py`
9. Frontend: `api.js`
10. Frontend: `integrations.html`
11. Frontend: `workOrders.js`
12. Frontend copy: `tips.js`
13. Tests: delete/update the backend test suite
14. Docs: `current-state.md`, `endpoint-map.md`, `open-work.md`
15. Render + Dockerfile + `render.yaml`

---

### Task 1: Simplify `NetFacilitiesConfig`

**Files:**
- Modify: `backend/app/integrations/netfacilities/config.py`
- Test: `backend/tests/test_netfacilities_config.py`

**Interfaces:**
- Produces: `NetFacilitiesConfig` with fields `enabled: bool`, `request_timeout_seconds: int`, `batch_timeout_seconds: int`, `render_document: bool`, `render_settle_seconds: int`. Every other field (`profile_dir`, `browser_channel`, `auth_timeout_seconds`, `storage_state_file`, `interactive_authentication_available`, `session_timeout_seconds`, `download_dir`) is removed. Properties removed: `playwright_channel`, `storage_state_path`, `has_saved_authentication`. Property kept: `render_settle_ms`, `request_timeout_ms`.
- Consumed by: `cloud_config.load_netfacilities_cloud_config(base: NetFacilitiesConfig, ...)` (Task unaffected — it only reads `base.enabled`), `netfacilities_jobs.py` (Task 5), `routers/netfacilities.py` (Task 7).

Rationale: `browser_channel`/`profile_dir`/`interactive_authentication_available`/`session_timeout_seconds`/`download_dir` existed only for the local headed/interactive flow (Windows) and the shared saved-state flow (Linux `storage_state_file`). The cloud path never launches its own browser (it connects over CDP to a Steel session `factory.py:87-88`) and never reads a storage-state *file* (it decrypts a per-user DB column, `factory.py:86`), so none of that config surface has a live reader once Tasks 2–5 land.

- [ ] **Step 1: Replace the whole file**

```python
"""Fail-closed configuration for NetFacilities enrichment."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os

from .errors import NetFacilitiesUnavailable

DEFAULT_REQUEST_TIMEOUT_SECONDS = 30
DEFAULT_BATCH_TIMEOUT_SECONDS = 1_800
DEFAULT_RENDER_SETTLE_SECONDS = 5


@dataclass(frozen=True, slots=True)
class NetFacilitiesConfig:
    """Validated capability settings with no browser or network side effects."""

    enabled: bool
    request_timeout_seconds: int
    batch_timeout_seconds: int
    render_document: bool = False
    render_settle_seconds: int = DEFAULT_RENDER_SETTLE_SECONDS

    @property
    def render_settle_ms(self) -> int:
        """How long a rendered document may settle before it is serialized."""

        return self.render_settle_seconds * 1_000

    @property
    def request_timeout_ms(self) -> int:
        return self.request_timeout_seconds * 1_000


def load_netfacilities_config(
    environ: Mapping[str, str] | None = None,
) -> NetFacilitiesConfig:
    """Read configuration without importing or starting the browser runtime.

    Missing or explicit ``false`` keeps the capability disabled and ignores all
    integration settings. An attempted enablement is strict: malformed
    configuration becomes one secret-safe ``unavailable`` failure.
    """

    values = os.environ if environ is None else environ
    enabled = _enabled(values.get("NETFACILITIES_ENABLED"))
    if not enabled:
        return NetFacilitiesConfig(
            enabled=False,
            request_timeout_seconds=DEFAULT_REQUEST_TIMEOUT_SECONDS,
            batch_timeout_seconds=DEFAULT_BATCH_TIMEOUT_SECONDS,
        )

    return NetFacilitiesConfig(
        enabled=True,
        request_timeout_seconds=_positive_seconds(
            values,
            "NETFACILITIES_REQUEST_TIMEOUT_SECONDS",
            DEFAULT_REQUEST_TIMEOUT_SECONDS,
        ),
        batch_timeout_seconds=_positive_seconds(
            values,
            "NETFACILITIES_BATCH_TIMEOUT_SECONDS",
            DEFAULT_BATCH_TIMEOUT_SECONDS,
        ),
        # Priority is server-rendered, so the primed raw response already carries it
        # and the batch needs no JavaScript. Rendering stays available behind this
        # flag for diagnosis, but costs a settle wait on every row when enabled.
        render_document=_flag(
            values.get("NETFACILITIES_RENDER_DOCUMENT"),
            name="NETFACILITIES_RENDER_DOCUMENT",
            default=False,
        ),
        render_settle_seconds=_positive_seconds(
            values,
            "NETFACILITIES_RENDER_SETTLE_SECONDS",
            DEFAULT_RENDER_SETTLE_SECONDS,
        ),
    )


def _enabled(raw: str | None) -> bool:
    if raw is None or not raw.strip():
        return False
    normalized = raw.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise NetFacilitiesUnavailable(
        "NETFACILITIES_ENABLED must be either true or false."
    )


def _flag(raw: str | None, *, name: str, default: bool) -> bool:
    if raw is None or not raw.strip():
        return default
    normalized = raw.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise NetFacilitiesUnavailable(f"{name} must be either true or false.")


def _positive_seconds(
    values: Mapping[str, str],
    name: str,
    default: int,
) -> int:
    raw = values.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        seconds = int(raw)
    except ValueError as exc:
        raise NetFacilitiesUnavailable(f"{name} must be a positive whole number.") from exc
    if seconds <= 0:
        raise NetFacilitiesUnavailable(f"{name} must be a positive whole number.")
    return seconds
```

- [ ] **Step 2: Rewrite `test_netfacilities_config.py`**

Delete every test that exercises `profile_dir`, `browser_channel`, `interactive_authentication_available`, `storage_state_file`/`storage_state_path`, `session_timeout_seconds`, `download_dir`, or the Windows/Linux platform branch (the old `platform=` kwarg no longer exists on `load_netfacilities_config`). Keep/rewrite only:

```python
from app.integrations.netfacilities.config import (
    DEFAULT_BATCH_TIMEOUT_SECONDS,
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    NetFacilitiesConfig,
    load_netfacilities_config,
)
from app.integrations.netfacilities.errors import NetFacilitiesUnavailable
import pytest


def test_disabled_by_default():
    config = load_netfacilities_config({})
    assert config.enabled is False
    assert config.request_timeout_seconds == DEFAULT_REQUEST_TIMEOUT_SECONDS
    assert config.batch_timeout_seconds == DEFAULT_BATCH_TIMEOUT_SECONDS


def test_enabled_reads_timeouts():
    config = load_netfacilities_config(
        {
            "NETFACILITIES_ENABLED": "true",
            "NETFACILITIES_REQUEST_TIMEOUT_SECONDS": "45",
            "NETFACILITIES_BATCH_TIMEOUT_SECONDS": "900",
        }
    )
    assert config.enabled is True
    assert config.request_timeout_seconds == 45
    assert config.batch_timeout_seconds == 900


def test_invalid_enabled_flag_raises():
    with pytest.raises(NetFacilitiesUnavailable):
        load_netfacilities_config({"NETFACILITIES_ENABLED": "sure"})


def test_non_positive_timeout_raises():
    with pytest.raises(NetFacilitiesUnavailable):
        load_netfacilities_config(
            {"NETFACILITIES_ENABLED": "true", "NETFACILITIES_BATCH_TIMEOUT_SECONDS": "0"}
        )


def test_render_document_flag_and_settle_seconds():
    config = load_netfacilities_config(
        {
            "NETFACILITIES_ENABLED": "true",
            "NETFACILITIES_RENDER_DOCUMENT": "true",
            "NETFACILITIES_RENDER_SETTLE_SECONDS": "9",
        }
    )
    assert config.render_document is True
    assert config.render_settle_seconds == 9
    assert config.render_settle_ms == 9_000
```

- [ ] **Step 3: Run the test file**

Run: `cd backend && python -m pytest tests/test_netfacilities_config.py -v`
Expected: all pass. (It will still fail at this point if `cloud_config.py` or other modules haven't been updated for the new `NetFacilitiesConfig` shape — that's expected; full-suite green is the end-of-plan gate, not per-task in the early tasks that touch shared types.)

- [ ] **Step 4: Commit**

```bash
git add backend/app/integrations/netfacilities/config.py backend/tests/test_netfacilities_config.py
git commit -m "refactor(netfacilities): drop local-auth fields from NetFacilitiesConfig"
```

---

### Task 2: Delete the local-auth service layer

**Files:**
- Delete: `backend/app/services/netfacilities_auth.py`
- Delete: `backend/app/services/netfacilities_live_session.py`
- Delete: `backend/app/services/netfacilities_operations.py`
- Delete: `backend/tests/test_netfacilities_auth.py`

**Interfaces:**
- Removes: `NetFacilitiesAuthenticationCoordinator`, `authentication_coordinator`, `NetFacilitiesAuthenticationSnapshot`, `PENDING_STATES`, `LiveSessionClientContext`, `NetFacilitiesOperationGate`, `operation_gate`. Nothing in the cloud stack imports any of these — `netfacilities_cloud_auth.py` has its own independent ceremony coordinator and never took the shared profile lease (confirmed: `netfacilities_jobs.py` docstring, "A cloud session never takes the shared profile lease").
- Downstream callers fixed in later tasks: `routers/netfacilities.py` (Task 7), `main.py`/`lifespan.py` (Task 8), `netfacilities_jobs.py` (Task 5).

- [ ] **Step 1: Delete the three service files and the test file**

```bash
git rm backend/app/services/netfacilities_auth.py
git rm backend/app/services/netfacilities_live_session.py
git rm backend/app/services/netfacilities_operations.py
git rm backend/tests/test_netfacilities_auth.py
```

- [ ] **Step 2: Confirm nothing outside this plan's later tasks still imports them**

Run: `cd backend && grep -rn "netfacilities_auth\|netfacilities_live_session\|netfacilities_operations" app tests`
Expected: only hits inside `app/routers/netfacilities.py`, `app/main.py`, `app/services/netfacilities_jobs.py` — every one of those is fixed by a later task in this plan. If any other file shows up, note it and fix it in this task before continuing (it means this plan's file inventory missed a caller).

- [ ] **Step 3: Commit**

```bash
git commit -m "chore(netfacilities): delete the local headed-browser auth service layer"
```

(Leave `main.py`, `lifespan.py`, `routers/netfacilities.py`, and `netfacilities_jobs.py` broken between this commit and their fix-up tasks — that's fine, this is one continuous refactor landing as several commits before the branch is tested/merged. Don't run the full suite until Task 8.)

---

### Task 3: Trim `client.py`

**Files:**
- Modify: `backend/app/integrations/netfacilities/client.py`
- Test: `backend/tests/test_netfacilities_client.py`

**Interfaces:**
- `NetFacilitiesClient.__init__` keeps: `headless`, `timeout_ms`, `max_response_bytes`, `request_only`, `render_document`, `render_settle_ms`, `_context`. Removes: `profile_dir`, `storage_state_path`, `browser_channel`, `use_saved_state`.
- Removes methods: `authenticate_interactively`, `persist_authentication_state`, `capture_downloads`, `wait_for_downloads`, `_save_download`, `on_context_closed` — all local-headed-browser-only (the cloud path saves state via `context.storage_state()` directly in `cloud_steel.py:112`, and captures downloads via Steel's Files API in `cloud_steel.py:115-131`, not through this client).
- Keeps: `open_authentication_page`, `verify_authentication_page`, `prime_session`, `get_work_order`, `get_work_order_with_diagnostics`, `_get_work_order_document`, `_ensure_session_primed`, `_read_work_order_document`, `_request_work_order_document`, `_navigate_to_work_order_document`, `_read_rendered_document`, `_read_bounded_body`, `_validate_response_metadata`, `_require_context`, `_stop_playwright`, `_stop_runtime`. `open_authentication_page`/`verify_authentication_page`/`prime_session` stay because `cloud_steel.py` calls all three (`open_login_session` calls `open_authentication_page`; `poll_signed_in` calls `verify_authentication_page` + `prime_session`).
- `__aenter__` collapses to only two cases: `self._context is not None` (cloud — return self immediately, unchanged) and "launch a bare headless browser with no storage state" is deleted entirely, since every remaining caller (`cloud_steel.py`) always passes `_context`. If `_context is None`, raise — there is no other way to construct a working client anymore.
- `__aexit__` drops the `wait_for_downloads()` call (that method is deleted).

- [ ] **Step 1: Edit `__init__`**

Replace (client.py:79-113):

```python
    def __init__(
        self,
        *,
        headless: bool,
        timeout_ms: int = REQUEST_TIMEOUT_MS,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
        request_only: bool = False,
        render_document: bool = False,
        render_settle_ms: int = DEFAULT_RENDER_SETTLE_MS,
        _context: BrowserContext | Any | None = None,
    ) -> None:
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.max_response_bytes = max_response_bytes
        self.request_only = request_only
        self.render_document = render_document
        self.render_settle_ms = render_settle_ms
        self._context = _context
        self._request_context: Any | None = None
        self._browser: Any | None = None
        self._playwright: Any | None = None
        self._owns_context = _context is None
        self._session_primed = False
        self._context_closed = False
```

- [ ] **Step 2: Edit `__aenter__`/`__aexit__`**

Replace (client.py:115-186):

```python
    async def __aenter__(self) -> "NetFacilitiesClient":
        if self._context is not None:
            return self
        raise NetFacilitiesUnavailable(
            "NetFacilitiesClient requires an existing browser context."
        )

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        try:
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

- [ ] **Step 3: Delete the local-only methods**

Delete `authenticate_interactively` (client.py:188-196), `persist_authentication_state` (client.py:231-247), `on_context_closed` (client.py:261-270), `capture_downloads` (client.py:272-298), `wait_for_downloads` (client.py:300-305), `_save_download` (client.py:307-325), and the `self._download_tasks: set[...]` field from `__init__` (already dropped in Step 1).

- [ ] **Step 4: Drop the now-unused `STORAGE_STATE_FILENAME` import**

Remove `from .config import STORAGE_STATE_FILENAME` (client.py:28) — `config.py` no longer exports it after Task 1.

- [ ] **Step 5: Rewrite `test_netfacilities_client.py`**

Read the current file first (`backend/tests/test_netfacilities_client.py`) and delete every test that constructs a client with `use_saved_state=True`, `profile_dir=...`, or exercises `persist_authentication_state`, `capture_downloads`, `authenticate_interactively`, or the launch-a-bare-browser path. Keep/adapt every test that constructs the client with `_context=<fake context>` and exercises `get_work_order`, `get_work_order_with_diagnostics`, `open_authentication_page`, `verify_authentication_page`, `prime_session`, response-metadata validation, rendering, and size-bound behavior — those are unchanged.

- [ ] **Step 6: Run**

Run: `cd backend && python -m pytest tests/test_netfacilities_client.py -v`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/integrations/netfacilities/client.py backend/tests/test_netfacilities_client.py
git commit -m "refactor(netfacilities): drop local-auth-only methods from NetFacilitiesClient"
```

---

### Task 4: Trim `factory.py`

**Files:**
- Modify: `backend/app/integrations/netfacilities/factory.py`
- Delete: `backend/tests/test_netfacilities_cloud_enrichment_factory.py` only if it also tests the removed local factory functions — otherwise keep it and just drop the local-factory tests from it (read the file first to decide; it's a cloud-focused file so it may need no change beyond removing an unused import).

**Interfaces:**
- Removes: `create_netfacilities_client`, `create_netfacilities_authentication_client` (both local-only).
- Keeps: `create_netfacilities_cloud_enrichment_client`, `_CloudEnrichmentContextAdapter` — unchanged.

- [ ] **Step 1: Replace the file**

```python
"""Lazy construction of hosted NetFacilities clients."""

from __future__ import annotations

from .cloud_config import NetFacilitiesCloudConfig
from .contracts import NetFacilitiesClientContextProtocol
from .errors import NetFacilitiesUnavailable


def create_netfacilities_cloud_enrichment_client(
    config: NetFacilitiesCloudConfig,
    encrypted_storage_state: bytes,
) -> NetFacilitiesClientContextProtocol:
    """Reconnect to a fresh, short-lived Steel session and replay a user's
    saved storage_state() for one enrichment job (spec D5, verified by the
    Task 1 manual spike). A context whose `__aenter__` returns a client with
    `get_work_order` -- exactly the shape `NetFacilitiesJobCoordinator`
    already expects."""

    from app.services import netfacilities_cloud_crypto as crypto

    from .cloud_steel import SteelCloudBrowserProvider

    if not config.enabled or config.steel_api_key is None:
        raise NetFacilitiesUnavailable(
            "NetFacilities cloud enrichment is disabled on this host."
        )
    storage_state = crypto.decrypt_storage_state(encrypted_storage_state)
    provider = SteelCloudBrowserProvider(api_key=config.steel_api_key)
    return _CloudEnrichmentContextAdapter(provider, storage_state)


class _CloudEnrichmentContextAdapter:
    """Defers `open_replay_context` (async) until `__aenter__`, since
    `create_netfacilities_cloud_enrichment_client` itself is sync."""

    def __init__(self, provider, storage_state: str) -> None:
        self._provider = provider
        self._storage_state = storage_state
        self._inner = None

    async def __aenter__(self):
        self._inner = await self._provider.open_replay_context(self._storage_state)
        return await self._inner.__aenter__()

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        if self._inner is not None:
            await self._inner.__aexit__(exc_type, exc, traceback)
```

- [ ] **Step 2: Check the cloud enrichment factory test file**

Run: `cd backend && grep -n "create_netfacilities_client\|create_netfacilities_authentication_client" tests/test_netfacilities_cloud_enrichment_factory.py`
Expected: no output. If there is output, delete those specific test functions (they test the functions just removed); leave the rest of the file as-is.

- [ ] **Step 3: Run**

Run: `cd backend && python -m pytest tests/test_netfacilities_cloud_enrichment_factory.py -v`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add backend/app/integrations/netfacilities/factory.py backend/tests/test_netfacilities_cloud_enrichment_factory.py
git commit -m "refactor(netfacilities): drop local-auth factory functions"
```

---

### Task 5: Simplify `netfacilities_jobs.py` to cloud-only

**Files:**
- Modify: `backend/app/services/netfacilities_jobs.py`
- Test: `backend/tests/test_netfacilities_jobs.py`

**Interfaces:**
- `JobSource` narrows from `Literal["live_session", "saved_state", "cloud_session"]` to `Literal["cloud_session"]`.
- `NetFacilitiesJobCoordinator.start(...)` drops the `live_client_context` parameter and the shared-profile-lease fallback entirely. New signature: `start(self, config: NetFacilitiesConfig, *, cloud_client_context: NetFacilitiesClientContextProtocol | None, cloud_user_id: UUID | None = None, cloud_batch_session_seconds: float | None = None) -> tuple[NetFacilitiesJobSnapshot, bool]`. If `cloud_client_context is None`, raise `NetFacilitiesAuthenticationRequired("Sign in to NetFacilities before enrichment.")` — there is no more silent fallback to a shared saved-state client.
- Removes: `_default_client_factory`, the `ClientFactory` type alias, the `client_factory` constructor parameter, `profile_gate`/`NetFacilitiesOperationGate` usage, `_release_profile`, the `lease` acquire/release block in `start`.
- `_run`'s `client_context` parameter is no longer `| None` — it is always provided (`cloud_client_context`), so drop the `self._client_factory(config)` fallback branch inside `_run`.

- [ ] **Step 1: Replace the file**

```python
"""One process-local, serialized NetFacilities enrichment job."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import logging
from typing import Literal, TypeAlias
from uuid import UUID, uuid4

from app.database import SessionLocal
from app.integrations.netfacilities.config import NetFacilitiesConfig
from app.integrations.netfacilities.contracts import (
    NetFacilitiesClientContextProtocol,
)
from app.integrations.netfacilities.errors import (
    NetFacilitiesAuthenticationRequired,
    NetFacilitiesError,
)
from app.services.netfacilities import (
    NetFacilitiesEnrichmentSummary,
    SessionFactory,
    enrich_work_orders,
)


logger = logging.getLogger(__name__)

JobState: TypeAlias = Literal[
    "queued",
    "running",
    "completed",
    "authentication_required",
    "timed_out",
    "failed",
    "cancelled",
]
FailureClass: TypeAlias = Literal[
    "authentication_required",
    "unavailable",
    "unexpected_failure",
    "cancelled",
]
JobSource: TypeAlias = Literal["cloud_session"]
EnrichmentRunner: TypeAlias = Callable[..., Awaitable[NetFacilitiesEnrichmentSummary]]


@dataclass(frozen=True, slots=True)
class NetFacilitiesJobSnapshot:
    """Immutable, source-value-free state safe for a gated API response.

    ``user_id`` is internal plumbing so the router can find and expire that
    user's saved cloud session on `authentication_required` (spec D8); it is
    never part of the response schema
    (`schemas.netfacilities.NetFacilitiesEnrichmentJob` has no such field)."""

    job_id: UUID
    state: JobState
    started_at: datetime | None = None
    finished_at: datetime | None = None
    failure: FailureClass | None = None
    summary: NetFacilitiesEnrichmentSummary | None = None
    current_work_order_number: str | None = None
    source: JobSource | None = None
    user_id: UUID | None = None


class NetFacilitiesJobCoordinator:
    """Admit at most one batch and own its browser lifetime through shutdown."""

    def __init__(
        self,
        *,
        session_factory: SessionFactory = SessionLocal,
        enrichment_runner: EnrichmentRunner = enrich_work_orders,
    ) -> None:
        self._session_factory = session_factory
        self._enrichment_runner = enrichment_runner
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._latest: NetFacilitiesJobSnapshot | None = None

    async def start(
        self,
        config: NetFacilitiesConfig,
        *,
        cloud_client_context: NetFacilitiesClientContextProtocol | None = None,
        cloud_user_id: UUID | None = None,
        cloud_batch_session_seconds: float | None = None,
    ) -> tuple[NetFacilitiesJobSnapshot, bool]:
        """Start a batch using the calling user's own cloud session, or
        return the currently active batch unchanged."""

        if not config.enabled:
            raise NetFacilitiesAuthenticationRequired(
                "NetFacilities enrichment is not enabled on this host."
            )
        if cloud_client_context is None:
            raise NetFacilitiesAuthenticationRequired(
                "Sign in to NetFacilities before enrichment."
            )

        async with self._lock:
            if self._task is not None and not self._task.done():
                if self._latest is None:  # defensive invariant
                    raise RuntimeError("active NetFacilities task has no job state")
                return self._latest, False

            job = NetFacilitiesJobSnapshot(
                job_id=uuid4(),
                state="queued",
                source="cloud_session",
                user_id=cloud_user_id,
            )
            self._latest = job
            self._task = asyncio.create_task(
                self._run(
                    job.job_id,
                    cloud_client_context,
                    job.user_id,
                    cloud_batch_session_seconds,
                ),
                name=f"netfacilities-enrichment-{job.job_id}",
            )
            return job, True

    async def latest(self) -> NetFacilitiesJobSnapshot | None:
        async with self._lock:
            return self._latest

    async def get(self, job_id: UUID) -> NetFacilitiesJobSnapshot | None:
        async with self._lock:
            if self._latest is None or self._latest.job_id != job_id:
                return None
            return self._latest

    async def shutdown(self) -> None:
        """Cancel an active job so its source client closes before exit."""

        async with self._lock:
            task = self._task
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _set(self, snapshot: NetFacilitiesJobSnapshot) -> None:
        async with self._lock:
            if self._latest is not None and self._latest.job_id == snapshot.job_id:
                self._latest = snapshot

    async def _report_request_started(
        self,
        job_id: UUID,
        work_order_number: str,
    ) -> None:
        async with self._lock:
            snapshot = self._latest
            if (
                snapshot is not None
                and snapshot.job_id == job_id
                and snapshot.state == "running"
            ):
                self._latest = replace(
                    snapshot,
                    current_work_order_number=work_order_number,
                )

    async def _run(
        self,
        job_id: UUID,
        client_context: NetFacilitiesClientContextProtocol,
        user_id: UUID | None,
        cloud_batch_session_seconds: float | None,
    ) -> None:
        started_at = datetime.now(timezone.utc)
        started_clock = asyncio.get_running_loop().time()
        await self._set(
            NetFacilitiesJobSnapshot(
                job_id=job_id,
                state="running",
                started_at=started_at,
                source="cloud_session",
                user_id=user_id,
            )
        )
        logger.info(
            "netfacilities.enrichment_started",
            extra={"fields": {"operation_id": str(job_id)}},
        )

        try:
            async with client_context as client:
                summary = await self._enrichment_runner(
                    session_factory=self._session_factory,
                    client=client,
                    batch_timeout_seconds=cloud_batch_session_seconds,
                    on_request_started=lambda number: self._report_request_started(
                        job_id,
                        number,
                    ),
                    cloud_session_deadline_seconds=cloud_batch_session_seconds,
                )
        except asyncio.CancelledError:
            await self._finish(
                job_id,
                started_at,
                state="cancelled",
                failure="cancelled",
                user_id=user_id,
            )
            raise
        except NetFacilitiesAuthenticationRequired:
            await self._finish(
                job_id,
                started_at,
                state="authentication_required",
                failure="authentication_required",
                user_id=user_id,
            )
        except NetFacilitiesError:
            await self._finish(
                job_id,
                started_at,
                state="failed",
                failure="unavailable",
                user_id=user_id,
            )
        except Exception:
            logger.error(
                "netfacilities.enrichment_failed",
                extra={
                    "fields": {
                        "operation_id": str(job_id),
                        "failure": "unexpected_failure",
                    }
                },
            )
            await self._finish(
                job_id,
                started_at,
                state="failed",
                failure="unexpected_failure",
                user_id=user_id,
            )
        else:
            if summary.authentication_required:
                state: JobState = "authentication_required"
                failure: FailureClass | None = "authentication_required"
            elif summary.timed_out:
                state = "timed_out"
                failure = None
            else:
                state = "completed"
                failure = None
            await self._finish(
                job_id,
                started_at,
                state=state,
                failure=failure,
                summary=summary,
                user_id=user_id,
            )
        finally:
            elapsed_ms = round(
                (asyncio.get_running_loop().time() - started_clock) * 1_000
            )
            snapshot = await self.get(job_id)
            fields: dict[str, object] = {
                "operation_id": str(job_id),
                "ms": elapsed_ms,
            }
            if snapshot is not None:
                fields["state"] = snapshot.state
                if snapshot.summary is not None:
                    fields.update(
                        {
                            "candidates": snapshot.summary.candidates,
                            "fetched": snapshot.summary.fetched,
                            "descriptions_updated": (
                                snapshot.summary.descriptions_updated
                            ),
                            "priorities_updated": snapshot.summary.priorities_updated,
                        }
                    )
            logger.info(
                "netfacilities.enrichment_finished",
                extra={"fields": fields},
            )

    async def _finish(
        self,
        job_id: UUID,
        started_at: datetime,
        *,
        state: JobState,
        failure: FailureClass | None,
        summary: NetFacilitiesEnrichmentSummary | None = None,
        user_id: UUID | None = None,
    ) -> None:
        await self._set(
            NetFacilitiesJobSnapshot(
                job_id=job_id,
                state=state,
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                failure=failure,
                summary=summary,
                source="cloud_session",
                user_id=user_id,
            )
        )


coordinator = NetFacilitiesJobCoordinator()
```

**Note on `batch_timeout_seconds` vs `cloud_batch_session_seconds`:** the previous code passed `config.batch_timeout_seconds` as the runner's `batch_timeout_seconds` argument for every source, with `cloud_session_deadline_seconds` as a *separate*, tighter cap applied only for cloud jobs (Steel's 15-minute session cap, spec: `cloud_config.py:27-31`). Now that every job is a cloud job, check `app/services/netfacilities.py::enrich_work_orders`'s signature before assuming `batch_timeout_seconds=cloud_batch_session_seconds` above is correct — if `enrich_work_orders` treats `batch_timeout_seconds=None` differently from a real value (e.g. "no timeout" vs "use default"), pass `config.batch_timeout_seconds` for `batch_timeout_seconds` and keep `cloud_session_deadline_seconds=cloud_batch_session_seconds` as the separate, tighter cap, matching the *original* two-argument call shown at the top of this file's original `_run` (`netfacilities_jobs.py:260-269` before this task). Read that function's docstring/body first; don't guess.

- [ ] **Step 2: Rewrite `test_netfacilities_jobs.py`**

Read the current file first. Delete every test involving `live_client_context`, `source="live_session"`, `source="saved_state"`, the shared profile lease/gate, or `client_factory=`. Keep/adapt tests for: `config.enabled is False` → raises `NetFacilitiesAuthenticationRequired`; `cloud_client_context is None` → raises `NetFacilitiesAuthenticationRequired`; a provided `cloud_client_context` runs to completion and reports `source="cloud_session"` and the right `user_id`; a second `start()` while one is running returns the same snapshot with `created=False`; `shutdown()` cancels an in-flight task; terminal states (`completed`, `timed_out`, `failed`, `authentication_required`, `cancelled`) map from the enrichment runner's summary/exceptions correctly.

- [ ] **Step 3: Run**

Run: `cd backend && python -m pytest tests/test_netfacilities_jobs.py -v`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/netfacilities_jobs.py backend/tests/test_netfacilities_jobs.py
git commit -m "refactor(netfacilities): make the job coordinator cloud-session-only"
```

---

### Task 6: Wire `render_document`/`render_settle_ms` into the Steel client

**Files:**
- Modify: `backend/app/integrations/netfacilities/cloud_steel.py`
- Modify: `backend/app/integrations/netfacilities/factory.py` (pass config through)
- Modify: `backend/app/routers/netfacilities.py` (pass base `NetFacilitiesConfig` to the cloud call — covered again in Task 7, but this task's construction change must land first or Task 7 will need it inline)
- Test: `backend/tests/test_netfacilities_cloud_steel.py`

**Why this task exists:** before this cleanup, `config.render_document`/`config.render_settle_seconds` only ever reached a real `NetFacilitiesClient` through the *local* `create_netfacilities_client` factory (`factory.py:33-48`, now deleted in Task 4). `cloud_steel.py`'s two `NetFacilitiesClient(...)` constructions (`open_login_session` at line 92, `_SteelEnrichmentContext.__aenter__` at line 174) never passed these two settings, defaulting to `render_document=False`. That was already true before this cleanup — this task doesn't fix a regression this plan introduces, it fixes a pre-existing gap that becomes the *only* code path once the local flow is gone, so it's the right moment to close it rather than carry it forward silently.

**Interfaces:**
- `create_netfacilities_cloud_enrichment_client(config: NetFacilitiesCloudConfig, encrypted_storage_state: bytes, *, render_document: bool, render_settle_ms: int)` — two new required keyword args.
- `SteelCloudBrowserProvider.open_replay_context(self, storage_state: str, *, render_document: bool, render_settle_ms: int)` — two new required keyword args, threaded into the `NetFacilitiesClient(...)` call inside `_SteelEnrichmentContext.__aenter__`.
- `SteelCloudBrowserProvider.open_login_session` — no config needed; the login ceremony never calls `get_work_order`, so `render_document` is irrelevant there. Leave it as `NetFacilitiesClient(profile_dir=None, headless=True, _context=context)` — **but** drop the `profile_dir=None` keyword now that Task 3 removed that parameter from `NetFacilitiesClient.__init__`.

- [ ] **Step 1: Update `cloud_steel.py`**

In `open_login_session` (cloud_steel.py:92), change:

```python
        client = NetFacilitiesClient(profile_dir=None, headless=True, _context=context)
```

to:

```python
        client = NetFacilitiesClient(headless=True, _context=context)
```

In `open_replay_context` (cloud_steel.py:137), change the signature and the returned dataclass to carry the two new settings through to `__aenter__`:

```python
    async def open_replay_context(
        self,
        storage_state: str,
        *,
        render_document: bool,
        render_settle_ms: int,
    ):
        """Open a fresh, short-lived session and replay saved storage_state
        into it (spec D5). Task 8 wraps the returned context."""

        try:
            steel_session = await self._client.sessions.create()
        except Exception as exc:
            raise NetFacilitiesUnavailable(
                "Could not open a NetFacilities cloud browser session for enrichment."
            ) from exc
        playwright, browser = await _connect_over_cdp(
            steel_session.websocket_url, self._api_key
        )
        context = await browser.new_context(storage_state=json.loads(storage_state))
        return _SteelEnrichmentContext(
            client=self,
            steel_session_id=steel_session.id,
            playwright=playwright,
            browser=browser,
            context=context,
            render_document=render_document,
            render_settle_ms=render_settle_ms,
        )
```

Update `_SteelEnrichmentContext`:

```python
@dataclass
class _SteelEnrichmentContext:
    """Implements `NetFacilitiesClientContextProtocol` for one reconnected job."""

    client: "SteelCloudBrowserProvider"
    steel_session_id: str
    playwright: object
    browser: object
    context: object
    render_document: bool
    render_settle_ms: int
    _wrapped: "NetFacilitiesClient | None" = None

    async def __aenter__(self) -> "NetFacilitiesClient":
        from .client import NetFacilitiesClient

        self._wrapped = NetFacilitiesClient(
            headless=True,
            _context=self.context,
            render_document=self.render_document,
            render_settle_ms=self.render_settle_ms,
        )
        return self._wrapped

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        try:
            await self.context.close()
            await self.browser.close()
        finally:
            await self.client._client.sessions.release(self.steel_session_id)
```

- [ ] **Step 2: Update `factory.py`'s `create_netfacilities_cloud_enrichment_client`**

```python
def create_netfacilities_cloud_enrichment_client(
    config: NetFacilitiesCloudConfig,
    encrypted_storage_state: bytes,
    *,
    render_document: bool,
    render_settle_ms: int,
) -> NetFacilitiesClientContextProtocol:
    """..."""  # keep existing docstring

    from app.services import netfacilities_cloud_crypto as crypto

    from .cloud_steel import SteelCloudBrowserProvider

    if not config.enabled or config.steel_api_key is None:
        raise NetFacilitiesUnavailable(
            "NetFacilities cloud enrichment is disabled on this host."
        )
    storage_state = crypto.decrypt_storage_state(encrypted_storage_state)
    provider = SteelCloudBrowserProvider(api_key=config.steel_api_key)
    return _CloudEnrichmentContextAdapter(
        provider, storage_state, render_document=render_document, render_settle_ms=render_settle_ms
    )


class _CloudEnrichmentContextAdapter:
    def __init__(
        self, provider, storage_state: str, *, render_document: bool, render_settle_ms: int
    ) -> None:
        self._provider = provider
        self._storage_state = storage_state
        self._render_document = render_document
        self._render_settle_ms = render_settle_ms
        self._inner = None

    async def __aenter__(self):
        self._inner = await self._provider.open_replay_context(
            self._storage_state,
            render_document=self._render_document,
            render_settle_ms=self._render_settle_ms,
        )
        return await self._inner.__aenter__()

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        if self._inner is not None:
            await self._inner.__aexit__(exc_type, exc, traceback)
```

The caller in `routers/netfacilities.py::_resolve_cloud_enrichment_context` (rewritten in Task 7) must pass `render_document=config.render_document, render_settle_ms=config.render_settle_ms` where `config` is the base `NetFacilitiesConfig` already loaded in that function.

- [ ] **Step 3: Update tests**

In `test_netfacilities_cloud_steel.py`, update every call to `open_replay_context` and every construction that reaches `_SteelEnrichmentContext` to pass `render_document=False, render_settle_ms=5000` (or whatever the test's existing fixture default timeout is) as keyword args. In `test_netfacilities_cloud_enrichment_factory.py`, do the same for `create_netfacilities_cloud_enrichment_client` calls.

- [ ] **Step 4: Run**

Run: `cd backend && python -m pytest tests/test_netfacilities_cloud_steel.py tests/test_netfacilities_cloud_enrichment_factory.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/integrations/netfacilities/cloud_steel.py backend/app/integrations/netfacilities/factory.py backend/tests/test_netfacilities_cloud_steel.py backend/tests/test_netfacilities_cloud_enrichment_factory.py
git commit -m "fix(netfacilities): thread render_document/render_settle_ms into the Steel enrichment client"
```

---

### Task 7: Rewrite `routers/netfacilities.py` and `schemas/netfacilities.py`

**Files:**
- Modify: `backend/app/routers/netfacilities.py`
- Modify: `backend/app/schemas/netfacilities.py`
- Delete: `backend/tests/test_netfacilities_routes.py` (tests the routes being deleted) — replace with a smaller `test_netfacilities_cloud_routes.py` addition if that file doesn't already cover `/work-orders/enrich` and `/work-orders/enrich/{job_id}` (check first; those two routes survive, just simplified, so they need coverage somewhere).

**Interfaces (schemas):**
- Delete: `NetFacilitiesAuthenticationAttempt`, `NetFacilitiesCapability`.
- `NetFacilitiesJobSource` narrows to `Literal["cloud_session"]`.
- Keep unchanged: `NetFacilitiesEnrichmentCounts`, `NetFacilitiesEnrichmentJob`, `NetFacilitiesCloudSessionState`, `NetFacilitiesCloudSessionStatus`, `NetFacilitiesCloudCapability`.

**Interfaces (router) — surviving routes, all under `/integrations/netfacilities`:**
- `POST /work-orders/enrich` → `NetFacilitiesEnrichmentJob` (202) — now only ever resolves the caller's own cloud session; 409 when they have none, 409 when another job is running, 503 when disabled.
- `GET /work-orders/enrich/{job_id}` → `NetFacilitiesEnrichmentJob` — unchanged behavior.
- `GET /cloud/session`, `POST /cloud/auth/start`, `POST /cloud/auth/cancel`, `POST /cloud/downloads/import` — unchanged, copy verbatim.
- Deleted routes: `GET /session`, `POST /auth/start`, `POST /auth/confirm`, `POST /auth/cancel`, `POST /downloads/import`.

- [ ] **Step 1: Edit `schemas/netfacilities.py`**

Delete the `NetFacilitiesAuthenticationAttempt` class (schemas/netfacilities.py:60-83) and the `NetFacilitiesCapability` class (schemas/netfacilities.py:86-102). Change line 21 from:

```python
NetFacilitiesJobSource = Literal["live_session", "saved_state", "cloud_session"]
```

to:

```python
NetFacilitiesJobSource = Literal["cloud_session"]
```

Leave everything else in the file untouched.

- [ ] **Step 2: Replace `routers/netfacilities.py`**

```python
"""TechFM OA+ API for NetFacilities enrichment jobs (per-user Steel cloud auth)."""

from __future__ import annotations

from dataclasses import asdict
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth_deps import require_min_role
from app.database import get_db
from app.domain import roles
from app.integrations.netfacilities.cloud_config import load_netfacilities_cloud_config
from app.integrations.netfacilities.cloud_steel import SteelCloudBrowserProvider
from app.integrations.netfacilities.config import load_netfacilities_config
from app.integrations.netfacilities.errors import (
    NetFacilitiesAuthenticationRequired,
    NetFacilitiesError,
    NetFacilitiesOperationInProgress,
    NetFacilitiesUnavailable,
)
from app.models import User
from app.routers.work_orders import run_csv_import
from app.schemas.netfacilities import (
    NetFacilitiesCloudCapability,
    NetFacilitiesCloudSessionStatus,
    NetFacilitiesEnrichmentCounts,
    NetFacilitiesEnrichmentJob,
)
from app.schemas.work_orders import WorkOrderImportResult
from app.services.netfacilities_cloud_auth import (
    NetFacilitiesCloudAuthenticationCoordinator,
)
from app.services.netfacilities_jobs import (
    NetFacilitiesJobCoordinator,
    NetFacilitiesJobSnapshot,
    coordinator,
)


router = APIRouter(prefix="/integrations/netfacilities", tags=["netfacilities"])

cloud_authentication_coordinator = NetFacilitiesCloudAuthenticationCoordinator(
    provider_factory=lambda config: SteelCloudBrowserProvider(api_key=config.steel_api_key),
)


def get_netfacilities_cloud_authentication_coordinator(
) -> NetFacilitiesCloudAuthenticationCoordinator:
    return cloud_authentication_coordinator


def _forbidden() -> dict[int, dict[str, str]]:
    return {
        403: {
            "description": (
                f"Requires the {roles.label(roles.ROLE_TECHFM_OA)} role or higher."
            )
        }
    }


def get_netfacilities_coordinator() -> NetFacilitiesJobCoordinator:
    return coordinator


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


@router.post(
    "/work-orders/enrich",
    response_model=NetFacilitiesEnrichmentJob,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        **_forbidden(),
        409: {"description": "Sign in or wait for the active operation."},
        503: {"description": "NetFacilities enrichment is unavailable."},
    },
)
async def start_netfacilities_enrichment(
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    db: Session = Depends(get_db),
    jobs: NetFacilitiesJobCoordinator = Depends(get_netfacilities_coordinator),
) -> NetFacilitiesEnrichmentJob:
    """Start one batch using the calling user's own NetFacilities cloud session."""

    try:
        config = load_netfacilities_config()
    except NetFacilitiesUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="NetFacilities enrichment is unavailable on this host.",
        ) from exc
    if not config.enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="NetFacilities enrichment is disabled on this host.",
        )
    try:
        cloud_context, cloud_batch_seconds = _resolve_cloud_enrichment_context(
            config, db, user
        )
        snapshot, _created = await jobs.start(
            config,
            cloud_client_context=cloud_context,
            cloud_user_id=user.id if cloud_context is not None else None,
            cloud_batch_session_seconds=cloud_batch_seconds,
        )
    except NetFacilitiesAuthenticationRequired as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Sign in to NetFacilities before enrichment.",
        ) from exc
    except NetFacilitiesOperationInProgress as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Another NetFacilities operation is already running.",
        ) from exc
    return _job_response(snapshot)


def _resolve_cloud_enrichment_context(config, db: Session, user: User):
    """The calling user's own cloud session, ready to reconnect, and the
    batch deadline it must respect (spec §4), or `(None, None)` if they have
    none or theirs has expired (spec D10)."""

    cloud_config = load_netfacilities_cloud_config(config)
    if not cloud_config.enabled:
        return None, None
    from app.integrations.netfacilities.factory import (
        create_netfacilities_cloud_enrichment_client,
    )
    from app.models import NetFacilitiesCloudSession

    row = db.query(NetFacilitiesCloudSession).filter_by(user_id=user.id).one_or_none()
    if row is None or row.expires_at is not None:
        return None, None
    context = create_netfacilities_cloud_enrichment_client(
        cloud_config,
        row.storage_state.encode("ascii"),
        render_document=config.render_document,
        render_settle_ms=config.render_settle_ms,
    )
    return context, cloud_config.batch_session_seconds


def _mark_cloud_session_expired_if_needed(
    db: Session, job: NetFacilitiesJobSnapshot
) -> None:
    """A cloud-sourced job that lost authentication expires that user's saved
    session (spec D8: set only once an attempt actually reports it)."""

    if job.source != "cloud_session" or job.state != "authentication_required":
        return
    from app.models import NetFacilitiesCloudSession

    row = (
        db.query(NetFacilitiesCloudSession)
        .filter_by(user_id=job.user_id)
        .one_or_none()
    )
    if row is not None and row.expires_at is None:
        row.expires_at = job.finished_at
        db.commit()


@router.get(
    "/work-orders/enrich/{job_id}",
    response_model=NetFacilitiesEnrichmentJob,
    responses={
        **_forbidden(),
        404: {"description": "The process-local enrichment job is unavailable."},
    },
)
async def get_netfacilities_enrichment(
    job_id: UUID,
    _user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    db: Session = Depends(get_db),
    jobs: NetFacilitiesJobCoordinator = Depends(get_netfacilities_coordinator),
) -> NetFacilitiesEnrichmentJob:
    snapshot = await jobs.get(job_id)
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="NetFacilities enrichment job was not found on this process.",
        )
    _mark_cloud_session_expired_if_needed(db, snapshot)
    return _job_response(snapshot)


def _cloud_status_response(
    snapshot,
) -> NetFacilitiesCloudSessionStatus:
    return NetFacilitiesCloudSessionStatus(
        attempt_id=snapshot.attempt_id,
        state=snapshot.state,
        started_at=snapshot.started_at,
        finished_at=snapshot.finished_at,
        failure=snapshot.failure,
        signed_in_at=snapshot.signed_in_at,
        last_download_filename=snapshot.last_download_filename,
        last_download_at=snapshot.last_download_at,
        live_view_url=snapshot.live_view_url,
    )


@router.get("/cloud/session", response_model=NetFacilitiesCloudCapability, responses=_forbidden())
async def netfacilities_cloud_session(
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    db: Session = Depends(get_db),
    cloud_auth: NetFacilitiesCloudAuthenticationCoordinator = Depends(
        get_netfacilities_cloud_authentication_coordinator
    ),
) -> NetFacilitiesCloudCapability:
    try:
        config = load_netfacilities_config()
    except NetFacilitiesUnavailable:
        return NetFacilitiesCloudCapability(
            available=False, message="NetFacilities is unavailable on this host."
        )
    cloud_config = load_netfacilities_cloud_config(config)
    if not cloud_config.enabled:
        return NetFacilitiesCloudCapability(
            available=False,
            message="NetFacilities cloud sign-in is not enabled on this host.",
        )

    from app.models import NetFacilitiesCloudSession

    has_saved = (
        db.query(NetFacilitiesCloudSession).filter_by(user_id=user.id).first() is not None
    )
    latest = await cloud_auth.latest(user.id)
    return NetFacilitiesCloudCapability(
        available=True,
        message="Log in to NetFacilities from any device." if latest is None else "",
        status=_cloud_status_response(latest) if latest is not None else None,
        has_saved_session=has_saved,
    )


@router.post(
    "/cloud/auth/start",
    response_model=NetFacilitiesCloudSessionStatus,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_forbidden(), 503: {"description": "Cloud sign-in is unavailable."}},
)
async def start_netfacilities_cloud_authentication(
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    cloud_auth: NetFacilitiesCloudAuthenticationCoordinator = Depends(
        get_netfacilities_cloud_authentication_coordinator
    ),
) -> NetFacilitiesCloudSessionStatus:
    try:
        config = load_netfacilities_config()
    except NetFacilitiesUnavailable as exc:
        raise HTTPException(status_code=503, detail="NetFacilities is unavailable on this host.") from exc
    cloud_config = load_netfacilities_cloud_config(config)
    if not cloud_config.enabled:
        raise HTTPException(status_code=503, detail="NetFacilities cloud sign-in is not enabled on this host.")
    try:
        snapshot = await cloud_auth.start(user.id, cloud_config)
    except NetFacilitiesError as exc:
        raise HTTPException(status_code=503, detail="Could not open a NetFacilities cloud session.") from exc
    return _cloud_status_response(snapshot)


@router.post(
    "/cloud/auth/cancel",
    response_model=NetFacilitiesCloudSessionStatus,
    responses={**_forbidden(), 409: {"description": "No cloud session is active."}},
)
async def cancel_netfacilities_cloud_authentication(
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    cloud_auth: NetFacilitiesCloudAuthenticationCoordinator = Depends(
        get_netfacilities_cloud_authentication_coordinator
    ),
) -> NetFacilitiesCloudSessionStatus:
    try:
        snapshot = await cloud_auth.cancel(user.id)
    except NetFacilitiesError as exc:
        raise HTTPException(status_code=409, detail="No NetFacilities cloud session is active.") from exc
    return _cloud_status_response(snapshot)


@router.post(
    "/cloud/downloads/import",
    response_model=WorkOrderImportResult,
    responses={**_forbidden(), 409: {"description": "No CSV has been captured yet."}},
)
def import_netfacilities_cloud_download(
    background: BackgroundTasks,
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    db: Session = Depends(get_db),
    cloud_auth: NetFacilitiesCloudAuthenticationCoordinator = Depends(
        get_netfacilities_cloud_authentication_coordinator
    ),
) -> WorkOrderImportResult:
    found = cloud_auth.captured_csv_bytes(user.id)
    if found is None:
        raise HTTPException(
            status_code=409,
            detail="No CSV has been exported through the NetFacilities cloud window yet.",
        )
    _filename, data = found
    return run_csv_import(db, background, data=data, user=user)
```

Note: `read_file_capped`/`MAX_CSV_UPLOAD_BYTES` import from `app.routers._uploads` is dropped — it was only used by the deleted `import_netfacilities_download` (the local live-window download route).

- [ ] **Step 3: Test file disposition**

First check whether `test_netfacilities_cloud_routes.py` already covers `POST /work-orders/enrich` and `GET /work-orders/enrich/{job_id}`:

Run: `cd backend && grep -n "work-orders/enrich" tests/test_netfacilities_cloud_routes.py`

If it has no hits, port the relevant (non-`live_session`/non-`saved_state`) test cases out of `test_netfacilities_routes.py` into `test_netfacilities_cloud_routes.py` before deleting the old file: disabled-host 503, no-cloud-session 409, successful start with a cloud context returning 202 and `source: "cloud_session"`, duplicate-start-while-running returns the same job, and `GET .../enrich/{job_id}` 404 for an unknown id plus 200 for a known one. Then:

```bash
git rm backend/tests/test_netfacilities_routes.py
```

- [ ] **Step 4: Check `test_route_role_gates.py`**

Run: `cd backend && grep -n "netfacilities" tests/test_route_role_gates.py`

Remove any row/case referencing `/integrations/netfacilities/session`, `/auth/start`, `/auth/confirm`, `/auth/cancel`, or `/downloads/import` (the plain, non-`cloud/` one). Keep the cases for the surviving routes.

- [ ] **Step 5: Run**

Run: `cd backend && python -m pytest tests/test_netfacilities_cloud_routes.py tests/test_route_role_gates.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/netfacilities.py backend/app/schemas/netfacilities.py backend/tests/test_netfacilities_cloud_routes.py backend/tests/test_route_role_gates.py
git rm backend/tests/test_netfacilities_routes.py 2>/dev/null || true
git commit -m "refactor(netfacilities): drop local-auth routes, cloud session is the only enrichment path"
```

---

### Task 8: Fix `main.py`/`lifespan.py`

**Files:**
- Modify: `backend/app/lifespan.py`
- Modify: `backend/app/main.py` (check only — Task 7 already keeps `app.include_router(netfacilities.router)`, which still works since the router module still exists with a (smaller) route set)

**Interfaces:**
- `lifespan.py` no longer imports or calls `netfacilities_authentication` (the deleted `authentication_coordinator`).

- [ ] **Step 1: Edit `lifespan.py`**

Change (lifespan.py:7-9):

```python
from app.services.netfacilities_auth import (
    authentication_coordinator as netfacilities_authentication,
)
from app.services.netfacilities_jobs import coordinator as netfacilities_jobs
```

to:

```python
from app.services.netfacilities_jobs import coordinator as netfacilities_jobs
```

Change (lifespan.py:23-26) — remove the `netfacilities_authentication.shutdown()` call and its now-stale comment about the borrowed window:

```python
        await netfacilities_jobs.shutdown()
        await stop_dispatch()
```

(Read the surrounding comment at lifespan.py:23-24 first — "closing the window under it would turn a clean cancel into a browser error" refers to the live-session window this plan removes; delete that comment along with the call, keep any comment lines that still describe `netfacilities_jobs.shutdown()`'s own behavior if they're still accurate for the cloud-only coordinator.)

- [ ] **Step 2: Confirm `main.py` needs no change**

Run: `cd backend && grep -n "netfacilities" app/main.py`
Expected: only the router import and `app.include_router(netfacilities.router)` lines — no change needed there.

- [ ] **Step 3: Run the full backend suite for the first time since Task 2**

Run: `cd backend && python -m pytest`
Expected: all pass. This is the first point where every backend file this refactor touches is internally consistent — fix any remaining import errors or stale references surfaced here before moving on (most likely culprits: a leftover import of `netfacilities_auth`/`netfacilities_operations`/`netfacilities_live_session` somewhere `grep` in Task 2 Step 2 didn't catch, or a schema/type mismatch from Task 5's `NetFacilitiesJobSource` narrowing).

- [ ] **Step 4: Commit**

```bash
git add backend/app/lifespan.py
git commit -m "fix(netfacilities): drop lifespan shutdown hook for the deleted local-auth coordinator"
```

---

### Task 9: Frontend — `api.js`

**Files:**
- Modify: `backend/static/api.js`

**Interfaces:**
- Remove: `apiGetNetFacilitiesSession`, `apiStartNetFacilitiesAuthentication`, `apiConfirmNetFacilitiesAuthentication`, `apiCancelNetFacilitiesAuthentication`, `apiImportNetFacilitiesDownload`.
- Keep unchanged: `apiStartNetFacilitiesEnrichment`, `apiGetNetFacilitiesEnrichment`, `apiGetNetFacilitiesCloudSession`, `apiStartNetFacilitiesCloudAuthentication`, `apiCancelNetFacilitiesCloudAuthentication`, `apiImportNetFacilitiesCloudDownload`.

- [ ] **Step 1: Edit**

Replace (api.js:548-594):

```javascript
// NetFacilities enrichment: runs against the calling user's own cloud
// session (see the cloud sign-in functions below). Never returns browser
// state or source field values.
export async function apiStartNetFacilitiesEnrichment() {
  return parseResponse(await fetch(
    "/integrations/netfacilities/work-orders/enrich",
    { method: "POST", credentials: "include" },
  ));
}

export async function apiGetNetFacilitiesEnrichment(jobId) {
  return liveGet(`/integrations/netfacilities/work-orders/enrich/${encodeURIComponent(jobId)}`);
}
```

Leave the "Per-user NetFacilities cloud sign-in" block (api.js:596-621) untouched.

- [ ] **Step 2: Verify no other file still imports the removed functions**

Run: `grep -rn "apiGetNetFacilitiesSession\|apiStartNetFacilitiesAuthentication\|apiConfirmNetFacilitiesAuthentication\|apiCancelNetFacilitiesAuthentication\|apiImportNetFacilitiesDownload" backend/static`
Expected: no hits after Task 11 lands (it will still show hits in `workOrders.js` right now — that's fine, fixed next task; don't proceed past Task 11 with this grep still showing results).

- [ ] **Step 3: Commit**

Commit together with Task 11 (same logical change, split only because `workOrders.js` is large) — see Task 11's commit step.

---

### Task 10: Frontend — `integrations.html`

**Files:**
- Modify: `backend/static/pages/integrations.html`

**Interfaces:** removes the DOM ids `wo-netfacilities-sign-in-btn`, `wo-netfacilities-confirm-btn`, `wo-netfacilities-cancel-btn`, `wo-netfacilities-import-download-btn`. Keeps `wo-netfacilities-status`, `wo-netfacilities-cloud-sign-in-btn`, `wo-netfacilities-cloud-cancel-btn`, `wo-netfacilities-cloud-import-download-btn`, `wo-import-btn`, `wo-netfacilities-enrich-btn`, and everything export-related.

- [ ] **Step 1: Edit the button row**

Replace (integrations.html:24-33):

```html
                    <div class="filter-row">
                        <button id="wo-netfacilities-cloud-sign-in-btn" type="button" class="secondary-btn" hidden>Log in to NetFacilities</button>
                        <button id="wo-netfacilities-cloud-cancel-btn" type="button" class="secondary-btn" hidden>Close NetFacilities</button>
                        <button id="wo-netfacilities-cloud-import-download-btn" type="button" hidden>Import downloaded CSV</button>
                        <button id="wo-import-btn" type="button">Import from CSV&hellip;</button>
                        <button id="wo-netfacilities-enrich-btn" type="button" class="secondary-btn" hidden>Import Tasks and Priority</button>
                        <select id="wo-export-scope" aria-label="Work orders to export">
```

Note the cloud sign-in/cancel/import button labels drop their old "(any device)"/"(cloud)" qualifiers — those existed to distinguish from the local flow's identical-sounding buttons, which no longer exist, so the plain label reads correctly now.

- [ ] **Step 2: No test** — this is markup with no automated coverage; verification happens in Task 11's manual check.

- [ ] **Step 3: Commit**

Commit together with Task 11.

---

### Task 11: Frontend — `workOrders.js`

**Files:**
- Modify: `backend/static/views/workOrders.js`

**Interfaces:**
- Removes: the entire old-card block from the import list (`apiGetNetFacilitiesSession` through `apiImportNetFacilitiesDownload`), the four old DOM consts (`netFacilitiesSignInBtn`, `netFacilitiesConfirmBtn`, `netFacilitiesCancelBtn`, `netFacilitiesImportDownloadBtn`), `netFacilitiesSessionPolling`, `NETFACILITIES_ACTIVE_AUTH_STATES`, `NETFACILITIES_LIVE_STATES`, `updateNetFacilitiesControls`, `netFacilitiesReauthenticationAction`, `renderNetFacilitiesSignedIn`, `refreshNetFacilitiesSession`, `ensureNetFacilitiesSessionPolling`, `startNetFacilitiesAuthentication`, `confirmNetFacilitiesAuthentication`, `cancelNetFacilitiesAuthentication`, and their `addEventListener` wiring.
- Keeps and adapts: `NETFACILITIES_SESSION_POLL_MS`, `netFacilitiesCountsMessage`, `describeNetFacilitiesJob` (drop its `authentication_required` message's reference to the old reauth text — see Step 3), `renderNetFacilitiesJob`, `pollNetFacilitiesJob`, `runNetFacilitiesEnrichment`, everything in the "Per-user NetFacilities cloud sign-in" block (`refreshNetFacilitiesCloudSession`, `updateNetFacilitiesCloudControls`, `startNetFacilitiesCloudAuthentication`, `cancelNetFacilitiesCloudAuthentication`, `importNetFacilitiesCloudDownload`), `afterWorkOrderImport` (rewired — see Step 4), `netFacilitiesCapability` module-level variable (removed, replaced by relying solely on the cloud capability already tracked via `updateNetFacilitiesCloudControls`'s closure — see Step 5).

- [ ] **Step 1: Trim the import list**

Change (workOrders.js:42-52) from:

```javascript
  apiGetNetFacilitiesSession,
  apiStartNetFacilitiesAuthentication,
  apiConfirmNetFacilitiesAuthentication,
  apiCancelNetFacilitiesAuthentication,
  apiStartNetFacilitiesEnrichment,
  apiGetNetFacilitiesEnrichment,
  apiImportNetFacilitiesDownload,
  apiGetNetFacilitiesCloudSession,
  apiStartNetFacilitiesCloudAuthentication,
  apiCancelNetFacilitiesCloudAuthentication,
  apiImportNetFacilitiesCloudDownload,
```

to:

```javascript
  apiStartNetFacilitiesEnrichment,
  apiGetNetFacilitiesEnrichment,
  apiGetNetFacilitiesCloudSession,
  apiStartNetFacilitiesCloudAuthentication,
  apiCancelNetFacilitiesCloudAuthentication,
  apiImportNetFacilitiesCloudDownload,
```

- [ ] **Step 2: Trim the DOM element consts**

Change (workOrders.js:100-108) from:

```javascript
const netFacilitiesStatus = document.getElementById("wo-netfacilities-status");
const netFacilitiesSignInBtn = document.getElementById("wo-netfacilities-sign-in-btn");
const netFacilitiesConfirmBtn = document.getElementById("wo-netfacilities-confirm-btn");
const netFacilitiesCancelBtn = document.getElementById("wo-netfacilities-cancel-btn");
const netFacilitiesEnrichBtn = document.getElementById("wo-netfacilities-enrich-btn");
const netFacilitiesImportDownloadBtn = document.getElementById("wo-netfacilities-import-download-btn");
const netFacilitiesCloudSignInBtn = document.getElementById("wo-netfacilities-cloud-sign-in-btn");
const netFacilitiesCloudCancelBtn = document.getElementById("wo-netfacilities-cloud-cancel-btn");
const netFacilitiesCloudImportDownloadBtn = document.getElementById("wo-netfacilities-cloud-import-download-btn");
```

to:

```javascript
const netFacilitiesStatus = document.getElementById("wo-netfacilities-status");
const netFacilitiesEnrichBtn = document.getElementById("wo-netfacilities-enrich-btn");
const netFacilitiesCloudSignInBtn = document.getElementById("wo-netfacilities-cloud-sign-in-btn");
const netFacilitiesCloudCancelBtn = document.getElementById("wo-netfacilities-cloud-cancel-btn");
const netFacilitiesCloudImportDownloadBtn = document.getElementById("wo-netfacilities-cloud-import-download-btn");
```

- [ ] **Step 3: Replace the whole old-card block (roughly workOrders.js:2080–2365)**

Delete everything from `const NETFACILITIES_ACTIVE_AUTH_STATES = new Set([` through the `if (netFacilitiesEnrichBtn) { netFacilitiesEnrichBtn.addEventListener("click", runNetFacilitiesEnrichment); }` block (inclusive) that immediately precedes the `// --- Per-user NetFacilities cloud sign-in` comment, and replace it with:

```javascript
const NETFACILITIES_SESSION_POLL_MS = 3000;

function netFacilitiesCountsMessage(job) {
  const counts = job && job.counts;
  if (!counts) return "NetFacilities enrichment did not return result counts.";
  return [
    `checked ${counts.fetched} of ${counts.candidates} candidate${counts.candidates === 1 ? "" : "s"}`,
    `${counts.descriptions_updated} Task/Symptom updated`,
    `${counts.priorities_updated} Priority updated`,
    `${counts.unchanged} unchanged`,
    `${counts.not_found} not found`,
    `${counts.permission_denied} permission denied`,
    `${counts.other_failures} other failure${counts.other_failures === 1 ? "" : "s"}`,
  ].join(" · ");
}

// Pure: one job snapshot -> the line the card shows and its message kind.
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
      text: "NetFacilities authentication is missing or expired. Log in to NetFacilities, then click Import Tasks and Priority.",
      kind: "error",
    };
  }
  if (job.state === "timed_out") {
    return { text: `NetFacilities enrichment timed out with partial results: ${netFacilitiesCountsMessage(job)}.`, kind: "error" };
  }
  if (job.state === "cancelled") {
    return { text: "NetFacilities enrichment stopped when the app shut down.", kind: "error" };
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

async function pollNetFacilitiesJob(jobId) {
  if (!jobId || netFacilitiesPollingJobId === jobId) return;
  netFacilitiesPollingJobId = jobId;
  if (netFacilitiesEnrichBtn) netFacilitiesEnrichBtn.disabled = true;
  try {
    while (netFacilitiesPollingJobId === jobId) {
      const job = await apiGetNetFacilitiesEnrichment(jobId);
      renderNetFacilitiesJob(job);
      if (job.state !== "queued" && job.state !== "running") {
        if (job.state === "completed" || job.state === "timed_out") {
          usersLoaded = false;
          filterOptionsLoaded = false;
          await loadWorkOrders();
        }
        await refreshNetFacilitiesCloudSession();
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
  } catch (err) {
    if (netFacilitiesStatus) {
      setMessage(netFacilitiesStatus, friendlyError(err, "Could not check NetFacilities enrichment progress."), "error");
    }
  } finally {
    if (netFacilitiesPollingJobId === jobId) netFacilitiesPollingJobId = null;
  }
}

async function runNetFacilitiesEnrichment() {
  if (netFacilitiesEnrichBtn) netFacilitiesEnrichBtn.disabled = true;
  try {
    const job = await apiStartNetFacilitiesEnrichment();
    renderNetFacilitiesJob(job);
    await pollNetFacilitiesJob(job.job_id);
  } catch (err) {
    if (netFacilitiesStatus) {
      setMessage(netFacilitiesStatus, friendlyError(err, "Could not start NetFacilities enrichment. Log in to NetFacilities, then try again."), "error");
    }
  } finally {
    await refreshNetFacilitiesCloudSession();
  }
}

if (netFacilitiesEnrichBtn) {
  netFacilitiesEnrichBtn.addEventListener("click", runNetFacilitiesEnrichment);
}
```

`netFacilitiesPollingJobId` stays declared wherever it already is (search: `let netFacilitiesPollingJobId` — it's declared once, near the other module-level `let`s at the top of this section; keep that declaration, only the block above changes).

- [ ] **Step 4: Rewire `updateNetFacilitiesCloudControls` to also drive the shared Enrich button**

The old card's `updateNetFacilitiesControls` used to show/enable `netFacilitiesEnrichBtn` based on the old capability's `state === "ready" || signedIn`. That button is now driven entirely by the cloud capability. Edit `updateNetFacilitiesCloudControls` (workOrders.js:2388-2415 in the pre-cleanup file) to add this at the end, right before the polling-timer block:

```javascript
function updateNetFacilitiesCloudControls(capability) {
  const available = Boolean(capability && capability.available);
  const cloudStatus = capability && capability.status;
  const awaitingSignIn = Boolean(cloudStatus && cloudStatus.state === "awaiting_sign_in");
  const signedIn = Boolean(cloudStatus && cloudStatus.state === "signed_in");
  const hasCsv = signedIn && Boolean(cloudStatus.last_download_filename);

  if (netFacilitiesCloudSignInBtn) {
    netFacilitiesCloudSignInBtn.hidden = !available || awaitingSignIn || signedIn;
  }
  if (netFacilitiesCloudCancelBtn) {
    netFacilitiesCloudCancelBtn.hidden = !(awaitingSignIn || signedIn);
  }
  if (netFacilitiesCloudImportDownloadBtn) {
    netFacilitiesCloudImportDownloadBtn.hidden = !hasCsv;
  }
  if (netFacilitiesEnrichBtn) {
    netFacilitiesEnrichBtn.hidden = !available;
    netFacilitiesEnrichBtn.disabled = !(available && capability.has_saved_session)
      || Boolean(netFacilitiesPollingJobId);
  }
  if (netFacilitiesStatus && !awaitingSignIn) {
    if (!available) {
      setMessage(netFacilitiesStatus, capability ? capability.message : "NetFacilities status is unavailable. CSV import still works normally.", "");
    } else if (signedIn) {
      const parts = [];
      if (cloudStatus.last_download_filename) {
        parts.push(`Saved ${cloudStatus.last_download_filename}. Click Import downloaded CSV to import it and fill in Task/Symptom and Priority.`);
      } else {
        parts.push("NetFacilities is open and logged in. Export the work-order CSV in that window; it can be imported from here.");
      }
      setMessage(netFacilitiesStatus, parts.join(" "), "success");
    } else if (capability.has_saved_session) {
      setMessage(netFacilitiesStatus, "Saved NetFacilities login is ready. Choose a downloaded CSV to import it and seek Task/Symptom and Priority, or log in to export a fresh one.", "success");
    } else {
      setMessage(netFacilitiesStatus, capability.message, "");
    }
  }

  const shouldPoll = available && (awaitingSignIn || signedIn);
  if (shouldPoll && !netFacilitiesCloudPollTimer) {
    netFacilitiesCloudPollTimer = setInterval(
      refreshNetFacilitiesCloudSession,
      NETFACILITIES_SESSION_POLL_MS,
    );
  } else if (!shouldPoll && netFacilitiesCloudPollTimer) {
    clearInterval(netFacilitiesCloudPollTimer);
    netFacilitiesCloudPollTimer = null;
  }
}
```

This is the "overhaul" the user asked for: one capability (`/cloud/session`), one status line, one Enrich button gated on it — no more two parallel cards silently duplicating each other's job.

- [ ] **Step 5: Rewire `afterWorkOrderImport`**

Change (workOrders.js:2481-2493) from:

```javascript
async function afterWorkOrderImport(r) {
  setMessage(importMessage, importSummary(r), "success");
  usersLoaded = false;
  filterOptionsLoaded = false;
  await loadWorkOrders();
  const capability = await refreshNetFacilitiesSession();
  if (capability && (capability.state === "ready" || capability.state === "signed_in")) {
    await runNetFacilitiesEnrichment();
  }
}
```

to:

```javascript
async function afterWorkOrderImport(r) {
  setMessage(importMessage, importSummary(r), "success");
  usersLoaded = false;
  filterOptionsLoaded = false;
  await loadWorkOrders();
  const capability = await refreshNetFacilitiesCloudSession();
  const cloudStatus = capability && capability.status;
  if (
    capability
    && capability.available
    && (capability.has_saved_session || (cloudStatus && cloudStatus.state === "signed_in"))
  ) {
    await runNetFacilitiesEnrichment();
  }
}
```

- [ ] **Step 6: Wire the initial page-load call**

Search for `void refreshNetFacilitiesCloudSession();` (workOrders.js:1061 in the pre-cleanup file) — it already runs on load; there is no equivalent old-card call to remove there (`refreshNetFacilitiesSession()` was called only reactively, from `afterWorkOrderImport` and the old button handlers, not on initial load — confirm this with `grep -n "refreshNetFacilitiesSession" backend/static/views/workOrders.js` before this edit; if it turns out there *was* an initial-load call to the old function, replace it with `refreshNetFacilitiesCloudSession()` too, guarding against calling it twice).

- [ ] **Step 7: Manual smoke test**

Run the app locally (consult the `run` skill or existing local-dev docs for how this repo starts its dev server) with `NETFACILITIES_ENABLED=true`, `NETFACILITIES_CLOUD_AUTH_ENABLED=true`, a real `STEEL_API_KEY`, and `NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY` set (see `backend/scripts/generate_netfacilities_cloud_encryption_key.py` if one isn't already in your local `.env`). As an Admin+ user, open the Integrations page and confirm: only cloud buttons render; "Log in to NetFacilities" opens a Steel live-view tab; after completing sign-in the card shows signed-in status; "Import Tasks and Priority" starts a job and the status line updates to completion; importing a CSV auto-triggers enrichment when a saved cloud session exists.

- [ ] **Step 8: Commit (covers Tasks 9, 10, 11)**

```bash
git add backend/static/api.js backend/static/pages/integrations.html backend/static/views/workOrders.js
git commit -m "feat(netfacilities): overhaul the Integrations card to cloud-only sign-in"
```

---

### Task 12: Frontend copy — `tips.js`

**Files:**
- Modify: `backend/static/tips.js`

- [ ] **Step 1: Edit**

Change (tips.js:257-258) from:

```javascript
    label: "NetFacilities import and export",
    text: "Log in to NetFacilities opens a window that stays open. Export the work-order CSV there; it lands in your Downloads folder and Import downloaded CSV brings it in, then Task/Symptom and Priority fill in through the same window. Import from CSV still accepts any file you already have. For Client exports the billing sheet with totals and receipts, scoped by the dropdown beside it.",
```

to:

```javascript
    label: "NetFacilities import and export",
    text: "Log in to NetFacilities opens a cloud sign-in window from any device. Export the work-order CSV there; Import downloaded CSV brings it in, then Import Tasks and Priority fills in Task/Symptom and Priority from the same session. Import from CSV still accepts any file you already have. For Client exports the billing sheet with totals and receipts, scoped by the dropdown beside it.",
```

- [ ] **Step 2: Commit**

```bash
git add backend/static/tips.js
git commit -m "docs(netfacilities): update the Integrations tip for cloud-only sign-in"
```

---

### Task 13: Delete/update remaining tests and scripts

**Files:**
- Delete: `backend/tests/test_netfacilities_poc.py` if `backend/scripts/netfacilities_poc.py` is itself a local-profile CLI being removed — check first (Step 1 below); if the script stays (e.g. still useful for someone with local Playwright + a manual cookie file for debugging outside this app's auth system), leave both and skip this deletion.
- Check: `backend/tests/test_netfacilities_diagnostic.py` / `backend/scripts/netfacilities_diagnostic.py` — these read a single work order through whatever client the caller constructs; confirm they don't hard-depend on `use_saved_state`/`profile_dir` (removed in Task 3) and fix the construction call if they do.
- Check: `backend/tests/test_netfacilities_service.py`, `backend/tests/test_work_order_import.py`, `backend/tests/test_work_order_priority.py`, `backend/tests/test_work_orders_service.py`, `backend/tests/test_models_netfacilities_cloud_session.py` — these test `enrich_work_orders`/import/priority behavior against fake clients, not the auth machinery; expect no changes, but the full-suite run below will surface anything that does need one.

- [ ] **Step 1: Decide the fate of `netfacilities_poc.py`**

Run: `cd backend && grep -n "profile_dir\|use_saved_state\|NetFacilitiesClient(" scripts/netfacilities_poc.py`

If it constructs `NetFacilitiesClient` with `profile_dir=`/`use_saved_state=` (parameters removed in Task 3), either delete the script and its test (it's local-profile tooling for the system being removed) or update it to take a `_context` the way `cloud_steel.py` does — ask the person driving this session which they want if it's not obvious from the script's own docstring/purpose; default to deleting it, since this whole cleanup's premise is "the local profile system is gone."

- [ ] **Step 2: Run the full backend suite**

Run: `cd backend && python -m pytest`
Expected: all pass, zero references to any deleted symbol anywhere in `tests/`.

- [ ] **Step 3: Grep sweep for anything missed**

Run: `cd backend && grep -rln "netfacilities_auth\|netfacilities_live_session\|netfacilities_operations\|NetFacilitiesAuthenticationCoordinator\|NetFacilitiesAuthenticationAttempt\|NetFacilitiesCapability\b\|use_saved_state\|profile_dir\|interactive_authentication_available\|has_saved_authentication\|storage_state_path\b" app tests`
Expected: no output. Fix anything that appears.

- [ ] **Step 4: Commit**

```bash
git add -A backend/tests backend/scripts
git commit -m "chore(netfacilities): finish removing local-auth test/script references"
```

---

### Task 14: Docs — `current-state.md`, `endpoint-map.md`, `open-work.md`

**Files:**
- Modify: `docs/current-state.md`
- Modify: `docs/endpoint-map.md`
- Modify: `docs/open-work.md`

Per this repo's doc-routing convention, `current-state.md` and `endpoint-map.md` are the living reference and must reflect the code as it now stands; `open-work.md` is the backlog and should reflect that IMP-039 (live session) is retired rather than "in progress."

- [ ] **Step 1: `docs/open-work.md`**

Find the `### IMP-039 — NetFacilities live session — IN PROGRESS` section (open-work.md:80-94 as of this plan's writing). Change its status line to `RETIRED` and replace its body with one or two sentences: the shared-secret-file/live-session auth path was removed on this date in favor of IMP-040's per-user Steel cloud auth becoming the sole path; see this plan's commit range for what changed. Leave IMP-040's section as-is (still accurate) except drop any sentence there that describes cloud auth as "a third, additive" path alongside the two others — it is now the only path.

- [ ] **Step 2: `docs/endpoint-map.md`**

Delete rows NF1, NF1a, NF1b, NF1c, NF4 (endpoint-map.md:131-137 — the plain `/session`, `/auth/*`, `/downloads/import` rows). Renumber or leave NF2/NF3/NF5/NF5a/NF5b/NF6 with their existing ids (don't renumber — other docs/tests may cite these ids; adding a note "NF1/NF1a-c/NF4 removed 2026-08-29" above the table is fine and cheaper than renumbering). Update NF2's description to drop "if no live window" language (matches Task 7's simplified `start_netfacilities_enrichment`). Update the prose walkthrough around endpoint-map.md:475-500 (the "On the local Windows host, an Admin calls..." paragraph) to remove the local-flow narrative; keep the cloud-flow narrative. Update the schema section around endpoint-map.md:997-1033 to drop `NetFacilitiesCapability`/`NetFacilitiesAuthenticationAttempt` and note `NetFacilitiesJobSource` is now `cloud_session`-only.

- [ ] **Step 3: `docs/current-state.md`**

This file has the deepest coverage (roughly current-state.md:59, 134, 163-184, 231, 260, 1670-1933, 2962-2997, 3027-3035). Read each of those ranges in full before editing (they're long and interleaved with unrelated content) and:
- Update the one-line feature summary (~line 59) to say the enrichment path is per-user Steel cloud auth, not "a bundled Playwright" local/hosted split.
- Update the file-list table (~line 134) and the file-purpose list (~lines 163-184) to drop `netfacilities_auth.py`, `netfacilities_operations.py`, and the "TechFM OA+ local headed sign-in..." sentence; describe the cloud-only flow instead.
- Update the endpoint table (~lines 1923-1929) to match Task 7's surviving routes only.
- Update the test-file table (~lines 2962-2997) to drop the row for `test_netfacilities_auth.py` (deleted) and `test_netfacilities_routes.py` if fully replaced, and adjust `test_netfacilities_jobs.py`'s description to say "cloud-session-only precondition" instead of "local/hosted saved-auth precondition."
- Update the changelog-style notes around ~3027-3035 with a dated entry (use today's date) noting the local-auth removal, mirroring how prior entries in this file are written (read a few of the surrounding entries for the house style before writing this one).

- [ ] **Step 4: Commit**

```bash
git add docs/current-state.md docs/endpoint-map.md docs/open-work.md
git commit -m "docs(netfacilities): retire the local-auth flow from the reference docs"
```

---

### Task 15: Render + Dockerfile + `render.yaml`

**Files:**
- Modify: `render.yaml`
- Modify: `backend/Dockerfile`

**Interfaces:** `NETFACILITIES_STORAGE_STATE_PATH` and `NETFACILITIES_BROWSER_CHANNEL` are no longer read anywhere in the code after Task 1 — remove both from both files. `NETFACILITIES_ENABLED` stays (still the master switch `load_netfacilities_config` checks).

- [ ] **Step 1: Edit `render.yaml`**

Replace (render.yaml:47-59):

```yaml
      # Hosted enrichment reads a per-user NetFacilities session captured through
      # Steel cloud sign-in (see STEEL_API_KEY and
      # NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY, set via the dashboard's
      # Environment page since they're credentials, not committed here).
      - key: NETFACILITIES_ENABLED
        value: "true"
```

- [ ] **Step 2: Edit `backend/Dockerfile`**

Replace (Dockerfile:14-16):

```dockerfile
ENV NETFACILITIES_ENABLED=true
```

(drop the `\` continuation and the two removed keys; adjust the surrounding `ENV` block's syntax if this was part of a multi-line `ENV` statement with other keys below it — read the lines immediately after Dockerfile:16 before editing, so the `ENV` statement stays syntactically valid.)

- [ ] **Step 3: Confirm no other file reads the two removed env vars**

Run: `grep -rln "NETFACILITIES_STORAGE_STATE_PATH\|NETFACILITIES_BROWSER_CHANNEL" --include="*.py" --include="*.yaml" --include="Dockerfile" .`
Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add render.yaml backend/Dockerfile
git commit -m "chore(netfacilities): drop the storage-state secret file and browser-channel settings"
```

- [ ] **Step 5: Render dashboard action (not a code change — do this once the branch from this plan is merged and deployed)**

In Render's dashboard (inventory-app → Environment): delete the secret file `netfacilities-storage-state.json`. Do not remove `NETFACILITIES_ENABLED` — it stays `true`. There is nothing else to change in the dashboard; `NETFACILITIES_STORAGE_STATE_PATH` and `NETFACILITIES_BROWSER_CHANNEL` are removed by this task's `render.yaml`/Dockerfile edit and Render will simply stop setting them once this branch deploys — no separate dashboard edit needed for those two.

---

## Self-review notes (for whoever executes this)

- **Coverage:** every backend module that imports something this plan deletes is listed in some task's Step (verified via the grep in Task 2 Step 2 and the sweep in Task 13 Step 3) — if the full-suite run in Task 8 Step 3 or Task 13 Step 2 surfaces an import error this plan didn't anticipate, that's a gap in this inventory, not a sign to work around it; fix the actual caller.
- **`NetFacilitiesOperationGate`/`operation_gate`:** confirmed unused by the cloud path (`netfacilities_jobs.py`'s own docstring says so) — safe to delete outright in Task 2, not just stop calling.
- **`render_document`/`render_settle_ms` gap (Task 6):** this is the one place this plan changes behavior rather than just deleting dead code — flagged explicitly so it isn't missed or mistaken for scope creep. If whoever executes this plan wants to skip it, that's a valid call (it predates this cleanup and isn't strictly required to remove the old system) — but skipping it means the cloud path continues silently never using `NETFACILITIES_RENDER_DOCUMENT`, which is worth a deliberate decision, not an accident.
- **Type consistency:** `NetFacilitiesJobSource` narrows to `Literal["cloud_session"]` consistently across `schemas/netfacilities.py` (Task 7) and `services/netfacilities_jobs.py` (Task 5) — both edited to match.
- **No placeholders:** every task above either gives the full replacement file content or an exact before/after diff; the only steps that say "check first" (Task 4 Step 2, Task 7 Step 3, Task 13 Steps 1/3) are ones where this plan's author did not have the current file content in hand and the check itself is a one-line grep with a stated expected result, not an open-ended "figure it out."

---

## Execution options

This plan is meant to be picked up cold in a separate session. Once there:

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task above, review between tasks, fast iteration.

**2. Inline Execution** — work through the tasks in one session using `superpowers:executing-plans`, batching a few tasks between checkpoints.

Either way, do not skip ahead of the "Order of operations" list at the top — several tasks leave the tree in a temporarily-broken state on purpose (Task 2 through Task 8) and the full test suite is not expected to pass until Task 8 Step 3.
