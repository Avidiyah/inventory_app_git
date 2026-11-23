# Tutorials 0b — progress record, red dot, Hub Tutorials tab, Users-page count

> **Added 2026-11-23 for the Starter batch (overrides anything below):** The Tutorials tab has THREE sub-tabs: To do, Completed, Starter (the sketch's "Done" is "Completed"). A starter script has no page: its audience is its `minRole`, and it is exempt from the page-minimum guard line (5.4). Page-button dots count page-button scripts only; starters feed the Tutorials-tab dot and the Users-page counts (5.5). See starter spec section 10.

> **Rule added by the user 2026-11-23 (overrides anything below):** every box shows ONE simple sentence. A step that needs more is written as a list of sentences (`text: ["...", "..."]`, at most 3, each at most 120 characters) and the player gives each sentence its own tap on the same lit section. Wording tables that hold two sentences in one step are split at the sentence boundary, never merged into a longer sentence. Use plain words a new hire would use; one idea per sentence. See 0a spec 5.2 and 5.4.

Date: 2026-11-23 · Status: awaiting approval · Budget: ≤ 1,800 words

Builds on `2026-11-23-tutorials-0a-player-design.md` ("0a"). Section numbers
below refer to it.

## 1. Intent

The app remembers, per person, which tutorials they finished. A red dot on a
page's button says "something here is still new to you". A Tutorials tab in the
User Hub lists what is left and lets them replay what they finished. Team Lead
and above can see how far each person has got, on the Users page only.

## 2. Goals, non-goals, anti-goals

| Kind | Item |
| --- | --- |
| Goal | Finished = reached the last step. Pressing End early never counts |
| Goal | Progress follows the person across phones and desktops |
| Goal | The record already holds what the welcome (batch 6) needs: "seen" and "completed" are separate |
| Goal | The Hub's eighth tab fits a phone with no sideways scrolling |
| Non-goal | The player, any tutorial wording, the welcome itself |
| Non-goal | A Team sub-tab, a report, reminders or push |
| Anti-goal | One person's progress visible to a Technician, anywhere |
| Anti-goal | Progress from a sample-data run touching anything but this record |
| Anti-goal | A server that must know the tutorial catalogue |

## 3. Decisions already made by the user

- Server-side, per user. Red dot until finished.
- Hub Tutorials tab: to-do sub-tab (tap = go to that page and start it) and a
  second sub-tab named **Completed** (user's pick). The per-page buttons stay.
- Others' progress on the Users page only: a count per row, what is left on the
  profile, visible to whoever can already open that page.
- The welcome is shown once ever; ended early it stays listed as not completed.

## 4. Approaches

| Question | Option | Trade-off |
| --- | --- | --- |
| Storage | **A (picked): one row per person per script key** | Two devices writing at once cannot clobber each other; "seen" and "completed" are plain columns |
| | B: a JSON column on `users` | Smaller migration, but read-modify-write loses a write when two devices finish at once |
| | C: browser storage | Rejected: not per person, lost on a new phone |
| Others' counts | **A (picked): one extra Team Lead+ GET returning completed keys per person; the page computes counts** | `GET /users` and every History filter stay untouched |
| | B: add counts to `UserResponse` | Every consumer of `/users` pays for it; the server would need the catalogue |
| | C: fetch per row | N requests per paint |
| Where "of 14" comes from | **A (picked): the client catalogue** | The scripts files are data only (5.1), so the client can load them all without sample data |
| | B: the server stores a total | Goes stale at every tutorial batch |

## 5. Design

### 5.1 The record

Table `tutorial_progress`, one Alembic migration:

| Column | Type | Meaning |
| --- | --- | --- |
| `user_id` | FK `users.id`, ON DELETE CASCADE | Person. Deleting a user removes their rows |
| `script_key` | text | The 0a script key, e.g. `work-orders.card.notes` |
| `seen_at` | timestamptz, not null | First time it started |
| `completed_at` | timestamptz, null | First time the last step was reached |

Primary key `(user_id, script_key)`. Timestamps are first-write-wins and never
cleared: replaying a finished tutorial changes nothing, and the dot cannot come
back. The server stores keys only, so a renamed or deleted script leaves a
harmless orphan; counts intersect with the live catalogue and ignore it.

Rows per person are capped at 500 (400 beyond it) as a guard against abuse.

### 5.2 Routes

New router `tutorials`, prefix `/tutorials`, mounted in `app/main.py`.

| Route | Who | Does |
| --- | --- | --- |
| `GET /tutorials/progress/me` | any signed-in user | `[{key, seen_at, completed_at}]` for the caller |
| `PUT /tutorials/progress/{key}` | any signed-in user, own row only | Body `{event: "seen" \| "completed"}`. Idempotent upsert. `completed` also fills `seen_at` if empty. 204 |
| `GET /tutorials/progress/users` | Team Lead+ (`ROLE_SUPERVISOR`, same gate as `GET /users`) | `{"<user_id>": ["<completed key>", ...]}` for active users |

The caller never names a user id on a write, so nobody can write another
person's row. `key` must match `^[a-z0-9][a-z0-9.-]{0,79}$` (400 otherwise);
`event` is validated by a Pydantic enum on the body. No query parameters, so the
int-Literal 422 quirk does not arise; if the builder adds one, use `int` plus
manual validation.

### 5.3 Client record

One module, `backend/static/tutorialProgress.js`, imports no view:

| Function | Does |
| --- | --- |
| `loadProgress()` | GET `me` once after sign-in; cached |
| `isDone(key)`, `hasSeen(key)` | Read the cache |
| `mark(key, event)` | Update the cache at once, PUT in the background; a failed PUT is logged and not retried unless the builder adds it |
| `clearProgress()` | Called on sign-out and on a 401. Shared crew phones must never show the last person's dots |

The player (0a 5.4) calls `mark(key, "seen")` when a script starts and
`mark(key, "completed")` when its last step is shown. The last step is the last
**visible** step, since skipped steps are never shown. A sample-data run writes
real progress: the PUT is not a listed GET, so 0a 5.3 leaves it alone.

### 5.4 Who a script is for

| Rule | Detail |
| --- | --- |
| Default | Anyone `PAGE_ACCESS[page]` lists (`views/nav.js`). Every entry there is "this role and above", so the audience is one minimum role |
| Narrower tab | A script may carry one optional field, `minRole: "supervisor"` (stored role values, 0a 5.2). Only used where a tab is narrower than its page, e.g. Hub Timesheets and Report |
| Display | "Everyone", else "Team Lead and above" using the role labels the app already shows |
| Guard test | `minRole`, if present, is a real role and not lower than the page minimum |

`relevant(script, role)` is one client function, used by the dot, the Hub tab
and the Users counts.

### 5.5 Red dot

A page's button shows the dot while **any script on that page that is relevant
to this person has no `completed_at`**. It clears the moment the last such
script is finished and never returns for that person. A role change recomputes
it, since relevance is read live.

The dot is a CSS class on the 0a button. The button gains `aria-label` and
`title` "How this page works, you have not finished it yet" while dotted, so
the dot is not colour alone. Dot colour: the brand red, as in the existing
badges.

### 5.6 Hub Tutorials tab

Seen by every role. Built in its own module `views/hubTutorials.js` (the Hub
files are near their line caps); `userHub.js` only registers the panel and loads
it lazily like the other tabs.

```
 Tutorials
 [ To do (6) ] [ Done (3) ]
 ┌───────────────────────────────────────┐
 │ Work orders                           │
 │  Notes            For everyone      >  │
 │  Materials        For everyone      >  │
 │ Users                                 │
 │  Add a user       Team Lead and up  >  │
 └───────────────────────────────────────┘
```

| Item | Behaviour |
| --- | --- |
| To do | Relevant scripts without `completed_at`, grouped by page. A script that was seen but not finished is listed here with a "Started" label |
| Done | Relevant scripts with `completed_at`, same grouping, labelled with a "Replay" tap |
| Tap an entry | `showPage(page)`, wait for its loader, then play that script by key. 0a's player must export `startTutorial(key)` for this; its button path is unchanged |
| Empty | To do: "You have finished every tutorial." Done: "Nothing finished yet." |
| Count | The number in each sub-tab label is the list length |

Replay does not change the record. Pages the person cannot open never appear.

### 5.7 Hub tab row

Today `#hub-tabs` is a flex row of seven tab buttons with no wrapping. Up to
600 px a toggle card (`hubPicker.js`) replaces the row and lists every tab as an
icon tile, so phones already cannot scroll sideways. What changes:

| Change | Where |
| --- | --- |
| Eighth tab button and panel `hub-tab-tutorials`, `hub-tabpanel-tutorials` | `user-hub.html` |
| An icon mask `--hub-ico-tutorials` and two rules (current card, tile) | `styles.css` beside the other seven |
| `tutorials` added to the panels map | `userHub.js` |
| `HUB_TABS` gains `"tutorials"` | `tests/e2e/test_mobile_overflow.py` |
| Check 601–900 px: eight labels may exceed the row. If so `flex-wrap: wrap` on `.hub-tabs` and add widths 640 and 768 to the e2e test | builder |

### 5.8 Users page

| Surface | Shows |
| --- | --- |
| Row | A small "9 of 14 tutorials" line beside the existing counts, for every active user. Reflows under the name on a phone, never sideways |
| Profile (`userProfile.js`) | A "Tutorials" block listing the scripts that person has not finished, grouped by page, as plain text. No tap action |

The count is `completed relevant scripts / relevant scripts` for that person's
role, using the client catalogue (`catalogue()`, a helper that imports every
page's scripts file but no sample file). `GET /tutorials/progress/users` is
fetched with the list and refetched on the same one-minute tick as the to-fix
counts; a failed fetch hides the line and nothing else.

### 5.9 Welcome (batch 6)

Needs no migration. It reads `seen_at` from `GET .../me`: no row = never shown.
It calls `mark("welcome", "seen")` when it opens, so ending early never shows it
again, and `mark("welcome", "completed")` only at its last step, so an early
end stays in To do. The welcome's key is a normal script key.

## 6. Tests

| Test | Proves |
| --- | --- |
| Service (pytest) | First write wins; `completed` fills `seen_at`; replay changes nothing; the 500-row cap |
| Router (pytest, real TestClient) | Own-row writes only; bad key and bad event 400/422; the all-users map lists active users only |
| `tests/test_route_role_gates.py` | `me` and `PUT` have no minimum role beyond signed-in; the all-users route requires `ROLE_SUPERVISOR` |
| `tests/test_memprobe.py::test_every_route_is_catalogued_or_excluded` | The three routes get entries in `CATALOGUE` in `scripts/memprobe_routes.py` |
| Cascade | Deleting a user removes their rows; archiving keeps them |
| Vitest `tutorialProgress`, `hubTutorials`, relevance, catalogue | Cache, optimistic mark, clear on sign-out, both sub-tabs, empty states, tap path, counts, the dot rule. These keep the coverage gate (94/84/96/96) green |
| Guard test (0a) | Gains: `minRole` valid; every key unique across all pages |
| Id census, `staticImports.test.js` | Updated for the new ids and imports |
| E2E `test_mobile_overflow` | The Tutorials tab at 375 and 320 px |

## 7. Constraints

- No inline styles (CSP): dot and label colours through classes. No nested
  buttons: a tab entry is one button or one anchor, not both.
- No new request on a page load for a person with nothing to track; the single
  `me` fetch happens once per sign-in.
- New files under 500 lines; `docs/current-state.md` gains the table, the three
  routes and the Tutorials tab, and the Roles section notes the gate.

## 8. Left to the builder

- Whether `loadProgress()` runs before first paint or just after (the dot may
  appear a moment late).
- Retry of a failed PUT.
- Exact placement and wording of the Users-row line, within `docs/design-system.md`.
- The wrap fix in 5.7, if the 601–900 px check shows overflow.

## 9. Calls made by Claude, for the user to check

- Dot clears only when **every** relevant script on the page is finished, and
  is judged per person's current role.
- "Seen" is set at start, "completed" at the last visible step; replay never
  clears either.
- Counts and "of N" are worked out in the browser, so a tutorial batch changes
  everyone's total with no data migration.
- Tutorials tab visible to every role, with a "Started" label on unfinished
  ones. It carries a red dot of its own while the person has any relevant tutorial unfinished (user's pick, 2026-11-23).
- Users-row count shows for every active user, Team Lead and above included.
- 0a gains one export, `startTutorial(key)`, and calls `mark` on start and end.
- Ceiling: 500 progress rows per person.
