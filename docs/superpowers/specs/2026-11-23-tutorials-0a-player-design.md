# Tutorials 0a — player, button, sample data, guard test, work-order pilot

Date: 2026-11-23 · Status: awaiting approval · Budget: ≤ 1,800 words

## 1. Intent

Every page gets a button that walks a person through it: the page darkens, one
section is lit, a short box explains it, a tap moves on. The goal of 0a is to
make every later tutorial a short list of text, so batches 1–5 are writing
work and never code work.

0a ships the shared player, the button, the sample-data switch, one guard
test, and four pilot tutorials for the work-order card.

## 2. Goals, non-goals, anti-goals

| Kind | Item |
| --- | --- |
| Goal | A new tutorial = one script entry + sample records. No new code, no new test |
| Goal | One script serves every role |
| Goal | A UI change that breaks a tutorial fails CI |
| Goal | Works the same on phone and desktop, no sideways scrolling |
| Non-goal | Progress tracking, red dot, Hub Tutorials tab, Users-page count (0b) |
| Non-goal | One-time welcome (batch 6) |
| Non-goal | Tutorials for any page but the work-order card (batches 1–5) |
| Non-goal | Opening pop-ups, a second language, usage analytics |
| Anti-goal | A tutorial tap that changes real data |
| Anti-goal | Sample records still on screen after a tutorial ends |
| Anti-goal | Starting a tutorial losing an unsaved note: with unsaved text on the page the button refuses to start and says why (user's pick) |

## 3. Decisions already made by the user

- First tap hides the box (the lit section stays), second tap moves on.
- One button per page, beside the first heading.
- Tutorials run on made-up sample data, never the person's real data.
- One script per tab. The button plays the tab the person is on; the last box
  offers the next tab.
- "Group" means role. Steps a role cannot see are skipped; a step may carry
  different wording for a named role.
- Pop-ups are described, never opened.
- English only.

## 4. Approaches

| | Approach | Trade-off |
| --- | --- | --- |
| **A (picked)** | Feed sample records to the real page code through one switch in `api.js`, then point at the real markup | Tutorials cannot drift from the real layout; role rules apply by themselves. Needs care that sample data never leaks past the end |
| B | Hand-build a sample copy of each page inside the overlay | No leak risk, but every tutorial doubles its writing and drifts the day the page changes |
| C | Run on the person's real page | Rejected by the user: empty lists, and taps near real data |

A library (driver.js, Shepherd) was dropped: the app has no build step, the
two-tap behaviour is custom, and the CSP forbids inline styles. The player is
about 200 lines, modelled on `tooltip.js`.

## 5. Design

### 5.1 Files

| File | Owner | Holds |
| --- | --- | --- |
| `backend/static/tutorial.js` | 0a | The player. One overlay, delegated listeners, like `tooltip.js` |
| `backend/static/tutorials/index.js` | orchestrator only | Page name → that page's two files |
| `backend/static/tutorials/<page>.js` | one agent per page | That page's scripts. Data only, no imports, no functions |
| `backend/static/tutorials/<page>.sample.js` | same agent | `sample(user)` → the records the page reads |
| `backend/static/api.js` | 0a | `setSampleResponder(fn or null)`, beside the two existing handlers |
| `backend/static/styles.css` | 0a | Overlay, box, button |

Tips (`tips.js`) explain a rule. Tutorials say where things are. Neither
replaces the other.

### 5.2 Script format

```js
export const SCRIPTS = [
  {
    key: "work-orders.card.notes",        // <page>.<area>.<tab>, lowercase
    title: "Notes",                       // shown in "Next: Notes"
    here: '.wo-tab[data-wo-tab="notes"][aria-selected="true"]',  // optional
    open: ['[data-wo-id="-1"] .wo-card-head', '.wo-tab[data-wo-tab="notes"]'],
    steps: [
      { target: "#wo-sec-notes", title: "Notes", text: "Read what the last person left before you start." },
      { target: "#wo-notes-input", title: "Add your own", text: "Write what you did and what is left.",
        textFor: { supervisor: "Write what the next crew needs to know." } },
    ],
  },
];
```

| Field | Meaning |
| --- | --- |
| `key` | Stable id. 0b stores progress against it; never rename one |
| `title` | Plain name of the tab or section |
| `here` | Checked against the real page when the button is pressed. The last script in file order whose `here` matches is played; with no match, the first script |
| `open` | Selectors the player clicks, in order, to reach the tab on the sample page. After each click it waits up to 3 s for the next selector (or the first step's target) to be visible. A click is skipped when what it should reveal is already visible, so an open section is never toggled shut |
| `steps[].target` | What to light up. Missing from the page or not visible → the step is skipped at once |
| `steps[].text` | The box body: **one sentence**, or a list of sentences. The box shows one sentence at a time and each further sentence takes its own tap. Plain text, escaped |
| `steps[].textFor` | Optional wording (a sentence or a list, as `text`) per stored role value (`technician`, `supervisor`, `techfm_oa`, `admin`, `owner`), exact match |

Selectors above are illustrative; the builder uses the real ones.

House rules, checked by the guard test where possible: at most 8 steps per
script, one sentence per box, at most 3 sentences per step and 120 characters per sentence, simple words a new hire would use with one idea per sentence, every sentence
traceable to `tips.js` or `docs/current-state.md`, each target small enough to
fit a phone screen.

### 5.3 Sample data

- `sample(user)` returns a map of `"GET <path>"` → JSON body. A request matches
  on its path alone; the query string is ignored (list pages send variable
  filters). It receives the
  signed-in user so a sample can put that person on the crew; a Technician
  then sees the whole card instead of the read-only one.
- While a tutorial runs, `rawFetch` answers a listed GET from the map. Every
  other request goes to the server untouched, so background requests keep
  working.
- Every sample record uses an id with the **reserved prefix**
  `ffffffff-ffff-4fff-8fff-` (ids here are UUID strings; "negative id"
  elsewhere in these specs means this). A stray write therefore cannot
  touch a real record, and no stored draft or cache key can collide with one.
- Start: set the responder, call `showPage(activePage)` (which runs the page's
  loader), run `open`, show step 1.
- End, by any route: clear the responder, call `showPage(activePage)` so real
  data returns.
- Real-time needs no change: an invalidation during a tutorial refetches and
  gets the sample again. The player looks its target up fresh every time it
  places the highlight.

### 5.4 The player

Behaviour is the approved preview, option A:

| Moment | Behaviour |
| --- | --- |
| Step shown | Target scrolled to the middle; everything else darkened; box below the target, else above, else pinned to the bottom; never wider than the screen |
| Tap, more sentences left | The box shows the step's next sentence; the lit section does not change |
| First tap anywhere (last sentence showing) | Box hides, a "Tap anywhere for the next step" pill shows, the lit section stays |
| Second tap | Next step |
| Box footer | "3 of 5", Back (not on step 1), End |
| Last step | The box stays up and shows **Next: \<title\>** and **Done**. Next is offered only when a later script on the page has at least one visible step for this person |
| Keyboard | Enter or → acts as a tap, Esc ends |
| All input | Blocked from reaching the page while a tutorial runs; focus stays in the box |
| `open` fails, or no step is visible | End quietly and restore the page |
| Leaving | `showPage` to another page, a 401, or sign-out ends the tutorial and clears sample mode first |

Positions are written through CSSOM, as `tooltip.js` does, because the CSP
drops `style=` attributes. The overlay sits above the tip bubble; starting a
tutorial closes any open tip.

### 5.5 The button

- The player adds it at startup to the first `h2` of `#<page>-page` for every
  page in `tutorials/index.js`. No page HTML is edited.
- A labelled pill, "How this page works", so it does not read like the round
  `?` bubble some titles already carry. It sits after that bubble.
- Same line as the title when it fits; wraps under the title when it does not.
- No red dot in 0a.

### 5.6 Pilot: the work-order card

Sample: two orders. One In-Progress with a note, three materials and 2.5 h of
labor, the viewer on its crew; one Created, to show a second status colour.
The Invoice tab is SMR-only; SMR is finished and gets no tutorials.

| Script | Step points at | Wording |
| --- | --- | --- |
| Details | The card header | One card per job. The colour is the status: yellow means In-Progress. |
| | The tab row | Everything about the job sits under these tabs. The numbers show how much is logged so far. |
| | The details block | Where the job is, what was asked for, and who is on the crew. |
| | Begin Charging | Starts your clock on this job and puts you on the crew. Tap it again when you stop. |
| | The ⋯ button | Less common actions live behind this button. |
| Notes | The note log | Read what the last person left before you start. |
| | The note box | Write what you did and what is left, then tap Save note. |
| Materials | The materials list | Every item used on this job so far. |
| | The add-material row | Search or scan the item, then enter how many you used. |
| | New entries (Team Lead+) | Dispense takes the item out of stock. Retroactive records paper usage without touching stock. |
| Labor | The labor list | Hours charged to this job, person by person. |
| | Add hours (Team Lead+) | Key hours in by hand for anyone on the crew. |

The Owner has no Begin Charging button, so that step is skipped for the Owner
by the missing-target rule.

## 6. Tests

| Test | Proves |
| --- | --- |
| Player unit | One sentence per box with a tap per sentence, two-tap advance, Back, End, Esc, skip on a missing target, `textFor`, the Next offer, `here` selection |
| `api.js` | A listed GET is answered from the sample; an unlisted request reaches the server; nothing is answered after the responder is cleared |
| **Guard** (one test, every page in the index) | Mounts the real view on the page's sample. Every step target exists for at least one role; every script has a visible step for each role that can open the page; house-rule limits hold; `textFor` keys are real roles; every sample id is negative |
| Leak | After End, no sample record is on the page and the list request went to the server |
| Unsaved text | With a note typed but not saved, the button does not start a tutorial, shows the reason, and the note is untouched |

Existing gates that must stay green: `staticImports.test.js`, the id census,
the coverage gate. 0a adds no route and no migration.

## 7. Constraints

- No inline styles (CSP). No nested buttons.
- `api.js` stays free of DOM and state imports; the responder is injected.
- `tutorial.js` under 500 lines.
- `docs/current-state.md` gains a short Tutorials entry when 0a lands.

## 8. Left to the builder

- Loading a page's two files on demand or with the app.
- The real selectors for the pilot, adding an id where none exists (and
  updating the id census).
- Exact overlay colours and sizes, within `docs/design-system.md`.
- Whether any page caches reference data across loads in a way the Leak test
  must cover beyond the work-order list.

## 9. Calls made by Claude, for the user to check

- Button text "How this page works", as in the preview.
- Only listed GETs are replaced; writes are not blocked, negative ids make
  them harmless.
- The sample puts the viewer on the crew.
- Pilot is four tabs; the SMR-only Invoice tab gets no tutorial (user, 2026-11-23: SMR is finished).
- The pilot wording in 5.6.
