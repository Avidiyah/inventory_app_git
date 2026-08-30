# Work Orders Search Expansion (Location + Task Keyword) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task (this repo forbids subagents, so subagent-driven-development is not an option here). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two independent keyword searches — Location and Task/Symptom — to the Work Orders page, its API, and its filtered CSV export, ANDed with every existing filter.

**Architecture:** Thread two new optional filters through the existing single filter pipeline: router query params `location_q`/`task_q` → service kwargs `location_search`/`task_search` → `_apply_work_order_filters` predicates built with the existing `_search_pattern` LIKE-escaper. Location ORs across raw `location` plus structured `community`/`building_number`/`unit_number` (bridging imported vs hand-created rows); Task hits `description` only. Frontend adds two debounced text inputs in the filter grid feeding `currentFilters()`.

**Tech Stack:** FastAPI + SQLAlchemy (backend), vanilla JS modules (frontend), pytest with a real `TestClient` for router tests.

**Spec:** `docs/superpowers/specs/2026-08-30-work-orders-search-expansion-design.md`

## Global Constraints

- No schema or model changes; no new DB indexes.
- `notes` is NEVER searched (separate operational log).
- The number bar, `/work-orders/lookup`, and the archived-restore flow are untouched; `checkArchivedSearch` stays number-search-only.
- The `client` CSV export variant stays scope-only (its `export_filters` dict stays `{}`).
- Exact names: query params `location_q` / `task_q`; service kwargs `location_search` / `task_search`; JS filter keys `locationQ` / `taskQ`; element ids `work-orders-location-search` / `work-orders-task-search`; labels `Location` and `Task / symptom`; placeholders `Search location` and `Search task keywords`.
- Router tests go over real HTTP via `TestClient` (this repo was bitten by FastAPI query parsing that direct handler calls never exercise — see the docstring at the top of `backend/tests/test_work_orders_router.py`).
- Run tests from the worktree's `backend/` dir with the MAIN checkout's venv:
  `C:/Users/mcclu/Desktop/inventory_app_git/backend/venv/Scripts/python.exe -m pytest ...`
  DB-backed tests need local Postgres (port 8801, `backend/.env` already present in this worktree). If DB tests SKIP, that's a broken environment, not a pass.
- Known pre-existing env failure: `test_cascade_deletes_with_user` fails against the dev DB (real cloud-session rows). Not a regression; ignore it in full-suite runs.
- Commits: conventional style (`feat(work-orders): ...`), end body with the `Claude-Session:` trailer, NO `Co-Authored-By`. Do NOT push or merge — pushing main deploys production.

---

### Task 1: Service list path — `location_search` / `task_search` predicates

**Files:**
- Modify: `backend/app/services/work_orders.py` (`_apply_work_order_filters` ~L1145, `list_work_orders` ~L1242)
- Test: `backend/tests/test_work_orders_service.py` (append after `test_status_filter_and_search`, ~L1370)

**Interfaces:**
- Consumes: existing `_search_pattern(value)` → `(like, escape)` or `None` (L166); `or_`, `func` already imported.
- Produces: `_apply_work_order_filters(..., location_search: Optional[str] = None, task_search: Optional[str] = None)` and `list_work_orders(..., location_search=None, task_search=None)` — Tasks 2–4 rely on these exact kwarg names.

- [ ] **Step 1: Write the failing tests** — append to `backend/tests/test_work_orders_service.py` (helpers `_seed_user`, `_wo`, `wos`, `uuid` already exist in the file):

```python
def test_location_search_matches_raw_and_structured_locations(db):
    sup = _seed_user(db, "supervisor")
    raw = wos.get_or_create_work_order(
        db,
        number=f"WO-LOC-{uuid.uuid4().hex[:8]}",
        created_by_id=sup.id,
        location="Building 2312\nDenton TX",
    )
    structured = wos.get_or_create_work_order(
        db,
        number=f"WO-LOC-{uuid.uuid4().hex[:8]}",
        created_by_id=sup.id,
        community="Commons Apartments",
        building_number="2312",
        unit_number="7A",
    )
    other = wos.get_or_create_work_order(
        db,
        number=f"WO-LOC-{uuid.uuid4().hex[:8]}",
        created_by_id=sup.id,
        location="Building 9000",
    )

    found = {w.id for w in wos.list_work_orders(db, user=sup, location_search="2312")}
    assert raw.id in found and structured.id in found
    assert other.id not in found

    # Case-insensitive, and community / unit_number participate too.
    assert structured.id in {
        w.id for w in wos.list_work_orders(db, user=sup, location_search="commons")
    }
    assert structured.id in {
        w.id for w in wos.list_work_orders(db, user=sup, location_search="7a")
    }


def test_task_search_matches_description_not_notes(db):
    sup = _seed_user(db, "supervisor")
    described = wos.get_or_create_work_order(
        db,
        number=f"WO-TASK-{uuid.uuid4().hex[:8]}",
        created_by_id=sup.id,
        description="Broken toilet flapper in unit bath",
    )
    noted = wos.get_or_create_work_order(
        db,
        number=f"WO-TASK-{uuid.uuid4().hex[:8]}",
        created_by_id=sup.id,
        description="Paint touch-up",
    )
    wos.update_work_order(
        db, noted.id, user=sup, fields={"notes": "toilet flapper mentioned in notes"}
    )

    found = {w.id for w in wos.list_work_orders(db, user=sup, task_search="FLAPPER")}
    assert described.id in found
    assert noted.id not in found


def test_keyword_searches_escape_like_wildcards(db):
    sup = _seed_user(db, "supervisor")
    literal = wos.get_or_create_work_order(
        db,
        number=f"WO-ESC-{uuid.uuid4().hex[:8]}",
        created_by_id=sup.id,
        location="50% Building",
        description="fix under_score panel",
    )
    decoy = wos.get_or_create_work_order(
        db,
        number=f"WO-ESC-{uuid.uuid4().hex[:8]}",
        created_by_id=sup.id,
        location="50x Building",
        description="fix underXscore panel",
    )

    by_location = {
        w.id for w in wos.list_work_orders(db, user=sup, location_search="50%")
    }
    assert literal.id in by_location and decoy.id not in by_location

    by_task = {
        w.id for w in wos.list_work_orders(db, user=sup, task_search="under_score")
    }
    assert literal.id in by_task and decoy.id not in by_task


def test_keyword_searches_combine_with_and(db):
    sup = _seed_user(db, "supervisor")
    prefix = f"WO-AND-{uuid.uuid4().hex[:8]}"
    target = wos.get_or_create_work_order(
        db,
        number=f"{prefix}-T",
        created_by_id=sup.id,
        location="Building 2312",
        description="leaking sink",
    )
    wos.get_or_create_work_order(
        db,
        number=f"{prefix}-L",
        created_by_id=sup.id,
        location="Building 2312",
        description="door hinge",
    )

    narrowed = {
        w.id
        for w in wos.list_work_orders(
            db, user=sup, search=prefix, location_search="2312", task_search="sink"
        )
    }
    assert narrowed == {target.id}

    # Still narrows alongside the dropdown filters.
    wos.update_work_order(db, target.id, user=sup, fields={"status": "in_progress"})
    assert {
        w.id
        for w in wos.list_work_orders(
            db,
            user=sup,
            status="in_progress",
            search=prefix,
            location_search="2312",
            task_search="sink",
        )
    } == {target.id}
    assert not wos.list_work_orders(
        db,
        user=sup,
        status="completed",
        search=prefix,
        location_search="2312",
        task_search="sink",
    )


def test_blank_keyword_searches_are_noops(db):
    sup = _seed_user(db, "supervisor")
    work_order = _wo(db, created_by=sup)

    found = {
        w.id
        for w in wos.list_work_orders(
            db, user=sup, location_search="   ", task_search=""
        )
    }
    assert work_order.id in found
```

- [ ] **Step 2: Run them to verify they fail**

Run (from worktree `backend/`): `C:/Users/mcclu/Desktop/inventory_app_git/backend/venv/Scripts/python.exe -m pytest tests/test_work_orders_service.py -k "location_search or task_search or keyword_search" -v`
Expected: 5 FAIL with `TypeError: list_work_orders() got an unexpected keyword argument`.

- [ ] **Step 3: Implement** — in `backend/app/services/work_orders.py`:

3a. `_apply_work_order_filters` signature: after `search: Optional[str] = None,` add:

```python
    location_search: Optional[str] = None,
    task_search: Optional[str] = None,
```

3b. In its body, after the existing number-search block (`query = query.filter(WorkOrder.number.ilike(like, escape=escape))`), before `return query`:

```python
    location_pattern = _search_pattern(location_search)
    if location_pattern is not None:
        like, escape = location_pattern
        # One bar finds both shapes of location data: imported rows carry the
        # raw multi-line `location` text, hand-created rows carry structured
        # community/building/unit instead (the same bridge `_community_match`
        # and the frontend's `placeMeta` already make).
        query = query.filter(
            or_(
                func.coalesce(WorkOrder.location, "").ilike(like, escape=escape),
                func.coalesce(WorkOrder.community, "").ilike(like, escape=escape),
                func.coalesce(WorkOrder.building_number, "").ilike(
                    like, escape=escape
                ),
                func.coalesce(WorkOrder.unit_number, "").ilike(like, escape=escape),
            )
        )

    task_pattern = _search_pattern(task_search)
    if task_pattern is not None:
        like, escape = task_pattern
        # `description` is the Task/Symptom field. `notes` is a separate
        # append-only log and is deliberately NOT searched here.
        query = query.filter(
            func.coalesce(WorkOrder.description, "").ilike(like, escape=escape)
        )
```

3c. `list_work_orders` signature: after `search: Optional[str] = None,` add the same two kwargs; inside its `scoped()` helper pass `location_search=location_search, task_search=task_search,` right after `search=search,`. Add one docstring sentence: "`location_search` matches raw location plus structured community/building/unit; `task_search` matches the Task/Symptom `description` only."

- [ ] **Step 4: Run the tests again** — same command. Expected: 5 PASS. Also run the neighbors: `... -m pytest tests/test_work_orders_service.py -k "filter or search" -v` — all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/work_orders.py backend/tests/test_work_orders_service.py
git commit -m "feat(work-orders): location + task keyword filters in the list service"
```

---

### Task 2: Service export path — the two filters reach the CSV

**Files:**
- Modify: `backend/app/services/work_orders.py` (`list_work_orders_for_export` ~L1446, `export_work_orders_csv` ~L1628)
- Test: `backend/tests/test_work_order_export.py` (new test after `test_operational_export_honors_the_priority_filter` ~L285; extend `test_client_variant_remains_scope_only_when_operational_filters_are_supplied` ~L436)

**Interfaces:**
- Consumes: Task 1's `_apply_work_order_filters(..., location_search=..., task_search=...)`.
- Produces: `list_work_orders_for_export(..., location_search=None, task_search=None)` and `export_work_orders_csv(..., location_search=None, task_search=None)` — Task 4's router threading relies on these names.

- [ ] **Step 1: Write the failing test** — append to `backend/tests/test_work_order_export.py` (helpers `_seed_user`, `wos`, `uuid` exist):

```python
def test_operational_export_honors_location_and_task_search(db):
    admin = _seed_user(db, "admin")
    prefix = f"WO-EXP-{uuid.uuid4().hex[:8]}"
    target = wos.get_or_create_work_order(
        db,
        number=f"{prefix}-T",
        created_by_id=admin.id,
        location="Building 2312",
        description="leaking sink trap",
    )
    wos.get_or_create_work_order(
        db,
        number=f"{prefix}-O",
        created_by_id=admin.id,
        location="Building 9000",
        description="door hinge",
    )

    body = wos.export_work_orders_csv(
        db,
        user=admin,
        scope="all",
        search=prefix,
        location_search="2312",
        task_search="sink",
    )
    assert target.number in body
    assert f"{prefix}-O" not in body
```

- [ ] **Step 2: Run it to verify it fails**

Run: `C:/Users/mcclu/Desktop/inventory_app_git/backend/venv/Scripts/python.exe -m pytest tests/test_work_order_export.py::test_operational_export_honors_location_and_task_search -v`
Expected: FAIL with `TypeError: export_work_orders_csv() got an unexpected keyword argument`.

- [ ] **Step 3: Implement** — in `backend/app/services/work_orders.py`:

3a. `list_work_orders_for_export`: after `search: Optional[str] = None,` add the two kwargs; pass them into its `_apply_work_order_filters(...)` call after `search=search,`.

3b. `export_work_orders_csv`: after `search: Optional[str] = None,` add the two kwargs; in the `export_filters` dict (full variant only — the `{} if is_client` branch is untouched) add:

```python
        "location_search": location_search,
        "task_search": task_search,
```

- [ ] **Step 4: Extend the client-variant pin** — in `test_client_variant_remains_scope_only_when_operational_filters_are_supplied` (~L436), add to the existing `export_work_orders_csv(...)` call alongside `search="does-not-match"`:

```python
        location_search="does-not-match",
        task_search="does-not-match",
```

- [ ] **Step 5: Run the export suite** — `... -m pytest tests/test_work_order_export.py -v`. Expected: all PASS (new test plus every existing one).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/work_orders.py backend/tests/test_work_order_export.py
git commit -m "feat(work-orders): thread location/task search through the CSV export service"
```

---

### Task 3: List route — `location_q` / `task_q` over real HTTP

**Files:**
- Modify: `backend/app/routers/work_orders.py` (`list_work_orders` route, params ~L530, service call ~L572)
- Test: `backend/tests/test_work_orders_router.py` (after `test_mine_defaults_to_off`, before the UI-wiring section ~L98)

**Interfaces:**
- Consumes: Task 1's `list_work_orders(..., location_search=..., task_search=...)`; test helpers `_seed_user`, `_numbers`, `auth_service.create_session` already in the file.
- Produces: `GET /work-orders/?location_q=&task_q=` — Task 5's `api.js` params target these names.

- [ ] **Step 1: Write the failing tests** — append to `backend/tests/test_work_orders_router.py` before the UI-wiring section:

```python
def test_location_q_and_task_q_filter_over_real_http(db):
    admin = _seed_user(db, "admin")
    prefix = f"WO-KW-{uuid.uuid4().hex[:8]}"
    match = wos.get_or_create_work_order(
        db,
        number=f"{prefix}-M",
        created_by_id=admin.id,
        location="Building 2312",
        description="leaking sink trap",
    )
    miss = wos.get_or_create_work_order(
        db,
        number=f"{prefix}-X",
        created_by_id=admin.id,
        location="Building 9000",
        description="door hinge",
    )
    db.commit()
    token = auth_service.create_session(db, admin)

    by_location = _numbers(db, token, f"?q={prefix}&location_q=2312")
    assert match.number in by_location and miss.number not in by_location

    by_task = _numbers(db, token, f"?q={prefix}&task_q=sink")
    assert match.number in by_task and miss.number not in by_task

    # All three text searches AND together: location matches only -M,
    # task matches only -X, so their intersection is empty.
    assert _numbers(db, token, f"?q={prefix}&location_q=2312&task_q=hinge") == set()


def test_blank_keyword_params_are_noops_over_real_http(db):
    admin = _seed_user(db, "admin")
    prefix = f"WO-KWB-{uuid.uuid4().hex[:8]}"
    work_order = wos.get_or_create_work_order(
        db, number=f"{prefix}-B", created_by_id=admin.id
    )
    db.commit()
    token = auth_service.create_session(db, admin)

    assert work_order.number in _numbers(
        db, token, f"?q={prefix}&location_q=&task_q="
    )
```

- [ ] **Step 2: Run them to verify they fail**

Run: `... -m pytest tests/test_work_orders_router.py -k "location_q or blank_keyword" -v`
Expected: FAIL — the route ignores unknown query params, so `by_location` also contains `miss.number` (assertion failure, not a 422).

- [ ] **Step 3: Implement** — in `backend/app/routers/work_orders.py`, `list_work_orders` route:

After `q: Optional[str] = Query(None),` add:

```python
    location_q: Optional[str] = Query(None),
    task_q: Optional[str] = Query(None),
```

In the `wo_service.list_work_orders(...)` call, after `search=q,` add:

```python
                location_search=location_q,
                task_search=task_q,
```

Docstring: extend the filter list sentence with "`location_q` (substring over raw location plus structured community/building/unit) and `task_q` (substring over the Task/Symptom description; never `notes`)".

- [ ] **Step 4: Run to verify green** — same `-k` command PASS, then the whole file: `... -m pytest tests/test_work_orders_router.py -v` all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/work_orders.py backend/tests/test_work_orders_router.py
git commit -m "feat(work-orders): accept location_q/task_q on the list route"
```

---

### Task 4: Export route + filename — `location_q` / `task_q` reach the CSV download

**Files:**
- Modify: `backend/app/routers/work_orders.py` (`export_work_orders` route ~L680; `_export_filename` ~L295)
- Test: `backend/tests/test_work_order_export.py` (`test_route_forwards_operational_export_filters` ~L487)

**Interfaces:**
- Consumes: Task 2's `export_work_orders_csv(..., location_search=..., task_search=...)`.
- Produces: `GET /work-orders/export?location_q=&task_q=` — Task 5's `apiExportWorkOrders` targets these names.

- [ ] **Step 1: Extend the forwarding test to fail first** — in `test_route_forwards_operational_export_filters`:

Add to the `export_route(...)` call, after `q="WO-123",`:

```python
        location_q="Bldg 7",
        task_q="leak",
```

Extend the filename regex — the third line becomes:

```python
        r'date-2026-07-28-number-wo-123-location-bldg-7-task-leak\.csv"',
```

Extend the expected `captured` dict, after `"search": "WO-123",`:

```python
        "location_search": "Bldg 7",
        "task_search": "leak",
```

- [ ] **Step 2: Run it to verify it fails**

Run: `... -m pytest tests/test_work_order_export.py::test_route_forwards_operational_export_filters -v`
Expected: FAIL with `TypeError: export_work_orders() got an unexpected keyword argument 'location_q'`.

- [ ] **Step 3: Implement** — in `backend/app/routers/work_orders.py`:

3a. `export_work_orders` route signature: after `q: Optional[str] = None,` add (plain defaults, matching that route's existing style):

```python
    location_q: Optional[str] = None,
    task_q: Optional[str] = None,
```

3b. Thread into BOTH calls in the route body — `wo_service.export_work_orders_csv(...)` and `_export_filename(...)` — after `search=q,` in each:

```python
        location_search=location_q,
        task_search=task_q,
```

3c. `_export_filename` signature: after `search: Optional[str],` add:

```python
    location_search: Optional[str],
    task_search: Optional[str],
```

and in its full-variant branch, after `parts.extend(("number", search))`:

```python
        if location_search and location_search.strip():
            parts.extend(("location", location_search))
        if task_search and task_search.strip():
            parts.extend(("task", task_search))
```

(The filename names every honored filter — that's this helper's stated contract, so the two new honored filters must appear in it.)

3d. Extend the route docstring's filter list with `location_q` / `task_q` alongside `q`.

- [ ] **Step 4: Run the export suite** — `... -m pytest tests/test_work_order_export.py -v`. Expected: all PASS (the untouched `test_route_returns_a_csv_attachment` proves omitted params leave filenames unchanged).

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/work_orders.py backend/tests/test_work_order_export.py
git commit -m "feat(work-orders): accept location_q/task_q on the CSV export route"
```

---

### Task 5: Frontend — two filter-grid inputs wired to the API

**Files:**
- Modify: `backend/static/pages/work-orders.html` (filter grid, after the scheduled-date field ~L72)
- Modify: `backend/static/views/workOrders.js` (element refs ~L86, `currentFilters` ~L286, `resetFilterControls` ~L303, search wiring ~L2600, clear-filters handler ~L2613)
- Modify: `backend/static/api.js` (`apiListWorkOrders` ~L452, `apiExportWorkOrders` ~L600)
- Test: `backend/tests/test_work_orders_router.py` (UI wiring guards section, after `test_only_the_solo_card_suppresses_its_own_click`)

**Interfaces:**
- Consumes: Tasks 3–4's `location_q` / `task_q` query params.
- Produces: `currentFilters()` keys `locationQ` / `taskQ` (spread into `apiListWorkOrders` and passed as `filters` to `apiExportWorkOrders` by existing code — no call-site changes needed).

- [ ] **Step 1: Write the failing pin test** — append to `backend/tests/test_work_orders_router.py` (in the UI wiring guards section; `Path`, `_code`, `_view` exist):

```python
def test_work_orders_ui_wires_location_and_task_searches():
    """The two keyword filters exist in the grid, feed currentFilters, clear
    with Clear filters, and reach the API as `location_q` / `task_q` --
    without inheriting the number bar's archived-restore lookup."""
    html = (
        Path(__file__).resolve().parents[1] / "static" / "pages" / "work-orders.html"
    ).read_text(encoding="utf-8")
    assert 'id="work-orders-location-search"' in html
    assert 'id="work-orders-task-search"' in html

    code = _code("workOrders.js")
    assert 'getElementById("work-orders-location-search")' in code
    assert 'getElementById("work-orders-task-search")' in code
    assert "locationQ: locationSearchInput" in code
    assert "taskQ: taskSearchInput" in code
    assert "wireKeywordSearch(locationSearchInput)" in code
    assert "wireKeywordSearch(taskSearchInput)" in code
    assert 'if (locationSearchInput) locationSearchInput.value = "";' in code
    assert 'if (taskSearchInput) taskSearchInput.value = "";' in code

    view = _view("../api.js")
    assert 'params.set("location_q", locationQ)' in view
    assert 'params.set("task_q", taskQ)' in view
    assert 'params.set("location_q", filters.locationQ)' in view
    assert 'params.set("task_q", filters.taskQ)' in view
```

- [ ] **Step 2: Run it to verify it fails**

Run: `... -m pytest tests/test_work_orders_router.py::test_work_orders_ui_wires_location_and_task_searches -v`
Expected: FAIL on the first `assert`.

- [ ] **Step 3: HTML** — in `backend/static/pages/work-orders.html`, inside the filter grid, directly after the scheduled-date `wo-filter-field` div (before the grid's closing `</div>`):

```html
                <div class="wo-filter-field">
                    <label for="work-orders-location-search">Location</label>
                    <input type="text" id="work-orders-location-search" placeholder="Search location">
                </div>
                <div class="wo-filter-field">
                    <label for="work-orders-task-search">Task / symptom</label>
                    <input type="text" id="work-orders-task-search" placeholder="Search task keywords">
                </div>
```

- [ ] **Step 4: workOrders.js** — four edits:

4a. Element refs, directly under the `searchBtn` declaration (~L85):

```js
const locationSearchInput = document.getElementById("work-orders-location-search");
const taskSearchInput = document.getElementById("work-orders-task-search");
```

4b. `currentFilters()` — add after the `q:` entry:

```js
    locationQ: locationSearchInput ? locationSearchInput.value.trim() : "",
    taskQ: taskSearchInput ? taskSearchInput.value.trim() : "",
```

(`hasActiveFilters()` reads `Object.values(currentFilters())`, so either search lifts the browse cap automatically. `loadWorkOrders` spreads `currentFilters()` into `apiListWorkOrders`, and `handleFilteredExport` passes it as `filters` — no changes there.)

4c. `resetFilterControls()` — add after the `if (searchInput) ...` line:

```js
  if (locationSearchInput) locationSearchInput.value = "";
  if (taskSearchInput) taskSearchInput.value = "";
```

4d. Wiring — insert after the number-search `keydown` block (the `if (searchInput) { ... }` block, ~L2600) and BEFORE the dropdown `.forEach` wiring:

```js
// The Location and Task/symptom keyword searches reuse the number bar's
// 250 ms debounce + immediate Enter, but run plain loadWorkOrders():
// checkArchivedSearch stays a number-search-only behavior, because only an
// exact number can name an archived work order.
function wireKeywordSearch(input) {
  if (!input) return () => {};
  let debounce = null;
  const run = () => loadWorkOrders();
  input.addEventListener("input", () => {
    clearTimeout(debounce);
    debounce = setTimeout(run, 250);
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      clearTimeout(debounce);
      run();
    }
  });
  return () => clearTimeout(debounce);
}
const cancelLocationSearchDebounce = wireKeywordSearch(locationSearchInput);
const cancelTaskSearchDebounce = wireKeywordSearch(taskSearchInput);
```

Then in the `clearFiltersBtn` click handler, after `clearTimeout(woSearchDebounce);`:

```js
    cancelLocationSearchDebounce();
    cancelTaskSearchDebounce();
```

- [ ] **Step 5: api.js** — two edits:

5a. `apiListWorkOrders`: add `locationQ = null,` and `taskQ = null,` to the destructured params (after `q = null,`), and after `if (q) params.set("q", q);`:

```js
  if (locationQ) params.set("location_q", locationQ);
  if (taskQ) params.set("task_q", taskQ);
```

5b. `apiExportWorkOrders`: after `if (filters.q) params.set("q", filters.q);`:

```js
  if (filters.locationQ) params.set("location_q", filters.locationQ);
  if (filters.taskQ) params.set("task_q", filters.taskQ);
```

- [ ] **Step 6: Run to verify green** — `... -m pytest tests/test_work_orders_router.py -v`. Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/static/pages/work-orders.html backend/static/views/workOrders.js backend/static/api.js backend/tests/test_work_orders_router.py
git commit -m "feat(work-orders): Location and Task/symptom search inputs in the filter grid"
```

---

### Task 6: Docs + full verification

**Files:**
- Modify: `docs/endpoint-map.md` (rows for `GET /work-orders/` L79 and `GET /work-orders/export` L116)

**Interfaces:**
- Consumes: everything above.
- Produces: nothing further — vault mirror is automated, no manual Obsidian sync.

- [ ] **Step 1: Update the two rows**

Row 25 (`GET /work-orders/`, L79): change `joinable status/service/supervisor/community/date/number filters` → `joinable status/service/supervisor/community/date/number/location/task filters`.

Row 62 (`GET /work-orders/export`, L116): change `(full: current live filters; client: unchanged scope dropdown; + \`domain.receipt\`)` → `(full: current live filters incl. location/task keyword search; client: unchanged scope dropdown; + \`domain.receipt\`)`.

- [ ] **Step 2: Full test suite**

Run: `C:/Users/mcclu/Desktop/inventory_app_git/backend/venv/Scripts/python.exe -m pytest tests/ -q`
Expected: all PASS except the known environmental `test_cascade_deletes_with_user` failure. Confirm no NEW failures and that the work-orders suites actually ran (not skipped for a missing DB).

- [ ] **Step 3: Commit**

```bash
git add docs/endpoint-map.md
git commit -m "docs(endpoint-map): name the location/task filters on the work-orders list and export rows"
```
