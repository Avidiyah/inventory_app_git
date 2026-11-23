# User Hub live (W7): design

Date: 2026-11-23. Status: draft for owner review. Scope: `views/userHub.js` and the hub tab modules (`hubHome`, `hubClock`, `hubTechnician`, `hubPriorities`, `hubSupervisor`, `hubAdmin`, `hubTimesheetsTab` and its roster/day/hours children, `hubLeaderboardsTab`, `hubPerformanceBoard`, `hubReport`), plus two audience lines in `domain/realtime.py`. Builds on W1/W2/W5/W6 (`2026-11-14-work-order-live-rendering-design.md`, `2026-11-23-low-stock-and-review-pages-live-design.md`).

## Intent

The owner wants the whole app to feel live. The hub already refetches on events and on a 60-second timer, but most tabs then wipe and redraw, which closes what the user opened and can jump the page. Home does not follow events at all: a punch or clock started on another device stays invisible until the user acts. W7 makes every hub tab follow changes and patch in place.

## Roadmap

| W | Scope |
|---|---|
| W1–W3, W5, W6 | Work Orders, User Requests, Low Stock, review pages (shipped) |
| W4 | Dropped (IMP-042) |
| **W7** | **User Hub, every tab (this spec)** |

## Owner decisions (2026-11-23)

- Every tab, Leaderboards and Report included (option b).
- Approach A: patch in place with `morph.js`, existing events.

## Goals

- Every tab updates without a manual reload: Home, Dashboard, My Work Orders, Timesheets, Leaderboards, Graphs, Report.
- An update changes only what changed; open `<details>`, an open punch editor, a focused or typed field and the scroll position survive; a changed tile or row glows once.
- The user's own punch and clock, started on any device, show on every device within one event.

## Non-goals

- New events, new endpoints, or event payloads carrying data.
- Changing what any tab shows, its layout or its wording (beyond rule 7's note).
- A conflict check on punch or hours edits (last save wins, as today).
- Making closed Report weeks live (they are frozen records).

## Anti-goals

- A second rendering path for "live" versus "after my own action".
- A live update that closes an editor, steals focus, or drops typed input silently.
- A live update that makes `GET /hub/admin` or the Leaderboards/Report queries fire per event (memory: N-MEMORY-CRASH names `GET /hub/admin`).

## Constraints

| Constraint | Source |
|---|---|
| No inline style or script | CSP |
| One patch helper: `morph.js` (`morphInto`, `isDirty`, `keepPlace`) | W1–W6 |
| REST is the truth; events carry an id only | `realtime.js`, `domain/realtime.py` |
| Files under 500 lines; `userHub.js` is 601 | repo rule |
| The clock node is reparented, never rebuilt (keeps `hubClock.js` state) | `userHub.js::renderHome` |
| Readable on a phone, no legend, no sideways scroll | owner design rules |

## Findings (code read 2026-11-23)

| Finding | Consequence |
|---|---|
| Every hub tab module paints with `innerHTML` | Each builds into a detached node and goes through `morphInto` (rule 1) |
| `refreshPersonal` repaints Dashboard and Work Orders but never Home | Home joins the live path (rule 4) |
| `attendance.changed` audience is Supervisor+; `labor.session.changed` is Supervisor+ | A technician's own other device never hears its punch or clock; widen both to Technician (rule 3) |
| Audiences are by role only; there is no per-user target | Widening is the only option without new plumbing; envelopes carry no data, so it is noise, not disclosure |
| Home closes the punch editor and the week list on every reload (`refreshUserHub` → `loadUserHub` → full repaint) | Rule 2 keeps them |
| Timesheets already skips the week refetch while a profile or punch editor is open | Keep that guard; the patch makes the roster and week safe to update otherwise |
| Leaderboards and Report fetch only on tab entry | Add rule 6 |
| Graphs already keeps its pop-up and drill path across re-mounts | Only the outer patch changes; keep its state |
| `loadUserHub` (the own-action refresh) re-runs role checks, crew and admin fetches every time | Own actions go through the same targeted refresh as events (rule 5) |

## Approaches

| Approach | Trade-off | Verdict |
|---|---|---|
| A. Patch in place with `morph.js`, events as invalidations | Same rules as W1–W6; `userHub.js` must be split | **Chosen (owner, 2026-11-23)** |
| B. Keep wipe-and-redraw, save and restore UI state around it | Second mechanism, loses focus and caret, no glow | Rejected (W5 anti-goal) |
| C. Send new numbers in the event | Breaks "events carry an id only" | Rejected |

## Design

### Rules

1. **One path.** Every hub tab renders by building its markup into a detached container and calling `morphInto(mount, nodes, { skip, flashSelector })` inside `keepPlace`. First draw, tab change, own action, event, reconnect and the 60-second timer all use it. Loading skeletons and error panels may still replace the mount when nothing good is on screen.
2. **What a patch leaves alone.** `skip` is true for: the focused field; any field that `isDirty`; an open punch editor (`.punch-editor`) and its host; the Timesheets profile and day drill-down while open. `open` on `<details>` already belongs to the user (`morph.js`). The clock mount is skipped by Home's patch (it is reparented, rule 4).
3. **Audiences.** `attendance.changed` and `labor.session.changed` go to Technician+. Both carry `id: null`; a recipient with no matching tab ignores them, as today.
4. **Home is live.** On `attendance.changed`, `labor.session.changed`, `work_order.status.changed`, reconnect and the timer, the hub refetches `GET /hub` and `GET /attendance/me` (one of each in flight, rule 6) and repaints Home through rule 1; the clock remount (`mountHubClock`) runs on the same payload. A punch editor that is open stays open; if the punch it edits is gone, the editor closes and the punch message says: "That punch was changed on another device." Never silent.
5. **Own actions use the same refresh.** Punch, switch, clock start/stop and punch-editor saves call the targeted refresh of rule 4, not `loadUserHub`. `loadUserHub` stays the page-entry and user-change path.
6. **Coalesced fetches.** Each feed (`/hub`, `/attendance/me`, crew, admin, graphs, leaderboards, report, timesheets week/live) runs at most one request at a time with one rerun queued (W6 rule 9). A feed for a hidden tab is not fetched; it fetches on tab entry, as today. Crew and admin keep their current triggers.
7. **Leaderboards and Report.** While their tab is showing, `work_order.status.changed`, `attendance.changed`, reconnect and the timer refetch the current selection (Leaderboards' period; Report only when showing the week in progress). They patch through rule 1. A closed Report week is never refetched by an event.
8. **Highlight.** A new or changed tile, row or card gets `just-changed` (existing CSS). The one-second tick of the punch and clock counters is excluded from the flash.
9. **Split `userHub.js`.** Its feeds, timer and subscriptions move to a new `views/hubLive.js`; `userHub.js` keeps tabs, roles and entry. Both end under 500 lines.

### What the user sees

```
Phone on Home, punch list open; the same worker punches out on the desktop:

  ○ Not punched in          Today 7h 42m     (glows)
  ▾ This week's punches                        ← stays open
      Mon Nov 23  6:58 AM – 2:40 PM  7h 42m    (new row glows)

Admin on Leaderboards (week); a technician's hours are edited:

  2  J. Ortiz   84  → 86  (row glows, order may change)
```

## Risks

| # | Hazard | Handling |
|---|---|---|
| 1 | Editor or typed input lost in a patch | Rule 2; test each editor and a dirty field |
| 2 | Clock widget state lost | Clock mount skipped by Home's patch and reparented, not rebuilt; test a running session keeps ticking |
| 3 | Event floods trigger repeated `/hub/admin` or leaderboard queries | Rule 6; test a burst costs at most two fetches per feed |
| 4 | Wider audiences add socket noise | Accepted: small crew, id-only envelopes; backend test pins the new audience |
| 5 | Own action plus its own event repaint twice | Rule 6 coalesces; the patch is idempotent, so a second identical paint changes nothing and does not glow |
| 6 | Counter tick flagged as a change every second | Rule 8 |
| 7 | Leaderboard rows paired wrongly when ranks reorder | Rows keyed by user id; census test for ids on every patched row/tile |
| 8 | Splitting `userHub.js` breaks imports in the browser only | `staticImports.test.js` covers it; add the new module |
| 9 | iOS jump or lost caret on a patch | `keepPlace`; owner's phone check |
| 10 | `current-state.md` event rows and `test_realtime_emit.py` audiences out of date | Builder updates both |

## Testing

Frontend (Vitest, `importView`): each tab patches in place (unchanged nodes keep identity, changed ones glow); an open `<details>`, punch editor and dirty field survive an event; Home updates on `attendance.changed` and `labor.session.changed`; the gone-punch message; own punch uses the targeted refresh; coalescing per feed; Leaderboards and Report refetch only while showing, Report only for the week in progress; hidden tabs do not fetch; census of ids.

Backend (real `TestClient`): `attendance.changed` and `labor.session.changed` reach a Technician socket.

Owner's phone check, two devices or logins: punch out on one, the other updates with the week list still open; clock start shows on the other device; Dashboard sections stay open through an update; a Leaderboards row updates after an hours edit; the glow.

## Left to the builder

- Ids and keys for each tile and row.
- Whether rule 2's skip set lives in one shared hub helper.
- Exact split line between `userHub.js` and `hubLive.js`.
- The `docs/current-state.md` rows.

## Calls made by the author, not the owner

- Widening two event audiences to Technician instead of adding per-user delivery.
- An open punch editor whose punch disappeared closes with a note.
- Closed Report weeks are not live.
- Hidden tabs do not fetch on events.
- Own actions stop calling `loadUserHub`.
- New module `hubLive.js`.
- W7 ships as one push.
