# Memory Sweep (Phase 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `python scripts/memprobe.py sweep` drives every HTTP route through the Phase 1 instrument and prints a table ranked by repeating cgroup growth, plus a CSV.

**Architecture:** A data file (`memprobe_routes.py`) holds the catalogue and pure planning/ranking functions; `memprobe.py` gains a `sweep` subcommand that reuses Phase 1's `drive` / `parse_request_lines` / `aggregate` per route group. The seed grows the rows the catalogue needs. Two cookie jars: the owner for everything, the seed technician for assigned-worker routes.

**Tech Stack:** Python 3.12 stdlib (`argparse` subparsers, `csv`, `uuid`, `datetime`, `re`, `urllib.request`); `tests.e2e._seed`; pytest.

**Spec:** `docs/superpowers/specs/2026-10-13-memory-sweep-p2-design.md` — read it first; the plan does not restate it.

## Global Constraints

- Everything in the Phase 1 plan's Global Constraints still holds (stdlib only, `.env` untouched, `E2E-` rows only, no push, targeted tests only).
- `scripts/memprobe.py` ≤ 500 lines; `scripts/memprobe_routes.py` is data plus pure functions and never imports `app.*` at module level (the coverage test imports `app.main` itself).
- Exit codes: 0 clean · 1 any failed/unmatched/skipped route · 2 container, Docker CLI or login lost.
- The e2e seed work order stays `created` with no assignee at build time (`tests/e2e/test_work_orders.py:23` asserts it); every row that would advance it goes on a different seed work order.
- Tests run from `backend/` with `.\venv\Scripts\python.exe -m pytest`.

## Review Focus

1. Archiving the technician (`POST /users/{user_id}/archive`) revokes their sessions; later technician routes would 401. The technician jar logs in again before every group that uses it. Pinned in Task 4 (`test_plan_marks_technician_groups`) and by the acceptance run.
2. A cycle whose create returns no `id` (a 4xx) leaves `{id}` unresolvable for the delete; the delete must be recorded as failed with status `None`, not raise. Test in Task 4 (`test_sweep_group_records_missing_id_as_failed`).
3. `--n 1` with a cycle: every member still sent once; `rest` empty; no `ZeroDivisionError`. Covered by Phase 1's `test_aggregate_with_one_request_has_no_rest` plus Task 2 (`test_plan_cycle_rotation`).
4. Rank ties and absent values: a route with `rest(sum)` 0 and one with `None` must not crash the sort. Test in Task 4 (`test_rank_orders_by_rest_sum_then_max_and_tolerates_none`).
5. A route added to the app without a catalogue entry fails CI before anyone runs a sweep. Test in Task 3 (`test_every_route_is_catalogued_or_excluded`).

---

### Task 1: Seed rows the catalogue needs

**Files:**
- Modify: `backend/tests/e2e/_seed.py`

**Interfaces:**
- Produces: `Seed` dataclass with these new fields, all `str` (UUIDs as `str(uuid)` so `vars(seed)` is a ready token dict): `owner_id`, `user_id` (technician), `technician_username`, `work_order_id`, `signed_work_order_id`, `signed_work_order_number`, `active_work_order_id`, `active_work_order_number`, `item_id`, `item2_id`, `tool_id`, `tool_barcode`, `transaction_id`, `stage_id`, `slot_id`, `stage_item_id`, `loading_stage_id`, `completed_stage_id`, `request_id`, `punch_id`, `labor_id`, `wo_item_id`. Existing fields unchanged.

- [ ] **Step 1: Extend the dataclass**

Every new field defaults to `""` so `build` can assign incrementally and the e2e suite's constructor calls stay valid.

```python
@dataclass
class Seed:
    prefix: str
    owner_username: str
    work_order_number: str
    item_barcode: str
    owner_id: str = ""
    user_id: str = ""
    technician_username: str = ""
    work_order_id: str = ""
    signed_work_order_id: str = ""
    signed_work_order_number: str = ""
    active_work_order_id: str = ""
    active_work_order_number: str = ""
    item_id: str = ""
    item2_id: str = ""
    tool_id: str = ""
    tool_barcode: str = ""
    transaction_id: str = ""
    stage_id: str = ""
    slot_id: str = ""
    stage_item_id: str = ""
    loading_stage_id: str = ""
    completed_stage_id: str = ""
    request_id: str = ""
    punch_id: str = ""
    labor_id: str = ""
    wo_item_id: str = ""
```

- [ ] **Step 2: Build the rows**

Append to `build()` after the existing work order, keeping the seed WO `created` and unassigned. Imports to add: `from datetime import datetime, timedelta, timezone`, `from app.models import Tool, WorkOrderSignature`, and services `attendance`, `mass_staging`, `material_requests` (unused here), `tools`, `transactions`, `user_requests`, `users`, `work_order_signature`.

```python
    seed.owner_id = str(owner.id)
    seed.work_order_id = str(work_order.id)          # change the existing call to `work_order = wo_service.get_or_create_work_order(...)`

    tech = users_service.create_user(
        db, username=f"{RUN_PREFIX}-tech", first_name="Eetoo", last_name="Tech",
        password_hash=auth_service.hash_password(SEED_PASSWORD), role="technician")
    seed.user_id, seed.technician_username = str(tech.id), tech.username

    item = items_service.get_item_by_barcode(db, seed.item_barcode)
    seed.item_id = str(item.id)
    item2 = items_service.create_item(db, barcode=f"{RUN_PREFIX}-ITEM2", name=f"{RUN_PREFIX} gadget",
                                      quantity=Decimal("5"), location=f"{RUN_PREFIX}-shelf")
    seed.item2_id = str(item2.id)

    community = f"{RUN_PREFIX} community"
    signed = wo_service.get_or_create_work_order(db, number=f"{RUN_PREFIX}-WO2", community=community,
                                                 description=f"{RUN_PREFIX} signed", created_by_id=owner.id)
    active = wo_service.get_or_create_work_order(db, number=f"{RUN_PREFIX}-WO3", community=community,
                                                 description=f"{RUN_PREFIX} active", created_by_id=owner.id)
    seed.signed_work_order_id, seed.signed_work_order_number = str(signed.id), signed.number
    seed.active_work_order_id, seed.active_work_order_number = str(active.id), active.number
    db.commit()

    work_order_signature.save_signature(db, signed.id, user=owner, image_data_url=SIGNATURE_PNG,
                                        witness_name="Eetoo Witness", witness_phone="5555555555")
    labor = wo_service.add_work_order_labor(db, active.id, user=owner, technician_id=tech.id, minutes=30)
    line = wo_service.add_work_order_item(db, active.id, user=owner, item_id=item.id, quantity=Decimal("1"))
    seed.labor_id, seed.wo_item_id = str(labor.id), str(line.id)

    tool = tools_service.create_tool(db, barcode=f"{RUN_PREFIX}-TOOL", name=f"{RUN_PREFIX} drill",
                                     quantity=Decimal("5"))
    seed.tool_id, seed.tool_barcode = str(tool.id), tool.barcode

    txn = transactions_service.apply_transaction(db, item_id=item.id, transaction_type="stock",
                                                 quantity=Decimal("1"), user_id=owner.id,
                                                 work_order_number=None)
    seed.transaction_id = str(txn.id)

    planning = mass_staging.create_stage(db, community=community, building_name="1", created_by_id=owner.id)
    slot = mass_staging.add_work_order_to_stage(db, planning.id, work_order_number=seed.work_order_number)
    stage_item = mass_staging.add_item(db, planning.id, slot.id, item_id=item.id, planned_quantity=Decimal("2"))
    loading = mass_staging.create_stage(db, community=community, building_name="2", created_by_id=owner.id)
    loading_slot = mass_staging.add_work_order_to_stage(db, loading.id, work_order_number=active.number)
    mass_staging.add_item(db, loading.id, loading_slot.id, item_id=item.id, planned_quantity=Decimal("100"))
    mass_staging.update_stage(db, loading.id, status="loading")
    completed = mass_staging.create_stage(db, community=community, building_name="3", created_by_id=owner.id)
    mass_staging.update_stage(db, completed.id, status="loading")
    mass_staging.update_stage(db, completed.id, status="completed")
    seed.stage_id, seed.slot_id, seed.stage_item_id = str(planning.id), str(slot.id), str(stage_item.id)
    seed.loading_stage_id, seed.completed_stage_id = str(loading.id), str(completed.id)

    request = user_requests_service.create_catalogue_request(
        db, searched_text=f"{RUN_PREFIX} thing", quantity=Decimal("1"), note=None,
        work_order_id=active.id, work_order_number=active.number, source="find_item",
        created_by_id=owner.id)
    seed.request_id = str(request.id)

    day = datetime.now(timezone.utc).replace(hour=8, minute=0, second=0, microsecond=0) - timedelta(days=2)
    punch = attendance_service.admin_add_punch(db, actor=owner, user_id=tech.id,
                                               started_at=day, ended_at=day + timedelta(hours=1))
    seed.punch_id = str(punch.id)
    db.commit()
    return seed
```

`SIGNATURE_PNG` is a module constant in `_seed.py`: `"data:image/png;base64,"` + the base64 of a 1×1 PNG (`iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==`). Task 3 repeats the literal in `memprobe_routes.py` (which must not import `app.*` at module level) and the coverage test asserts the two are equal. Every keyword above was checked against its service signature on 2026-10-13: `get_item_by_barcode(db, barcode)`, `update_stage(db, stage_id, *, community=None, building_name=None, status=None)`, `add_work_order_to_stage(db, stage_id, *, work_order_number, …)`, `add_item(db, stage_id, slot_id, *, item_id, planned_quantity)`, `create_catalogue_request(db, *, searched_text, quantity, note, work_order_id, work_order_number, source, created_by_id)`, `admin_add_punch(db, *, actor, user_id, started_at, ended_at, …)`, `save_signature(db, work_order_id, *, user, image_data_url, witness_name, witness_phone)`.

- [ ] **Step 3: Teach `_purge` about tools and signatures**

In `_purge`, after `item_ids`, add `tool_ids = db.scalars(select(Tool.id).where(Tool.barcode.like(pattern))).all()`. Signatures and labor sessions cascade from the work order (`ondelete="CASCADE"` in `app/models.py`), so nothing else is needed for them. After the `Item` delete add:

```python
    if tool_ids:
        _run(delete(ToolTransaction).where(ToolTransaction.tool_id.in_(tool_ids)))
        _run(delete(Tool).where(Tool.id.in_(tool_ids)))
```

- [ ] **Step 4: Prove build and destroy round-trip**

Run from `backend/` (dev Postgres on 8801 must be up):

```
.\venv\Scripts\python.exe -c "from app.database import SessionLocal; from tests.e2e import _seed; db=SessionLocal(); s=_seed.build(db); print({k:v for k,v in vars(s).items() if not v} or 'all fields set'); _seed.destroy(db,s); print('debris', _seed.sweep_debris(db))"
```

Expected: `all fields set` then `debris 0`. If a service raises, fix the keyword names, destroy by running `sweep_debris` alone, and rerun.

- [ ] **Step 5: Run the e2e guard and commit**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_e2e_guard.py -q` → PASS.

```bash
git add backend/tests/e2e/_seed.py
git commit -m "test(e2e): seed the rows the memory sweep catalogue drives"
```

---

### Task 2: Catalogue data model and planner

**Files:**
- Create: `backend/scripts/memprobe_routes.py`
- Modify: `backend/tests/test_memprobe.py` (append)

**Interfaces:**
- Produces:
  - `Entry` dataclass: `body: str|None = None`, `file: str|tuple[str,str]|None = None` (fixture path, or `(filename, text_template)`), `cycle: list[str]|None = None`, `expect: int|None = None`, `exclude: str|None = None`, `path: str|None = None`, `token: dict[str,str]|None = None`, `as_user: str = "owner"`.
  - `Step(route: str, method: str, path: str, body: str|None, file, expect: int|None, as_user: str)` — templates still unfilled.
  - `Plan(groups: list[list[Step]], skipped: list[tuple[str,str]], excluded: list[tuple[str,str]])`.
  - `enumerate_routes(app) -> tuple[list[tuple[str,str]], list[str]]` → `([(method, path), …], ["WS /ws", …])`.
  - `plan(routes, catalogue, tokens: dict[str,str], only: str|None) -> Plan`.
  - `fill(template: str, tokens: dict[str,str], seq: int, now: datetime) -> str` — `{name}` from tokens, `{seq}`, `{now}` (ISO UTC `…Z`), `{days_ago:N}` (date), `{id}` left for the driver.
  - `TOKEN_RE = re.compile(r"\{([a-z_0-9]+)(?::(\d+))?\}")`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_memprobe.py`)

```python
from datetime import datetime, timezone
from scripts import memprobe_routes as mr

NOW = datetime(2026, 10, 13, 15, 0, 0, tzinfo=timezone.utc)
TOKENS = {"item_id": "I1", "barcode": "E2E-x-ITEM", "prefix": "E2E-x"}


def test_fill_substitutes_seed_seq_now_and_days_ago():
    out = mr.fill('{"a":"{item_id}","b":"{prefix}-{seq}","c":"{now}","d":"{days_ago:3}","e":"{id}"}', TOKENS, 7, NOW)
    assert out == '{"a":"I1","b":"E2E-x-7","c":"2026-10-13T15:00:00Z","d":"2026-10-10","e":"{id}"}'


def test_fill_raises_on_unknown_token():
    import pytest
    with pytest.raises(KeyError):
        mr.fill("/x/{nope}", TOKENS, 0, NOW)


def _routes():
    return [("GET", "/healthz"), ("GET", "/items/{barcode}"), ("POST", "/items/"),
            ("DELETE", "/items/{item_id}"), ("POST", "/new"), ("GET", "/x/{unknown}")]


def _catalogue():
    return {
        "POST /items/": mr.Entry(body='{"barcode":"{prefix}-{seq}"}', cycle=["POST /items/", "DELETE /items/{item_id}"]),
        "DELETE /items/{item_id}": mr.Entry(path="/items/{id}"),
        "POST /new": mr.Entry(exclude="because"),
    }


def test_plan_groups_cycles_and_token_free_gets():
    p = mr.plan(_routes()[:5], _catalogue(), TOKENS, only=None)
    routes = [[s.route for s in g] for g in p.groups]
    assert routes == [["GET /healthz"], ["GET /items/{barcode}"], ["POST /items/", "DELETE /items/{item_id}"]]
    assert p.excluded == [("POST", "/new")]
    assert p.skipped == []
    assert p.groups[2][1].path == "/items/{id}"


def test_plan_skips_uncatalogued_and_unresolvable():
    p = mr.plan(_routes(), {}, TOKENS, only=None)
    assert ("POST", "/items/") in p.skipped and ("GET", "/x/{unknown}") in p.skipped
    assert ("GET", "/items/{barcode}") not in p.skipped


def test_plan_only_filters_by_substring():
    p = mr.plan(_routes()[:5], _catalogue(), TOKENS, only="/items")
    assert [s.route for g in p.groups for s in g] == ["GET /items/{barcode}", "POST /items/", "DELETE /items/{item_id}"]
    assert p.excluded == []


def test_plan_cycle_declared_once_and_member_in_one_cycle():
    import pytest
    bad = {"POST /items/": mr.Entry(cycle=["POST /items/", "DELETE /items/{item_id}"]),
           "DELETE /items/{item_id}": mr.Entry(cycle=["DELETE /items/{item_id}", "POST /items/"])}
    with pytest.raises(ValueError):
        mr.plan(_routes()[:4], bad, TOKENS, only=None)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_memprobe.py -q -k "fill or plan"`
Expected: FAIL with `ModuleNotFoundError: scripts.memprobe_routes`.

- [ ] **Step 3: Implement the model and planner**

```python
"""Route catalogue and pure planning/ranking for `memprobe.py sweep`.
Spec: docs/superpowers/specs/2026-10-13-memory-sweep-p2-design.md."""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

TOKEN_RE = re.compile(r"\{([a-z_0-9]+)(?::(\d+))?\}")


@dataclass(frozen=True)
class Entry:
    body: Optional[str] = None
    file: Optional[object] = None          # fixture path, or (filename, text template)
    cycle: Optional[list[str]] = None
    expect: Optional[int] = None
    exclude: Optional[str] = None
    path: Optional[str] = None
    token: Optional[dict[str, str]] = None
    as_user: str = "owner"


@dataclass(frozen=True)
class Step:
    route: str
    method: str
    path: str
    body: Optional[str]
    file: Optional[object]
    expect: Optional[int]
    as_user: str


@dataclass
class Plan:
    groups: list[list[Step]] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    excluded: list[tuple[str, str]] = field(default_factory=list)


def fill(template: str, tokens: dict[str, str], seq: int, now: datetime) -> str:
    def sub(m: re.Match) -> str:
        name, arg = m.group(1), m.group(2)
        if name == "id":
            return m.group(0)                      # resolved by the driver from the last response
        if name == "seq":
            return str(seq)
        if name == "now":
            return now.strftime("%Y-%m-%dT%H:%M:%SZ")
        if name == "days_ago":
            return (now - timedelta(days=int(arg))).strftime("%Y-%m-%d")
        return tokens[name]                        # KeyError = unresolvable, caller decides
    return TOKEN_RE.sub(sub, template)


def enumerate_routes(app) -> tuple[list[tuple[str, str]], list[str]]:
    http, other = [], []
    for r in app.routes:
        methods = getattr(r, "methods", None)
        if methods:
            http += [(m, r.path) for m in sorted(methods - {"HEAD", "OPTIONS"})]
        elif type(r).__name__ == "WebSocketRoute":
            other.append(f"WS {r.path}")
    return http, other


def _resolvable(template: str, tokens: dict[str, str]) -> bool:
    return all(n in tokens or n in ("id", "seq", "now", "days_ago") for n, _ in TOKEN_RE.findall(template))


def _step(method: str, path: str, entry: Entry, tokens: dict[str, str]) -> Optional[Step]:
    """`path` is the enumerated route path; the Step's route keeps it as the
    key even when `entry.path` overrides what is actually requested."""
    route = f"{method} {path}"
    merged = {**tokens, **(entry.token or {})}
    requested = entry.path or path
    templates = [requested, entry.body or ""] + ([entry.file[1]] if isinstance(entry.file, tuple) else [])
    if not all(_resolvable(t, merged) for t in templates):
        return None
    return Step(route, method, requested, entry.body, entry.file, entry.expect, entry.as_user)


def plan(routes, catalogue: dict[str, Entry], tokens: dict[str, str], only: Optional[str]) -> Plan:
    out = Plan()
    owners: dict[str, str] = {}
    for key, e in catalogue.items():
        for member in e.cycle or []:
            if member in owners and owners[member] != key:
                raise ValueError(f"{member} is in two cycles: {owners[member]} and {key}")
            owners[member] = key
    placed: set[str] = set()
    for method, path in routes:
        key = f"{method} {path}"
        if only and only not in key:
            continue
        entry = catalogue.get(key)
        if entry is None and method != "GET":
            out.skipped.append((method, path))         # a mutation needs a body or a cycle decision
            continue
        entry = entry or Entry()                       # a GET resolves its tokens from the seed
        if entry.exclude:
            out.excluded.append((method, path))
            continue
        owner = owners.get(key)
        if owner and owner != key:
            continue                                   # placed when its cycle's first member was
        members = entry.cycle or [key]
        steps = []
        for m in members:
            e = catalogue.get(m, Entry())
            route_path = m.split(" ", 1)[1]
            s = _step(m.split(" ")[0], route_path, e, tokens)
            if s is None:
                out.skipped.append(tuple(m.split(" ", 1)))
                steps = None
                break
            steps.append(s)
        if steps:
            out.groups.append(steps)
            placed.update(members)
    return out
```

`Step.route` keeps the enumerated key so ranking lines up with `app.routes`; `Step.path` is what gets requested.

- [ ] **Step 4: Run tests**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_memprobe.py -q -k "fill or plan"`
Expected: PASS (6 new).

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/memprobe_routes.py backend/tests/test_memprobe.py
git commit -m "feat(memprobe): route catalogue model, token fill and sweep planner"
```

---

### Task 3: The catalogue and the coverage guard

**Files:**
- Modify: `backend/scripts/memprobe_routes.py` (add `CATALOGUE`)
- Modify: `backend/tests/test_memprobe.py` (append)

**Interfaces:**
- Produces: `CATALOGUE: dict[str, Entry]` keyed exactly as `enumerate_routes` prints.
- Consumes: seed field names from Task 1 as tokens, plus aliases the driver adds: `barcode` = `item_barcode`, `wo` = `work_order_number`, `prefix`.

- [ ] **Step 1: Write the failing coverage test**

```python
def test_every_route_is_catalogued_or_excluded():
    """The drift guard: a new route must get a catalogue entry or an exclude."""
    from app.main import app
    from tests.e2e import _seed
    routes, _ = mr.enumerate_routes(app)
    tokens = {k: "x" for k in vars(_seed.Seed("p", "o", "w", "b"))} | {"barcode": "x", "wo": "x", "prefix": "x"}
    p = mr.plan(routes, mr.CATALOGUE, tokens, only=None)
    assert p.skipped == []
    assert {f"{m} {path}" for m, path in p.excluded} == set(mr.EXCLUDED)
    assert len(p.groups) + len(p.excluded) >= 100


def test_catalogue_keys_are_real_routes():
    from app.main import app
    routes, _ = mr.enumerate_routes(app)
    keys = {f"{m} {p}" for m, p in routes}
    assert set(mr.CATALOGUE) - keys == set()
```

- [ ] **Step 2: Run to verify they fail**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_memprobe.py -q -k catalogue`
Expected: FAIL with `AttributeError: CATALOGUE`.

- [ ] **Step 3: Write the catalogue**

Add `EXCLUDED` (a tuple of keys) and `CATALOGUE` to `memprobe_routes.py`. Shorthands: `J = json.dumps`; `T = "technician"`. All ids below come from the seed unless the path carries `{id}` (the most recent response in the cycle). Every mutating route is here; GETs appear only when they carry a token or need a query string.

```python
EXCLUDED = (
    "POST /auth/login", "POST /auth/logout",
    "POST /push/subscribe", "POST /push/unsubscribe",
    "POST /users/{user_id}/reset-password",
    "POST /integrations/netfacilities/cloud/auth/start",
    "POST /integrations/netfacilities/work-orders/enrich",
    "POST /integrations/netfacilities/cloud/downloads/import",
    "POST /hub/attendance/week/review",       # marks real dev-DB punches reviewed
    "POST /work-orders/legacy/archive",       # archives real dev-DB rows
)
WO_LIFECYCLE = ["PATCH /work-orders/{work_order_id}", "POST /work-orders/{work_order_id}/start",
                "POST /work-orders/{work_order_id}/hold", "POST /work-orders/{work_order_id}/resume",
                "POST /work-orders/{work_order_id}/complete"]
ATTENDANCE = ["POST /attendance/punch-in", "POST /attendance/punch-out",
              "POST /attendance/punch-in", "POST /attendance/self-close",
              "POST /attendance/punch-in", "POST /hub/attendance/clock-out/{user_id}"]
MATERIAL = ["POST /user-requests/material-request", "POST /user-requests/{request_id}/cancel",
            "POST /user-requests/material-request", "POST /user-requests/{request_id}/mark-stocked",
            "PATCH /user-requests/{request_id}"]
STAGES = ["POST /mass-stages/", "DELETE /mass-stages/{stage_id}",
          "POST /mass-stages/{stage_id}/reuse", "DELETE /mass-stages/{stage_id}"]

CATALOGUE: dict[str, Entry] = {k: Entry(exclude="see EXCLUDED") for k in EXCLUDED} | {
    # --- GETs that need a token or query ---
    "GET /tools/{barcode}": Entry(path="/tools/{tool_barcode}"),
    "GET /work-orders/{work_order_id}/signature.png": Entry(path="/work-orders/{signed_work_order_id}/signature.png"),
    "GET /workorder_card/{number}": Entry(path="/workorder_card/{work_order_number}"),
    "GET /work-orders/lookup": Entry(path="/work-orders/lookup?number={work_order_number}"),
    "GET /integrations/netfacilities/work-orders/enrich/{job_id}": Entry(
        token={"job_id": "00000000-0000-4000-8000-000000000000"}, expect=404),
    "POST /integrations/netfacilities/cloud/auth/cancel": Entry(expect=409),
    # --- attendance (technician punches; owner clocks them out) ---
    "POST /attendance/punch-in": Entry(cycle=ATTENDANCE, as_user=T),
    "POST /attendance/punch-out": Entry(as_user=T),
    "POST /attendance/self-close": Entry(body=J({"ended_at": "{now}"}), as_user=T),
    "POST /hub/attendance/punches": Entry(
        body=J({"user_id": "{user_id}", "started_at": "{days_ago:3}T08:00:00Z", "ended_at": "{days_ago:3}T09:00:00Z"}),
        cycle=["POST /hub/attendance/punches", "DELETE /hub/attendance/punches/{punch_id}"]),
    "DELETE /hub/attendance/punches/{punch_id}": Entry(path="/hub/attendance/punches/{id}?reason=memprobe"),
    "PATCH /hub/attendance/punches/{punch_id}": Entry(body=J({"needs_review": False, "reason": "memprobe"})),
    "POST /barcodes/decode": Entry(file="tests/fixtures/code128.png"),
    # --- items ---
    "POST /items/": Entry(body=J({"barcode": "{prefix}-I{seq}", "name": "{prefix} new", "location": "{prefix}-shelf"}),
                          cycle=["POST /items/", "DELETE /items/{item_id}"]),
    "DELETE /items/{item_id}": Entry(path="/items/{id}"),
    "PATCH /items/{item_id}": Entry(body=J({"name": "{prefix} widget"})),
    "PATCH /items/{item_id}/notes": Entry(body=J({"notes": {"memprobe": "x"}})),
    "PATCH /items/{item_id}/barcodes": Entry(body=J({"barcodes": []})),
    "PATCH /items/{item_id}/low-stock-threshold": Entry(body=J({"low_stock_threshold": 1})),
    "POST /items/dispense-exports": Entry(),
    # --- mass stages ---
    "POST /mass-stages/": Entry(body=J({"community": "{prefix} community", "building_name": "B{seq}"}), cycle=STAGES),
    "DELETE /mass-stages/{stage_id}": Entry(path="/mass-stages/{id}"),
    "POST /mass-stages/{stage_id}/reuse": Entry(path="/mass-stages/{completed_stage_id}/reuse"),
    "PATCH /mass-stages/{stage_id}": Entry(body=J({"community": "{prefix} community"})),
    "POST /mass-stages/{stage_id}/work-orders": Entry(
        body=J({"work_order_number": "{signed_work_order_number}"}),
        cycle=["POST /mass-stages/{stage_id}/work-orders", "DELETE /mass-stages/{stage_id}/work-orders/{slot_id}"]),
    "DELETE /mass-stages/{stage_id}/work-orders/{slot_id}": Entry(path="/mass-stages/{stage_id}/work-orders/{id}"),
    "POST /mass-stages/{stage_id}/work-orders/{slot_id}/items": Entry(
        body=J({"item_id": "{item2_id}", "planned_quantity": 1}),
        cycle=["POST /mass-stages/{stage_id}/work-orders/{slot_id}/items",
               "DELETE /mass-stages/{stage_id}/work-orders/{slot_id}/items/{stage_item_id}"]),
    "DELETE /mass-stages/{stage_id}/work-orders/{slot_id}/items/{stage_item_id}": Entry(
        path="/mass-stages/{stage_id}/work-orders/{slot_id}/items/{id}"),
    "PATCH /mass-stages/{stage_id}/work-orders/{slot_id}/items/{stage_item_id}": Entry(body=J({"planned_quantity": 2})),
    "POST /mass-stages/{stage_id}/load": Entry(path="/mass-stages/{loading_stage_id}/load",
                                               body=J({"item_id": "{item_id}", "quantity": 1}),
                                               cycle=["POST /mass-stages/{stage_id}/load", "POST /mass-stages/{stage_id}/return"]),
    "POST /mass-stages/{stage_id}/return": Entry(path="/mass-stages/{loading_stage_id}/return",
                                                 body=J({"item_id": "{item_id}", "quantity": 1})),
    # --- push ---
    "POST /push/test": Entry(),            # add expect=503 if the container has no VAPID keys (acceptance run decides)
    # --- tools ---
    "POST /tools/": Entry(body=J({"barcode": "{prefix}-T{seq}", "name": "{prefix} saw"}),
                          cycle=["POST /tools/", "DELETE /tools/{tool_id}"]),
    "DELETE /tools/{tool_id}": Entry(path="/tools/{id}"),
    "PATCH /tools/{tool_id}": Entry(body=J({"name": "{prefix} drill"})),
    "POST /tools/{tool_id}/adjust": Entry(body=J({"new_quantity": 5, "reason": "memprobe"})),
    "POST /tools/{tool_id}/checkout": Entry(body=J({"quantity": 1, "assigned_to_id": "{user_id}"}),
                                            cycle=["POST /tools/{tool_id}/checkout", "POST /tools/{tool_id}/return"]),
    "POST /tools/{tool_id}/return": Entry(body=J({"quantity": 1, "assigned_to_id": "{user_id}"})),
    # --- transactions ---
    "POST /transactions/": Entry(body=J({"item_id": "{item_id}", "transaction_type": "stock", "quantity": 1}),
                                 cycle=["POST /transactions/", "DELETE /transactions/{transaction_id}"]),
    "DELETE /transactions/{transaction_id}": Entry(path="/transactions/{id}"),
    "POST /transactions/adjust": Entry(body=J({"item_id": "{item_id}", "new_quantity": 5, "reason": "memprobe"})),
    "PATCH /transactions/{transaction_id}/billing": Entry(body=J({"billable_quantity": 1})),
    # --- user requests ---
    "POST /user-requests/material-request": Entry(
        body=J({"item_id": "{item_id}", "work_order_id": "{active_work_order_id}", "quantity": 1}), cycle=MATERIAL),
    "POST /user-requests/{request_id}/cancel": Entry(path="/user-requests/{id}/cancel"),
    "POST /user-requests/{request_id}/mark-stocked": Entry(path="/user-requests/{id}/mark-stocked"),
    "PATCH /user-requests/{request_id}": Entry(path="/user-requests/{id}",
                                               body=J({"status": "resolved", "resolution_note": "memprobe"})),
    "POST /user-requests/catalogue-request": Entry(
        body=J({"searched_text": "{prefix} thing {seq}", "source": "find_item", "work_order_id": "{active_work_order_id}"}),
        cycle=["POST /user-requests/catalogue-request", "POST /user-requests/{request_id}/fulfill"]),
    "POST /user-requests/{request_id}/fulfill": Entry(path="/user-requests/{id}/fulfill", body=J({"item_id": "{item_id}"})),
    # --- users ---
    "POST /users/": Entry(body=J({"username": "{prefix}-u{seq}", "first_name": "Eetoo", "last_name": "U",
                                  "password": "e2e-password-1", "role": "technician"}),
                          cycle=["POST /users/", "DELETE /users/{user_id}"]),
    "DELETE /users/{user_id}": Entry(path="/users/{id}"),
    "PATCH /users/{user_id}/name": Entry(body=J({"first_name": "Eetoo", "last_name": "Tech"})),
    "PATCH /users/{user_id}/role": Entry(body=J({"role": "technician"})),
    "POST /users/{user_id}/archive": Entry(cycle=["POST /users/{user_id}/archive", "POST /users/{user_id}/restore"]),
    "POST /users/{user_id}/restore": Entry(),
    # --- work orders ---
    "POST /work-orders/import": Entry(file=("import.csv", "WORK ORDER,LOCATION\r\n{prefix}-IMP{seq},Commons\r\n")),
    "PATCH /work-orders/{work_order_id}": Entry(body=J({"status": "assigned", "assigned_to_ids": ["{user_id}"]}), cycle=WO_LIFECYCLE),
    "POST /work-orders/{work_order_id}/start": Entry(as_user=T),
    "POST /work-orders/{work_order_id}/hold": Entry(as_user=T),
    "POST /work-orders/{work_order_id}/resume": Entry(as_user=T),
    "POST /work-orders/{work_order_id}/complete": Entry(as_user=T),
    "POST /work-orders/{work_order_id}/tracking/start": Entry(
        path="/work-orders/{active_work_order_id}/tracking/start",
        cycle=["POST /work-orders/{work_order_id}/tracking/start", "POST /work-orders/{work_order_id}/tracking/stop"]),
    "POST /work-orders/{work_order_id}/tracking/stop": Entry(path="/work-orders/{active_work_order_id}/tracking/stop"),
    "POST /work-orders/{work_order_id}/archive": Entry(
        path="/work-orders/{active_work_order_id}/archive",
        cycle=["POST /work-orders/{work_order_id}/archive", "POST /work-orders/{work_order_id}/restore"]),
    "POST /work-orders/{work_order_id}/restore": Entry(path="/work-orders/{active_work_order_id}/restore"),
    "DELETE /work-orders/{work_order_id}/signature": Entry(
        path="/work-orders/{signed_work_order_id}/signature",
        cycle=["DELETE /work-orders/{work_order_id}/signature", "POST /work-orders/{work_order_id}/signature"]),
    "POST /work-orders/{work_order_id}/signature": Entry(
        path="/work-orders/{signed_work_order_id}/signature",
        body=J({"image": SIGNATURE_PNG, "witness_name": "Eetoo Witness", "witness_phone": "5555555555"})),
    "POST /work-orders/{work_order_id}/items": Entry(
        path="/work-orders/{active_work_order_id}/items", body=J({"item_id": "{item2_id}", "quantity": 1}),
        cycle=["POST /work-orders/{work_order_id}/items", "DELETE /work-orders/{work_order_id}/items/{wo_item_id}"]),
    "DELETE /work-orders/{work_order_id}/items/{wo_item_id}": Entry(path="/work-orders/{active_work_order_id}/items/{id}"),
    "PATCH /work-orders/{work_order_id}/items/{wo_item_id}": Entry(
        path="/work-orders/{active_work_order_id}/items/{wo_item_id}", body=J({"quantity": 1})),
    "PATCH /work-orders/{work_order_id}/items/{wo_item_id}/billing": Entry(
        path="/work-orders/{active_work_order_id}/items/{wo_item_id}/billing", body=J({"billable_quantity": 1})),
    "POST /work-orders/{work_order_id}/labor": Entry(
        path="/work-orders/{active_work_order_id}/labor", body=J({"technician_id": "{user_id}", "minutes": 5}),
        cycle=["POST /work-orders/{work_order_id}/labor", "DELETE /work-orders/{work_order_id}/labor/{labor_id}"]),
    "DELETE /work-orders/{work_order_id}/labor/{labor_id}": Entry(path="/work-orders/{active_work_order_id}/labor/{id}"),
    "PATCH /work-orders/{work_order_id}/labor/{labor_id}": Entry(
        path="/work-orders/{active_work_order_id}/labor/{labor_id}", body=J({"minutes": 6})),
}
```

`SIGNATURE_PNG` is the same literal as `_seed.SIGNATURE_PNG`, repeated here because `memprobe_routes` must not import `app.*` at module level; add `assert mr.SIGNATURE_PNG == _seed.SIGNATURE_PNG` to `test_every_route_is_catalogued_or_excluded`. The two week-review/legacy-archive exclusions are additions to the spec's list; the reason is on each line.

- [ ] **Step 4: Run the coverage tests**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_memprobe.py -q -k catalogue`
Expected: PASS. If `skipped` is non-empty, the failure message lists the routes; add entries until it is empty.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/memprobe_routes.py backend/tests/test_memprobe.py
git commit -m "feat(memprobe): the route catalogue and the coverage guard"
```

---

### Task 4: Ranking, CSV and the `sweep` subcommand

**Files:**
- Modify: `backend/scripts/memprobe_routes.py` (add `rank`, `to_csv`, `render_sweep`)
- Modify: `backend/scripts/memprobe.py` (subparsers, multipart, technician jar, `run_sweep`)
- Modify: `backend/tests/test_memprobe.py` (append)

**Interfaces:**
- `RouteResult(route: str, summary: memprobe.Summary, expect: int|None, state: str)` where `state` ∈ `measured|failed`.
- `rank(results: list[RouteResult]) -> list[Row]`; `Row` is a dataclass with the spec's CSV columns in order: `method, path, n, first_cg, rest_sum_cg, rest_max_cg, rest_mean_cg, first_rss, rest_sum_rss, drift_cg, p50_ms, max_ms, statuses, matched, state`.
- `to_csv(rows: list[Row], skipped, excluded, path: str) -> None` (skipped/excluded rows carry `state` and dashes).
- `render_sweep(rows, baseline_start, baseline_end, plan, container, n) -> str`.
- `memprobe.Sent` gains `body: Optional[str] = None` (last field, default keeps Phase 1 tests valid).
- `memprobe._send(opener, base, method, path, body, content_type="application/json")` accepts `bytes` bodies.
- `memprobe.multipart(filename: str, data: bytes) -> tuple[bytes, str]` → `(body, content_type)`.
- `memprobe.run_group(openers, base, group, tokens, n, gap, now) -> dict[str, list[Sent]]` — one cycle rotation; `{id}` filled from the last response JSON `id` in the group; a missing id records `Sent(None, 0)` for that step.

- [ ] **Step 1: Write the failing tests**

```python
def _result(route, first=0, rest=(0,), statuses=None, expect=None, matched=None):
    sent = [memprobe.Sent(f"{route}-{i}", 200) for i in range(1 + len(rest))]
    samples = {s.req: memprobe.Sample(s.req, 200, 5, 100, 200, d, d) for s, d in zip(sent, (first,) + rest)}
    return mr.RouteResult(route, memprobe.aggregate(sent, samples), expect, "measured")


def test_rank_orders_by_rest_sum_then_max_and_tolerates_none():
    rows = mr.rank([_result("GET /a", rest=(1, 1)), _result("GET /b", rest=(2, 0)), _result("GET /c", rest=()),
                    _result("GET /d", rest=(0, 2))])
    assert [r.path for r in rows] == ["/b", "/d", "/a", "/c"]   # sum 2,2,2,0; max 2,2,1; then path
    assert rows[-1].rest_mean_cg is None


def test_rank_marks_unexpected_status_failed_and_expected_ok():
    ok = mr.RouteResult("GET /x", memprobe.aggregate([memprobe.Sent("1", 404)], {"1": memprobe.Sample("1", 404, 1, 1, 1, 0, 0)}), 404, "measured")
    bad = mr.RouteResult("GET /y", memprobe.aggregate([memprobe.Sent("2", 422)], {"2": memprobe.Sample("2", 422, 1, 1, 1, 0, 0)}), None, "measured")
    rows = mr.rank([ok, bad])
    assert {r.path: r.state for r in rows} == {"/x": "measured", "/y": "failed"}


def test_to_csv_writes_one_row_per_route(tmp_path):
    rows = mr.rank([_result("GET /a", rest=(1,))])
    out = tmp_path / "s.csv"
    mr.to_csv(rows, [("POST", "/new")], [("WS", "/ws")], str(out))
    lines = out.read_text().splitlines()
    assert lines[0].startswith("method,path,n,first_cg,rest_sum_cg")
    assert len(lines) == 4 and lines[2].startswith("POST,/new") and lines[3].endswith("excluded")


def test_multipart_body_carries_filename_and_boundary():
    body, ctype = memprobe.multipart("a.csv", b"WORK ORDER\r\n1\r\n")
    boundary = ctype.split("boundary=")[1]
    assert boundary.encode() in body and b'filename="a.csv"' in body and body.endswith(b"--\r\n")


class _FakeOpener:
    def __init__(self, responses): self.calls, self.responses = [], list(responses)
    def open(self, req, timeout=0):
        self.calls.append((req.get_method(), req.full_url, req.data))
        status, body = self.responses.pop(0)
        return _FakeResp(status, body)


class _FakeResp:
    def __init__(self, status, body): self.status, self._b = status, body; self.headers = {"X-Request-ID": f"r{status}{len(body)}"}
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def read(self): return self._b


def test_run_group_fills_id_from_the_create_response():
    group = [mr.Step("POST /items/", "POST", "/items/", '{"b":"{prefix}-{seq}"}', None, None, "owner"),
             mr.Step("DELETE /items/{item_id}", "DELETE", "/items/{id}", None, None, None, "owner")]
    op = _FakeOpener([(200, b'{"id":"X1"}'), (204, b""), (200, b'{"id":"X2"}'), (204, b"")])
    out = memprobe.run_group({"owner": op}, "http://h", group, {"prefix": "p"}, 2, 0, NOW)
    assert [c[1] for c in op.calls] == ["http://h/items/", "http://h/items/X1", "http://h/items/", "http://h/items/X2"]
    assert len(out["POST /items/"]) == 2 and len(out["DELETE /items/{item_id}"]) == 2


def test_sweep_group_records_missing_id_as_failed():
    group = [mr.Step("POST /items/", "POST", "/items/", "{}", None, None, "owner"),
             mr.Step("DELETE /items/{item_id}", "DELETE", "/items/{id}", None, None, None, "owner")]
    op = _FakeOpener([(422, b'{"detail":"no"}')])
    out = memprobe.run_group({"owner": op}, "http://h", group, {}, 1, 0, NOW)
    assert out["DELETE /items/{item_id}"] == [memprobe.Sent(None, 0, None)]
    assert len(op.calls) == 1


def test_plan_marks_technician_groups():
    cat = {"POST /a": mr.Entry(as_user="technician")}
    p = mr.plan([("POST", "/a")], cat, {}, None)
    assert p.groups[0][0].as_user == "technician"
```

- [ ] **Step 2: Run to verify they fail**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_memprobe.py -q -k "rank or csv or multipart or run_group or technician"`
Expected: FAIL (`AttributeError` on `rank`, `multipart`, `run_group`).

- [ ] **Step 3: Implement ranking and CSV in `memprobe_routes.py`**

```python
@dataclass
class RouteResult:
    route: str
    summary: object           # memprobe.Summary
    expect: Optional[int]
    state: str


COLUMNS = ("method", "path", "n", "first_cg", "rest_sum_cg", "rest_max_cg", "rest_mean_cg", "first_rss",
           "rest_sum_rss", "drift_cg", "p50_ms", "max_ms", "statuses", "matched", "state")


@dataclass
class Row:
    method: str; path: str; n: int
    first_cg: Optional[int]; rest_sum_cg: Optional[float]; rest_max_cg: Optional[float]; rest_mean_cg: Optional[float]
    first_rss: Optional[int]; rest_sum_rss: Optional[float]; drift_cg: Optional[int]
    p50_ms: Optional[int]; max_ms: Optional[int]; statuses: str; matched: str; state: str


def _state(r: RouteResult) -> str:
    s = r.summary
    allowed = {r.expect} if r.expect else set()
    bad = any(not (200 <= code < 300) and code not in allowed for code in s.statuses)
    return "failed" if bad or s.unmatched or r.state == "failed" else "measured"


def rank(results: list[RouteResult]) -> list[Row]:
    rows = []
    for r in results:
        s = r.summary
        method, path = r.route.split(" ", 1)
        a, b = s.drift["cg_mb"]
        rows.append(Row(method, path, s.sent, s.first["cg_delta_mb"], s.rest["cg_delta_mb"]["sum"],
                        s.rest["cg_delta_mb"]["max"], s.rest["cg_delta_mb"]["mean"], s.first["rss_delta_mb"],
                        s.rest["rss_delta_mb"]["sum"], None if a is None or b is None else b - a, s.ms_p50, s.ms_max,
                        " ".join(f"{c}x{n}" for c, n in s.statuses.items()), f"{s.matched}/{s.sent}", _state(r)))
    return sorted(rows, key=lambda x: (-(x.rest_sum_cg or 0), -(x.rest_max_cg or 0), x.path))


def to_csv(rows: list[Row], skipped, excluded, path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(COLUMNS)
        for r in rows:
            w.writerow([getattr(r, c) if getattr(r, c) is not None else "" for c in COLUMNS])
        for state, pairs in (("skipped", skipped), ("excluded", excluded)):
            for m, p in pairs:
                w.writerow([m, p] + [""] * (len(COLUMNS) - 3) + [state])


def render_sweep(rows, start, end, plan: Plan, container: str, n: int) -> str:
    def fmt(v): return "-" if v is None else (f"{v:.2f}" if isinstance(v, float) else str(v))
    def base(s): return "-" if s is None else f"cg_mb={s.cg_mb} rss_mb={s.rss_mb}"
    measured = [r for r in rows if r.state == "measured"]; failed = [r for r in rows if r.state == "failed"]
    out = [f"sweep        routes={len(rows) + len(plan.skipped) + len(plan.excluded)} measured={len(measured)} "
           f"failed={len(failed)} skipped={len(plan.skipped)} excluded={len(plan.excluded)}   n={n}  container={container}",
           f"baseline     start {base(start)}   end {base(end)}", "",
           f"{'rank':>4}  {'route':40} {'first':>5} {'rest(sum)':>9} {'rest(max)':>9} {'rest(mean)':>10} {'rss(sum)':>8} {'p50ms':>5}  statuses"]
    for i, r in enumerate(rows, 1):
        out.append(f"{i:>4}  {r.method + ' ' + r.path:40} {fmt(r.first_cg):>5} {fmt(r.rest_sum_cg):>9} {fmt(r.rest_max_cg):>9} "
                   f"{fmt(r.rest_mean_cg):>10} {fmt(r.rest_sum_rss):>8} {fmt(r.p50_ms):>5}  {r.statuses}")
    for title, items in (("failed", [f"{r.method} {r.path}  {r.statuses}  matched {r.matched}" for r in failed]),
                         ("skipped", [f"{m} {p}  no catalogue entry or unresolvable token" for m, p in plan.skipped]),
                         ("excluded", [f"{m} {p}" for m, p in plan.excluded])):
        if items:
            out += ["", title] + [f"  {x}" for x in items]
    return "\n".join(out)
```

- [ ] **Step 4: Implement the driver pieces in `memprobe.py`**

Change `Sent` and `_send`; add `multipart` and `run_group`; keep every Phase 1 signature otherwise.

```python
@dataclass(frozen=True)
class Sent:
    req: Optional[str]
    status: int
    body: Optional[str] = None


def _send(opener, base, method, path, body, content_type="application/json") -> Sent:
    data = body.encode() if isinstance(body, str) else body
    req = urllib.request.Request(base + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", content_type)
    try:
        resp = opener.open(req, timeout=60)
    except urllib.error.HTTPError as err:
        resp = err
    with resp:
        raw = resp.read()
        return Sent(resp.headers.get("X-Request-ID"), resp.status, raw.decode("utf-8", "replace") if raw else None)


def multipart(filename: str, data: bytes) -> tuple[bytes, str]:
    boundary = "memprobe" + uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def _payload(step, tokens, seq, now, last_id):
    from scripts.memprobe_routes import fill
    path = fill(step.path, tokens, seq, now)
    if "{id}" in path:
        if last_id is None:
            return None
        path = path.replace("{id}", last_id)
    if step.file is None:
        return path, (fill(step.body, tokens, seq, now) if step.body else None), "application/json"
    if isinstance(step.file, tuple):
        name, data = step.file[0], fill(step.file[1], tokens, seq, now).encode()
    else:
        name, data = os.path.basename(step.file), open(step.file, "rb").read()
    body, ctype = multipart(name, data)
    return path, body, ctype


def run_group(openers, base, group, tokens, n, gap, now) -> dict[str, list[Sent]]:
    """One cycle rotation: every member is sent n times; `{id}` comes from the
    most recent JSON response in the group that carried one."""
    out: dict[str, list[Sent]] = {s.route: [] for s in group}
    last_id = None
    for seq in range(n):
        for step in group:
            p = _payload(step, tokens, seq, now, last_id)
            if p is None:
                out[step.route].append(Sent(None, 0, None))
                continue
            path, body, ctype = p
            sent = _send(openers[step.as_user], base, step.method, path, body, ctype)
            out[step.route].append(sent)
            try:
                last_id = json.loads(sent.body or "")["id"] or last_id
            except (ValueError, KeyError, TypeError):
                pass
            time.sleep(gap)
    return out
```

`aggregate` must tolerate `Sent(None, 0)`: it already counts `req is None` as unmatched and `0` lands in `statuses` (non-2xx → failed). Good.

- [ ] **Step 5: Wire the `sweep` subcommand**

Restructure `main()` into subparsers: the default parser keeps the Phase 1 positional form (use `argparse` with `sys.argv[1:2] == ["sweep"]` dispatch rather than subparsers to keep `METHOD PATH` positional and under 500 lines). `run_sweep(args)`:

1. Reachability, seed, owner login exactly as Phase 1; tokens = `{**vars(seed), "barcode": seed.item_barcode, "wo": seed.work_order_number, "prefix": seed.prefix}`.
2. `from app.main import app` (inside the function); `routes, _ = enumerate_routes(app)`; `p = plan(routes, CATALOGUE, tokens, args.only)`.
3. `start_base = _send(owner, …, "GET", "/healthz")`.
4. For each group: if any step has `as_user == "technician"`, build a fresh `CookieJar` opener and `_login(tech, base, seed.technician_username, SEED_PASSWORD)` first (Review Focus 1). `openers = {"owner": owner, "technician": tech}`. Catch `(urllib.error.URLError, OSError)` → print, set `aborted = True`, break.
5. `end_base = _send(owner, …, "/healthz")`; sleep 0.5; one `read_container_logs`; `parse_request_lines` with every id.
6. `results = [RouteResult(route, aggregate(sent, samples), expect_for(route), "measured") …]` where `expect_for` reads `CATALOGUE.get(route).expect` for every step of every group.
7. `rows = rank(results)`; print `render_sweep(...)`; if `args.out`: `to_csv(...)`.
8. Teardown in `finally` as Phase 1. Exit: 2 if aborted; else 1 if any row `failed` or `p.skipped`; else 0.

Flags: `--n` 20, `--gap` 0.05, `--out`, `--only`, `--base`, `--container`.

- [ ] **Step 6: Run the whole test file**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_memprobe.py -q`
Expected: PASS, all Phase 1 tests included.

- [ ] **Step 7: Line count and commit**

Run: `(Get-Content scripts/memprobe.py | Measure-Object -Line).Lines` → under 500; move `_payload`/`multipart` into `memprobe_routes.py` if not.

```bash
git add backend/scripts/memprobe.py backend/scripts/memprobe_routes.py backend/tests/test_memprobe.py
git commit -m "feat(memprobe): sweep subcommand with ranking, CSV and cycle driver"
```

---

### Task 5: Acceptance run, render plan, docs

**Files:**
- Modify: `render.yaml:10`
- Modify: `docs/current-state.md` (Local Docker reproduction bullet list)
- Modify: `docs/open-work.md` (N-MEMORY-CRASH entry)
- Modify: `backend/scripts/memprobe_routes.py` (only if the run reveals a wrong body)

- [ ] **Step 1: Rebuild the container with the seed and scripts**

The container runs the app only, so no rebuild is needed for script changes; rebuild only if `app/` changed (it did not). Confirm it is up: `docker ps --filter name=inventory-local`.

- [ ] **Step 2: Smoke the sweep on one group**

Run from `backend/`: `.\venv\Scripts\python.exe scripts/memprobe.py sweep --only /healthz --n 20`
Expected: one ranked row, `skipped=0`, exit 0, baseline start/end both printed.

- [ ] **Step 3: Full sweep**

Run: `.\venv\Scripts\python.exe scripts/memprobe.py sweep --n 20 --out ../docs/superpowers/plans/sweep-2026-10-13.csv`
Expected: `skipped=0 failed=0`. For each failed route, read its status mix: 422 → fix the body in the catalogue; 403 → `as_user`; 409/404 by design → `expect`; 503 on `POST /push/test` → `expect=503`. Rerun with `--only <route>` until clean, then the full run again. Paste the final table into the completion report. Delete the CSV from `docs/` afterwards (it is evidence for the report, not a doc) — or keep it out of git.

- [ ] **Step 4: Fix `render.yaml`**

Change line 10 to the live plan name (`plan: standard` is Render's 2 GB / 1 CPU tier; confirm against the Render dashboard name before committing) and drop the `# free web tier …` comment.

- [ ] **Step 5: Docs**

`docs/current-state.md`, after the Phase 1 bullet: one bullet — `sweep` form, `--out`/`--only`, the two cookie jars, "every route catalogued or excluded; `tests/test_memprobe.py` guards it".
`docs/open-work.md` N-MEMORY-CRASH: "Phase 2 shipped <date>" with the top five routes by `rest(sum)` from Step 3; remove the `render.yaml` sentence.

- [ ] **Step 6: Commit**

```bash
git add render.yaml docs/current-state.md docs/open-work.md backend/scripts/memprobe_routes.py
git commit -m "feat(memprobe): phase 2 sweep shipped; render plan corrected; docs"
```

Do not push. Report the two tables (Step 2 and Step 3) and the pytest line.
