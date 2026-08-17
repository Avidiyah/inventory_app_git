# Work Orders Live Status Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every role sees work-order status changes on the Work Orders page in real time, scoped by the existing permission rules.

**Architecture:** Add a second event type to the existing real-time vocabulary (`work_order.status.changed`, audience technician-and-above), emit it from the seven routes that can change a work order's status, and subscribe `workOrders.js` to it. Events carry no row data, so the client re-fetches over REST and the server's existing `can_view_work_order` scoping enforces permissions with no new authorization code. Cards being edited are frozen so a refresh never destroys unsaved input.

**Tech Stack:** FastAPI, SQLAlchemy, pytest (backend); vanilla ES modules, no build step, no JS test runner (frontend).

**Spec:** `docs/superpowers/specs/2026-08-16-work-orders-live-status-design.md`

## Global Constraints

- **Emit order is pinned: review-queue first, status second.** Every route emitting both does so in this order. `test_realtime_emit.py:148` depends on it.
- **`emit` results are always ignored.** Delivery is best-effort; a full handoff must never fail a durable write.
- **Envelopes carry no row data.** Only `{type, id, req}`. Never add fields.
- **`entity_id=None` means a collection/membership command** — the client refetches the list rather than one card.
- **The transport is out of bounds.** Do not modify `app/services/realtime.py`, `app/routers/realtime.py`, or `static/realtime.js`.
- **Do not modify `adminReview.js`** or the review-queue event, its audience, or its five emitters.
- **Backend tests run from `backend/`** with `./venv/Scripts/python.exe -m pytest`. The tests in this plan are pure — no Postgres required.
- **The frontend has no automated test coverage.** Frontend tasks are verified by reading plus the manual steps given. Do not invent a test runner.

---

### Task 1: Add the status event to the domain policy

**Files:**
- Modify: `backend/app/domain/realtime.py:28-59`
- Test: `backend/tests/test_realtime_domain.py` (append)

**Interfaces:**
- Consumes: nothing (first task)
- Produces: `realtime.EVENT_WORK_ORDER_STATUS_CHANGED` — the string constant `"work_order.status.changed"`, allowed for `roles.ROLE_TECHNICIAN` and above via the existing `audience_allows(event_type, role) -> bool`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_realtime_domain.py`:

```python
def test_status_events_reach_every_role_that_can_open_the_page():
    """Work Orders is available to all five roles (static/views/nav.js:67), so
    the status event's audience is the whole hierarchy. This is a noise rule,
    not a security one -- P2 means the re-fetch is what enforces scoping."""
    for role in ("technician", "supervisor", "techfm_oa", "admin", "owner"):
        assert (
            realtime.audience_allows(realtime.EVENT_WORK_ORDER_STATUS_CHANGED, role)
            is True
        )


def test_status_and_review_queue_are_distinct_event_types():
    assert (
        realtime.EVENT_WORK_ORDER_STATUS_CHANGED
        != realtime.EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED
    )
    assert realtime.EVENT_WORK_ORDER_STATUS_CHANGED == "work_order.status.changed"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && ./venv/Scripts/python.exe -m pytest tests/test_realtime_domain.py -q
```

Expected: FAIL with `AttributeError: module 'app.domain.realtime' has no attribute 'EVENT_WORK_ORDER_STATUS_CHANGED'`

- [ ] **Step 3: Add the constant and audience entry**

In `backend/app/domain/realtime.py`, add to `__all__` immediately after `"EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED",`:

```python
    "EVENT_WORK_ORDER_STATUS_CHANGED",
```

Then replace the vocabulary block (currently lines 50-59):

```python
# The only server->client event type in v1. This is intentionally narrower
# than a general work-order aggregate event: it invalidates the Review-status
# queue projection (membership plus the fields shown on its cards). Material,
# labor, billing, and price changes do not belong to this vocabulary because
# the first consumer refreshes only the queue, not an open receipt.
EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED = "work_order.review_queue.changed"

# The Work Orders card list. Narrower than an aggregate event in the same way:
# it invalidates a card's *summary* projection -- status, assignee, item count --
# and nothing else. Material, labor, billing, and price stay out of the
# vocabulary, because no consumer refreshes an open card body.
#
# `id` names one work order; `None` means a membership command (restore), where
# the recipient's list may have gained a row that no on-screen card represents.
EVENT_WORK_ORDER_STATUS_CHANGED = "work_order.status.changed"

_AUDIENCE_MIN_ROLE = {
    EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED: roles.ROLE_TECHFM_OA,
    # Every role that can open the Work Orders page. Not a security boundary:
    # P2 keeps row data out of the envelope, so a technician who receives an
    # event for a work order they cannot see simply re-fetches nothing.
    EVENT_WORK_ORDER_STATUS_CHANGED: roles.ROLE_TECHNICIAN,
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && ./venv/Scripts/python.exe -m pytest tests/test_realtime_domain.py -q
```

Expected: PASS, and the pre-existing `test_review_queue_events_do_not_reach_lower_roles_in_v1` still passes — the new constant has its own audience entry and does not touch the review-queue one.

- [ ] **Step 5: Commit**

```bash
git add backend/app/domain/realtime.py backend/tests/test_realtime_domain.py
git commit -m "Add a work-order status event to the real-time vocabulary"
```

---

### Task 2: Emit from the four walkthrough transitions

**Files:**
- Modify: `backend/app/routers/work_orders.py:74-88` (add helper), `:550-625` (four routes)
- Test: `backend/tests/test_realtime_emit.py` (append)

**Interfaces:**
- Consumes: `realtime_policy.EVENT_WORK_ORDER_STATUS_CHANGED` from Task 1
- Produces: `_emit_status_changed(entity_id: Optional[uuid.UUID]) -> None` in `app.routers.work_orders`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_realtime_emit.py`:

```python
@pytest.mark.parametrize(
    "route_name",
    ["start_work_order", "complete_work_order", "hold_work_order", "resume_work_order"],
)
def test_each_walkthrough_transition_emits_one_status_invalidation(
    monkeypatch, route_name
):
    """The four assigned-worker transitions are the whole reason this event
    exists: they change the status a card renders and emitted nothing before."""
    work_order_id = uuid.uuid4()
    saved = SimpleNamespace(id=work_order_id)
    user = SimpleNamespace(role=roles.ROLE_TECHNICIAN)
    envelopes = _capture_emits(monkeypatch)
    monkeypatch.setattr(
        work_orders_router.wo_service,
        route_name,
        lambda db, incoming_id, *, user: saved,
    )
    monkeypatch.setattr(
        work_orders_router.wo_service,
        "get_work_order",
        lambda db, incoming_id, *, user: saved,
    )
    _passthrough_detail(monkeypatch)

    result = getattr(work_orders_router, route_name)(
        work_order_id, user=user, db=None
    )

    assert result is saved
    assert envelopes == [
        {
            "type": realtime_policy.EVENT_WORK_ORDER_STATUS_CHANGED,
            "id": str(work_order_id),
            "req": REQUEST_ID,
        }
    ]


def test_a_failed_transition_emits_nothing(monkeypatch):
    work_order_id = uuid.uuid4()
    user = SimpleNamespace(role=roles.ROLE_TECHNICIAN)
    envelopes = _capture_emits(monkeypatch)

    def fail(db, incoming_id, *, user):
        raise WorkOrderStateError("not in progress")

    monkeypatch.setattr(work_orders_router.wo_service, "complete_work_order", fail)

    with pytest.raises(HTTPException):
        work_orders_router.complete_work_order(work_order_id, user=user, db=None)

    assert envelopes == []
```

Note: the route function and the service function share a name for all four
transitions, which is why one `route_name` parameter drives both `setattr` and
the call.

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && ./venv/Scripts/python.exe -m pytest tests/test_realtime_emit.py -q
```

Expected: FAIL — `assert [] == [{...}]`, because no transition emits yet.

- [ ] **Step 3: Add the helper**

In `backend/app/routers/work_orders.py`, immediately after `_emit_review_queue_changed` (which ends at line 88):

```python
def _emit_status_changed(entity_id: Optional[uuid.UUID]) -> None:
    """Invalidate the Work Orders card list after a status change.

    ``None`` identifies a membership command (restore), where a recipient's
    list may have gained a row that no on-screen card can represent, so the
    client refetches the list instead of one card.

    Emitted *after* ``_emit_review_queue_changed`` on every route that sends
    both. Order is pinned rather than incidental: restore's status envelope
    carries ``id: None``, so a caller inspecting ``envelopes[0]`` must still
    find the review-queue entity invalidation.

    Delivery is best-effort for the same reason as the review-queue emitter:
    a full handoff must never fail a durable write.
    """
    realtime_service.emit(
        realtime_policy.build_envelope(
            event_type=realtime_policy.EVENT_WORK_ORDER_STATUS_CHANGED,
            entity_id=entity_id,
            request_id=current_request_id(),
        )
    )
```

- [ ] **Step 4: Call it from the four transitions**

In each of `start_work_order` (`:550`), `complete_work_order` (`:571`), `hold_work_order` (`:594`) and `resume_work_order` (`:611`), add the emit between the command and the response hydration. `start_work_order` becomes:

```python
    try:
        work_order = wo_service.start_work_order(db, work_order_id, user=user)
        _emit_status_changed(work_order.id)
        return _detail(
            wo_service.get_work_order(db, work_order.id, user=user),
            include_price=_can_see_price(user),
        )
    except DomainError as exc:
        raise to_http(exc)
```

Apply the identical one-line insertion to the other three, each calling its own
`wo_service` function. Emitting inside the `try` and after the command is what
makes the failure test pass: a `DomainError` raised by the command reaches the
`except` before any emit runs.

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd backend && ./venv/Scripts/python.exe -m pytest tests/test_realtime_emit.py tests/test_realtime_domain.py -q
```

Expected: PASS. The five pre-existing emit tests are untouched by this task — none of the four transition routes appears in them.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/work_orders.py backend/tests/test_realtime_emit.py
git commit -m "Emit a status invalidation from the work-order transitions"
```

---

### Task 3: Emit from update, archive and restore

This is the task that changes existing expectations. `update_work_order` and
`archive_work_order` will emit two envelopes each.

**Files:**
- Modify: `backend/app/routers/work_orders.py:537`, `:641`, `:662`
- Modify: `backend/tests/test_realtime_emit.py:96-103`, `:119-125`, `:240`
- Test: `backend/tests/test_realtime_emit.py` (append)

**Interfaces:**
- Consumes: `_emit_status_changed` from Task 2
- Produces: the complete seven-route status emitter set

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_realtime_emit.py`:

```python
def test_restore_emits_a_collection_style_status_invalidation(monkeypatch):
    """A restored work order is on nobody's screen, so no on-screen card can be
    updated in place. `None` is the established collection signal (import and
    bulk legacy archive both use it) and tells the client to refetch its list."""
    work_order_id = uuid.uuid4()
    saved = SimpleNamespace(id=work_order_id)
    user = SimpleNamespace(role=roles.ROLE_SUPERVISOR)
    envelopes = _capture_emits(monkeypatch)
    monkeypatch.setattr(
        work_orders_router.wo_service,
        "restore_work_order",
        lambda db, incoming_id, *, user: saved,
    )
    monkeypatch.setattr(
        work_orders_router.wo_service,
        "get_work_order",
        lambda db, incoming_id, *, user: saved,
    )
    _passthrough_detail(monkeypatch)

    work_orders_router.restore_work_order(work_order_id, user=user, db=None)

    assert [e["type"] for e in envelopes] == [
        realtime_policy.EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED,
        realtime_policy.EVENT_WORK_ORDER_STATUS_CHANGED,
    ]
    assert envelopes[1]["id"] is None


def test_archive_emits_an_entity_style_status_invalidation(monkeypatch):
    """Archive is surgical, not collection: the card IS on screen, so the client
    refetches it, gets a 404 from the scoping, and drops that one row."""
    work_order_id = uuid.uuid4()
    user = SimpleNamespace(role=roles.ROLE_ADMIN)
    envelopes = _capture_emits(monkeypatch)
    monkeypatch.setattr(
        work_orders_router.wo_service,
        "archive_work_order",
        lambda db, incoming_id, *, user: None,
    )

    work_orders_router.archive_work_order(work_order_id, user=user, db=None)

    assert envelopes[1] == {
        "type": realtime_policy.EVENT_WORK_ORDER_STATUS_CHANGED,
        "id": str(work_order_id),
        "req": REQUEST_ID,
    }


def test_the_status_emitter_set_is_exactly_the_seven_capable_routes():
    """Mirrors the review-queue emitter-set test. Any future route able to change
    a work order's status or its card summary must join this set deliberately."""
    emitters = {
        route.endpoint.__name__
        for route in work_orders_router.router.routes
        if route.endpoint.__module__ == work_orders_router.__name__
        and "_emit_status_changed(" in inspect.getsource(route.endpoint)
    }

    assert emitters == {
        "start_work_order",
        "complete_work_order",
        "hold_work_order",
        "resume_work_order",
        "update_work_order",
        "archive_work_order",
        "restore_work_order",
    }
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && ./venv/Scripts/python.exe -m pytest tests/test_realtime_emit.py -q
```

Expected: FAIL — the three new tests fail (only one envelope is emitted, and the emitter set has four members).

- [ ] **Step 3: Add the three emit calls**

`update_work_order` — after the existing emit at `:537`:

```python
        _emit_review_queue_changed(work_order.id)
        _emit_status_changed(work_order.id)
```

`archive_work_order` — after the existing emit at `:641`:

```python
        wo_service.archive_work_order(db, work_order_id, user=user)
        _emit_review_queue_changed(work_order_id)
        _emit_status_changed(work_order_id)
```

`restore_work_order` — after the existing emit at `:662`, note the `None`:

```python
        work_order = wo_service.restore_work_order(db, work_order_id, user=user)
        _emit_review_queue_changed(work_order.id)
        _emit_status_changed(None)
```

- [ ] **Step 4: Update the three existing tests whose subject changed**

In `test_update_emits_after_the_command_and_before_response_hydration`, replace
the two assertions at `:96-103`:

```python
    assert order == ["command", "emit", "emit", "hydrate"]
    assert envelopes == [
        {
            "type": realtime_policy.EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED,
            "id": str(work_order_id),
            "req": REQUEST_ID,
        },
        {
            "type": realtime_policy.EVENT_WORK_ORDER_STATUS_CHANGED,
            "id": str(work_order_id),
            "req": REQUEST_ID,
        },
    ]
```

In `test_archive_emits_one_entity_invalidation`, replace the assertion at `:119-125`:

```python
    assert result is None
    assert envelopes == [
        {
            "type": realtime_policy.EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED,
            "id": str(work_order_id),
            "req": REQUEST_ID,
        },
        {
            "type": realtime_policy.EVENT_WORK_ORDER_STATUS_CHANGED,
            "id": str(work_order_id),
            "req": REQUEST_ID,
        },
    ]
```

In `test_a_dropped_invalidation_never_changes_the_http_result`, replace `:240`:

```python
    assert len(envelopes) == 2
```

Leave `test_restore_emits_even_when_the_successful_command_is_a_noop` alone. Its
`envelopes[0]["id"]` assertion still holds because the review-queue emit stays
first — that is the ordering constraint this plan pins.

- [ ] **Step 5: Run the full realtime suite**

```bash
cd backend && ./venv/Scripts/python.exe -m pytest tests/test_realtime_domain.py tests/test_realtime_emit.py tests/test_realtime_registry.py tests/test_realtime_limits.py tests/test_realtime_endpoint.py tests/test_realtime_dependency.py tests/test_realtime_session_binding.py -q
```

Expected: all PASS. In particular `test_the_review_queue_emitter_set_is_exactly_the_five_capable_routes` must still pass unmodified — archive and restore keep their `_emit_review_queue_changed(` call.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/work_orders.py backend/tests/test_realtime_emit.py
git commit -m "Emit status invalidations from update, archive and restore"
```

---

### Task 4: Extract the card summary builder

Pure refactor, no behavior change. Isolated so the next task's diff is only new
behavior.

**Files:**
- Modify: `backend/static/views/workOrders.js:831-860`

**Interfaces:**
- Consumes: nothing
- Produces: `summaryHtml(card)` — takes a `WorkOrderCard`-shaped object (or a `WorkOrderDetail`, which is a superset) and returns the inner HTML string for a card's `<summary>`.

- [ ] **Step 1: Add the helper above `buildCard`**

```js
// The summary line of a work-order card. Shared by the initial render and the
// real-time single-card update, so the two projections cannot drift. Accepts a
// WorkOrderDetail as well: the schema subclasses WorkOrderCard, so a detail
// response carries every field this reads.
function summaryHtml(card) {
  const place = placeMeta(card);
  const technicianNames = assignedNames(card);
  const assignee = technicianNames.length
    ? ` · ${escapeHtml(technicianNames.join(", "))}`
    : "";
  const legacyTag = card.legacy ? `<span class="wo-legacy-tag">Legacy</span>` : "";
  return (
    `<span class="wo-title">WO ${escapeHtml(card.number)}</span>` +
    statusBadge(card.status) +
    legacyTag +
    `<span class="wo-meta">${place ? escapeHtml(place) + " · " : ""}${card.item_count} items${assignee}</span>`
  );
}
```

- [ ] **Step 2: Use it in `buildCard`**

Replace lines `:836-848` — the `const summary` block through the `summary.innerHTML = ...` assignment — with:

```js
  const summary = document.createElement("summary");
  summary.className = "wo-summary";
  summary.innerHTML = summaryHtml(card);
```

The `place`, `technicianNames`, `assignee` and `legacyTag` locals move into
`summaryHtml` and must not be left behind in `buildCard`; nothing else in
`buildCard` reads them.

- [ ] **Step 3: Verify no behavior change**

```bash
cd backend && ./venv/Scripts/python.exe -m pytest tests/test_realtime_domain.py tests/test_realtime_emit.py -q
```

Expected: PASS (unaffected — this confirms nothing was broken structurally).

Then read the diff and confirm the produced HTML string is byte-identical to
what `buildCard` built before: same order, same separators, same escaping.

- [ ] **Step 4: Commit**

```bash
git add backend/static/views/workOrders.js
git commit -m "Extract the work-order card summary builder"
```

---

### Task 5: Subscribe and update one card in place

**Files:**
- Modify: `backend/static/views/workOrders.js` (imports, plus new code near the bottom)

**Interfaces:**
- Consumes: `summaryHtml(card)` from Task 4; `subscribe` from `../realtime.js`; `apiGetWorkOrder` from `../api.js`
- Produces: `refreshCardSummary(cardEl) -> Promise<void>`; the module-level constant `STATUS_CHANGED_EVENT`

- [ ] **Step 1: Add the imports**

`apiGetWorkOrder` is already imported by this module (it is used by `openDetail`).
Add only the realtime import, beside the other `../` imports near the top:

```js
import { subscribe } from "../realtime.js";
```

- [ ] **Step 2: Add the constants**

Beside the other module-level constants:

```js
const STATUS_CHANGED_EVENT = "work_order.status.changed";
const WORK_ORDERS_PAGE = "work-orders";
```

The page name must match the key used in `nav.js` (`"work-orders"`,
`static/views/nav.js:67`).

- [ ] **Step 3: Add the single-card refresh**

```js
// One work order changed. Rewrite just that card's summary and status class --
// the body, and any editor open inside it, is deliberately left untouched.
//
// A 404 means the work order left this user's view: archived, or unassigned
// from them. Either way the row goes. Only 404 removes a card; a network blip
// rejects without a `status` field and must leave the list alone.
async function refreshCardSummary(cardEl) {
  let detail;
  try {
    detail = await apiGetWorkOrder(cardEl.dataset.id);
  } catch (err) {
    if (err?.status !== 404) return;
    cardEl.remove();
    if (!listEl.querySelector("details.wo-card")) {
      listEl.innerHTML = `<p class="hint">No work orders match.</p>`;
    }
    return;
  }
  const summary = cardEl.querySelector("summary.wo-summary");
  if (summary) summary.innerHTML = summaryHtml(detail);
  cardEl.className = `wo-card wo-card-status-${detail.status}`;
}
```

`cardEl.className` is reassigned wholesale because `buildCard` sets it the same
way (`:833`); the status suffix is the only part that varies.

- [ ] **Step 4: Subscribe**

At the bottom of the module, beside the other top-level listener registrations:

```js
// Status invalidations for the card list. Like Admin Review, this refreshes only
// while its own page is active -- an inactive page needs no dirty flag because
// nav.js already performs a fresh REST load on entry (static/views/nav.js:154).
//
// An event for a work order that is not on screen is ignored. Chasing it with a
// list refetch would mean every technician's client reloading the whole list
// every time anyone changed a status anywhere. A work order newly *appearing*
// for someone is a membership change, which arrives as a null id instead.
subscribe(STATUS_CHANGED_EVENT, ({ activePage, envelope }) => {
  if (activePage !== WORK_ORDERS_PAGE) return;
  if (!listEl || !envelope?.id) return;

  const cardEl = listEl.querySelector(`details.wo-card[data-id="${envelope.id}"]`);
  if (!cardEl) return;
  return refreshCardSummary(cardEl);
});
```

Collection events (`envelope.id === null`) and reconnect are handled in Task 7;
the `!envelope?.id` guard makes them a no-op until then.

- [ ] **Step 5: Manual verification**

Start the app locally (port 8124 per the project runbook) and sign in as two
different users in two browsers — one Supervisor, one Technician assigned to a
work order. Hard-refresh both to defeat the static-asset cache.

1. Both on the Work Orders page, technician's card visible in the supervisor's list.
2. Technician clicks **Set In-Progress**.
3. Supervisor's card badge flips to In-Progress **without the page reloading**, with scroll position unchanged and any other expanded card still expanded.
4. Technician clicks **Mark Completed**; supervisor's badge flips again.
5. Supervisor navigates to another page and back; the list still loads normally.

- [ ] **Step 6: Commit**

```bash
git add backend/static/views/workOrders.js
git commit -m "Update a work-order card in place on a status event"
```

---

### Task 6: Freeze cards that are being edited

**Files:**
- Modify: `backend/static/views/workOrders.js`

**Interfaces:**
- Consumes: `refreshCardSummary` from Task 5
- Produces: `isHeld(cardEl) -> boolean`, `anyCardHeld() -> boolean`, and the `data-missed-update` card attribute

- [ ] **Step 1: Add the hold predicates**

```js
// The four editor sections inside a card body. A card holding any of them open
// is "held": nothing refreshes it, because rewriting it would discard an unsaved
// note, a material quantity, labor hours, or a technician selection in progress.
// The technician combobox needs no entry -- it renders inside `.wo-edit-card`.
const EDITOR_SECTIONS =
  ".wo-edit-card, .wo-notes-section, .wo-materials-section, .wo-labor-section";

function isHeld(cardEl) {
  return Array.from(cardEl.querySelectorAll(EDITOR_SECTIONS)).some((s) => s.open);
}

function anyCardHeld() {
  if (!listEl) return false;
  return Array.from(listEl.querySelectorAll("details.wo-card")).some(isHeld);
}
```

- [ ] **Step 2: Skip held cards in the subscriber**

In the `subscribe(STATUS_CHANGED_EVENT, ...)` handler from Task 5, replace
everything from `const cardEl = ...` to the closing `});` with:

```js
  const cardEl = listEl.querySelector(`details.wo-card[data-id="${envelope.id}"]`);
  if (!cardEl) return;
  if (isHeld(cardEl)) {
    // Catch up when the editor closes rather than yanking input away mid-edit.
    cardEl.dataset.missedUpdate = "1";
    return;
  }
  return refreshCardSummary(cardEl);
```

- [ ] **Step 3: Catch up when the last editor closes**

```js
// `toggle` does not bubble, so this listens in the capture phase -- a delegated
// bubble-phase listener here would silently never fire.
if (listEl) {
  listEl.addEventListener(
    "toggle",
    () => {
      const cards = Array.from(listEl.querySelectorAll("details.wo-card"));
      for (const cardEl of cards) {
        if (cardEl.dataset.missedUpdate !== "1" || isHeld(cardEl)) continue;
        delete cardEl.dataset.missedUpdate;
        void refreshCardSummary(cardEl);
      }
    },
    true
  );
}
```

- [ ] **Step 4: Manual verification**

With the same two-browser setup:

1. Supervisor expands a card and opens its **Edit details** section; types into the description field but does not save.
2. Technician changes that work order's status.
3. Supervisor's card does **not** change — badge and body both still show the old status, and the typed text is still there.
4. Supervisor closes the Edit details section without saving.
5. The badge now updates to the technician's new status.
6. Repeat with the notes textarea, the materials section, and the labor section — each must hold the card the same way.

- [ ] **Step 5: Commit**

```bash
git add backend/static/views/workOrders.js
git commit -m "Freeze work-order cards while their editors are open"
```

---

### Task 7: Handle collection events and reconnect

**Files:**
- Modify: `backend/static/views/workOrders.js`

**Interfaces:**
- Consumes: `anyCardHeld` from Task 6, `loadWorkOrders` (existing, `:711`)
- Produces: `deferredListRefresh` module state; `runOrDeferListRefresh()`

- [ ] **Step 1: Add the deferred refresh**

```js
// A full list refetch rebuilds every card (renderCards clears the list), so it
// must never run while an editor is open. Restore and reconnect are both rare,
// so deferring until the last hold clears costs nothing.
let deferredListRefresh = false;

function runOrDeferListRefresh() {
  if (anyCardHeld()) {
    deferredListRefresh = true;
    return;
  }
  deferredListRefresh = false;
  void loadWorkOrders();
}
```

- [ ] **Step 2: Handle null-id events and reconnect in the subscriber**

Replace the `if (!listEl || !envelope?.id) return;` guard from Task 5 with:

```js
  if (!listEl) return;

  // A null id is a membership command (restore) and a reconnect means events
  // were missed while the socket was down. Both mean "the list itself may be
  // wrong", which only a refetch can settle -- deciding locally would duplicate
  // the server's ordering, row cap and filter semantics.
  if (reason === "reconnect" || !envelope?.id) {
    runOrDeferListRefresh();
    return;
  }
```

and add `reason` to the handler's destructured parameter:

```js
subscribe(STATUS_CHANGED_EVENT, ({ activePage, envelope, reason }) => {
```

- [ ] **Step 3: Drain the deferred refresh when the last hold clears**

In the capture-phase `toggle` listener from Task 6, add before the per-card loop:

```js
      if (deferredListRefresh && !anyCardHeld()) {
        deferredListRefresh = false;
        void loadWorkOrders();
        return;
      }
```

A full refetch supersedes any per-card catch-up, so returning early is correct —
`renderCards` rebuilds every card from fresh server data.

- [ ] **Step 4: Manual verification**

1. **Restore:** Admin archives a work order (supervisor's row disappears from the list). Admin then restores it from History. The supervisor's list shows the row again without navigating.
2. **Deferred restore:** Supervisor opens a card's notes editor and types. Admin restores a different work order. Nothing moves. Supervisor closes the notes section — the list refreshes and the restored row appears.
3. **Reconnect:** With the Work Orders page open, stop the backend, wait for the socket to drop, change a status via another session, restart the backend. Within the reconnect backoff window the supervisor's list catches up on its own.
4. **Archive:** Admin archives a work order visible in the supervisor's list; that single row disappears and the rest of the list, including expanded cards, is undisturbed.

- [ ] **Step 5: Commit**

```bash
git add backend/static/views/workOrders.js
git commit -m "Refetch the work-order list on membership events and reconnect"
```

---

### Task 8: Update the project documentation

**Files:**
- Modify: `docs/current-state.md:384-392`

**Interfaces:**
- Consumes: the finished behavior from Tasks 1-7
- Produces: nothing

- [ ] **Step 1: Read the current realtime section**

Read `docs/current-state.md` around lines 375-395. Two statements are now false:
"Only explicitly subscribed, UX-6-reviewed views may refresh" is still true, but
"Admin Review subscribes to the queue event" is no longer the whole story.

- [ ] **Step 2: Update it**

Amend the section so it records:

- Two event types now exist: `work_order.review_queue.changed` (TechFM OA+, consumed by Admin Review) and `work_order.status.changed` (technician+, consumed by Work Orders).
- The status event's seven emitters, and that restore emits `id: null` as a membership signal while archive emits an entity id.
- Work Orders updates one card in place on an entity event, ignores events for work orders not on screen, and refetches the list on a null id or a reconnect.
- Cards with an open editor section are held: no refresh touches them, and a full list refetch is deferred until the last one closes.
- The audience map is a noise rule, not a security boundary — `can_view_work_order` on the re-fetch is what scopes delivery.

Keep the existing tone: statements of fact about current behavior, no roadmap.

- [ ] **Step 3: Verify the docs mirror**

The `docs/` → Obsidian vault mirror is automated; do not hand-copy the file into
the vault. Confirm only that `docs/current-state.md` itself is correct.

- [ ] **Step 4: Commit**

```bash
git add docs/current-state.md
git commit -m "Document the Work Orders live status integration"
```

---

## Final verification

- [ ] Full backend suite passes:

```bash
cd backend && ./venv/Scripts/python.exe -m pytest -q
```

Note: database-backed tests skip without a reachable Postgres. Per the project
runbook the local instance listens on **port 8801**, not 5432, and `DATABASE_URL`
is not set by default — export it before this run or the DB tests will skip
rather than fail, which is easy to mistake for a pass.

- [ ] All four manual scenarios from Tasks 5-7 re-run once end to end.
- [ ] `git log --oneline` shows eight focused commits.
- [ ] Nothing under `app/services/realtime.py`, `app/routers/realtime.py`, `static/realtime.js` or `views/adminReview.js` appears in `git diff main --stat`.
