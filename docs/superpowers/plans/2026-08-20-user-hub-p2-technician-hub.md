# User Hub P2 — Technician Hub Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the User Hub page itself — tab shell, the persistent clock widget, the technician dashboard (counts, time-today, timeline strip, tools out), the embedded Work Orders list, and the header/nav/landing wiring that makes the hub the front door for every role.

**Architecture:** P1 already shipped `GET /hub` and everything behind it — this phase is frontend-only, consuming that one endpoint. `views/userHub.js` is the tab shell: it mounts `hubClock.js` (persistent, above the tabs) and `hubTechnician.js` (the Dashboard and My Work Orders tab bodies), and owns the one `GET /hub` fetch every tab reads from. `views/workOrders.js` gains one exported entry point, `mountWorkOrderList`, so the hub's card list is the *same* rendering code the standalone Work Orders page uses — not a second implementation to keep in sync.

**Tech Stack:** Vanilla ES modules (no framework, no build step), matching every existing view under `backend/static/views/`. No new dependencies — the CSP (`default-src 'self'`) rules out a charting or combo-box library, so the timeline strip and the `Start on…` picker are plain DOM/CSS, the same way `views/workOrders.js` already builds its own combo widget.

**Spec:** `docs/superpowers/specs/2026-08-20-user-hub-design.md` — read §4.3–4.6 (frontend files, the `workOrders.js` refactor, the header button, landing precedence), §5.1–5.2 (clock widget, technician dashboard), §6.1 (ticking without polling), §8 (visual language), §10 (edge cases), §11 (testing), §12 (phasing — this plan implements exactly the P2 row and nothing from P3/P4).

**P1 status:** shipped on `user-hub-p1-time-engine` (PR #10). `GET /hub` returns (field names as actually implemented, not the spec's abbreviated sketch):

```
{
  user: { id, first_name, last_name, role },
  server_now, day,
  clock: {
    running_session: { work_order_id, number, started_at, day_counting_from } | null,
    closed_minutes_today, running_minutes_today, adjustment_minutes_today,
    total_minutes_today,   // computed: sum of the three
    adjustments: [ { minutes, recorded_by_name, work_order_number } ],
  },
  timeline: [ { work_order_id, number, started_at, ended_at, auto_closed, minutes } ],
  counts: { assigned, in_progress, ready_to_complete },
  startable: [ { work_order_id, number, status, community, building_number, unit_number, location } ],
  tools_out: [ { tool_id, name, barcode, quantity, since } ],
}
```

---

## Global Constraints

- **P2 ships the *technician-shaped* dashboard for every role.** D3 (three page designs, TechFM OA/Owner reuse Admin) and D9 (Admin's three tabs) are P3/P4. Until then, every authenticated role lands on the same two tabs — Dashboard and My Work Orders — built from the same `GET /hub` payload, which is role-agnostic by construction (P1's `personal_hub` does not branch on role). A Supervisor or Admin with no assigned work orders simply sees honest zeros. This is not a spec deviation; it is what "P2 is technician hub, P3 is supervisor hub" already implies, made explicit here because the landing-page change (D4) puts every role on this page starting with this phase.
- **No frontend test harness exists** (spec §11, verified against the repo — no JS test runner is configured). Every task below substitutes a scripted manual-verification step (via the `chrome-devtools` MCP tools: navigate, snapshot, console-check) for the automated test/run/pass cycle the backend tasks use. This is not a gap this plan introduces; it is the existing, accepted boundary.
- **The `workOrders.js` risk is smaller than the spec worried about.** §4.4 names this the riskiest change in the spec. Verified against the actual file: cards on the list page never expand in place — `summary.addEventListener("click", ...)` always calls `event.preventDefault()` and hands off to `openWorkOrderPage`, which pushes `/workorder_card/<number>` and renders the single card in "solo" mode. So the click-delegation body, the held-card tracking (`isHeld`/`anyCardHeld`), and the realtime single-card repaint all apply *only* to the one expanded solo card — never to a collapsed card in a plain list. The hub's card list only ever shows collapsed cards. **`mountWorkOrderList` therefore needs none of that machinery** — it fetches, renders collapsed cards with the exact existing `buildCard`/`summaryHtml`, and on click hands off to the Work Orders page's own existing deep-link mechanism (`focusWorkOrderNumber` + `showPage("work-orders")`) — the same mechanism the Mass Stage tree and a shared card link already use today. Task 3 implements this; read its preamble before touching the file.
- **`buildCard`'s only change is one new optional parameter** (`{ onOpen }`, defaulting to today's `openWorkOrderPage` call). The Work Orders page's own call site passes nothing, so its behavior is provably unchanged by construction, not by re-testing every branch.
- **Never touch `listEl`'s six delegated listeners, `isHeld`, `anyCardHeld`, `runOrDeferListRefresh`, solo mode, or the realtime subscriber.** None of them need to change for this phase; touching them would be scope creep against the acceptance bar in spec §4.4 ("No behavior change on the Work Orders page").
- **Session-elapsed vs. day-total are two different numbers, both already on the payload.** The clock widget's live "2 h 47 m" ticks from `running_session.started_at` (session elapsed — matches "started 8:12 AM" directly below it in the spec's mockup). The Dashboard's "Time today" hero ticks from `running_session.day_counting_from` plus `closed_minutes_today` plus `adjustment_minutes_today` (today's total — see P1's `day_counting_from` correction). Conflating them reports an hour of "today" for a session that gave today thirty minutes. See `hubClock.js` Task 4 and `hubTechnician.js` Task 5.
- **Self-warnings (D18) key off *session* elapsed, not day total** — the 12-hour cap is per-session (`LABOR_SESSION_MAX_MINUTES = 720` from that session's own `started_at`), so 8 h/11 h are compared against `now − running_session.started_at`, never against today's total.
- **The "switch clocks" confirm dialog in spec §5.1 ("Stop your clock on WO 88190 and start on WO 88214?") is deliberately not built in P2.** Verified against `services/work_orders.py::start_labor_session`: starting while another session runs already closes it automatically and safely server-side (no data loss, the other row's notification is preserved via `side_transitions`), with no confirmation required by the API. The widget's off-clock state only ever offers "Start on…" when `running_session` is already `null` at fetch time, so the only way this path is reached with another session actually still live is a stale payload from a race with a concurrent start elsewhere — narrow, and P2 has no realtime push to close that window (that is P3's `labor.session.changed`). Building a confirm dialog for a race this narrow, with no live signal to trigger it accurately, is deferred rather than built speculatively; note it if P3's realtime event makes the race visible enough to matter.
- **No new nav button, no new backend route, no new realtime event.** The header identity button is the only nav affordance (D10); `GET /hub` is the only endpoint this phase reads; `labor.session.changed` is P3.
- **Frosted panel is the default for free.** `styles.css`'s global `section { background-color: var(--panel-bg); ... }` rule already gives every `<section>` the app's default frosted-panel treatment — most of this phase's new markup needs no new panel CSS, only layout (grid/flex) rules.
- **Commit message style:** `feat(user-hub): …` / `docs(user-hub): …`, matching P1's history.
- **Work on a branch.** `git checkout -b user-hub-p2-technician-hub` off `main` before Task 1 (P1's PR is not yet merged; branch off `main` regardless — rebase onto P1 once #10 lands, or ask the owner whether to branch off `user-hub-p1-time-engine` instead if it is still open when this plan starts). Merging to `main` deploys to production — the merge is the owner's call.
- **Never truncate an existing file.** Every "Modify" step below is a targeted insertion at a located line. Read first, edit in place.

---

## File Structure

```
backend/app/main.py                    EDIT  register pages/user-hub.html in SHELL_PARTS
backend/static/api.js                  EDIT  add apiGetHub()
backend/static/pages/user-hub.html     NEW   fragment: clock widget mount point + tab bar + 2 tab bodies
backend/static/views/userHub.js        NEW   tab shell: one GET /hub fetch, mounts hubClock + hubTechnician
backend/static/views/hubClock.js       NEW   the persistent ticking clock widget (§5.1)
backend/static/views/hubTechnician.js  NEW   Dashboard tab (tiles, time-today, timeline, tools out) + My Work Orders tab
backend/static/shell-head.html         EDIT  #auth-user-indicator span -> button (§4.5)
backend/static/views/nav.js            EDIT  PAGE_ACCESS + LANDING_PAGE_BY_ROLE + visiblePageCount exclusion + loadUserHub wiring
backend/static/views/auth.js           EDIT  identity button fill via roleLabel()
backend/static/views/users.js          EDIT  same fix at its second call site
backend/static/views/workOrders.js     EDIT  buildCard({ onOpen }) + export mountWorkOrderList
backend/static/main.js                 EDIT  side-effect import ./views/userHub.js
backend/static/styles.css              EDIT  .user-hub-btn, hub tab bar, clock widget, dashboard tiles, timeline strip
```

Six new frontend modules become five: the spec's `static/pages/user-hub.html` + `userHub.js` + `hubClock.js` + `hubTechnician.js` (P2's slice of its 4-file frontend list — `hubSupervisor.js`/`hubAdmin.js` are P3/P4 and do not exist yet).

---

### Task 1: Page shell, API wrapper, tab switching

Gets a navigable (empty-bodied) hub page into the DOM and wired into `main.js`, so every later task has somewhere to render into and can be checked in the browser immediately.

**Files:**
- Modify: `backend/app/main.py` (SHELL_PARTS tuple, line ~341)
- Modify: `backend/static/api.js` (append near the work-orders wrappers, after `apiGetWorkOrder`, line ~481)
- Create: `backend/static/pages/user-hub.html`
- Create: `backend/static/views/userHub.js`
- Modify: `backend/static/main.js` (side-effect import block)
- Modify: `backend/static/styles.css` (tab bar only)

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `api.js::apiGetHub() -> Promise<HubResponse>` — `GET /hub`, the shape in this plan's header.
  - `userHub.js::loadUserHub()` — called by `nav.js::showPage("user-hub")`; fetches once, mounts the clock widget and the active tab.
  - Markup IDs `user-hub-page`, `hub-clock-mount`, `hub-tabs`, `hub-tab-dashboard`, `hub-tab-work-orders`, `hub-tabpanel-dashboard`, `hub-tabpanel-work-orders` — the contract every later task's JS reads.

- [ ] **Step 1: Add the API wrapper**

In `backend/static/api.js`, immediately after `apiGetWorkOrder` (which ends `}` around line 481), insert:

```js
// --- User Hub ------------------------------------------------------
export async function apiGetHub() {
  return liveGet("/hub");
}
```

- [ ] **Step 2: Create the page fragment**

Create `backend/static/pages/user-hub.html`:

```html
    <!-- =================== USER HUB PAGE =================== -->
    <!-- The landing page for every role (D4). Static shell only: the clock
         widget and both tab bodies are built by views/hubClock.js and
         views/hubTechnician.js, orchestrated by views/userHub.js. Reached
         via the header identity button (#auth-user-indicator, see
         shell-head.html) -- there is no button in #main-nav (D10). -->
    <div class="page" id="user-hub-page">

        <section id="hub-clock-mount" aria-live="polite"></section>

        <nav id="hub-tabs" class="hub-tabs" aria-label="User hub sections">
            <button type="button" class="hub-tab active" id="hub-tab-dashboard" data-hub-tab="dashboard" aria-selected="true" role="tab">Dashboard</button>
            <button type="button" class="hub-tab" id="hub-tab-work-orders" data-hub-tab="work-orders" aria-selected="false" role="tab">My Work Orders</button>
        </nav>

        <div class="hub-tabpanel active" id="hub-tabpanel-dashboard" role="tabpanel"></div>
        <div class="hub-tabpanel" id="hub-tabpanel-work-orders" role="tabpanel" hidden></div>

    </div>
```

- [ ] **Step 3: Register the fragment in the shell**

In `backend/app/main.py`, in the `SHELL_PARTS` tuple (line ~341), insert `"pages/user-hub.html",` as the first page fragment, immediately after `"shell-head.html",` and before `"pages/create-item.html",`. It goes first because it is the landing page for every role — reading `SHELL_PARTS` top to bottom should read like the app's own priority order:

```python
SHELL_PARTS = (
    "shell-head.html",          # head, login, header/nav, <main>
    "pages/user-hub.html",
    "pages/create-item.html",
    "pages/saved-items.html",
```

(Leave every other tuple entry exactly as it is — this is a one-line insertion, not a reordering.)

- [ ] **Step 4: Write the tab shell**

Create `backend/static/views/userHub.js`:

```js
// View: User Hub tab shell.
//
// Layer: views. The landing page for every role (D4). Owns the one GET /hub
// fetch every tab reads from, the persistent clock widget above the tabs
// (mounted once, refreshed on every reload), and switching between the
// Dashboard and My Work Orders tab bodies. Role-specific dashboards
// (Supervisor/Admin) are P3/P4; every role sees this same shape for now,
// built from the same role-agnostic payload GET /hub already returns.

import { apiGetHub } from "../api.js";
import { friendlyError } from "../format.js";
import { setMessage } from "../dom.js";
import { mountHubClock } from "./hubClock.js";
import { mountHubDashboard, mountHubWorkOrders } from "./hubTechnician.js";

const tabButtons = document.querySelectorAll(".hub-tab");
const tabPanels = {
  dashboard: document.getElementById("hub-tabpanel-dashboard"),
  "work-orders": document.getElementById("hub-tabpanel-work-orders"),
};
const clockMount = document.getElementById("hub-clock-mount");

let activeTab = "dashboard";
let latestPayload = null;

function showTab(name) {
  activeTab = name;
  tabButtons.forEach((btn) => {
    const on = btn.dataset.hubTab === name;
    btn.classList.toggle("active", on);
    btn.setAttribute("aria-selected", String(on));
  });
  Object.entries(tabPanels).forEach(([key, panel]) => {
    panel.hidden = key !== name;
    panel.classList.toggle("active", key === name);
  });
  if (latestPayload) renderActiveTab();
}

function renderActiveTab() {
  if (activeTab === "dashboard") {
    mountHubDashboard(tabPanels.dashboard, latestPayload);
  } else {
    mountHubWorkOrders(tabPanels["work-orders"], latestPayload);
  }
}

tabButtons.forEach((btn) => {
  btn.addEventListener("click", () => showTab(btn.dataset.hubTab));
});

// Called by nav.js on every activation of the hub page. A fresh fetch on
// every entry (not a cache) matches the rest of the app's data-driven pages
// (loadWorkOrders, loadTools, ...) -- the hub is exactly the kind of page
// where "stale since I last looked" is the failure mode to avoid.
export async function loadUserHub() {
  try {
    latestPayload = await apiGetHub();
  } catch (err) {
    clockMount.innerHTML = `<p class="error">${friendlyError(err, "Could not load your hub.")}</p>`;
    return;
  }
  mountHubClock(clockMount, latestPayload);
  renderActiveTab();
}

// Exposed so hubClock.js can ask for a fresh payload after a Start/Stop
// action changes the running session -- one fetch serves the clock and
// both tabs, so a start/stop refreshes all three consistently rather than
// only the widget that triggered it.
export async function refreshUserHub() {
  await loadUserHub();
}
```

- [ ] **Step 5: Add stub `hubClock.js` and `hubTechnician.js` exports**

Task 4 and Task 5 write these for real; `userHub.js` needs them to exist and export the right names *now* so the page does not throw on load. Create `backend/static/views/hubClock.js`:

```js
// View: the persistent clock widget, above the User Hub's tabs.
// Layer: views. See Task 4 in the P2 plan for the full implementation.

export function mountHubClock(container, payload) {
  container.innerHTML = `<p class="hint">Clock widget coming soon.</p>`;
}
```

Create `backend/static/views/hubTechnician.js`:

```js
// View: the User Hub's Dashboard and My Work Orders tab bodies.
// Layer: views. See Tasks 5-6 in the P2 plan for the full implementation.

export function mountHubDashboard(container, payload) {
  container.innerHTML = `<p class="hint">Dashboard coming soon.</p>`;
}

export function mountHubWorkOrders(container, payload) {
  container.innerHTML = `<p class="hint">Work orders coming soon.</p>`;
}
```

- [ ] **Step 6: Wire nav.js's page-activation call and main.js's import**

This step only makes `loadUserHub` reachable by direct call for a manual smoke test — the page is not yet linked from the header (Task 2) or landable-on (Task 2's `LANDING_PAGE_BY_ROLE`), so route to it by hand in the browser console during Step 7.

In `backend/static/main.js`, add the side-effect import alongside the other view imports (after `import "./views/tools.js";`, before `import "./views/toolCheckout.js";` — alphabetical-ish grouping is not enforced elsewhere in this list, so append at the end of the block instead, immediately before `import "./views/auth.js";`, since `auth.js` must stay last — it is the one that calls `initAuth()` implicitly via its own module-load side effects and is already listed last):

```js
import "./views/toolCorrection.js";
import "./views/push.js";
import "./views/userHub.js";
import "./views/auth.js";
```

Do **not** wire `nav.js` yet — that is Task 2, alongside the header button that makes the page reachable normally. For this task's manual check, activate it directly.

- [ ] **Step 7: Manual verification**

```
Start the app locally per the runbook (port 8124). Sign in as any user.
Open the browser devtools console and run:
  document.querySelectorAll(".page").length   // should include user-hub-page
  document.getElementById("user-hub-page")    // should exist, currently not .active
Force it active for this check only:
  document.getElementById("user-hub-page").classList.add("active")
```

Expected: the page renders with the tab bar (Dashboard / My Work Orders, Dashboard active), and clicking "My Work Orders" switches the active tab class without a console error. The clock mount shows "Clock widget coming soon." and each tab shows its stub message. Remove the forced `.active` class before moving on (`classList.remove("active")`) — the page has no real route into it yet.

- [ ] **Step 8: Commit**

```bash
git add backend/app/main.py backend/static/api.js backend/static/pages/user-hub.html \
        backend/static/views/userHub.js backend/static/views/hubClock.js \
        backend/static/views/hubTechnician.js backend/static/main.js
git commit -m "feat(user-hub): add the hub page shell and tab switching"
```

---

### Task 2: Header identity button, nav wiring, landing page

Makes the hub reachable and lands every role on it. Bundled as one task (rather than split across "markup" and "nav wiring" tasks) because the button would otherwise be invisible the moment it is committed: `nav.js`'s `applyRoleVisibility` hides every `.nav-btn` whose `data-page` fails `canAccessPage`, and the identity button is collected by the same `document.querySelectorAll(".nav-btn")` nav.js already runs (§4.5's whole point) — so the markup and the `PAGE_ACCESS` entry must land together or the header identity element disappears until they do.

**Files:**
- Modify: `backend/static/shell-head.html` (`#auth-user-indicator`, line 146)
- Modify: `backend/static/views/nav.js` (`PAGE_ACCESS`, `LANDING_PAGE_BY_ROLE`, `applyRoleVisibility`'s count, `showPage`)
- Modify: `backend/static/views/auth.js` (`enterApp`, line ~102)
- Modify: `backend/static/views/users.js` (line ~220-221)
- Modify: `backend/static/styles.css` (`#auth-user-indicator` rule, line 1664, and the new `.user-hub-btn` rule)

**Interfaces:**
- Consumes: `roles.js::roleLabel` (existing), `userHub.js::loadUserHub` (Task 1).
- Produces: the hub reachable by click, landed-on by default, and role-labeled correctly everywhere `#auth-user-indicator` is written.

- [ ] **Step 1: Markup — span to button**

In `backend/static/shell-head.html`, replace line 146:

```html
            <span id="auth-user-indicator"></span>
```

with:

```html
            <button id="auth-user-indicator" type="button" class="nav-btn user-hub-btn" data-page="user-hub">
                <svg class="nav-ico" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/><path d="M10 20v-6h4v6"/></svg>
                <span class="user-hub-name"></span>
                <span class="user-hub-role"></span>
            </button>
```

- [ ] **Step 2: `nav.js` — access, landing, count, and the page-activation call**

In `backend/static/views/nav.js`, add `user-hub` to `PAGE_ACCESS` (after the closing `};` is too late — insert as a new key; place it first since it is the landing page for everyone):

```js
export const PAGE_ACCESS = {
  // The landing page for every role (D4). No nav button reads this key --
  // the header identity button is wired directly, and this entry exists so
  // `canAccessPage`/`landingPageForRole` have one source of truth to check
  // against, same as every other page.
  "user-hub": ["owner", "admin", "techfm_oa", "supervisor", "technician"],
  "create-item": ["owner", "admin", "techfm_oa"],
```

Change `LANDING_PAGE_BY_ROLE` so every role lands on the hub:

```js
const LANDING_PAGE_BY_ROLE = {
  technician: "user-hub",
  supervisor: "user-hub",
  techfm_oa: "user-hub",
  admin: "user-hub",
  owner: "user-hub",
};
```

Exclude `user-hub` from the compact-nav threshold count in `applyRoleVisibility` — it draws no button in `#main-nav`, so counting its key would inflate every role's count by one for nothing rendered:

```js
  const visiblePageCount = Object.keys(PAGE_ACCESS)
    .filter((page) => page !== "user-hub")
    .filter(page => canAccessPage(role, page)).length;
```

Add the page-activation call in `showPage`, alongside every other data-driven page (insert as a new `if` branch — place first, matching its landing-page priority, right after the `if (pageName === "transaction")` branch since that stays the resumed-batch destination and both are checked first):

```js
  if (pageName === "transaction") {
    enterTransactionPage();
  } else if (pageName === "user-hub") {
    loadUserHub();
  } else if (pageName === "history") {
```

And the import, alongside the other view imports at the top of the file:

```js
import { loadWorkOrders, loadIntegrationsPage } from "./workOrders.js";
import { loadUserHub } from "./userHub.js";
import { loadAdminReview } from "./adminReview.js";
```

`nav.js` importing `userHub.js`, and `userHub.js`/`hubTechnician.js` importing `showPage` from `nav.js` (Task 3, for the card-click handoff) is the same shape `massStage.js` and `transactions.js` already have with `nav.js` today — verified, not a new pattern.

- [ ] **Step 3: `auth.js` — render the identity button through `roleLabel`**

In `backend/static/views/auth.js`, add the import:

```js
import { applyRoleVisibility, canAccessPage, landingPageForRole, showPage } from "./nav.js";
import { roleLabel } from "../roles.js";
```

Replace line 102:

```js
  authUserIndicator.textContent = `${formatUserName(user)} (${user.role})`;
```

with:

```js
  authUserIndicator.querySelector(".user-hub-name").textContent = formatUserName(user);
  authUserIndicator.querySelector(".user-hub-role").textContent = roleLabel(user.role);
  authUserIndicator.setAttribute(
    "aria-label",
    `Your hub — ${formatUserName(user)}, ${roleLabel(user.role)}`
  );
```

- [ ] **Step 4: `users.js` — same fix at its own-name-update call site**

In `backend/static/views/users.js`, add the import (alongside the existing `roles.js` import at line 35):

```js
import { assignableRoles, canManage, roleAtLeast, roleLabel } from "../roles.js";
```

Replace lines 220-221:

```js
        const indicator = document.getElementById("auth-user-indicator");
        if (indicator) indicator.textContent = `${formatUserName(updated)} (${updated.role})`;
```

with:

```js
        const indicator = document.getElementById("auth-user-indicator");
        if (indicator) {
          indicator.querySelector(".user-hub-name").textContent = formatUserName(updated);
          indicator.querySelector(".user-hub-role").textContent = roleLabel(updated.role);
          indicator.setAttribute(
            "aria-label",
            `Your hub — ${formatUserName(updated)}, ${roleLabel(updated.role)}`
          );
        }
```

- [ ] **Step 5: CSS — the button's layout override + tab bar (from Task 1)**

In `backend/static/styles.css`, replace the `#auth-user-indicator` rule (line 1664):

```css
#auth-user-indicator {
    color: var(--gray-200);
}
```

with:

```css
/* The identity button inherits .nav-btn's box entirely (padding, hover,
   active-page highlight, box-shadow underline) -- this only restacks its
   contents: name over role, role a step smaller and dimmer, matching the
   two-line reading order in the design spec's header mockup. */
#auth-user-indicator.user-hub-btn {
    flex-direction: column;
    align-items: flex-start;
    gap: 0;
    line-height: 1.2;
}

.user-hub-name {
    font-size: var(--fs-sm);
}

.user-hub-role {
    font-size: var(--fs-xs);
    color: var(--text-panel-mute);
}

#auth-user-indicator.user-hub-btn.active .user-hub-role {
    /* Dimmer role text would fail contrast on the brand-red active pill --
       let it inherit the button's own (white) active-state color instead. */
    color: inherit;
}
```

Add the tab bar rules (Task 1's markup, styled now that the page is reachable):

```css
.hub-tabs {
    display: flex;
    gap: var(--space-2);
    border-bottom: var(--border);
    margin-bottom: var(--space-4);
}

.hub-tab {
    background: none;
    border: none;
    border-bottom: 2px solid transparent;
    padding: var(--space-2) var(--space-3);
    min-height: var(--btn-h-sm);
    color: var(--text-panel-mute);
    font-weight: var(--fw-semibold);
    cursor: pointer;
}

.hub-tab.active {
    color: var(--text-panel);
    border-bottom-color: var(--color-brand);
}

.hub-tabpanel {
    display: none;
}

.hub-tabpanel.active {
    display: block;
}
```

Confirm `--fs-xs` exists as a token (it is used elsewhere in the stylesheet for secondary text); if the codebase does not define it, use `0.8125rem` directly instead of introducing a new token — this phase introduces no new design tokens per spec §8.

- [ ] **Step 6: Manual verification**

```
Reload the app. Sign in as a technician.
```

Expected: lands on the hub page (Dashboard tab, still showing Task 1's stub content). The header shows a two-line button — name over role — with a home icon, and it is highlighted (brand-red pill) as the active page. Click "Work Orders" in the main nav, then click the header identity button: it returns to the hub. Sign in as an Admin (or any other role) in a second check: also lands on the hub. Confirm in devtools that `document.querySelectorAll(".nav-btn.active")` contains exactly the identity button while on the hub, and that a Technician's visible nav-button count is still 4 (unchanged from before this task — `#main-nav .nav-btn:not([hidden])`).

- [ ] **Step 7: Commit**

```bash
git add backend/static/shell-head.html backend/static/views/nav.js \
        backend/static/views/auth.js backend/static/views/users.js backend/static/styles.css
git commit -m "feat(user-hub): wire the header identity button and land every role on the hub"
```

---

### Task 3: `mountWorkOrderList` — the real card list, embeddable

The one task this plan's Global Constraints section already de-risked: no click-delegation, hold-tracking, or realtime machinery needs to move. Read the Global Constraints entry on this before starting.

**Files:**
- Modify: `backend/static/views/workOrders.js` (`buildCard`, line ~1208; new export near `focusWorkOrderNumber`, line ~1317)

**Interfaces:**
- Consumes: nothing new (existing `apiListWorkOrders`, `summaryHtml`, `focusWorkOrderNumber` from earlier in the same file).
- Produces:
  - `workOrders.js::buildCard(card, { onOpen } = {})` — `onOpen`, if given, replaces the default `openWorkOrderPage({ id: card.id, number: card.number })` call the summary's click handler makes. Existing call sites (`renderCards`, `showSoloCard`) pass nothing, so their behavior is unchanged.
  - `workOrders.js::mountWorkOrderList({ container, lockedFilter, onOpen } = {}) -> { refresh: () => Promise<void> }` — fetches `apiListWorkOrders(lockedFilter || {})` and renders collapsed cards into `container` using the same `buildCard`. `onOpen(card)` fires on a card click instead of `openWorkOrderPage`, so a second caller (the hub) can hand the click off to `focusWorkOrderNumber` + a `showPage` it supplies, without `workOrders.js` importing `nav.js` (avoiding the only import-cycle direction this codebase does *not* already have — `nav.js` imports `workOrders.js`, and the caller of `mountWorkOrderList` supplies navigation instead of `workOrders.js` reaching for it itself).

- [ ] **Step 1: Parameterize `buildCard`'s click handler**

In `backend/static/views/workOrders.js`, locate `buildCard` (line ~1208). Change its signature and the summary click handler:

```js
function buildCard(card) {
```

becomes:

```js
function buildCard(card, { onOpen } = {}) {
```

And the click handler body (currently):

```js
  summary.addEventListener("click", (event) => {
    // Cards navigate rather than expand in place. `preventDefault` suppresses
    // the native toggle, and covers the keyboard path with it: Enter and Space
    // on a focused summary both dispatch a click, so there is no second path
    // to intercept. It also makes the card page's own card non-collapsible,
    // which is right -- there is nothing to collapse to.
    event.preventDefault();
    if (soloActive) return;
    void openWorkOrderPage({ id: card.id, number: card.number });
  });
```

becomes:

```js
  summary.addEventListener("click", (event) => {
    // Cards navigate rather than expand in place. `preventDefault` suppresses
    // the native toggle, and covers the keyboard path with it: Enter and Space
    // on a focused summary both dispatch a click, so there is no second path
    // to intercept. It also makes the card page's own card non-collapsible,
    // which is right -- there is nothing to collapse to.
    event.preventDefault();
    if (soloActive) return;
    if (onOpen) {
      onOpen(card);
      return;
    }
    void openWorkOrderPage({ id: card.id, number: card.number });
  });
```

Every existing call (`cards.forEach((c) => listEl.appendChild(buildCard(c)))` in `renderCards`, and `buildCard(detail)` in `showSoloCard`) passes no second argument, so `onOpen` is `undefined` and the `if (onOpen)` branch never fires for them — behavior is unchanged by construction.

- [ ] **Step 2: Add `mountWorkOrderList`**

Immediately after `focusWorkOrderNumber` (line ~1317, right before the `// Render \`detail\` as the only card...` comment that introduces `showSoloCard`), insert:

```js
// A second, independent card-list renderer for a container other than
// `#work-orders-list` -- the User Hub's "My Work Orders" tab (spec §4.4).
// Deliberately does NOT reuse listEl, the six delegated listeners, solo
// mode, held-card tracking, or the realtime subscriber: none of that
// machinery is reachable from a *collapsed* card (see this plan's Global
// Constraints for why), and a collapsed card is all this ever renders --
// a click hands off to `onOpen` instead of expanding in place, exactly like
// the standalone page's own collapsed cards already do via `openWorkOrderPage`.
//
// `lockedFilter` is forwarded to `apiListWorkOrders` as-is (the same
// {status, serviceType, supervisorId, community, priority, scheduledDate,
// q, limit} shape that function already accepts). The technician's own
// scope needs no filter at all -- `apiListWorkOrders` is already scoped
// server-side per role (`_scoped_to_user`), so an unfiltered call already
// returns exactly "my work orders" for a Technician. A future Supervisor/
// Admin caller (P3/P4) passes `{ supervisorId }` or nothing, respectively.
export function mountWorkOrderList({ container, lockedFilter = null, onOpen } = {}) {
  async function refresh() {
    container.innerHTML = `<p class="hint">Loading…</p>`;
    let cards;
    try {
      cards = await apiListWorkOrders(lockedFilter || {});
    } catch (err) {
      container.innerHTML = `<p class="error">${escapeHtml(friendlyError(err, "Could not load work orders."))}</p>`;
      return;
    }
    container.innerHTML = "";
    if (!cards.length) {
      container.innerHTML = `<p class="hint">No work orders match.</p>`;
      return;
    }
    cards.forEach((card) => container.appendChild(buildCard(card, { onOpen })));
  }
  return { refresh };
}
```

- [ ] **Step 3: Manual verification — the acceptance bar**

```
Reload the app. Open the Work Orders page as a technician with at least
one assigned work order.
```

Expected, unchanged from before this task: the list renders, clicking a card opens it in solo mode with the URL updated to `/workorder_card/<number>`, the Back control returns to the list, and every existing interaction (technician picker, notes, labor, tracking start/stop) inside an expanded card still works. This is the regression check the spec's acceptance bar names — confirm it explicitly rather than assuming the additive change is safe.

Then, in the devtools console, smoke-test the new function directly (the hub does not call it yet — that is Task 6):

```js
import("/static/views/workOrders.js").then(async (m) => {
  const scratch = document.createElement("div");
  document.body.appendChild(scratch);
  const { refresh } = m.mountWorkOrderList({ container: scratch, onOpen: (card) => console.log("would open", card.number) });
  await refresh();
  console.log(scratch.querySelectorAll("details.wo-card").length);
});
```

Expected: logs a card count matching the technician's assigned work orders, and clicking a rendered card's summary logs `would open <number>` instead of navigating. Remove the scratch element afterward.

- [ ] **Step 4: Commit**

```bash
git add backend/static/views/workOrders.js
git commit -m "feat(user-hub): export a mountable work-order list for the hub"
```

---

### Task 4: The clock widget (`hubClock.js`)

**Files:**
- Modify: `backend/static/views/hubClock.js` (replace Task 1's stub)
- Modify: `backend/static/styles.css` (clock widget + combo classes it reuses)

**Interfaces:**
- Consumes: `GET /hub`'s `clock` block (`running_session`, `closed_minutes_today`, `running_minutes_today`, `adjustment_minutes_today`, `total_minutes_today`), `server_now`, `startable` (Task 1's payload shape); `apiStartWorkOrderTracking`, `apiStopWorkOrderTracking` (existing `api.js`); `comboHtml` (exported this task from `workOrders.js`, mirroring its existing internal use).
- Produces: `hubClock.js::mountHubClock(container, payload)` (replaces Task 1's stub with the real widget); a private ticking interval owned entirely by this module, started/stopped on mount/unmount.

- [ ] **Step 1: Export `comboHtml` from `workOrders.js`**

In `backend/static/views/workOrders.js`, change:

```js
function comboHtml({ id, extraClass, nativeSelectHtml, options, selectedValue, ariaLabel }) {
```

to:

```js
export function comboHtml({ id, extraClass, nativeSelectHtml, options, selectedValue, ariaLabel }) {
```

Pure HTML-string function, no state, no `listEl` reference (already confirmed reading it) — this is a zero-risk export.

- [ ] **Step 2: Write the widget**

Replace `backend/static/views/hubClock.js` entirely:

```js
// View: the persistent clock widget above the User Hub's tabs.
//
// Layer: views. Every role's one clock, in one place (D8). Mounted once per
// `loadUserHub()` call; owns its own 1-second tick interval, started on
// mount and cleared on the next mount (page re-entry) or explicitly via
// `unmountHubClock` (tab-hide safety net, spec §6.1).
//
// Two different elapsed numbers, both derived from the same payload and
// never confused: the widget's own hero figure ticks *session* elapsed from
// `running_session.started_at` ("started 8:12 AM" directly below it, spec
// §5.1's mockup). The Dashboard tab's "Time today" hero (hubTechnician.js)
// ticks from `running_session.day_counting_from` instead -- see this plan's
// Global Constraints for why they must stay separate.

import { apiStartWorkOrderTracking, apiStopWorkOrderTracking, comboHtml } from "./workOrders.js";
import { escapeHtml, friendlyError } from "../format.js";
import { setMessage } from "../dom.js";

// D18: the technician's own long-clock warnings, keyed off *session*
// elapsed minutes -- mirrors the constants the design spec assigns to
// `domain/hub.py` (deferred to P3; duplicated here as plain numbers since
// nothing server-side reads them yet). 720 is `LABOR_SESSION_MAX_MINUTES`.
const LONG_SESSION_WARN_MINUTES = 480;
const SESSION_CAP_WARN_MINUTES = 660;

let container = null;
let payload = null;
let skewMs = 0; // server_now - Date.now() at fetch time
let tickHandle = null;
let comboOpen = false;
let refreshCallback = null; // set by mountHubClock's `onChanged` option

function formatHm(totalMinutes) {
  const minutes = Math.max(0, Math.round(totalMinutes));
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (!h) return `${m} m`;
  return `${h} h ${m} m`;
}

function nowWithSkew() {
  return Date.now() + skewMs;
}

function sessionElapsedMinutes() {
  if (!payload?.clock?.running_session) return 0;
  const startedAt = new Date(payload.clock.running_session.started_at).getTime();
  return (nowWithSkew() - startedAt) / 60000;
}

function warningHtml() {
  const elapsed = sessionElapsedMinutes();
  if (elapsed >= SESSION_CAP_WARN_MINUTES) {
    return `<p class="hub-clock-warning" role="alert">⚠ At 12 h this session is capped and your time stops counting.</p>`;
  }
  if (elapsed >= LONG_SESSION_WARN_MINUTES) {
    return `<p class="hub-clock-warning" role="alert">⚠ Still on the clock after 8 h — did you forget to stop?</p>`;
  }
  return "";
}

function onClockHtml() {
  const session = payload.clock.running_session;
  const place = [session.number ? `WO ${session.number}` : null]
    .filter(Boolean)
    .join(" · ");
  return `
    <div class="hub-clock hub-clock-on">
      <p class="hub-clock-status"><span class="hub-clock-dot"></span> ON THE CLOCK</p>
      <p class="hub-clock-subject">${escapeHtml(place)}</p>
      <div class="hub-clock-row">
        <div>
          <p class="hub-clock-hero">${escapeHtml(formatHm(sessionElapsedMinutes()))}</p>
          <p class="hub-clock-started">started ${escapeHtml(
            new Date(session.started_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
          )}</p>
        </div>
        <button type="button" class="hub-clock-stop-btn" data-action="hub-clock-stop">Stop</button>
      </div>
      ${warningHtml()}
      <p class="hub-clock-message" id="hub-clock-message"></p>
    </div>`;
}

function startableOptionsHtml() {
  return (payload.startable || []).map((wo) => {
    const place = [wo.community, wo.building_number ? `Bldg ${wo.building_number}` : null, wo.unit_number ? `Unit ${wo.unit_number}` : null]
      .filter(Boolean)
      .join(" · ") || wo.location || "";
    const label = place ? `WO ${wo.number} — ${place}` : `WO ${wo.number}`;
    return { value: wo.work_order_id, label };
  });
}

function offClockHtml() {
  const options = startableOptionsHtml();
  const combo = options.length
    ? comboHtml({
        id: "hub-clock-start-list",
        extraClass: "hub-clock-combo",
        nativeSelectHtml: `<select class="wo-combo-native" hidden aria-hidden="true">${options
          .map((opt) => `<option value="${escapeHtml(opt.value)}">${escapeHtml(opt.label)}</option>`)
          .join("")}</select>`,
        options,
        selectedValue: null,
        ariaLabel: "Start tracking on…",
      })
    : `<p class="hint">Nothing assigned to start a clock on yet.</p>`;
  return `
    <div class="hub-clock hub-clock-off">
      <p class="hub-clock-status">○ Not clocked in</p>
      <div class="hub-clock-row">
        <p class="hub-clock-today">Today <strong>${escapeHtml(formatHm(payload.clock.total_minutes_today))}</strong></p>
        <div class="hub-clock-start-wrap">
          ${combo}
          <button type="button" class="hub-clock-start-btn" data-action="hub-clock-start" ${options.length ? "" : "disabled"}>Start</button>
        </div>
      </div>
      <p class="hub-clock-message" id="hub-clock-message"></p>
    </div>`;
}

function render() {
  container.innerHTML = payload.clock.running_session ? onClockHtml() : offClockHtml();
}

function tick() {
  if (!payload?.clock?.running_session) return;
  const hero = container.querySelector(".hub-clock-hero");
  if (hero) hero.textContent = formatHm(sessionElapsedMinutes());
  const warning = container.querySelector(".hub-clock-warning");
  const freshWarning = warningHtml();
  if (!warning && freshWarning) {
    render(); // a threshold was just crossed -- rebuild once to insert it
  } else if (warning && !freshWarning) {
    render();
  }
}

function stopTicking() {
  if (tickHandle !== null) {
    clearInterval(tickHandle);
    tickHandle = null;
  }
}

function startTicking() {
  stopTicking();
  tickHandle = setInterval(tick, 1000);
}

async function handleStart(workOrderId) {
  const message = document.getElementById("hub-clock-message");
  try {
    await apiStartWorkOrderTracking(workOrderId);
  } catch (err) {
    setMessage(message, friendlyError(err, "Could not start tracking."), "error");
    return;
  }
  if (refreshCallback) await refreshCallback();
}

async function handleStop() {
  const session = payload?.clock?.running_session;
  if (!session) return;
  const message = document.getElementById("hub-clock-message");
  try {
    await apiStopWorkOrderTracking(session.work_order_id);
  } catch (err) {
    setMessage(message, friendlyError(err, "Could not stop tracking."), "error");
    return;
  }
  if (refreshCallback) await refreshCallback();
}

// `onChanged` is called after a successful Start/Stop, and is expected to
// re-fetch GET /hub and remount -- userHub.js supplies its own
// `refreshUserHub`, so a Start/Stop here also refreshes the Dashboard tab's
// counts and timeline in the same round trip, not just this widget.
export function mountHubClock(mountEl, newPayload, { onChanged } = {}) {
  container = mountEl;
  payload = newPayload;
  skewMs = new Date(newPayload.server_now).getTime() - Date.now();
  refreshCallback = onChanged || null;
  render();
  startTicking();

  if (!container.dataset.wired) {
    container.dataset.wired = "1";
    container.addEventListener("click", (event) => {
      const btn = event.target.closest("[data-action]");
      if (btn?.dataset.action === "hub-clock-stop") {
        void handleStop();
        return;
      }
      if (btn?.dataset.action === "hub-clock-start") {
        const select = container.querySelector(".wo-combo-native");
        if (select?.value) void handleStart(select.value);
        return;
      }
      if (btn?.dataset.action === "toggle-combo") {
        const combo = btn.closest(".wo-combo");
        const list = combo.querySelector(".wo-combo-list");
        comboOpen = list.hidden;
        list.hidden = !comboOpen;
        btn.setAttribute("aria-expanded", String(comboOpen));
        return;
      }
      if (btn?.dataset.action === "pick-combo-option") {
        const combo = btn.closest(".wo-combo");
        const nativeSelect = combo.querySelector(".wo-combo-native");
        const label = combo.querySelector(".wo-combo-trigger-label");
        nativeSelect.value = btn.dataset.value;
        label.textContent = btn.textContent;
        combo.querySelectorAll(".wo-combo-option").forEach((opt) => {
          opt.setAttribute("aria-selected", String(opt === btn));
        });
        combo.querySelector(".wo-combo-list").hidden = true;
        comboOpen = false;
        return;
      }
    });
    container.addEventListener("focusout", (event) => {
      const combo = event.target.closest(".wo-combo");
      if (!combo) return;
      setTimeout(() => {
        if (!combo.contains(document.activeElement)) {
          combo.querySelector(".wo-combo-list").hidden = true;
        }
      }, 0);
    });
  }
}

// Tab-hide / page-leave safety net (spec §6.1): nothing ticks in a
// background tab. userHub.js's page is a `.page` toggled by nav.js, not a
// browser tab, so this is called from the same visibilitychange listener
// pattern nav.js already uses for camera scanners -- see Task 4 Step 3.
export function stopHubClockTicking() {
  stopTicking();
}
```

- [ ] **Step 3: Stop ticking on tab-hide**

In `backend/static/views/userHub.js`, add the import and the listener, so a backgrounded tab is not paying for a 1-second interval it cannot show (spec §6.1):

```js
import { mountHubClock, stopHubClockTicking } from "./hubClock.js";
```

Append near the bottom of the file, after `loadUserHub`:

```js
document.addEventListener("visibilitychange", () => {
  if (document.hidden) stopHubClockTicking();
});
```

Also update `mountHubClock`'s call in `loadUserHub` to pass the refresh callback so Start/Stop repaints the whole hub, not just the widget:

```js
  mountHubClock(clockMount, latestPayload, { onChanged: refreshUserHub });
```

- [ ] **Step 4: CSS**

Append to `backend/static/styles.css`:

```css
.hub-clock-status {
    font-weight: var(--fw-semibold);
    display: flex;
    align-items: center;
    gap: var(--space-2);
}

.hub-clock-on .hub-clock-status {
    color: var(--color-success);
}

.hub-clock-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background-color: var(--color-success);
    display: inline-block;
}

.hub-clock-subject {
    color: var(--text-panel-mute);
}

.hub-clock-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-4);
    margin-top: var(--space-3);
}

/* Hero figures throughout the hub: one per view, proportional (not
   tabular-nums) figures per spec §8. */
.hub-clock-hero {
    font-size: 2.5rem;
    line-height: 1.1;
    margin: 0;
}

.hub-clock-started,
.hub-clock-today {
    color: var(--text-panel-mute);
    margin: 0;
}

.hub-clock-stop-btn,
.hub-clock-start-btn {
    /* Red is the primary action color here, not a status color (spec §8) --
       Stop and Start use the default button red, same as everywhere else. */
    min-width: 96px;
}

.hub-clock-start-wrap {
    display: flex;
    align-items: center;
    gap: var(--space-2);
}

.hub-clock-warning {
    color: var(--color-error);
    margin-top: var(--space-2);
    font-weight: var(--fw-semibold);
}

.hub-clock-message:empty {
    display: none;
}
```

- [ ] **Step 5: Manual verification**

```
Reload as a technician with at least one startable work order (created,
assigned, in_progress, or on_hold status) and currently not tracking.
```

Expected: the widget shows "○ Not clocked in", today's total, and a "Start on…" combo listing the technician's startable work orders. Open the combo (verify it opens as a styled popover, not a native `<select>` dropdown — the whole reason this reuses `comboHtml` instead of a plain `<select>`), pick one, click Start. Expected: the widget switches to "● ON THE CLOCK", shows the work order, a ticking hero figure (watch it advance across a minute boundary if convenient, or confirm the number recomputes every second in devtools), and "started H:MM AM/PM". Click Stop: returns to the off-clock state with today's total increased. Confirm no console errors during any step, and confirm switching to the "My Work Orders" tab and back leaves the clock still ticking (it is outside the tab bodies, per spec §5.1).

- [ ] **Step 6: Commit**

```bash
git add backend/static/views/hubClock.js backend/static/views/workOrders.js \
        backend/static/views/userHub.js backend/static/styles.css
git commit -m "feat(user-hub): add the persistent clock widget"
```

---

### Task 5: Dashboard tab — tiles, time today, timeline strip, tools out

**Files:**
- Modify: `backend/static/views/hubTechnician.js` (replace Task 1's `mountHubDashboard` stub)
- Modify: `backend/static/styles.css` (tiles, timeline strip)

**Interfaces:**
- Consumes: `GET /hub`'s `counts`, `clock` (`closed_minutes_today`, `running_minutes_today`, `adjustment_minutes_today`, `total_minutes_today`, `adjustments`, `running_session`), `timeline`, `tools_out`, `day` (Task 1's payload shape); `labor_day.DISPLAY_ANCHOR_HOUR` is a backend-only constant (8am) — mirrored here as a plain number since P2 has no reason to fetch it over the wire.
- Produces: `hubTechnician.js::mountHubDashboard(container, payload)`.

**Accepted assumption — the timeline strip reads the browser's local clock.** `minutesSinceMidnight` below uses `Date.getHours()`/`getMinutes()`, which reflect whatever timezone the *browser* is set to, not `America/Chicago`. Every minutes figure on the page (the tiles, the hero, each block's tooltip) is still correct regardless, because those are numbers the server already computed against the Central day (P1's `labor_day.py`). Only the axis's hour labels and each block's horizontal position could visually shift for a device not set to Central time. Field devices in this deployment are physically in Central time, so this is accepted rather than built around; a client-side timezone conversion would be new complexity for a cosmetic-only edge case. Revisit only if a real device in another timezone is reported.

- [ ] **Step 1: Write the Dashboard tab**

Replace the top portion of `backend/static/views/hubTechnician.js` (keep `mountHubWorkOrders` as Task 1 left it — Task 6 replaces that half):

```js
// View: the User Hub's Dashboard tab (technician-shaped, every role for now
// -- see this plan's Global Constraints) and My Work Orders tab.
//
// Layer: views. Consumes exactly the GET /hub payload userHub.js already
// fetched; makes no requests of its own except the embedded work-order list
// (Task 6).

import { escapeHtml } from "../format.js";
import { mountWorkOrderList, focusWorkOrderNumber } from "./workOrders.js";
import { showPage } from "./nav.js";

// Mirrors `domain.labor_day.DISPLAY_ANCHOR_HOUR` -- the timeline strip's
// axis starts here unless work began earlier. A *display* anchor only,
// never a day boundary (see P1's labor_day.py).
const DISPLAY_ANCHOR_HOUR = 8;

function formatHm(totalMinutes) {
  const minutes = Math.max(0, Math.round(totalMinutes));
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (!h) return `${m} m`;
  return `${h} h ${m} m`;
}

function tileHtml(label, value, sub) {
  return `
    <section class="hub-tile">
      <p class="hub-tile-label">${escapeHtml(label)}</p>
      <p class="hub-tile-value">${escapeHtml(String(value))}</p>
      ${sub ? `<p class="hub-tile-sub">${escapeHtml(sub)}</p>` : ""}
    </section>`;
}

function countsHtml(counts) {
  return `
    <div class="hub-tile-grid">
      ${tileHtml("Assigned to me", counts.assigned, "work orders")}
      ${tileHtml("In progress", counts.in_progress, "")}
      ${tileHtml("Ready to complete", counts.ready_to_complete, counts.ready_to_complete ? "waiting on supervisor" : "")}
    </div>`;
}

// The axis range: `min(8am, earliest session start)` to `max(now, 5pm)`, so
// an early start extends it left instead of falling off (spec §5.2). All in
// minutes-since-midnight for the local day the payload's `day` describes.
function timelineRangeMinutes(timeline, nowMinutes) {
  const anchor = DISPLAY_ANCHOR_HOUR * 60;
  const fivePm = 17 * 60;
  let start = anchor;
  let end = Math.max(fivePm, nowMinutes);
  timeline.forEach((entry) => {
    const startedMinutes = minutesSinceMidnight(entry.started_at);
    if (startedMinutes < start) start = startedMinutes;
  });
  return { start, end: Math.max(end, start + 60) };
}

function minutesSinceMidnight(isoString) {
  const d = new Date(isoString);
  return d.getHours() * 60 + d.getMinutes();
}

function hourLabelsHtml(rangeStart, rangeEnd) {
  const labels = [];
  const firstHour = Math.floor(rangeStart / 60);
  const lastHour = Math.ceil(rangeEnd / 60);
  for (let h = firstHour; h <= lastHour; h++) {
    const hour12 = ((h + 11) % 12) + 1;
    const suffix = h < 12 || h === 24 ? "a" : "p";
    labels.push(`<span class="hub-timeline-hour">${hour12}${suffix}</span>`);
  }
  return `<div class="hub-timeline-axis">${labels.join("")}</div>`;
}

function timelineBlocksHtml(timeline, rangeStart, rangeEnd) {
  const span = rangeEnd - rangeStart;
  return timeline
    .map((entry) => {
      const startedMinutes = minutesSinceMidnight(entry.started_at);
      const leftPct = ((startedMinutes - rangeStart) / span) * 100;
      const widthPct = Math.max((entry.minutes / span) * 100, 0.5);
      const running = !entry.ended_at;
      const label = running ? `${entry.number} (running)` : entry.number;
      return `<div class="hub-timeline-block${running ? " hub-timeline-block-running" : ""}" style="left:${leftPct}%;width:${widthPct}%" title="WO ${escapeHtml(entry.number)} — ${escapeHtml(formatHm(entry.minutes))}${entry.auto_closed ? " (auto-closed estimate)" : ""}">${escapeHtml(label)}</div>`;
    })
    .join("");
}

function timelineHtml(payload) {
  const { timeline, clock } = payload;
  const nowMinutes = minutesSinceMidnight(payload.server_now);
  if (!timeline.length && !clock.running_session) {
    return `<p class="hint">No time tracked yet today. Start a clock from a work order or use Start on… above.</p>`;
  }
  const { start, end } = timelineRangeMinutes(timeline, nowMinutes);
  return `
    <div class="hub-timeline">
      ${hourLabelsHtml(start, end)}
      <div class="hub-timeline-track">
        ${timelineBlocksHtml(timeline, start, end)}
      </div>
    </div>`;
}

function adjustmentsHtml(adjustments) {
  if (!adjustments.length) return "";
  return adjustments
    .map(
      (a) =>
        `<p class="hub-adjustment-line">Adjustments &nbsp;<strong>${escapeHtml(formatHm(a.minutes))}</strong> &nbsp;recorded by ${escapeHtml(a.recorded_by_name)} · WO ${escapeHtml(a.work_order_number)}</p>`
    )
    .join("");
}

function timeTodayHtml(payload) {
  const { clock } = payload;
  return `
    <section class="hub-time-today">
      <p class="hub-tile-label">Time today</p>
      <div class="hub-time-today-row">
        <p class="hub-clock-hero">${escapeHtml(formatHm(clock.total_minutes_today))}</p>
        ${clock.running_session ? `<span class="hub-running-badge">● running</span>` : ""}
      </div>
      <p class="hub-time-today-line">Tracked &nbsp;<strong>${escapeHtml(formatHm(clock.closed_minutes_today + clock.running_minutes_today))}</strong></p>
      ${adjustmentsHtml(clock.adjustments)}
      ${timelineHtml(payload)}
    </section>`;
}

function toolsOutHtml(toolsOut) {
  if (!toolsOut.length) {
    return `<section class="hub-tools-out"><p class="hub-tile-label">Tools out</p><p class="hint">No tools currently checked out.</p></section>`;
  }
  const rows = toolsOut
    .map((t) => {
      const since = t.since
        ? new Date(t.since).toLocaleDateString([], { weekday: "short", month: "numeric", day: "numeric" })
        : "";
      return `<li><span>${escapeHtml(t.name)}</span><span class="hub-tool-since">since ${escapeHtml(since)}</span></li>`;
    })
    .join("");
  return `
    <section class="hub-tools-out">
      <p class="hub-tile-label">Tools out <span class="hub-tile-count">${toolsOut.length}</span></p>
      <ul class="hub-tools-list">${rows}</ul>
    </section>`;
}

export function mountHubDashboard(container, payload) {
  container.innerHTML =
    countsHtml(payload.counts) +
    timeTodayHtml(payload) +
    toolsOutHtml(payload.tools_out);
}

export function mountHubWorkOrders(container, payload) {
  container.innerHTML = `<p class="hint">Work orders coming soon.</p>`;
}
```

- [ ] **Step 2: CSS**

Append to `backend/static/styles.css`:

```css
.hub-tile-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: var(--space-4);
    margin-bottom: var(--space-6);
}

.hub-tile-label {
    color: var(--text-panel-mute);
    font-size: var(--fs-sm);
    margin: 0;
}

.hub-tile-value {
    font-size: 2rem;
    margin: var(--space-1) 0;
}

.hub-tile-sub {
    color: var(--text-panel-mute);
    font-size: var(--fs-sm);
    margin: 0;
}

.hub-tile-count {
    color: var(--text-panel-mute);
    font-weight: var(--fw-normal);
}

.hub-time-today-row {
    display: flex;
    align-items: baseline;
    gap: var(--space-3);
}

.hub-running-badge {
    color: var(--color-success);
}

.hub-time-today-line {
    color: var(--text-panel-mute);
    margin: var(--space-1) 0;
}

.hub-adjustment-line {
    color: var(--text-panel-mute);
    font-size: var(--fs-sm);
    margin: 0 0 var(--space-1);
}

/* Timeline strip: uniform white-at-alpha blocks, the running one in brand
   red, identity from the direct label -- never color alone (spec §8). */
.hub-timeline {
    margin-top: var(--space-4);
}

.hub-timeline-axis {
    display: flex;
    justify-content: space-between;
    color: var(--text-panel-mute);
    font-size: var(--fs-xs);
    margin-bottom: var(--space-1);
}

.hub-timeline-track {
    position: relative;
    height: 32px;
    background-color: var(--panel-well);
    border-radius: var(--radius-sm);
    border: var(--border);
}

.hub-timeline-block {
    position: absolute;
    top: 2px;
    bottom: 2px;
    /* 2px surface gaps between touching blocks, per spec §8. */
    margin: 0 1px;
    background-color: rgba(255, 255, 255, .35);
    color: var(--text-panel);
    font-size: var(--fs-xs);
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
    white-space: nowrap;
    border-radius: 2px;
}

.hub-timeline-block-running {
    background-color: var(--color-brand);
    color: var(--color-white);
}

.hub-tools-list {
    list-style: none;
    margin: 0;
    padding: 0;
}

.hub-tools-list li {
    display: flex;
    justify-content: space-between;
    padding: var(--space-2) 0;
    border-bottom: 1px solid var(--panel-rule-soft);
}

.hub-tools-list li:last-child {
    border-bottom: none;
}

.hub-tool-since {
    color: var(--text-panel-mute);
    font-size: var(--fs-sm);
}
```

- [ ] **Step 3: Manual verification**

```
Reload as a technician with a mix of assigned/in-progress/ready-to-complete
work orders, at least one closed tracked session today, and (if easy to
arrange) one currently running.
```

Expected: three count tiles matching the technician's actual counts (cross-check against the Work Orders page's own filtered counts for the same statuses); the Time Today section shows the hero total, a "Tracked" line, an "Adjustments" line only if any exist, and the timeline strip with one block per session, the running one in brand red and labeled "(running)"; Tools Out lists anything currently checked out with a "since" date, or the empty-state line if none. Confirm the empty-state copy renders verbatim when a technician has no tracked time today. Confirm no console errors.

- [ ] **Step 4: Commit**

```bash
git add backend/static/views/hubTechnician.js backend/static/styles.css
git commit -m "feat(user-hub): add the Dashboard tab (counts, time today, timeline, tools out)"
```

---

### Task 6: My Work Orders tab

**Files:**
- Modify: `backend/static/views/hubTechnician.js` (`mountHubWorkOrders`)
- Modify: `backend/static/views/userHub.js` (tab label count)
- Modify: `backend/static/styles.css` (the "view all" link)

**Interfaces:**
- Consumes: `workOrders.js::mountWorkOrderList` (Task 3), `focusWorkOrderNumber` (existing), `nav.js::showPage` (existing).
- Produces: `hubTechnician.js::mountHubWorkOrders(container, payload)` — real implementation; tab label reading `N` from `payload.counts.assigned`.

- [ ] **Step 1: Implement `mountHubWorkOrders`**

In `backend/static/views/hubTechnician.js`, replace the stub:

```js
export function mountHubWorkOrders(container, payload) {
  container.innerHTML = `<p class="hint">Work orders coming soon.</p>`;
}
```

with:

```js
// Capped so an Admin/Owner's (currently company-wide, until P4 scopes it)
// call does not render hundreds of cards in a hub tab -- the escape hatch
// is the "View all" link, not client-side pagination duplicating the real
// page's "Show all" control.
const HUB_WORK_ORDERS_LIMIT = 10;

let mountedList = null;

export function mountHubWorkOrders(container, payload) {
  container.innerHTML = `
    <div class="hub-wo-list"></div>
    <p class="hub-wo-view-all"><button type="button" class="secondary-btn" data-action="hub-view-all-work-orders">View all in Work Orders →</button></p>
  `;
  const listContainer = container.querySelector(".hub-wo-list");
  mountedList = mountWorkOrderList({
    container: listContainer,
    lockedFilter: { limit: HUB_WORK_ORDERS_LIMIT },
    onOpen: (card) => {
      focusWorkOrderNumber(card.number);
      showPage("work-orders");
    },
  });
  void mountedList.refresh();

  container.querySelector('[data-action="hub-view-all-work-orders"]').addEventListener("click", () => {
    showPage("work-orders");
  });
}
```

- [ ] **Step 2: Tab label count**

In `backend/static/views/userHub.js`, update `renderActiveTab` (or wherever the payload is first available after fetch) to write the count into the tab button. Add this call inside `loadUserHub`, right after `latestPayload = await apiGetHub();`:

```js
  document.getElementById("hub-tab-work-orders").textContent =
    `My Work Orders (${latestPayload.counts.assigned})`;
```

- [ ] **Step 3: CSS**

Append to `backend/static/styles.css`:

```css
.hub-wo-view-all {
    margin-top: var(--space-3);
    text-align: right;
}
```

- [ ] **Step 4: Manual verification**

```
Reload as a technician with more than 10 assigned work orders if available
(otherwise any number > 0). Open the User Hub, switch to "My Work Orders".
```

Expected: the tab button reads "My Work Orders (N)" where N matches the Dashboard tab's "Assigned to me" tile. Up to 10 collapsed cards render, visually identical to the standalone Work Orders page's collapsed cards (same badges, same meta line). Click a card: the app switches to the Work Orders page and opens that exact card in solo mode, URL updated to `/workorder_card/<number>`, Back returns to the Work Orders list (not back to the hub — this matches "Card click navigates to /workorder_card/<number> exactly as today", which the spec deliberately did not ask to be reversible back into the hub). Click "View all in Work Orders →": switches to the Work Orders page showing the full, unfiltered/uncapped list.

- [ ] **Step 5: Commit**

```bash
git add backend/static/views/hubTechnician.js backend/static/views/userHub.js backend/static/styles.css
git commit -m "feat(user-hub): add the My Work Orders tab"
```

---

### Task 7: Full regression pass and edge cases

**Files:** none (verification only, plus small fixes if this pass finds anything).

**Interfaces:** none new.

- [ ] **Step 1: Work Orders page regression, exhaustively**

This is the acceptance bar named in spec §4.4. Walk every interaction the header comment at the top of `workOrders.js` lists (technician picker, notes, materials, labor entry, billing editor, tracking start/stop, hold/resume, complete, archive, search, filters, CSV export, NetFacilities card, Mass Stage unit click, a shared card link opened cold) as at least one role each (Technician + Supervisor + TechFM OA, minimum). Confirm every one behaves exactly as it did before this plan — none of this plan's changes should have touched any of this, so this pass should find nothing; if it does, treat it as a genuine regression and fix it before continuing, not as expected churn.

- [ ] **Step 2: Cross-role landing**

Sign in as one user per role (Technician, Supervisor, TechFM OA, Admin, Owner). Confirm every one lands on the hub. Confirm a Supervisor/Admin/Owner with zero assigned work orders sees honest zero tiles and the "No time tracked yet today" empty state, not an error.

- [ ] **Step 3: Landing precedence (§4.6) — unbroken by this plan**

Confirm the two cases spec §4.6 says outrank the landing page still do: (a) a resumed scan batch (start a Scan/Stock batch, hard-reload mid-batch, sign back in) still resumes on Transaction, not the hub; (b) a shared work-order card link (`/workorder_card/<number>`) opened cold (not signed in) still opens that card on the Work Orders page after login, not the hub.

- [ ] **Step 4: Edge cases from spec §10 relevant to P2**

- A technician assigned to zero work orders: hub loads cleanly, "Start on…" shows its disabled/empty state, not a broken combo.
- A session already running when the hub loads (started from a work-order card, not the widget): widget opens directly into the ON-clock state.
- Tab backgrounded for a while (switch OS tabs, wait, switch back): clock interval was cleared (Task 4 Step 3) and the figure is correct on return, not drifted.
- A `GET /hub` failure (simulate by stopping the backend briefly): the clock mount shows a message, not a blank widget or a thrown error in the console.

- [ ] **Step 5: Fix anything this pass found, then re-run the affected checks.**

- [ ] **Step 6: Final commit (only if Step 5 changed anything)**

```bash
git add -A
git commit -m "fix(user-hub): address regressions found in the P2 verification pass"
```

(Skip this commit entirely if Step 5 found nothing to fix.)

---

## Done when

- Every role lands on the User Hub after login, showing the header identity button (name over role) as the active nav element.
- The clock widget shows the correct on/off-clock state, ticks live, starts and stops a session correctly, and shows the two D18 warnings at the right thresholds.
- The Dashboard tab's three tiles, Time Today (hero + tracked + adjustments + timeline), and Tools Out all match what `GET /hub` actually returned for that user.
- The My Work Orders tab shows up to 10 of the caller's own work orders, using the *same* card rendering as the standalone Work Orders page, and clicking one opens it there exactly as a deep link does today.
- The standalone Work Orders page is behaviorally unchanged — Task 7's regression pass is clean.
- No new backend route, no new realtime event, no new nav button in `#main-nav`.

## Not in this phase

`GET /hub/crew`, `GET /hub/admin`, `GET /hub/timesheets`, the Supervisor and Admin dashboards, `hubSupervisor.js`/`hubAdmin.js`, the `labor.session.changed` realtime event, `domain/hub.py`'s attention-flag thresholds as a real backend module (this phase duplicates two of its future constants as plain numbers in `hubClock.js`, flagged in that task), and the timesheet grid. All of that is P3 (bulk) and P4 (the rest), per spec §12.
