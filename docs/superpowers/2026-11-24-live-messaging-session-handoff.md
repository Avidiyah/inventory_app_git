# Live messaging — session handoff

2026-11-24. **Completed.** Messaging is built, checked in-app by the user, and **live in production**; CI is fully green.

## State

| Item | Value |
|---|---|
| Production | `4a6b4de` (deployed by the push); migration `e6a8c0d2f4b6` (add messaging) ran via `entrypoint.sh` at `f27a9b1` |
| `main` | in sync with `origin/main` |
| CI on `4a6b4de` | Static ✅ · Frontend ✅ · Backend ✅ · End-to-end ✅ (74 passed, 0 skipped) |
| Local | dev server and preview server stopped; Docker `inventory-local` **stopped** (`docker start inventory-local` to bring back; it holds pre-messaging code — rebuild before using it) |

## What shipped (commits on main)

| Commit | What |
|---|---|
| `18e9e39` `4abadc3` `f268a5c` `3940f5a` | Plan Phase 1–3: realtime + push, tables/service/routes, panel/bubble/Hub tab, docs |
| `b1507d6` | Live name filter on New chat / New group pickers |
| `d51d6bd` | Admin+ **Message many** (Hub Messages tab only): `POST /messages/broadcast`, separate direct message per person; Select all / Deselect all act on shown people |
| `8e9939f` | Fix: floating panel opened off-screen on desktop (nothing positioned `#msg-float`); ported the preview's `placePanel()` |
| `f27a9b1` | Two stale backend guards repointed (catalogue test → `hubLive.js`; card-open query budget 16 → 17 for the photo count) |
| `4a6b4de` | Starter e2e green (red since the tutorials push `a57f119`; never messaging). Three stacked causes, below |

## Resolved: starter-tutorial e2e failures

| Cause | Fix |
|---|---|
| One-time Welcome tour (batch 6, same push) claimed the fresh E2E users and covered the screen | `_seed.py` marks `welcome` seen for owner/admin/tech |
| Clock-in prompt re-offered on reload; its `.modal-overlay` sat over the lit spot (the stray `POST /attendance/punch-in`) | Test clicks `[data-action="skip"]`, as `test_work_orders.py` does |
| `userHub.js` first load treated `loadedUserId = null` as a user change and reset a tab tapped mid-load to Home | Only a real user switch resets now (user's pick: fix in app); Vitest guards it. Also ended the mobile-overflow false skips (14 → 0) |

## Decisions this session (do not re-litigate)

| Decision | Whose |
|---|---|
| People filter: New chat + New group, name only, live per keystroke, picks survive filtering | User |
| Message many: Hub tab only, Admin+, one server request, back to list with "Sent to N people." | User |
| Select all / Deselect all act on the people the filter shows | User |
| Extra deploys are fine (test-only pushes OK); still ask before pushing, then watch CI | User |

## Gotchas learned

- Python `open()` on Windows defaults to cp1252: non-ASCII written through a Python rewrite becomes invalid UTF-8. Pass `encoding="utf-8"` or use Edit.
- Agent-wave bugs were all contract gaps between units (modifier class prefixes; who positions `#msg-float`). Review seams, not units.
- `services/messages.py` is at 497 lines — new messaging service code goes in a sibling module (as `messages_broadcast.py` did).
