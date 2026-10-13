# Request Memory Telemetry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stamp process RSS, container cgroup memory, and the per-request cgroup delta onto the existing `event=request` log line so a production memory step-up can be traced to the exact request that caused it.

**Architecture:** One new stdlib-only function in `app/logging_config.py` reads `/proc/self/statm` (Python process resident set) and the cgroup memory file (the container total Render enforces, which also counts child processes such as the Playwright driver). The `log_request` middleware in `app/main.py` samples before and after `call_next` and adds three fields to the completion and error lines. Nothing new is emitted; the existing per-request line (including the platform's `/healthz` polls) becomes a free memory sampler.

**Tech Stack:** Python 3.12 stdlib only (`os`, file reads). FastAPI middleware already in place. pytest + `TestClient` for tests.

**Spec:** None. Design settled in chat on 2026-10-13 (option 2 of the four discussed: request-line telemetry, no tracemalloc, no periodic sampler).

## Global Constraints

- No new dependencies. `psutil` is not installed and must not be added.
- Files stay under 500 lines (`app/main.py` is 468, `app/logging_config.py` is 214; the additions fit).
- Local dev is Windows: neither file exists there. Absent readings render as `-`, never raise.
- Never logged: anything beyond the three integer fields. No paths, no `/proc` contents.
- Run targeted tests only (`tests/test_logging.py`) before commit; the full suite is not required for this bounded diff.
- Do not push. Pushing `main` deploys to production; the user decides when.

## Review Focus

1. Windows dev machine (no `/proc`, no cgroup files): request line still renders with `rss_mb=- cg_mb=- cg_delta_mb=-` and the app serves normally. Test in Task 1 (`test_memory_sample_is_absent_where_the_files_do_not_exist`) and Task 2 (`test_the_request_line_survives_absent_memory_readings`).
2. Container running cgroup v1 instead of v2: the v1 path is the fallback. Test in Task 1 (`test_memory_sample_falls_back_to_cgroup_v1`).
3. A cgroup file holding a non-integer (some platforms write `max`): reads as absent, never raises inside the middleware. Test in Task 1 (`test_memory_sample_treats_garbage_as_absent`).
4. A request that raises: the `request.error` line also carries the memory fields, because the request that tips the container over is often the one that fails. Test in Task 2 (`test_the_error_line_carries_memory_fields`).
5. `/healthz` is polled continuously by Render: the three fields add roughly 40 bytes per existing line and no new lines. No test; noted here so nobody adds a separate sampler for it.

---

### Task 1: `memory_sample()` in `app/logging_config.py`

**Files:**
- Modify: `backend/app/logging_config.py` (append after `bind_user`, around line 214)
- Test: `backend/tests/test_logging.py` (new section at the end)

**Interfaces:**
- Produces: `memory_sample() -> dict[str, Optional[int]]` with keys `rss_mb` and `cg_mb`, whole megabytes, `None` where unreadable. Module constants `_STATM_PATH: str`, `_CGROUP_PATHS: tuple[str, ...]`, `_PAGE_SIZE: int` exist so tests can monkeypatch them.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_logging.py`:

```python
# --------------------------------------------------------------------------
# memory sampling
# --------------------------------------------------------------------------

MB = 1024 * 1024


def _point_sampler_at(monkeypatch, tmp_path, *, statm=None, cgroup=()):
    """Redirect the sampler's file reads into tmp_path. `statm` is the
    whole /proc/self/statm line; `cgroup` is an ordered list of
    (filename, content) in fallback order, content None = file absent."""
    statm_path = tmp_path / "statm"
    if statm is not None:
        statm_path.write_text(statm)
    cgroup_paths = []
    for name, content in cgroup:
        path = tmp_path / name
        if content is not None:
            path.write_text(content)
        cgroup_paths.append(str(path))
    monkeypatch.setattr(logging_config, "_STATM_PATH", str(statm_path))
    monkeypatch.setattr(logging_config, "_CGROUP_PATHS", tuple(cgroup_paths))
    monkeypatch.setattr(logging_config, "_PAGE_SIZE", 4096)


def test_memory_sample_reads_rss_pages_and_cgroup_v2_bytes(monkeypatch, tmp_path):
    # statm: size resident shared text lib data dt -- resident is field 2.
    _point_sampler_at(
        monkeypatch, tmp_path,
        statm="9000 2560 100 1 0 200 0",
        cgroup=[("memory.current", str(300 * MB))],
    )

    assert logging_config.memory_sample() == {"rss_mb": 10, "cg_mb": 300}


def test_memory_sample_falls_back_to_cgroup_v1(monkeypatch, tmp_path):
    _point_sampler_at(
        monkeypatch, tmp_path,
        statm="9000 2560 100 1 0 200 0",
        cgroup=[("memory.current", None), ("memory.usage_in_bytes", str(123 * MB))],
    )

    assert logging_config.memory_sample()["cg_mb"] == 123


def test_memory_sample_is_absent_where_the_files_do_not_exist(monkeypatch, tmp_path):
    # Windows dev box: no /proc, no cgroup. Must not raise.
    _point_sampler_at(monkeypatch, tmp_path, statm=None, cgroup=[("memory.current", None)])

    assert logging_config.memory_sample() == {"rss_mb": None, "cg_mb": None}


def test_memory_sample_treats_garbage_as_absent(monkeypatch, tmp_path):
    _point_sampler_at(
        monkeypatch, tmp_path,
        statm="not numbers",
        cgroup=[("memory.current", "max\n")],
    )

    assert logging_config.memory_sample() == {"rss_mb": None, "cg_mb": None}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run from `backend/`: `python -m pytest tests/test_logging.py -k memory_sample -v`
Expected: 4 FAIL with `AttributeError: module 'app.logging_config' has no attribute '_STATM_PATH'`

- [ ] **Step 3: Implement `memory_sample`**

Append to `backend/app/logging_config.py` after `bind_user`:

```python
# Memory readings for the request-completion line. Two numbers on purpose:
# the Python process's resident set, and the container's cgroup total. The
# platform enforces its limit on the cgroup figure, and child processes
# (the Playwright driver, for one) count there but never in RSS -- so the
# gap between the two is what separates heap growth from subprocesses.
# Both are plain file reads that exist only on Linux; elsewhere they read
# as absent, which the formatter renders as `-`.
_STATM_PATH = "/proc/self/statm"
_CGROUP_PATHS = (
    "/sys/fs/cgroup/memory.current",                # cgroup v2
    "/sys/fs/cgroup/memory/memory.usage_in_bytes",  # cgroup v1
)
_PAGE_SIZE = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096
_MB = 1024 * 1024


def _read_int_field(path: str, index: int = 0) -> Optional[int]:
    """Whitespace-split field `index` of a small text file as an int, or
    None if the file is missing or the field is not a number."""
    try:
        with open(path) as handle:
            return int(handle.read().split()[index])
    except (OSError, ValueError, IndexError):
        return None


def memory_sample() -> dict[str, Optional[int]]:
    """Current memory in whole MB: `rss_mb` for this process, `cg_mb` for
    the container. Either is None where its file is unavailable."""
    resident_pages = _read_int_field(_STATM_PATH, index=1)
    cgroup_bytes = next(
        (value for value in map(_read_int_field, _CGROUP_PATHS) if value is not None),
        None,
    )
    return {
        "rss_mb": None if resident_pages is None else resident_pages * _PAGE_SIZE // _MB,
        "cg_mb": None if cgroup_bytes is None else cgroup_bytes // _MB,
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run from `backend/`: `python -m pytest tests/test_logging.py -k memory_sample -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/logging_config.py backend/tests/test_logging.py
git commit -m "feat(logging): stdlib memory sampler for process RSS and cgroup total"
```

---

### Task 2: Memory fields on the request line, plus the doc bullet

**Files:**
- Modify: `backend/app/main.py:41-45` (import block) and `backend/app/main.py:240-310` (`log_request`)
- Modify: `docs/current-state.md:313` (the `event=request` bullet)
- Test: `backend/tests/test_logging.py` (same new section)

**Interfaces:**
- Consumes: `memory_sample()` from Task 1, imported into `app.main` by name (tests monkeypatch `main.memory_sample`).
- Produces: three new fields on both `event=request` and `event=request.error` lines: `rss_mb`, `cg_mb`, `cg_delta_mb` (after minus before, cgroup figure; `None` when either reading is absent).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_logging.py` (add `from fastapi.testclient import TestClient` to the imports at the top of the file):

```python
def _sampler_returning(monkeypatch, *samples):
    """Make `main.memory_sample` hand out the given dicts in order."""
    queue = iter(samples)
    monkeypatch.setattr(main, "memory_sample", lambda: next(queue))


def test_the_request_line_carries_memory_fields_and_the_cgroup_delta(monkeypatch, caplog):
    monkeypatch.setattr(main, "check_connection", lambda: None)
    _sampler_returning(
        monkeypatch,
        {"rss_mb": 80, "cg_mb": 300},
        {"rss_mb": 95, "cg_mb": 420},
    )
    caplog.set_level(logging.INFO)

    TestClient(main.app).get("/healthz")

    record = next(r for r in caplog.records if r.getMessage() == "request")
    assert record.fields["rss_mb"] == 95
    assert record.fields["cg_mb"] == 420
    assert record.fields["cg_delta_mb"] == 120


def test_the_request_line_survives_absent_memory_readings(monkeypatch, caplog):
    monkeypatch.setattr(main, "check_connection", lambda: None)
    _sampler_returning(
        monkeypatch,
        {"rss_mb": None, "cg_mb": None},
        {"rss_mb": None, "cg_mb": None},
    )
    caplog.set_level(logging.INFO)

    response = TestClient(main.app).get("/healthz")

    assert response.status_code == 200
    record = next(r for r in caplog.records if r.getMessage() == "request")
    assert record.fields["cg_delta_mb"] is None
    # The formatter renders None as the column placeholder, not "None".
    assert "cg_delta_mb=-" in LogfmtFormatter().format(record)


def test_the_error_line_carries_memory_fields(monkeypatch, caplog):
    def explode():
        raise RuntimeError("boom")

    monkeypatch.setattr(main, "check_connection", explode)
    _sampler_returning(
        monkeypatch,
        {"rss_mb": 80, "cg_mb": 300},
        {"rss_mb": 80, "cg_mb": 480},
    )
    caplog.set_level(logging.ERROR)

    TestClient(main.app, raise_server_exceptions=False).get("/healthz")

    record = next(r for r in caplog.records if r.getMessage() == "request.error")
    assert record.fields["cg_delta_mb"] == 180
```

Note for the implementer: `healthz` catches only SQLAlchemy errors, so a `RuntimeError` from `check_connection` propagates to the middleware's `except Exception` branch. If that turns out not to be true when you run it, use `monkeypatch.setattr(main, "check_connection", ...)` on a different exception type that `healthz` does not catch; do not change `healthz`.

- [ ] **Step 2: Run the tests to verify they fail**

Run from `backend/`: `python -m pytest tests/test_logging.py -k "request_line or error_line" -v`
Expected: 3 FAIL. The first fails with `AttributeError: <module 'app.main'> has no attribute 'memory_sample'` from the monkeypatch.

- [ ] **Step 3: Import and sample in the middleware**

In `backend/app/main.py`, add `memory_sample` to the existing import from `app.logging_config` (line 41 block):

```python
from app.logging_config import (
    configure_logging,
    memory_sample,
    new_request_context,
    request_context,
)
```

`app/main.py` has no `from typing` import today; add `from typing import Any` beside the other stdlib imports (after `from pathlib import Path`, line 29).

In `log_request`, after `started = time.perf_counter()`, add the before-sample and a helper, then spread it into both log calls:

```python
    context = new_request_context(uuid.uuid4().hex[:12])
    token = request_context.set(context)
    started = time.perf_counter()
    before = memory_sample()

    def elapsed_ms() -> int:
        return round((time.perf_counter() - started) * 1000)

    def memory_fields() -> dict[str, Any]:
        # Sampled at completion so the line shows where memory ended up.
        # The delta is on the cgroup figure because that is what the
        # platform's limit is enforced against; sort the stream by it to
        # find the request behind a step-up.
        after = memory_sample()
        delta = None
        if before["cg_mb"] is not None and after["cg_mb"] is not None:
            delta = after["cg_mb"] - before["cg_mb"]
        return {**after, "cg_delta_mb": delta}

    try:
        try:
            response = await call_next(request)
        except Exception as exc:
            logger.error(
                "request.error",
                extra={"fields": {
                    "method": request.method,
                    "path": request.url.path,
                    "exc_type": type(exc).__name__,
                    "ms": elapsed_ms(),
                    **memory_fields(),
                }},
            )
            raise

        response.headers["X-Request-ID"] = context["req"]
        logger.info(
            "request",
            extra={"fields": {
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "ms": elapsed_ms(),
                **memory_fields(),
            }},
        )
        return response
    finally:
        request_context.reset(token)
```

Also extend the middleware docstring with one sentence after the paragraph about the query string:

```
    Three memory fields ride on both lines (`rss_mb`, `cg_mb`,
    `cg_delta_mb`, see `logging_config.memory_sample`) so a memory step-up
    in production can be matched to the request that caused it.
```

- [ ] **Step 4: Run the whole logging file to verify it passes**

Run from `backend/`: `python -m pytest tests/test_logging.py -v`
Expected: all PASS (the pre-existing tests plus 7 new ones).

- [ ] **Step 5: Update the doc bullet**

In `docs/current-state.md`, replace the bullet that begins `- **One \`event=request\` line per request**, with method, path, status, and ms.` so it reads:

```
- **One `event=request` line per request**, with method, path, status, ms,
  and memory: `rss_mb` (Python process), `cg_mb` (container cgroup total,
  the figure Render enforces; child processes count here, not in RSS), and
  `cg_delta_mb` (change across the request). To find what caused a memory
  step-up, sort `event=request` lines by `cg_delta_mb`; the same request
  repeating with a positive delta is a leak, a one-off is allocator
  high-water retention. `request.error` lines carry the same three fields.
```

Keep the rest of that bullet (the uvicorn access-log sentences) unchanged after the new text. Do not touch the word budget elsewhere; this adds about 70 words to a 16,500 budget.

- [ ] **Step 6: Commit**

```bash
git add backend/app/main.py backend/tests/test_logging.py docs/current-state.md
git commit -m "feat(logging): stamp RSS, cgroup total and cgroup delta on every request line"
```

Do not push. Tell the user the two commits are on local `main` and that pushing deploys.

---

## Reading the result after the next incident

Not a task; the payoff. In the Render log viewer, filter `event=request` around the spike time and look at `cg_delta_mb`. A single line with a large positive delta names the endpoint. A plateau that never falls with `rss_mb` flat but `cg_mb` high means a child process is holding it (Playwright driver); `rss_mb` rising with `cg_mb` means Python heap.
