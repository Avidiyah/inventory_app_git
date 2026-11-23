# Tutorials 6 — the one-time welcome

> **Rule added by the user 2026-11-23 (overrides anything below):** every box shows ONE simple sentence. A step that needs more is written as a list of sentences (`text: ["...", "..."]`, at most 3, each at most 120 characters) and the player gives each sentence its own tap on the same lit section. Wording tables that hold two sentences in one step are split at the sentence boundary, never merged into a longer sentence. Use plain words a new hire would use; one idea per sentence. See 0a spec 5.2 and 5.4.

Date: 2026-11-23 · Status: awaiting approval · Budget: ≤ 1,200 words · Builds on 0a (player) and 0b (progress record, Tutorials tab)

## 1. Intent

At a person's first sign-in after this ships, a short greeting written by the user appears, followed by a tour that shows where the Tutorials section is. It never appears twice. It is the last thing built, so shipping it is switching it on.

## 2. Goals, non-goals, anti-goals

| Kind | Item |
| --- | --- |
| Goal | Every person sees it exactly once, current and new accounts alike, on any device |
| Goal | Greeting plus at most 5 tour steps; ends with the person knowing where Tutorials lives |
| Goal | Same flow on phone and desktop |
| Non-goal | Progress tracking, the Tutorials tab, red dots (0b); any page tutorial (1–5) |
| Anti-goal | A replay after a closed tab, dead phone or second device |
| Anti-goal | Welcome landing on top of the clock-in prompt, a resumed scan batch or a shared work-order link |
| Anti-goal | A feature flag |

## 3. Decisions already made by the user

- Greeting is written by the user (text owed); then a tour to the Tutorials tab.
- Once per person ever; ended early = never shown again, but listed in the Tutorials tab as not completed and runnable from there.
- Built and switched on only after every other batch is done.

## 4. Approaches (where "is it due?" is decided)

| | Approach | Trade-off |
| --- | --- | --- |
| **A (picked)** | `enterApp` asks the 0b progress routes: no `welcome` row seen → claim it, then show | Covers login and a still-valid session (both end in `enterApp`). One extra GET per sign-in, forever |
| B | Server adds `welcome_due` to `/api/auth/me` and the login reply | No extra request, but couples auth to tutorials and `me` is cached in places |
| C | Show it the first time the Hub loads | Misses people who land elsewhere (shared link, resumed batch) and fires on every Hub reload until seen |

## 5. Design

### 5.1 Trigger and order

`enterApp` (`backend/static/views/auth.js`) is the single funnel for a fresh sign-in (`loginBtn` handler) and an already-signed-in app open (`initAuth` → `apiMe`). The change is one line there: `void maybePromptClockIn(user)` becomes `void runWelcomeThenClockIn(user, { landed })`, in a new `views/welcome.js`.

| Step | Rule |
| --- | --- |
| 1 | Skipped when the landing was not the plain role landing: a resumed scan batch (`resumed`) or a work-order deep link (`deepLinkNumber !== null`). Nothing is recorded, so it comes at the next plain sign-in |
| 2 | `GET` own progress. A `welcome` row with `seen_at` set, or any failure → skip (a failed lookup stays quiet, like the clock-in prompt) |
| 3 | `POST seen` for `welcome`; show only if the reply says `first: true`. A failure → do not show |
| 4 | Run the tour; wait for it to end, by any route |
| 5 | Then `maybePromptClockIn(user)`, only if `getCurrentUser() === user` |

Every role's landing page is the Hub (`LANDING_PAGE_BY_ROLE`), so the tour always starts on it. The Owner is included; the clock-in prompt still skips the Owner by itself.

### 5.2 "Seen" at first appearance

Step 3 writes `seen_at` before anything is drawn, and the server sets it only if still null and says whether it did (`first`). That makes "once ever" atomic across two devices opening at once, and a closed tab, dead phone or sign-out mid-tour never replays it.

### 5.3 Script and player change

The welcome is one 0a script, key `welcome`, in `tutorials/welcome.js`, listed in `tutorials/index.js` as standalone: no page, no sample, no button. The player runs it without the sample responder and without the end-of-run `showPage` reload; it restores only the Hub tab it opened.

The greeting is the **first step of that script**, not a separate screen, so Back, End, the step counter and phone layout come free.

Player change (smallest possible): a step with **no `target` key** is a centred box on the darkened page with nothing lit. A step with a `target` that is missing is still skipped. The two-tap rule is unchanged. The guard test's 240-character and 2-sentence limits are lifted for step 1 of `welcome` only, replaced by 480 characters.

```
 +--------------------------------------+
 |  (page darkened, nothing lit)        |
 |   +------------------------------+   |
 |   |  Welcome                     |   |
 |   |  [GREETING TEXT, up to 480   |   |
 |   |   characters — owed]         |   |
 |   |  1 of 5          End   Next  |   |
 |   +------------------------------+   |
 +--------------------------------------+
```

### 5.4 Reaching the Tutorials tab

| Viewport | How |
| --- | --- |
| Desktop | Step 2 lights `#hub-tab-tutorials` in the tab row; step 3's `open` clicks it |
| Phone | The Hub tabs sit behind `#hub-picker-toggle`. The player's `open` list expands the picker first if `aria-expanded` is false (a click that is already satisfied is skipped), and collapses it again at the end |

Ending leaves the person on the Hub Home tab as they were. A "Done" on the last step marks `welcome` completed (0b's rule: reached the last step).

### 5.5 Tour wording (draft; Hub is where the person lands)

| # | Target | Title | Text |
| --- | --- | --- | --- |
| 1 | none | Welcome | Four sentences, one per tap (user's text, 2026-11-23): "Welcome to TechFM." / "TechFM is Technological Facilities Maintenance: our app for work orders, stock, tools and time." / "Each page has its own tutorial available at the top of the page." / "They are also in the Tutorials section, which we're about to navigate to first." The 3-sentence limit is lifted for this step only |
| 2 | `#hub-tab-tutorials` | Tutorials | The Hub has a Tutorials tab. Everything that teaches you the app is kept there. |
| 3 | Tutorials to-do list (after `open`) | Your to-do list | Tutorials you have not finished are listed here. Tap one to start it. |
| 4 | Completed sub-tab | Completed | Finished ones move to Completed, so you can run them again any time. |
| 5 | The "How this page works" button on the Hub | On every page | Each page has this button by its title. It explains the page you are on. |

If the person ended this welcome early it stays in the to-do list as not completed (0b).

## 6. What this needs from 0a and 0b

| From | Need |
| --- | --- |
| 0a | Targetless step (5.3); a script that runs without sample mode and without the closing `showPage`; an `onEnd(reason)` hook (`done` or `ended`) so the caller can wait and 0b can mark completed |
| 0b | `GET` own progress → rows `(key, seen_at, completed_at)`. `POST` seen: sets `seen_at` only if null, replies `{first}`. `POST` completed: sets `completed_at` |
| 0b | The Tutorials tab lists `welcome` as a to-do (never-run counts as not completed, no red dot before it fires) and starts it from a tap. A manual run never touches `seen_at` |

## 7. Tests

| Test | Proves |
| --- | --- |
| Sequence | Due → welcome shown, clock-in prompt only after it ends; not due → clock-in only; sign-out mid-welcome → no clock-in prompt |
| Skips | `resumed` and deep-link landings skip without a POST |
| Once | `first: false` and POST failure show nothing; `seen` is posted before the box is in the DOM |
| End vs Done | End never posts completed; Done on the last step does |
| Manual run | Running from the tab posts no `seen` |
| Guard | Welcome targets exist on the mounted Hub for every role; ≤ 5 steps after the greeting; limits hold; **fails while the greeting is still the placeholder**, so it cannot ship unwritten |
| Player | A targetless step shows centred with nothing lit; a missing target still skips |

## 8. Constraints

- No inline styles (CSP), no nested buttons; `views/welcome.js` under 500 lines.
- `api.js` stays free of DOM imports. No migration beyond 0b's.
- `docs/current-state.md` gets one line when this lands.

## 9. Left to the builder

- Exact route paths and the `first` field name, following 0b.
- The phone picker open/close mechanics.
- Whether `welcome.js` or `auth.js` owns the `landed` flag.

## 10. Calls made by Claude, for the user to check

- Welcome first, then clock-in prompt.
- Resumed batch and shared-link sign-ins skip the welcome and get it next time.
- If "seen" cannot be recorded, nothing is shown (never risk a replay).
- Greeting as step 1, limit 480 characters.
- The five-step tour wording in 5.5.

## 11. What the user still owes

Nothing: the greeting was supplied 2026-11-23 (section 5.5, step 1). It follows the one-sentence-per-tap rule like every other step, so the 480-character allowance is unused.
