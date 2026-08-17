# Work Orders live status — design

Date: 2026-08-16
Status: approved, ready for implementation planning

## Problem

The real-time layer shipped on 2026-08-12 with exactly one event type,
`work_order.review_queue.changed` (`domain/realtime.py:55`), and exactly one
consumer, Admin Review (`static/views/adminReview.js:204`). The Work Orders page
was never wired to it: `static/views/workOrders.js` does not import
`static/realtime.js` at all.

Work Orders is the most trafficked surface in the app. It is available to every
role (`static/views/nav.js:67`) and is the Supervisor landing page
(`static/views/nav.js:91`). Its card summaries render status as both a badge and
a CSS class (`workOrders.js:846`, `:833`), yet the four routes that change status
in the field — `start_work_order` (`routers/work_orders.py:550`),
`complete_work_order` (`:571`), `hold_work_order` (`:594`) and
`resume_work_order` (`:611`) — emit nothing.

The result: a technician marks a job complete, and their supervisor's list keeps
saying In-Progress until they navigate away and back.

## Goal

All users see status changes in real time, scoped to their existing role
permissions.

Deliberately narrow. This is not a general work-order aggregate event: materials,
labor, billing and price changes are out of scope, exactly as the original design
excluded them (`domain/realtime.py:50-54`).

## Scope — what counts as a status change

| Route | `entity_id` | Client effect |
| --- | --- | --- |
| `start` / `complete` / `hold` / `resume` | work order id | badge updates in place |
| `update_work_order` (PATCH) | work order id | badge + assignee update in place |
| `archive_work_order` | work order id | refetch 404s → row removed |
| `restore_work_order` | `None` | list refetch → row appears |

`update_work_order` emits unconditionally rather than testing whether status
actually changed. The layer already accepts that "a successful no-op can cause a
harmless extra refetch"; the cost here is one card, and it makes assignee edits
live for free.

**Restore is the one collection-style emitter.** An archived work order is not on
anyone's screen, so a surgical "update that card" has nothing to update. `None`
already means a collection command in this codebase — CSV import
(`routers/work_orders.py:359`) and bulk legacy archive (`:485`) both use it — so
restore follows established precedent rather than inventing a mechanism. Restore
is a rare explicit recovery action, so the full refetch costs nothing in practice.

Archive stays surgical because the card *is* on screen; removing one row
preserves scroll position and every other expanded card.

## Design

### 1. The event (`backend/app/domain/realtime.py`)

```python
EVENT_WORK_ORDER_STATUS_CHANGED = "work_order.status.changed"

_AUDIENCE_MIN_ROLE = {
    EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED: roles.ROLE_TECHFM_OA,
    EVENT_WORK_ORDER_STATUS_CHANGED: roles.ROLE_TECHNICIAN,
}
```

Plus the constant in `__all__`. Nothing else in this module changes:
`build_envelope` (`:129`) and `audience_allows` (`:171`) are already generic over
event type, and the `type` discriminator exists precisely so a second event is
additive rather than a wire-format change.

### 2. Audience, and why permissions need no new code

The audience floor is `ROLE_TECHNICIAN` — everyone who can open the page.

This is **not** the permission boundary and must not be mistaken for one. Under
P2 the envelope carries no row data, only `{type, id, req}`, so a mis-scoped
audience is a wasted frame rather than a disclosure. Authorization is enforced
where it already lives: on the re-fetch.

`can_view_work_order` (`domain/work_orders.py:457`) is the single visibility rule
and is already applied by both paths this design uses —
`GET /work-orders/` via `list_work_orders` (`routers/work_orders.py:260`) and
`GET /work-orders/{id}`, both through `_visible` (`services/work_orders.py:347`):

- TechFM OA / Admin / Owner see everything.
- A Supervisor sees unrouted work orders, ones routed to them, and ones they are
  assigned to work.
- A Technician sees only work orders assigned to them.

So this design writes **zero new authorization code**, and role scoping cannot
drift from the REST behaviour because it *is* the REST behaviour.

One consequence worth stating plainly: if a card is on your screen it was visible
to you, so a refetch returning 404 unambiguously means it just left your view —
archived, or unassigned from you. Removing the row is correct in both cases.

### 3. Emitters (`backend/app/routers/work_orders.py`)

A second helper beside `_emit_review_queue_changed` (`:74`):

```python
def _emit_status_changed(entity_id: Optional[uuid.UUID]) -> None:
```

Called from the seven routes in the scope table. `archive_work_order` (`:633`)
and `restore_work_order` (`:651`) gain it *in addition to* their existing
review-queue emit; they keep both because both surfaces care.

Delivery stays best-effort: `emit` is total and its boolean result is ignored, so
a full handoff can never fail a durable write.

### 4. Client subscription (`backend/static/views/workOrders.js`)

Import `subscribe` from `../realtime.js` and register one handler, following the
Admin Review precedent (`adminReview.js:204`) including its `activePage` guard:

| Notification | Action |
| --- | --- |
| `envelope.id` set, card on screen, not held | refetch that work order, rewrite its summary |
| `envelope.id` set, card not on screen | **ignore** |
| `envelope.id` null | full list refetch |
| `reason: "reconnect"` | full list refetch (catch-up) |

Ignoring unknown ids is load-bearing. Without it, every technician's client would
refetch the whole list every time anyone anywhere changed a status — the exact
cost this design exists to avoid. A work order newly *appearing* for you is a
membership change, not a status change; page entry already handles it
(`nav.js:154`).

**No new endpoint is required.** `WorkOrderDetail` subclasses `WorkOrderCard`
(`schemas/work_orders.py:302`) and `_detail` spreads `_card(...)` into itself
(`routers/work_orders.py:222`), so the existing `apiGetWorkOrder`
(`static/api.js:479`) already returns every field a card summary renders.

**One small extraction.** `buildCard` (`workOrders.js:831`) builds the summary
inline at `:844-848`. Lift that into a `summaryHtml(card)` helper used by both
`buildCard` and the new surgical update, so the two cannot drift. `renderCards`
(`:788`) is otherwise untouched and keeps serving page entry, filter changes and
Show all.

`renderMoreControl` (`:804`) is deliberately **not** re-run after a surgical
removal. It offers "Show all" when a capped browse came back full
(`shownCount >= RECENT_LIMIT`); removing one row drops the count below the cap
and would hide the control even though more work orders still exist beyond it.
Leaving it alone is the accurate behaviour, and it self-corrects on the next
full load.

### 5. The hold rule

A card is **held** while any of its four editor `<details>` sections is open:

| Selector | Content at risk |
| --- | --- |
| `.wo-edit-card` (`:636`) | field inputs, status select, supervisor select, description, and the technician picker (`technicianPickerHtml`, rendered inside it at `:648`) |
| `.wo-notes-section` (`:948`) | unsaved note textarea |
| `.wo-materials-section` (`:959`) | item search, quantity inputs |
| `.wo-labor-section` (`:332`) | hours inputs, technician select |

Four selectors, not five: the technician combobox (`.wo-tech-search`, `:432`) has
no `<details>` of its own and is covered by `.wo-edit-card`.

No refresh touches a held card. Its summary and body therefore stay mutually
consistent — the alternative is a badge reading "Completed" above a body still
offering a Mark Completed button.

A held card that misses an update carries a flag (a `data-` attribute on the card
element) and refreshes as soon as the last editor closes.

A **full list refetch is deferred entirely while any card is held**, because
`renderCards` clears `listEl.innerHTML` and would destroy the open editor. The
deferred refetch runs when the last hold clears.

This is what contains the vanishing-row behaviour: rows disappear only from a
list you are browsing, never from a card you are working in. If someone archives
the work order you are editing, you finish your thought and the save fails
loudly against the existing `WorkOrderStateError` / `WorkOrderAssignmentConflictError`
(`domain/errors.py:302`, `:285`), and only then does the row clear.

### 6. Silence

List-level messaging is already error-only — `setMessage(listMessage, ...)` is
cleared on success (`:766`) and set only on failure (`:784`) — so a background
refresh produces no "Loading…" copy at the list level. Socket-driven refreshes
must stay silent, per the Admin Review precedent.

## What does not change

- `backend/app/services/realtime.py` — transport, registry, handoff, dispatch
- `backend/app/routers/realtime.py` — the `/ws` endpoint
- `backend/static/realtime.js` — socket, reconnect, routing
- `backend/static/views/adminReview.js` — the existing consumer
- The review-queue event, its audience, and its five emitters

## Testing

### Stays green without edits

- `test_realtime_emit.py:243` derives the emitter set by grepping route source
  for the literal `_emit_review_queue_changed(`. `archive_work_order` and
  `restore_work_order` keep that call while gaining a second one, so the set is
  unchanged; the four walkthrough routes gain only `_emit_status_changed(` and do
  not join it.
- `test_realtime_domain.py:99` asserts against the review-queue constant only and
  is unaffected by a new constant with its own audience entry.

### Must be updated

`update_work_order` and `archive_work_order` now emit **two** envelopes each, and
three existing tests assert exact envelope lists:

| Test | Current assertion | Becomes |
| --- | --- | --- |
| `test_realtime_emit.py:63` | `order == ["command", "emit", "hydrate"]` and a one-item `envelopes` list | `["command", "emit", "emit", "hydrate"]`, two envelopes |
| `test_realtime_emit.py:106` | `envelopes == [<review-queue>]` | both envelopes |
| `test_realtime_emit.py:215` | `len(envelopes) == 1` | `== 2` |

These are correct tests whose subject genuinely changed; updating them is the
honest outcome, not a workaround.

**Emit order is pinned: review-queue first, status second.** This is not
cosmetic. `test_realtime_emit.py:148` asserts `envelopes[0]["id"] == str(work_order_id)`
for `restore_work_order`, and restore's status envelope carries `id: None` — so
emitting status first would break that test and, more importantly, would make
envelope order an accident rather than a decision. Every route that emits both
does so in this order, and the updated assertions above lock it in.

New tests, additive:

- Audience: the status event reaches technician, supervisor, techfm_oa, admin and
  owner; unknown types still reach nobody.
- Emitter set: exactly the seven capable routes carry `_emit_status_changed(`.
- `restore_work_order` emits a collection-style invalidation (`id is None`) while
  `archive_work_order` emits an entity one.
- A command failure emits nothing; a dropped invalidation never changes the HTTP
  result. (Mirrors the existing review-queue coverage.)

**The frontend half has no automated coverage.** There is no `package.json` and
no JS test runner in this repository; all seven realtime test files are Python.
The subscriber, the hold rule, the surgical update and the deferred catch-up are
manual-validation only. This is a known gap, not an oversight.

## Non-goals

- No general work-order aggregate event. Materials, labor, billing and price
  stay out of the vocabulary.
- No optimistic UI. Clients render server truth only.
- No socket status indicator, connection UI, or "N items updated" toast.
- No live refresh of an open card *body*. Only the summary updates, and only
  when the card is not held.
- No client-side replication of server filter semantics. When the changed work
  order's list membership is in question, the server is asked.
- Horizontal scaling remains out of scope (N3 in `docs/open-work.md`): the
  connection registry is in-process, and a second instance would silently halve
  delivery.

## Accepted costs

1. **Wasted frames.** A technician receives status events for work orders they
   cannot see and ignores them. By design — P2 makes this noise, not disclosure.
2. **A held card is stale.** Deliberate: consistency and unsaved input beat
   freshness while someone is typing. Nothing tells the user the work order
   changed underneath them; if manual validation shows this surprises people, a
   marker on the card is the follow-up, not a redesign.
3. **Restore triggers a full refetch for every connected client.** Rare enough to
   be irrelevant, and the alternative duplicates server ordering, the
   `RECENT_LIMIT` cap and filter semantics on the client.
4. **A row can vanish mid-browse** when someone archives it. Accepted explicitly;
   the hold rule confines it to lists being browsed rather than cards being
   edited.

## Files touched

| File | Change |
| --- | --- |
| `backend/app/domain/realtime.py` | event constant, `__all__`, audience entry |
| `backend/app/routers/work_orders.py` | `_emit_status_changed` + seven call sites |
| `backend/static/views/workOrders.js` | subscribe, surgical update, hold rule, deferred catch-up, `summaryHtml` extraction |
| `backend/tests/test_realtime_domain.py` | new audience tests (additive) |
| `backend/tests/test_realtime_emit.py` | new emitter-set + entity/collection tests, **plus three existing tests updated** for the second envelope |
| `docs/current-state.md` | realtime section: second event, second consumer |
