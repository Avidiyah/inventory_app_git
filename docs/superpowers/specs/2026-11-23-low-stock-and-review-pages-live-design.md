# Low Stock, Admin Review and SMR Admin Review live (W6): design

Date: 2026-11-23. Status: owner asked for the plan 2026-11-23 (author's calls not individually confirmed); plan: `docs/superpowers/plans/2026-11-23-low-stock-and-review-pages-live.md`. Scope: `views/lowStock.js`, `views/lowStockCard.js`, `views/adminReview.js`, `views/smrAdminReview.js`, and the server writes that should announce a low item's change. Builds on W1/W2/W5 (`2026-11-14-work-order-live-rendering-design.md`, `2026-11-15-user-requests-live-design.md`).

## Intent

The owner wants the whole app to feel live. These three pages still redraw by wiping their lists, and two of them miss changes:

- Low Stock loses anything typed in an open card when anyone changes any low item, and its numbers go stale because the server only announces an item entering or leaving the list.
- Admin Review keeps showing an old receipt after the order changes.
- SMR Admin Review never updates on its own, so an Admin can print or paste a block that is already out of date.

W6 makes all three patch in place and makes the open receipt or block refresh itself.

## Roadmap

| W | Scope |
|---|---|
| W1–W3, W5 | Work Orders and User Requests (shipped) |
| W4 | Dropped; requests from a work order are IMP-042 |
| **W6** | **Low Stock, Admin Review, SMR Admin Review (this spec)** |
| W7 | User Hub |

## Owner decisions (2026-11-23)

- W6 covers Admin Review as well as the two pages first named.
- When the selected order changes, the open receipt or block refreshes itself with a one-line note (not "warn only").

## Goals

- A live update changes only the cards or tiles that changed; they are inserted, patched and removed in place, and a changed one glows once.
- On Low Stock, an open card, anything typed, an added or removed barcode row and a row's message survive an update.
- On Low Stock, the on-hand count, 7-day figure, name, location and price of a listed item update without a refresh.
- SMR Admin Review updates on its own.
- On both review pages, the open receipt or block always matches the server, and says when it changed.

## Non-goals

- A save-time conflict check on Low Stock edits (last save wins, as today).
- Admin Review reacting to an item price edit made elsewhere (no work-order event exists for it; the page reloads on entry, as today).
- The SMR page itself (`smr.js`) and the User Hub (W7).
- Layout, wording or filter changes beyond the notes named below.

## Anti-goals

- A second rendering path for "live" versus "after my own save".
- A receipt or block that can be copied or printed after it stopped matching the order.
- A live refresh that steals focus, selects text or opens a pop-up.
- Dropping typed input silently.

## Constraints

| Constraint | Source |
|---|---|
| No inline style or script | CSP |
| One patch helper: `morph.js` (`morphInto`, `isDirty`, `keepPlace`) | W1/W2/W5 |
| REST is the truth; events carry an id only | `realtime.js`, `domain/realtime.py` |
| Emitter sets are pinned by `test_realtime_emit.py` | W1 |
| Files under 500 lines (largest here: `adminReview.js`, 287) | repo rule |
| Readable on a phone, no legend, no sideways scroll | owner design rules |

## Findings (code read 2026-11-23)

| Finding | Consequence |
|---|---|
| All three lists redraw with `replaceChildren()` | Patch with `morphInto` |
| Cards and tiles carry `data-id` but no `id` | Give each an id so the patcher can pair them |
| Low Stock reopens open cards after a rebuild but loses typed values, added barcode rows and row messages | Skip rules (rule 3) |
| `item.low_stock.changed` is sent only when an item enters or leaves the list, on create and on archive | A dispense, restock, correction or edit of an item that stays low never reaches the page; widen the event (rule 8) |
| Low Stock already drops out-of-order responses (`loadSequence`) | Keep |
| A Low Stock save reloads in the background but leaves the saved fields looking typed (their defaults are the old values) | Own-save rule 4 |
| `smrAdminReview.js` has no `subscribe` | Add one |
| Every SMR and work-order write route already sends `work_order.status.changed` with the order id (set ready, paper reviewed, line add/edit/delete, generate block, mark pasted, archive, restore, status, materials, labor) | No new backend event for either review page |
| Admin Review listens only to `work_order.review_queue.changed`, which excludes material, labor and billing changes | Also listen to `work_order.status.changed` for the selected order |
| `renderReceipt` focuses and selects the text and opens the missing-price picker | A live refresh must do none of these (rule 6) |
| After Close, Reopen, Not ready or Archive, both pages leave the text on screen "for reference" | Same end state when someone else does it (rule 7) |

## Approaches

| Approach | Trade-off | Verdict |
|---|---|---|
| A. Patch in place with `morph.js`, one render path, events as invalidations | Same rules and helper as W1–W5; small diffs | **Chosen** (author's call; the owner left the how to the author) |
| B. Keep the wipe-and-rebuild, save and restore typed values around it | Less new code on Low Stock, but a second mechanism, loses focus and caret, no glow | Rejected: W5 anti-goal |
| C. Send row data in the event and patch from it | No refetch | Rejected: breaks "events carry an id only" |

## Design

### Rules

1. **One path.** Each page builds its cards into a detached container and calls `morphInto(listEl, nodes, { skip, flashSelector })` inside `keepPlace`. First draw, tab change, Refresh, own save and live event all use it.
2. **Ids.** `low-stock-card-<id>`, `review-card-<id>`, `smr-review-card-<id>`. A census test holds the builders to it.
3. **Low Stock: what a patch leaves alone.** `skip` returns true for: the focused field; any field that `isDirty`; a `.ls-barcode-rows` block the user added to or removed from (marked `data-touched` by the add/remove handler); a row or edit message line that is showing text. `open` on a card already belongs to the user (`morph.js`), so `openCardIds` / `restoreOpenCards` are deleted. Everything else in the card updates, including the summary numbers.
4. **Low Stock: own saves.** A successful save makes the saved section clean before reloading: its fields' defaults become their values, `data-touched` is cleared, and the correction reason is emptied. Its success message stays. The reload then goes through rule 1.
5. **Low Stock: a card that left the list is removed**, even with typed input (W2 rule 5). If that discarded typed input, the page message says: "An item you were editing is no longer low." A live update that moves a card to another tab counts the same way. Never silent.
6. **Review pages: the open receipt or block refreshes itself.** When an event names the selected order (or the connection recovers), the page refetches that order. If the text or status differs from what is shown, it repaints the text, status line and buttons and sets the message to "This order was changed by someone else. The receipt is up to date." ("block" on the SMR page). No focus, no select, no picker. If nothing differs, nothing changes. The refetch is guarded by the existing `selectionRequestId`, so a tile the user taps meanwhile wins.
7. **Review pages: the selected order left the queue.** If the refetch shows it archived, no longer in Review, or no longer Ready to invoice (or returns 404), the text stays, the action buttons are disabled, and the message says: "WO 1234 was closed or sent back by someone else. The receipt remains for reference."
8. **Low Stock events from one place.** An after-commit listener (the `request_events.py` pattern) collects the id of every `Item` changed in a flush that is low before or after the change, and emits `item.low_stock.changed` once per id after commit. The route calls in `routers/items.py` and the emit in `_stock_events.py` are removed; the push notification for a crossing stays where it is. Audience unchanged.
9. **Low Stock coalesces fetches.** One list fetch at a time, with one rerun queued behind it, so a bulk write costs two fetches, not hundreds.
10. **Review queues.** Both tile lists patch through rule 1 and keep the `selected` class from the builder. SMR Admin Review subscribes to `work_order.status.changed` (any id, and recovery) and reloads its queue in the background; Admin Review keeps its queue event. Background loads leave the list message alone unless it is showing a count.
11. **Highlight.** A new or changed card or tile gets `just-changed` (existing CSS).

### What the user sees

```
Low Stock, card open, typing a new count; someone dispenses the item:

  ▾ 3/4 PEX elbow      4 on hand → 2 on hand (glows)
      New count: [ 6 ]   Reason: [ recounted shelf ]    ← kept

SMR Admin Review, WO 1234 selected; someone edits its labor:

  WO 1234 Correction Block        Block stale
  This order was changed by someone else. The block is up to date.
  [ Regenerate ]
```

## Risks

| # | Hazard | Handling |
|---|---|---|
| 1 | Typed value or added barcode row lost in a patch | Rule 3; test each field type and a touched barcode block |
| 2 | Saved fields still look typed, so they never update again | Rule 4; test a later live change lands in a just-saved card |
| 3 | Card `data-barcode` / `data-barcodes` update under a typed barcode, so the save compares against values the user never saw | Accepted (non-goal: no conflict check); the server still rejects a duplicate barcode |
| 4 | Event for a rolled-back write, or sent twice | Rule 8: after commit only, route calls removed; backend test counts envelopes |
| 5 | Listener cannot tell "low before" | Read the old quantity and threshold from attribute history at flush (the archived flag is ignored: an extra event is one harmless refetch); test a restock that clears the condition still emits |
| 6 | Bulk item writes flood the page | Rule 9; one envelope per id per commit |
| 7 | Live refresh steals focus or reopens the price picker | Rule 6; test |
| 8 | Refresh replaces text while the Admin is selecting it to copy | Accepted: stale text is the worse outcome (owner's pick); the note says why |
| 9 | Own action plus its own event repaint twice or show the "someone else" note | Rule 6 compares before repainting; an own action's message is set after its reload, so it wins; test |
| 10 | Selected order gone; buttons act on it | Rule 7 disables them; test |
| 11 | Tile paired with the wrong neighbour | Rule 2 ids; census test |
| 12 | iOS jump or lost caret on a patch | `keepPlace`; owner's phone check |
| 13 | `test_realtime_emit.py` pinned sets and `current-state.md` ("Three events") are out of date | Builder updates both |

## Testing

Frontend (Vitest, `importView`): Low Stock keeps a typed threshold, count, reason, price and a touched barcode block through a live update; summary numbers update in an open card; a just-saved card takes a later change; a removed card with typed input shows the rule 5 message; changed cards glow, unchanged do not; coalescing. Review pages: tiles patch and keep `selected`; the open text refreshes with the note and without focus; unchanged text shows no note; the gone-order state disables the buttons; an own action shows its own message; SMR Admin Review reloads on the event. Census: every card and tile has an id.

Backend (real `TestClient`): one `item.low_stock.changed` per changed low item per commit for dispense, restock, correction, threshold edit, item edit, create below threshold and archive; none for an item healthy before and after; none after a rollback; existing push tests still pass.

Owner's phone check, two logins: typed count survives a dispense and the number updates; the "no longer low" message; SMR block refreshes when labor is edited; the "closed or sent back" state; the glow.

## Left to the builder

- Whether the review pages share a small helper for rules 6–7.
- Where the `Item` listener lives (beside `request_events.py`).
- The `docs/current-state.md` rows.

## Calls made by the author, not the owner

- Approach A.
- Low Stock numbers and details update live, by widening the event to every change of a low item.
- Low Stock events move from route calls to one after-commit listener.
- A card that left the list is removed even with typed input; the page says so.
- No conflict check on Low Stock edits.
- An item price edit does not refresh an open Admin Review receipt.
- When the selected order leaves the queue, its text stays and the buttons are disabled.
- The exact wording of the three notes.
- W6 ships as one push.
