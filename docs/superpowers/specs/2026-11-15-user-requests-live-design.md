# User Requests page live (W5): design

Date: 2026-11-15. Status: approved by the owner 2026-11-15 (all author's calls accepted); plan: `docs/superpowers/plans/2026-11-15-user-requests-live.md`. Scope: the User Requests page (`views/userRequests.js`, `views/userRequestCards.js`) and the server writes that should announce a request change. Builds on W1/W2 (`2026-11-14-work-order-live-rendering-design.md`).

## Intent

The Requests page already reloads on every `user_request.changed` event, but
it reloads by wiping the list (`listEl.replaceChildren()`). An Admin halfway
through fulfilling a catalogue request, typing a recount, or entering a price
loses the open form, the typed values and their place on the page whenever
anyone anywhere files, stocks or resolves a request. Some changes also never
arrive: several server writes send no event at all. W5 makes the page patch in
place like Work Orders and makes every request change reach it.

## Roadmap

| W | Scope |
|---|---|
| W1–W3 | Work Orders list, card body, save-time conflict check (built, unpushed) |
| W4 | Dropped 2026-11-15; requests from a work order are IMP-042 |
| **W5** | **User Requests page (this spec)** |
| W6 | Low Stock and SMR Admin Review |
| W7 | User Hub |

## Goals

- A live update changes only the cards that changed; new, changed and removed cards are inserted, patched and removed in place.
- An open panel (Fulfil, Edit, Close) and anything typed survive an update.
- Every create, stock, resolve and reopen of a request reaches the page.
- A changed card glows once, as on Work Orders.

## Non-goals

- A save-time conflict check like W3. Request actions are state transitions the server already validates; two Admins resolving the same request is harmless.
- The User Hub's request tile (W7) and the work-order card (IMP-042).
- Presence or "Maria is fulfilling this".
- New request types, filters or layout changes.

## Anti-goals

- A second rendering path for "live" versus "after my own save".
- Event coverage that depends on each route remembering to emit.
- Dropping typed input silently.

## Constraints

| Constraint | Source |
|---|---|
| No inline style or script | CSP `default-src 'self'` |
| One patch helper, `morph.js` (`skip`, `flashSelector`) | W1/W2 |
| REST is the truth; socket frames are invalidations | `realtime.js` header |
| Events carry an id only, no row data | `domain/realtime.py` (P2) |
| Files under 500 lines (`userRequests.js` is 507, `userRequestCards.js` 455) | repo rule |
| Readable on a phone, no legend, no sideways scroll | owner design rules |

## Findings (code read 2026-11-15)

| Finding | Consequence |
|---|---|
| `render()` wipes and rebuilds every card | Patch with `morphInto` instead |
| Cards have no id | Patcher cannot pair them across a reorder; give each card `ureq-card-<id>` |
| Panels are client-only: the builder always emits an empty `.user-request-panel` | A patch would empty an open panel; skip a non-empty panel |
| Missing-price inputs are prefilled by setting `.value` after build | Their default is `""`, so a prefilled price looks typed; emit the price as a `value` attribute instead |
| Each live event starts a fetch; responses can land out of order | Drop stale responses |
| `render()` overwrites the message line with the count, wiping an action's error | Live updates leave an action message alone |
| No event from: catalogue request filed; recount filed (dispense, work order); missing-price filed or updated; missing-price resolved by an item price edit; recount resolved by a correction; request resolved by a transaction | Emit from one place (rule 9) |

## Design

### Rules

1. **One path.** `render()` builds the cards into a detached container, then `morphInto(listEl, nodes, { skip, flashSelector: ".user-request-card", flashKey: text })`. First draw, tab or status change, Refresh, own save and live event all use it. A first draw flags nothing (`morph.js` already guarantees this).
2. **Ids.** `buildRequestCard` sets `id="ureq-card-<id>"`. Every element a rule can keep has a unique id or sits inside a kept element; a census test holds the builders to it.
3. **Open panel is kept whole.** `skip` returns true for a `.user-request-panel` that has children. The card around it still updates (status, details, actions).
4. **Typed fields are kept.** `skip` returns true for the focused field and for any field whose value differs from its default (`isDirty`, moved from `workOrderLiveBody.js` into `morph.js` so both pages share it). Inline count, reason, price and link inputs are the cases.
5. **Prefill by attribute.** The missing-price price and link render as `value="…"`, so the default is the server value and only a real edit counts as typed.
6. **Own saves close their own panel.** An action that succeeds empties its card's panel, then reloads through rule 1. Other cards' panels and typing are untouched. A tab or status change empties every panel first, since it is a new list.
7. **A card the server removed is removed**, even with a panel open or a field typed (W2 rule 5). If that discarded a panel or typed value, the message line says: "A request you were working on was closed or moved by someone else." Never silent.
8. **Ordering.** Each load takes a sequence number; a response older than the newest load already applied is dropped. A response for a tab or status no longer selected is dropped.
9. **Events from one place.** A SQLAlchemy listener (beside `field_stamps.py`) collects the id of every `UserRequest` inserted or changed in a flush; after commit, each id is emitted as `user_request.changed`. The per-route `emit_user_request_changed` calls are removed so nothing is sent twice. This covers every writer in the findings table and any future one.
10. **Message line.** A live update rewrites the count line only while the line is showing a count. An action's error or success message stays until the next user action.
11. **Reading position.** Focus and caret are restored after a patch (iOS Safari loses them on a move); where `overflow-anchor` is unsupported, the first visible card's position is restored. Same code as W2's `patchBodyLive`, moved into a shared helper.
12. **Highlight.** A new or changed card gets `just-changed` (existing CSS, `prefers-reduced-motion` respected). The Admin Review focus highlight (`highlightItemCard`) is unchanged.
13. **Tab counts** keep refreshing on every load, as now.

### What the user sees

```
Fulfil panel open on "3/4 PEX elbow", someone files a new request:

  ▸ 1/2 ball valve        (new, glows 1 s)
  ▾ 3/4 PEX elbow         Fulfil panel still open, search text kept
  ▸ Wax ring
```

### Line budget

`userRequests.js` is already 507 lines. The load/render/ordering code moves to a new `userRequestsLive.js` (or the panel and action handlers move out), so both files end under 500. Which split is the builder's call.

## Practice checks

| Rule | Practice | Source |
|---|---|---|
| Stable ids on kept elements | "Give important elements ids so they survive morphs" | [htmx morphing guide](https://four.htmx.org/docs/morphing-swaps-guide) |
| Focused/typed field wins | LiveView keeps a focused input over a server patch | [Elixir Forum](https://elixirforum.com/t/liveview-input-forms-are-not-controlled-by-the-server-state-when-input-is-in-focus/41342) |
| Drop stale responses | "Ignore stale responses" | [react.dev](https://react.dev/learn/you-might-not-need-an-effect) |
| Emit after commit, from the data layer | Session `after_commit` fires only once the write is durable | [SQLAlchemy session events](https://docs.sqlalchemy.org/en/20/orm/events.html#sqlalchemy.orm.SessionEvents.after_commit) |
| Status message announced | `role="status"` present before text | [WCAG 4.1.3](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html) |

## Risks

| # | Hazard | Handling |
|---|---|---|
| 1 | Open panel emptied by a patch | Rule 3; test a live update with each panel type open |
| 2 | Prefilled price treated as typed, so it never updates | Rule 5; test someone else's price edit lands in an untouched card |
| 3 | Card paired with the wrong neighbour after a reorder | Rule 2 ids; census test |
| 4 | Out-of-order responses repaint an old list | Rule 8; test two loads resolving in reverse |
| 5 | Action error wiped by a live count | Rule 10; test |
| 6 | Event emitted for a rolled-back write | Rule 9 emits after commit only; collected ids cleared on rollback; test |
| 7 | Event sent twice (listener plus a leftover route call) | Remove route calls; backend test counts one envelope per write |
| 8 | Listener fires in scripts or tests with no event loop | Emit stays best-effort (as `emit_user_request_changed` is today); test a script-style write |
| 9 | Bulk writes (sibling fulfil, transaction voids) flood events | One envelope per request id per commit; tests: fulfil with three siblings sends three |
| 10 | Fulfil panel's sibling list goes stale | Unchanged: the server skips siblings that are no longer open and reports them (`result.skipped`) |
| 11 | Delegated handlers break on patched cards | Handlers are already delegated on `listEl`; test a button in a card inserted by a patch |
| 12 | iOS jump when a card is inserted above | Rule 11; owner's phone check |
| 13 | Hub tile and work-order card rely on the removed route calls | The listener emits the same event for the same writes, plus the missing ones; Hub test still passes |

## Testing

Frontend (Vitest, `importView`): each panel type survives a live update; typed count, price and link survive; a removed card with a panel open shows the rule 7 message; untouched prefilled price updates; stale response dropped; action error survives a live update; new and changed cards glow, unchanged do not; a button in a patched-in card works; own save closes only its panel; census: every card and kept element has an id.

Backend (`backend/tests`, real `TestClient`): one envelope per write for each writer in the findings table; none after a rollback; one per id for a three-sibling fulfil; existing `test_realtime_emit.py` cases still pass.

Owner's phone check with two logins: fulfil panel stays open while the other login files a request; typed price survives; the closed-by-someone-else message; the glow.

## Left to the builder

- How `userRequests.js` splits to get under 500 lines.
- Whether the shared focus/anchor code lives in `morph.js` or a sibling helper.
- The `docs/current-state.md` rows.

## Calls made by the author, not the owner

- No save-time conflict check on requests.
- Events move from route calls to one after-commit listener, adding the six missing writers.
- A removed card is removed even with a panel open; the message line says so.
- Own saves share the live path and close only their own panel.
- `isDirty` and W2's focus/anchor code move into a shared helper rather than being copied.
- W5 ships in its own push, after the W1–W3 push.
