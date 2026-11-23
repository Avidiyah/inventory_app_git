# Tutorials 5 — Starter tutorials (menu tours)

> **Rule (user, 2026-11-23):** every box shows ONE simple sentence; a step may carry a list of up to 3, each ≤ 120 characters, one tap each (0a 5.2, 5.4).

Date: 2026-11-23 · Status: awaiting approval · Budget: ≤ 1,800 words. Section numbers refer to 0a (`...-0a-player-design.md`) and 0b (`...-0b-progress-design.md`).

## 1. Intent

A new hire learns the menu by using it: the tutorial lights one menu button, waits for the person to tap it, describes the page that opens, then lights the next button.

## 2. Goals, non-goals, anti-goals

| Kind | Item |
| --- | --- |
| Goal | Five starters: "Using the menu", Inventory, Field, People, Review; each covers only pages the person's role can open |
| Goal | One new player ability: wait for a tap on the lit target |
| Non-goal | Page tutorials (batches 1–4), the welcome (6), SMR, an Integration starter (see 8) |
| Anti-goal | A forwarded tap that changes data: the only click ever forwarded is a menu button |

## 3. Decisions already made by the user

Third Hub sub-tab "Starter"; the person taps the real button and only it works; one starter per group after "Using the menu"; the welcome ends on Starter; one sentence per box; English only; pop-ups never opened; real data never changed.

## 4. Approaches

| Question | Option | Trade-off |
| --- | --- | --- |
| Across pages | **A: one script survives the page change** (`expectNav`, 5.1) | One progress key per tour, no flicker |
| | B: one script per page, auto-chained | Restarts on every tap; progress per page |
| Letting the tap through | **A: overlay forwards a click inside the lit rectangle by `target.click()`** | Overlay stays whole; no stacking fights |
| | B: raise the target above the overlay | Header and popover (`z-index: 20`) stack separately; "only that button" needs more blocking |

## 5. Design

### 5.1 Player change

Step fields (optional): `waitTap` (the button to tap; one-sentence `text`), `via` (selector lit first while `waitTap` is not visible, re-checked at every placement), `viaText` (one sentence). Script fields: `sample: false`, `minRole` (0b 5.4).

| Moment | Behaviour on a wait step |
| --- | --- |
| Box | Stays up; the first-tap-hides rule and pill are off |
| Tap inside the lit rectangle | Overlay stops propagation (the page's outside-click handler would close the popover), calls `target.click()`. After `via`, the player lights `waitTap`. After `waitTap`, it sets `expectNav` and waits up to 3 s for the next step's target |
| Tap elsewhere | Ignored |
| Enter or → | Acts as the lit tap; other keys blocked |
| Esc, End | End, not completed, person stays put |
| Back | Not offered on the first step after a wait |
| No `waitTap` or `via` visible | Step skipped, **and so are the steps after it up to the next wait step** (they describe the page it opens) |
| Next target absent after 3 s | End quietly, not completed |

`nav.showPage` ends a tutorial on a page change (0a plan C6); `endTutorial` returns at once while `expectNav` is set, cleared when the next step shows or the 3 s lapse. A page change not caused by the forwarded click still ends it. Visibility of `waitTap`/`via` also needs `getClientRects().length > 0`, since a closed popover is hidden by CSS; jsdom needs a stub there.

### 5.2 What is lit

The nav is dropdown groups when the role has more than 5 pages (`nav.js::COMPACT_NAV_THRESHOLD`), flat otherwise. That is role, not width, so phone and desktop match:

| Role | Tap 1 lit | Tap 2 lit |
| --- | --- | --- |
| Technician (flat) | The page button | none |
| Team Lead and above | The group toggle (`via`) | The page button inside the opened popover |

`showPage` closes the popover, so each next page starts from the toggle.

### 5.3 Data

No sample, no responder, no reload at start or end, no unsaved-text refusal: overview steps light the page as a whole (`#<page>-page`, clamped to the viewport, box pinned to the bottom) and input is blocked, so real data is safe. No starter waits on a batch 1–4 sample file. The "target fits a phone" rule is waived for `#<page>-page`.

### 5.4 Registration and audience

`tutorials/starter.js` (data only, keys `starter.menu|inventory|field|people|review`); `index.js` adds `starter: { scripts }`, no `sample`. No `#starter-page`, so no button; no `open`, so no "Next:". `minRole`: menu, inventory, field = technician; people, review = supervisor, so a group with no openable page is never offered. One-page starters (People; Review for a Team Lead, History) are kept. The two SMR entries are never lit.

### 5.5 Hub placement

```
 Tutorials
 [ To do (6) ] [ Completed (3) ] [ Starter (2) ]
 ┌───────────────────────────────────────┐
 │ Using the menu          Done   Replay  │
 │ Inventory               Started      > │
 │ Field                   New          > │
 └───────────────────────────────────────┘
```

| Question | Answer |
| --- | --- |
| Order, default | To do, Completed, Starter; opens on To do unless a caller (the welcome) asks for Starter |
| Starter list | Relevant starters in tour order, labelled New, Started, or Done + Replay; count = unfinished, hidden at 0 |
| In To do / Completed | Also, under "Menu", so "You have finished every tutorial" stays true |
| Totals and dots | They count in "9 of 14" and the Tutorials-tab dot (user's assumption); no page button, so no page dot |
| Tap an entry | Plays on the Hub at once, no `showPage`; finished = last visible step |

## 6. Tests

| Test | Proves |
| --- | --- |
| Player unit | Forward inside/ignore outside; popover re-light after `via`; `expectNav` set and cleared; Esc, End, Back; skip-with-wait; timeout; `sample: false` sets no responder and calls no `showPage` |
| Guard, cross-page | Per role from `minRole` up: real shell booted with that role, each starter walked on real markup. Each `waitTap` is a visible `.nav-btn[data-page]` (after its `via`, that group's toggle); clicking them shows `#<page>-page` and the next target. Pages visited = the group's pages for that role minus SMR. Roles below `minRole` open no page in the group. One-sentence wait text, ≤ 8 steps, limits, unique keys. The 0a per-page loop skips entries without `sample` |
| Playwright | Team Lead, Field starter at 375 px, real layout |
| Hub | Three sub-tabs, order, default, count, tap-to-play |

## 7. Constraints

No inline styles, nested buttons or sideways scroll; `tutorial.js` under 500 lines (move wait logic to `tutorialView.js`). `docs/current-state.md` Navigation says four groups; the shell has five. Fix it in the same commit. Left to the builder: the rectangle test's padding, how the Hub opens a sub-tab, clamping a tall target.

## 8. Calls made by Claude, for the user to check

- No Integration starter (one page; batch 4 covers it). SMR entries skipped.
- The dropdown split is by role, not phone (5.2).
- No sample data or reload during a starter; Back not offered across a page change.
- Starters also listed in To do and Completed; Starter sub-tab last, To do default.
- "Using the menu" has the person open Find Item (every role can).

## 9. Wording

Wait text: "Now tap *Page*." (first in a tour: "Tap *Page* to begin."); `viaText`: "Tap *Group* to open it." Overview steps light `#<page>-page`.

**Using the menu** (`starter.menu`, everyone)

| Lit | Sentences |
| --- | --- |
| `#main-nav` | "This bar at the top is the menu." / "Each button opens one page of the app." (`textFor` supervisor, techfm_oa, admin, owner: second sentence "The buttons are grouped under names like Inventory and Field.") |
| Wait: Find Item (via Inventory) | "Tap Find Item to try it." |
| `#main-nav` | "The button for the page you are on stays marked." |
| `#auth-user-indicator` | "Your name takes you back to your Hub." |
| `#logout-btn` | "Log Out signs you out of this device." |

**Inventory** (`starter.inventory`)

| Page | Wait lit | Sentences |
| --- | --- | --- |
| Add Item (TechFM OA+) | Inventory, Add Item | "Add Item puts a new item or tool in the catalogue." / "You enter its name, barcode, location and price." |
| Find Item | Inventory, Find Item | "Find Item searches the catalogue by name or barcode." / "Open an item to see its count and where it sits." / "Nothing shows until you search or tap Load All." |
| Tools | Inventory, Tools | "Tools tracks who is holding each shop tool." / "Custody shows a person's tools; Inventory looks up one tool." / "Anyone can check a tool back in." |

**Field** (`starter.field`)

| Page | Wait lit | Sentences |
| --- | --- | --- |
| Scan / Stock | Field, Scan / Stock | "Scan / Stock is where you scan material you use on a job." / "First pick the work order, then scan each item." / "Team Lead and above can also put stock back." |
| Work Orders | Field, Work Orders | "Work Orders lists the jobs, each as a card coloured by its status." / "Tap a card to see its notes, materials and labor." / "Work orders are imported, so you cannot create one here." |
| Mass Stage (Team Lead+) | Field, Mass Stage | "Mass Stage plans loading a truck for several jobs at once." / "Each plan is for one community and building." / "Its load list shows what is planned, loaded and left." |

**People** (`starter.people`, Team Lead+)

| Page | Wait lit | Sentences |
| --- | --- | --- |
| Users | People, Users | "Users lists everyone who has an account." / "You can add a person or archive an account, for roles below yours." / "Archiving blocks sign-in but keeps their history." |

**Review** (`starter.review`, Team Lead+)

| Page | Wait lit | Sentences |
| --- | --- | --- |
| Low Stock (TechFM OA+) | Review, Low Stock | "Low Stock lists the items that are running low." / "You can change the level where an item counts as low." |
| User Requests (TechFM OA+) | Review, User Requests | "User Requests collects what crews ask the office for." / "That means material to stock, new items, recounts and missing prices." |
| Admin Review (TechFM OA+) | Review, Admin Review | "Admin Review is the last billing check on a finished job." / "From here a job is closed, or sent back to In-Progress." |
| History | Review, History | "History lists every stock transaction." / "Filter it by work order number or by date." / "Pricing List makes a text list of priced rows to paste elsewhere." |

## 10. Edits to other documents (orchestrator applies)

1. 0b spec 5.6 and sketch: three sub-tabs "To do", "Completed" (sketch says Done), "Starter", plus the 5.5 table.
2. 0b spec 5.4: a starter has no page; audience = `minRole`; exempt from the page-minimum guard line.
3. 0b plan: `relevant()`/`catalogue()` accept pages absent from `PAGE_ACCESS` when `minRole` is set; T7 `startTutorial(page, key)` works for `"starter"` with no `showPage`.
4. 0b spec 5.5: page dots count page-button scripts only; starters feed the Tutorials-tab dot and Users counts.
5. Batch 6 spec 5.5: last step opens Tutorials on the Starter sub-tab.
6. 0a plan T2–T5: add 5.1 fields, `expectNav`, `sample: false`, layout visibility; guard loop skips entries without `sample`.
7. Handoff: batch 5 follows 4, precedes the welcome.
