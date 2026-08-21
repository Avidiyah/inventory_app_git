# User Hub P2 — Verification Handoff

**Branch:** `user-hub-p2-technician-hub`, at commit `2c126e5` (HEAD as of this handoff — no new commits were made during this verification pass; the one code fix below is uncommitted in the working tree).

**Context:** All six tasks in `docs/superpowers/plans/2026-08-20-user-hub-p2-technician-hub.md` are implemented in code (folded into two commits, `429b73a` and `2c126e5`, rather than one commit per task). This session ran a live manual-verification pass against that plan's per-task "Manual verification" steps, using the `chrome-devtools` MCP tools against a real running server. It found and fixed one bug, found and left open a second, and did not finish the full checklist — session ended with the user driving the browser directly.

---

## Bug 1 — FIXED, uncommitted

**File:** `backend/static/views/hubClock.js:15`

**Symptom:** Entire app loaded blank — both `#login-screen` and `#app-root` stayed `hidden`, no login form, only a sliver of the background crescent visible.

**Root cause:** `hubClock.js` imported `apiStartWorkOrderTracking`/`apiStopWorkOrderTracking` from `./workOrders.js`. Those two functions are defined and exported by `api.js`; `workOrders.js` only imports them for its own internal use and never re-exports them. That's an invalid named import — a **static** ES-module error, which aborts the entire module graph before any script runs, so `main.js` never reached the code that un-hides the login screen.

**Fix applied** (verified live in a real browser — login screen now renders correctly):

```js
// before
import { apiStartWorkOrderTracking, apiStopWorkOrderTracking, comboHtml } from "./workOrders.js";

// after
import { apiStartWorkOrderTracking, apiStopWorkOrderTracking } from "../api.js";
import { comboHtml } from "./workOrders.js";
```

**Action needed:** commit this. It's currently sitting as an uncommitted change in the working tree.

---

## Bug 2 — OPEN, needs a decision before it can be fixed

**File:** `backend/static/views/hubTechnician.js`, `timelineBlocksHtml` (~line 83)

**Symptom:** The Dashboard tab's timeline strip (Task 5) never positions its blocks correctly — confirmed live that a running session's block does not appear where the data says it should.

**Root cause:** `timelineBlocksHtml` renders each block with an inline attribute:

```js
`<div class="hub-timeline-block..." style="left:${leftPct}%;width:${widthPct}%" ...>`
```

The app's CSP (`backend/app/main.py`, `CONTENT_SECURITY_POLICY`) has no `style-src` directive:

```python
CONTENT_SECURITY_POLICY = "; ".join((
    "default-src 'self'",
    "img-src 'self' data: blob:",
    "media-src 'self' blob:",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
))
```

`style-src` therefore falls back to `default-src 'self'`, which blocks inline `style="..."` attributes outright (no `'unsafe-inline'`, no nonce, no hash allowance). Confirmed live via `getComputedStyle`:

```json
{"attrStyle":"left:74.81481481481481%;width:0.5%","computedLeft":"auto","computedWidth":"auto"}
```

The DOM attribute has the right numbers; the browser refuses to apply them. This is the **only** place in all of `backend/static/views/` that uses an inline `style=` attribute — every other dynamic-positioning need in this codebase (combos, cards, panels) is done with CSS classes instead, consistent with the CSP being intentionally strict. This looks like an oversight in Task 5, not a deliberate exception.

**Not fixed — needs a product/security call, not just a code change:**
- Option A: relax the CSP to add `style-src 'self' 'unsafe-inline'` (or similar). Weakens the security posture app-wide for one widget.
- Option B: rework `timelineBlocksHtml` to avoid inline styles — e.g., set a CSS custom property is *also* blocked the same way (CSSOM `.style` sets hit the same restriction), so the real options are more like: a fixed set of discrete CSS classes bucketed by percentage, or `grid-column` spans computed from a fixed-resolution column count, or a nonce-based CSP for this one dynamically generated fragment. None of these are a one-line fix.

Flag this to the user before choosing a direction — see the conversation where this was raised; they had not yet decided when this session ended.

---

## Environmental gotcha hit during this session (not a code bug, but will recur)

The local `uvicorn` process was started at 8:25 AM without `--reload`. Backend files (`hub.py` etc.) were last modified/committed at ~1:49–1:50 PM the same day. Because there's no `--reload`, Python route registration never picked up the changes — `GET /hub` 404'd on every request for hours, looking exactly like a routing bug, until the process was restarted.

**If `GET /hub` (or any backend route) 404s unexpectedly during dev, check `uvicorn`'s process start time against the last backend commit/edit time before debugging the route code.** Consider always launching with `--reload` during active backend work (see `[[inventory-app-runbook]]` for the launch command) to avoid re-hitting this.

---

## Verification checklist — status

Cross-referencing every "Manual verification" step across the P2 plan's Tasks 1–7:

**Done, passed (after Bug 1 and the stale-server restart):**
- Task 1: hub page reachable, tab bar renders, tab switching works, no console errors.
- Task 2: technician lands on the hub by default; header identity button (name over role) shows as the active nav pill; `Your hub — Test Tech, Technician` aria-label correct.
- Task 4 (clock widget): off-clock state renders (status line, today total, populated "Start on…" combo). **Start** action tested live: switched to on-clock state, showed the correct work order and a "started H:MM" timestamp, and — via the `onChanged` callback — refreshed the dashboard tiles/tab counts in the same round trip. Confirmed server-side persistence afterward (WO 23538724 showed status `In-Progress` / `Test Tech` on the standalone Work Orders page).
- Task 5 (dashboard tab): three count tiles matched the Work Orders page's own filtered counts (6 assigned / 1 in progress / 1 ready to complete). Time Today and Tools Out empty-state copy rendered verbatim as specified. **Timeline strip itself is broken — see Bug 2.**

**Not yet done — pick up here:**
- Task 4 Step 5: the **Stop** action (only Start was tested).
- Task 4 Step 5: the two D18 long-session warning thresholds (480 min / 660 min) — not practical to test in real time; consider a scripted check (e.g., temporarily fake `started_at` further in the past, or read the code path directly) rather than waiting hours.
- Task 4 Step 5: tab-hide/tab-return tick-pause behavior (`stopHubClockTicking` on `visibilitychange`).
- Task 3 / Task 6: **My Work Orders tab** — card list rendering, and the click → `focusWorkOrderNumber` + `showPage("work-orders")` deep-link handoff into solo-card mode. Tab label read "My Work Orders (6)" correctly but the tab body itself was never opened this session.
- Task 6: "View all in Work Orders →" link.
- Task 7 Step 1: full Work Orders page regression pass (technician picker, notes, materials, labor entry, billing editor, tracking start/stop, hold/resume, complete, archive, search, filters, CSV export, NetFacilities card, Mass Stage unit click, a cold-opened shared card link) — as Technician + Supervisor + TechFM OA minimum. Not started.
- Task 7 Step 2: cross-role landing — only Technician was checked. Need Supervisor, TechFM OA, Admin, Owner, including confirming a role with zero assigned work orders gets honest zero tiles, not an error. (Owner was seen mid-session on the Work Orders page, landed there via direct navigation by the user, not verified as a fresh-login landing check.)
- Task 7 Step 3: landing precedence — resumed scan/stock batch should still win over the hub landing page; a cold-opened `/workorder_card/<number>` link should still win too. Not started.
- Task 7 Step 4: edge cases — technician with zero assigned work orders; a session already running when the hub loads (started from a work-order card, not the widget); `GET /hub` failure handling (stop the backend briefly, confirm a message renders instead of a blank widget/thrown error).

## Test account used

`Test Tech` / technician role — already had an active session in the browser at the start of this pass (not logged in by this session; likely already signed in from earlier work). Owner credentials are in memory (`owner` / `owner1`) if a fresh technician login is needed and no session is available — but there was no need to discover a technician password this session since one was already signed in.

## Tooling note

Chrome DevTools MCP could not connect at the start of this session (`Could not connect to Chrome... 127.0.0.1:9222`) because no Chrome instance was running with remote debugging enabled. Fixed for this session by launching one directly:

```bash
"/c/Program Files/Google/Chrome/Application/chrome.exe" --remote-debugging-port=9222 \
  --user-data-dir="C:\Users\mcclu\AppData\Local\Temp\claude\chrome-debug-profile" \
  "http://127.0.0.1:8124/"
```

That profile is a separate, throwaway one — not the user's normal Chrome profile/session. It will need to be relaunched the same way next session unless it's still running.
