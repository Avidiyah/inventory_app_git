# User Hub — Design Spec

Status: **draft, iteration 1.** Written 2026-08-20. Not yet approved; not yet planned.

The User Hub is a new role-scoped landing page — the front door every user signs
in to. It answers "what am I responsible for right now, and how long have I been
working" without opening a work order.

---

## 1. Why this exists

Today every role signs in to a task page: technicians land on Scan / Stock,
supervisors on Work Orders, everyone above on History. None of those answers the
question a person actually opens the app with. A technician cannot see how many
jobs they hold or how long they have worked today without counting cards. A
supervisor cannot see their crew at all. Nobody can audit a worker's hours.

The 2026-08-19 time-tracking work shipped the hard part —
`work_order_labor_sessions` records every start and stop, and a partial unique
index guarantees **one running clock per person across the whole system**. That
data has never been surfaced anywhere except inside a single work-order card.
This spec surfaces it.

---

## 2. Decisions locked

Settled with the owner on 2026-08-20. Changing any of these reopens the design.

| # | Decision | Choice |
|---|---|---|
| D1 | Day boundary | **Calendar day, `America/Chicago`.** 8:00am is a *display* anchor, not a boundary. A session crossing midnight **splits** across two days. |
| D2 | Persistence | **Derive on read.** No new table, no nightly job. `work_order_labor_sessions` is already the audit record. |
| D3 | Role coverage | **Three page designs.** TechFM OA and Owner reuse the Admin hub, rank-gated. |
| D4 | Landing | **The hub becomes the landing page for every role.** |
| D5 | Hand-entered labor | **Counted, filed under the date entered, shown on its own `Adjustments` line** — never silently merged into tracked time. |
| D6 | Supervisor crew scope | **Technicians assigned to work orders routed to me.** Derived from the existing routing, not a new roster concept. |
| D7 | Work Orders tab | **Embed the real `views/workOrders.js` card list**, filter locked to the viewer's scope. |
| D8 | Clock control | **A persistent clock widget on the hub** — Stop always, Start against any assigned work order. |
| D9 | Admin tabs | **Three:** Dashboard · Crew & Timesheets · Work Orders. |
| D10 | Nav entry | **No nav button.** The header's existing user/role indicator becomes the button, with a home icon beside it. The username and role *are* the label. |
| D11 | Off-clock timestamp | **Last clock-out only**, labeled **"Last worked"**. Sessions are the only source; no activity union. |
| D12 | Billing tile range | **This week**, matching the week-based Timesheets tab so both Admin tabs speak one period. |
| D13 | Supervisor's own time | **Clock widget only.** Excluded from crew cards and from "Crew time today". |
| D14 | Timesheet CSV filename | **Payroll-friendly, ISO order:** `timesheet_<start>_to_<end>[_<user>].csv`. |
| D15 | Adjustments in totals | **Every displayed day total includes adjustments.** One number means one thing on every surface; the tracked/adjustment split is always one expand away. |
| D16 | Crew board above Supervisor | **Shown on the Admin page too, but only when the viewer is the routed supervisor on ≥1 live work order.** Hidden entirely otherwise. |
| D17 | Timesheet access | **Supervisor+**, rows scoped to the viewer's routed crew, CSV export included. TechFM OA+ sees everyone. |
| D18 | Self warnings | The technician sees their own long-clock warning at **8 h**, and a distinct **cap warning from 11 h** because 12 h truncates their recorded time. |

---

## 3. Time semantics

This is the part most likely to ship subtly wrong, so it is specified before any
UI.

### 3.1 Three different numbers

The app already computes labor three ways, and the hub must not blur them.

| Number | Definition | Where it lives | Used for |
|---|---|---|---|
| **Tracked minutes** | Real wall-clock overlap of a session with a day | new — `domain/labor_day.py` | The hub. Timesheets. Audit. |
| **Session minutes** | `capped_session_minutes` — floors at 1, caps at 720 | `domain/work_orders.py` | Producing a `work_order_labor` row on stop |
| **Billed minutes** | Combined per-work-order labor rounded **up to the next 30 min**, at $62.50/hr | `domain/work_orders.py::billed_labor_minutes` | The receipt, the client CSV, billing tiles |

A technician who worked 3h02m across two work orders has **3h02m tracked** and
**3h30m billed**. The hub's daily total is the tracked number. Billing figures
appear only on the Admin billing tile and are labeled as billing.

> **Rule.** No hub surface may display a billed figure under a "time worked"
> label, and no timesheet may apply 30-minute rounding.

### 3.2 The day, and the midnight split

A day is `[00:00:00, 24:00:00)` in `America/Chicago` — the same zone
`domain/work_orders.py::NOTE_TIMEZONE` already uses for the note log, so the hub
and the note timeline agree. DST is handled by `zoneinfo`; a spring-forward day
is 23 hours and a fall-back day is 25, and the overlap arithmetic below is
correct for both because it operates on absolute instants.

Aggregation is **interval overlap**, not a `started_at` range filter:

```
tracked_minutes(user, day) =
    Σ  overlap( [session.started_at, session.ended_at ?? now),
                [day_start_utc, day_end_utc) )
       for every session where session.technician_id = user
```

A session running 23:30 Monday → 00:30 Tuesday contributes 30 minutes to Monday
and 30 to Tuesday. A session still running contributes up to `now`, which is what
makes the number climb through the day.

### 3.3 New pure module: `domain/labor_day.py`

No FastAPI, no SQLAlchemy — consistent with the existing domain rule. Fully unit
testable without a database.

```python
CENTRAL = ZoneInfo("America/Chicago")

# 8:00am. The strip starts here unless work started earlier.
DISPLAY_ANCHOR_HOUR = 8

def day_bounds(day: date, *, tz=CENTRAL) -> tuple[datetime, datetime]:
    """UTC instants bracketing one Central calendar day. DST-correct."""

def central_date_of(instant: datetime, *, tz=CENTRAL) -> date:
    """Which Central day an instant falls on."""

def overlap_minutes(
    start: datetime,
    end: datetime | None,
    window_start: datetime,
    window_end: datetime,
    *,
    now: datetime,
) -> int:
    """Whole minutes a session occupies inside a window.

    `end=None` means still running; `now` stands in for it. Returns 0 when the
    session lies wholly outside the window. Unlike `capped_session_minutes`
    this does NOT floor at 1 — a session that merely touches a boundary
    contributes nothing to the far side of it.
    """

def split_by_day(
    start: datetime,
    end: datetime | None,
    *,
    now: datetime,
    tz=CENTRAL,
) -> list[tuple[date, int]]:
    """One (central_date, minutes) pair per day the session touches."""
```

**Rounding rule.** `overlap_minutes` rounds the total seconds to the nearest
minute *once per (session, day) pair*, not per session. Summing a day's pairs can
therefore differ from the session's own `minutes` column by at most a minute per
crossing — accepted, and noted here so a future reader does not treat it as a
bug.

**Deliberate difference from `capped_session_minutes`.** That function floors at
1 minute so a 20-second visit does not fail `validate_labor_minutes`. The daily
timesheet has no such constraint, and flooring here would invent a minute on
every midnight crossing. The two functions are allowed to disagree; each is right
for its job.

### 3.4 Adjustments (D5)

A supervisor can hand-enter labor minutes. Those rows are `work_order_labor` rows
with **no session** pointing at them:

```sql
LEFT JOIN work_order_labor_sessions s ON s.labor_id = l.id
WHERE s.id IS NULL
```

They carry no start/stop, so they are filed under the Central date of
`work_order_labor.created_at` and reported on a separate `Adjustments` line with
the recorder's name. They never appear on the timeline strip — there is nothing
to draw.

```
Today          6 h 20 m
  Tracked      5 h 50 m
  Adjustments  0 h 30 m   (recorded by M. Chen)
```

**Known limitation, accepted for iteration 1.** A Friday correction to Tuesday's
work lands on Friday. Fixing it means adding a work-date field to the existing
hand-entry flow and changing a shipped endpoint contract. Deferred — see §13.

### 3.5 The 12-hour cap and the global sweep

`services/work_orders.py::_apply_session_cap` closes a session that has outrun
720 minutes, lazily, whenever somebody opens that work order. There is no
scheduler in this app and this spec does not add one.

The Admin hub's crew board queries **every running session in the system** — which
makes it the first surface that can sweep them all at once. `GET /hub/admin`
therefore applies the cap globally before reading.

**`GET /hub` sweeps the caller's own session too**, and must. Without it a
technician who forgot to clock out on Tuesday opens their hub on Wednesday and
sees a 20-hour running clock spanning two days — a number that is both alarming
and wrong, and that the existing per-work-order sweep would not correct until
somebody happened to open that specific card. The cost is bounded to **at most one
row**: the partial unique index guarantees one running session per person, so this
is a single indexed lookup, not a scan.

This is also what keeps §3.2's midnight-split arithmetic honest. A running session
is otherwise unbounded, so a stale one would keep accruing tracked minutes against
today forever.

Two constraints carried over verbatim from the existing rule:

- **No auto-hold.** `_apply_session_cap` deliberately does not change work-order
  status, because a supervisor's phone should not buzz because someone opened a
  dashboard. The global sweep inherits this.
- **The capped instant is authoritative.** A swept session still closes at
  `started_at + 720min`, not at sweep time, so the billed figure is right and only
  the `auto_closed_at` flag is late.

A session closed by the cap is flagged in every hub surface that shows it, because
it is an estimate a supervisor should correct:

```
⚠ auto-closed at 12 h — estimate
```

---

## 4. Architecture

### 4.1 One page, stacked payloads

A single page `user-hub`. Payload endpoints stack by rank rather than branching by
role, so each gets exactly one declarative `Depends(require_min_role(...))` — the
hard invariant that `auth_deps.py:73` is the only place a role 403 is raised.

| Endpoint | Gate | Payload |
|---|---|---|
| `GET /hub` | any authenticated | Personal block |
| `GET /hub/crew` | `supervisor+` | Crew cards, work orders I lead |
| `GET /hub/admin` | `techfm_oa+` | Pipeline, exceptions, billing |
| `GET /hub/timesheets` | `supervisor+` | Timesheets tab, row-scoped by rank (D17) |

On dashboard load a Technician fetches 1, a Supervisor 2, an Admin 3. The
timesheet payload is fetched lazily on tab switch, not on load, for both
Supervisor and Admin — it is the only one whose cost scales with a date range.

**`/hub/timesheets` gates at `supervisor+` but scopes its rows by rank** (D17): a
Supervisor sees only their routed crew (D6), TechFM OA and above see everyone.
The gate stays a single declarative `require_min_role("supervisor")`; the row
filter lives in the service, alongside every other per-row visibility rule in this
app — the same division `can_view_work_order` already uses.

**Every role gets the personal block**, including Admin. This is not symmetry for
its own sake: `POST /tracking/start` is already open to Supervisor+ on any work
order they can see, precisely so a supervisor who does the work records it
without joining the crew. A supervisor with a running clock and no way to see it
would be a regression.

### 4.2 Backend files

```
app/domain/labor_day.py        NEW  pure day/overlap arithmetic (§3.3)
app/domain/hub.py              NEW  pure attention-flag rules + thresholds (§6.3)
app/services/labor_summary.py  NEW  session/labor aggregate queries
app/services/hub.py            NEW  composes the four payloads
app/routers/hub.py             NEW  four routes, four declarative gates
app/schemas/hub.py             NEW  response contracts
app/services/work_orders.py    EDIT expose a global session sweep (§3.5)
app/services/tools.py          —    reuse `user_custody` unchanged
app/domain/realtime.py         EDIT one new event (§6.2)
app/main.py                    EDIT register pages/user-hub.html in the shell list
```

`services/labor_summary.py` owns every query; `domain/labor_day.py` and
`domain/hub.py` own every rule. No aggregation logic in the router — the layering
chain `routers → schemas/services → domain/models → database` is unchanged.

### 4.3 Frontend files

Flat modules, matching the existing `toolCheckout.js` / `toolReturn.js`
sub-flow convention. Each stays small enough to hold in context.

```
static/pages/user-hub.html     NEW  fragment: tab bar + three tab bodies
static/views/userHub.js        NEW  tab shell, role dispatch, mount/unmount
static/views/hubClock.js       NEW  the ticking clock widget (§5.1)
static/views/hubTechnician.js  NEW  technician dashboard tiles
static/views/hubSupervisor.js  NEW  crew board
static/views/hubAdmin.js       NEW  admin tiles + timesheets tab
static/shell-head.html         EDIT #auth-user-indicator span -> button (§4.5)
static/views/nav.js            EDIT PAGE_ACCESS + LANDING_PAGE_BY_ROLE + count exclusion
static/views/auth.js           EDIT name/role spans via roleLabel() (§4.5)
static/views/users.js          EDIT same fix at its second call site (§4.5)
static/views/workOrders.js     EDIT make the card list mountable in a second container
static/api.js                  EDIT four fetch wrappers
static/main.js                 EDIT compose the new view
static/styles.css              EDIT hub surfaces
```

### 4.4 The `workOrders.js` refactor (D7)

The riskiest change in this spec, and worth naming precisely.

`views/workOrders.js` currently assumes it owns `#work-orders-list`. Embedding
its card list in a hub tab means parameterizing the container. What must survive
untouched:

- Cards stay `details.wo-card` inside the list container. Moving one into a
  different element silently breaks ~20 delegated click branches, the technician
  picker, the billing editor, and the realtime subscriber's card lookup — with no
  error. This is already a documented hard invariant.
- The realtime **hold** logic: a card with any of its four editor sections open
  is never refreshed out from under the user, and a full list refetch is deferred
  while any card is held.
- Card click navigates to `/workorder_card/<number>` exactly as today.

**Approach:** extract a `mountWorkOrderList({ container, lockedFilter })` entry
point; the existing page becomes its first caller with
`container: #work-orders-list, lockedFilter: null`. The hub tab is the second
caller. No behavior change on the Work Orders page — that is the acceptance bar.

If this proves messier than it looks, the fallback is the lightweight read-only
card list, at the cost of a second renderer to keep in sync. Flagged as the one
place this plan could need to change mid-implementation.

---

### 4.5 The header identity button (D10)

The hub gets **no nav button**. The header already renders the signed-in user and
their role in `#auth-user-indicator`; that element becomes the way in, with a home
icon beside it. The username and role are the label.

```
  TechFM   Inventory ▾  Field ▾  People ▾  Review ▾      ┌──────────────────┐
                                                          │ ⌂  Jose Rivera   │  [ Log Out ]
                                                          │    Technician    │
                                                          └──────────────────┘
```

This is the right affordance for a page that is *about you*, and it costs no nav
real estate at any role.

**Markup.** `#auth-user-indicator` changes from a `<span>` to a `<button>` and
carries **both** `nav-btn` and a styling hook:

```html
<button id="auth-user-indicator" type="button"
        class="nav-btn user-hub-btn" data-page="user-hub">
  <svg class="nav-ico" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
    <path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/><path d="M10 20v-6h4v6"/>
  </svg>
  <span class="user-hub-name"></span>
  <span class="user-hub-role"></span>
</button>
```

**Why `nav-btn` does the work for free.** `nav.js:21` collects
`document.querySelectorAll(".nav-btn")` — document-wide, *not* scoped to
`#main-nav`. So the identity button inherits three behaviors with no change to
nav.js's plumbing:

| nav.js | Effect on the identity button |
|---|---|
| `:226` click → `showPage(btn.dataset.page)` | Clicking it opens the hub |
| `:192` active-class toggle | It highlights while the hub is the active page |
| `:137` `applyRoleVisibility` | Governed by `PAGE_ACCESS["user-hub"]` — all five roles, so never hidden |

Group-hiding is unaffected: `:141` scopes its query to `.nav-group`, and this
button sits outside every group, in `#auth-bar`.

`.user-hub-btn` then overrides `.nav-btn`'s layout to stack name over role and
size the role a step down and dimmer (`--text-panel-mute`).

**Two real fixes this forces, both in scope.**

1. **The role must render through `roleLabel()`.** Both sites that populate this
   element today interpolate the raw slug — `views/auth.js:102` and
   `views/users.js:221` both do `` `${formatUserName(user)} (${user.role})` ``.
   That is survivable in parentheses but not as a button label: a TechFM OA's home
   button would read **`techfm_oa`**. `roles.js::roleLabel` exists precisely for
   this and is the single sanctioned way to render a role. Both call sites switch
   to it and write the two spans instead of `textContent`.

2. **`user-hub` should be excluded from `visiblePageCount`.** `nav.js:145` derives
   that count from `PAGE_ACCESS` keys, not from rendered buttons, so simply adding
   the key would inflate every role's count by one for a page that draws no nav
   button. The threshold means "how many buttons are in the nav", so the count
   must skip `user-hub`. Concretely this keeps a Technician at **4** and preserves
   their headroom before compact mode, rather than parking them on the boundary.

**Accessibility.** The button needs an accessible name that says where it goes,
since "Jose Rivera / Technician" reads as a status label, not a destination:
`aria-label="Your hub — Jose Rivera, Technician"`, refreshed whenever the name or
role is rewritten. The `<svg>` stays `aria-hidden`, matching every other nav icon.

**Icon.** Inline SVG with `stroke="currentColor"`, like every existing nav icon —
A4's CSP is `default-src 'self'`, so an icon font or CDN sprite would be blocked.

### 4.6 Landing precedence (D4)

D4 reads as absolute — "the hub is the landing page for every role" — but the
post-login boot already encodes **two cases that outrank the landing page**
(`views/auth.js:114–132`). Changing `LANDING_PAGE_BY_ROLE` must not flatten them:

```
1. Resumed scan batch   ->  transaction     (operator was mid-job when the session dropped)
2. Deep link            ->  work-orders     (/workorder_card/<number>, focus queued first)
3. Otherwise            ->  user-hub        <- D4 changes only this branch
```

Verified against the code: the deep-link branch is evaluated *before*
`landingPageForRole` is ever called, so **D4 breaks neither**. A shared card link
still opens the card, and a dropped scan session still resumes. The existing
fallback — a role that cannot reach Work Orders has the URL replaced with `/` —
now lands on the hub instead of the old per-role page, which is strictly better.

The only edit is the `LANDING_PAGE_BY_ROLE` map itself. `landingPageForRole`
already guards with `canAccessPage`, and `PAGE_ACCESS["user-hub"]` lists all five
roles, so the guard never fires.

**Also required:** `app/main.py` assembles the shell from an explicit ordered list
of fragments (`main.py:340–353`). `pages/user-hub.html` must be added to it or the
page is simply absent from the DOM and `showPage("user-hub")` silently matches
nothing. The fragment must also respect the shell's CSP rules — no inline `on*`
handlers, no `<style>` blocks (`main.py:131`).

---

## 5. The dashboards

Layouts are ASCII sketches of information hierarchy, not pixel specs. Visual
treatment is §8.

### 5.1 The clock widget — every role, above the tabs

Persistent, outside the tab bodies, because it is the one thing that must be
reachable from any tab.

```
┌────────────────────────────────────────────────────────────┐
│  ● ON THE CLOCK                                            │
│  WO 88214 · Commons B3 · Unit 214                          │
│                                                            │
│      2 h 47 m                              [   Stop   ]    │
│      started 8:12 AM                                       │
└────────────────────────────────────────────────────────────┘

  off the clock:

┌────────────────────────────────────────────────────────────┐
│  ○ Not clocked in                                          │
│      Today  6 h 20 m                   [ Start on…  ▾ ]    │
└────────────────────────────────────────────────────────────┘
```

- Uses the existing `POST /work-orders/{id}/tracking/start` and `/tracking/stop`.
  **No new backend.** Starting also advances a pre-work row to In-Progress or
  resumes an On-Hold one, exactly as it does from a card — the hub inherits that,
  it does not reimplement it.
- **`Start on…` must not be a native `<select>`.** The design system is explicit:
  on some Windows/Chromium builds the OS draws the popup and ignores page CSS
  entirely, confirmed by field testing on 2026-08-20. Use the
  `comboHtml()` / `.wo-combo-*` pattern from `views/workOrders.js` — hidden real
  `<select>` for the value, styled trigger + `.wo-combo-list` popover for the user.
- The picker lists the viewer's assigned, non-archived work orders, In-Progress
  first, then Assigned.
- Starting a clock while another runs **closes the other one first** — that is
  existing service behavior enforced by a partial unique index. The widget says so
  before acting: `Stop your clock on WO 88190 and start on WO 88214?`

**Self warnings (D18).** The person on the clock is the only one who can stop it,
and the 12-hour cap silently truncates their recorded time — so the warning that
matters most goes to them, not only to a supervisor's board. Two steps, driven by
the §6.3 constants:

```
  at 8 h  ⚠ Still on the clock after 8 h — did you forget to stop?

  at 11 h ⚠ At 12 h this session is capped and your time stops counting.
```

The second is deliberately worded in terms of *their* hours rather than a system
rule. It is the one warning in this spec with a direct financial consequence for
the person reading it: past 720 minutes the session closes at
`started_at + 12 h` and everything after that is not recorded at all. Both are
text plus an icon, never color alone, and neither blocks the widget.

### 5.2 Technician hub

**Tab 1 — Dashboard**

```
┌──────────────────────┐ ┌──────────────────────┐ ┌──────────────────────┐
│ Assigned to me       │ │ In progress          │ │ Ready to complete    │
│                      │ │                      │ │                      │
│        8             │ │        1             │ │        2             │
│ work orders          │ │                      │ │ waiting on supervisor│
└──────────────────────┘ └──────────────────────┘ └──────────────────────┘

┌────────────────────────────────────────────────────────────────────────┐
│  Time today                                                            │
│                                                                        │
│        6 h 20 m                                    ● running           │
│                                                                        │
│        Tracked      5 h 50 m                                           │
│        Adjustments  0 h 30 m   recorded by M. Chen                     │
│                                                                        │
│   8a      9a      10a     11a     12p      1p      2p      3p      4p  │
│   ├───────┴───────┴───────┴───────┴────────┴───────┴───────┴───────┤   │
│   ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░   │
│   └── 88214 ──────┘        └─ 88190 ─┘         └── 88233 (running) ─┘  │
└────────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────────┐
│  Tools out                                                        3    │
│                                                                        │
│    Hilti TE-2 rotary hammer            since Mon 8/18                  │
│    Extension ladder 8 ft               since Tue 8/19                  │
│    Fluke multimeter                    since today 7:55 AM             │
└────────────────────────────────────────────────────────────────────────┘
```

- **`6 h 20 m` is the hero figure** — the single ≥48px number this view leads
  with, and there is exactly one per view. It ticks live.
- **The timeline strip** spans `min(8:00am, earliest session start)` to
  `max(now, 5:00pm)`, so an early start extends it left rather than falling off.
  Blocks are labeled with their work-order number directly; identity is carried by
  the label, never by color alone.
- Tool custody comes from the existing `services/tools.py::user_custody` — no new
  query, no new endpoint.
- Empty states are content, not blanks: `No time tracked yet today. Start a clock
  from a work order or use Start on… above.`

**Tab 2 — My Work Orders** — the embedded card list, filter locked to the
technician's own scope, with the count in the tab label.

### 5.3 Supervisor hub

**Tab 1 — Dashboard**

```
┌──────────────────────┐ ┌──────────────────────┐ ┌──────────────────────┐
│ Work orders I lead   │ │ Crew on the clock    │ │ Crew time today      │
│                      │ │                      │ │                      │
│       34             │ │      4 of 7          │ │     18 h 42 m        │
│ 8 in progress        │ │                      │ │ ticking              │
└──────────────────────┘ └──────────────────────┘ └──────────────────────┘

┌────────────────────────────────────────────────────────────────────────┐
│  ⚠ Needs attention                                                 3   │
│                                                                        │
│   ⚠  M. Chen — 4 work orders assigned, no time tracked today           │
│   ⚠  D. Ortiz — clock running 9 h 20 m                                 │
│   ⚠  WO 88102 — In-Progress, no activity for 4 days                    │
└────────────────────────────────────────────────────────────────────────┘

  MY CREW                                              sort: [ activity ▾ ]

┌──────────────────────────────────┐ ┌──────────────────────────────────┐
│  ● J. Rivera            ON CLOCK │ │  ○ M. Chen             OFF CLOCK │
│                                  │ │                              ⚠   │
│  WO 88214 · Commons B3           │ │  Last worked  yesterday 4:40 PM  │
│  running  1 h 12 m               │ │                                  │
│                                  │ │  Today       0 h 00 m            │
│  Today       5 h 47 m            │ │                                  │
│                                  │ │  Assigned 4 · In-prog 0 · Ready 0│
│  Assigned 6 · In-prog 1 · Ready 2│ │                                  │
└──────────────────────────────────┘ └──────────────────────────────────┘
```

- Crew membership is derived (D6): distinct technicians assigned to non-archived
  work orders where `supervisor_id = me`. It changes as routing changes; there is
  no separate roster to maintain.
- **`Last worked` is the technician's most recent session `ended_at`** (D11) —
  nothing else. It is deliberately not a union across notes, materials, and
  transactions: those would make one label mean four things, and the honest
  answer to "when was this person last on the clock" is the one a supervisor is
  asking. The label says `Last worked`, not `Last seen`, because that is what it
  measures. A technician who has never tracked time shows `Never`.
- **The supervisor's own time is not on this board** (D13). Their clock lives in
  the widget above the tabs, like every other role's, and `Crew time today` sums
  the crew only. The count and the cards therefore always reconcile — a total a
  supervisor cannot verify by adding up the cards below it reads as a bug.
- Every number on a card is clickable through to the Work Orders page with the
  matching filter applied.
- **Attention flags ship with an icon and a label, never color alone** — required
  by the dataviz rules and by the fact that these are read in jobsite glare.

**Tab 2 — Timesheets** (D17) — the same grid and drill-down as §5.4's Admin tab,
with rows scoped to the supervisor's routed crew. A supervisor answering "how many
hours did Rivera put in last week" is asking an ordinary supervisory question, and
D6's crew scope already bounds the answer. CSV export included.

**Tab 3 — Work Orders I Lead** — embedded card list, locked to `supervisor_id = me`.

Tab count now rises with rank, which is the right shape — a technician should not
pay for tabs they cannot use:

```
  Technician   [ Dashboard ][ My Work Orders ]
  Supervisor   [ Dashboard ][ Timesheets ][ My Work Orders ]
  Admin        [ Dashboard ][ Crew & Timesheets ][ Work Orders ]
```

The Supervisor and Admin timesheet tabs are the **same component** with a
different row scope, not two implementations. The label differs only because the
Admin view spans the whole company.

### 5.4 Admin hub

**Tab 1 — Dashboard**

```
┌────────────────────────────────────────────────────────────────────────┐
│  ON THE CLOCK NOW                                    4 people          │
│                                                                        │
│   J. Rivera    WO 88214  Commons B3        1 h 12 m                    │
│   M. Chen      WO 88190  Scholars 2A       0 h 47 m                    │
│   D. Ortiz     WO 88233  Young Hall        9 h 20 m   ⚠ long           │
│   T. Boyd      WO 88241  Centennial 4C     0 h 05 m                    │
│                                                                        │
│   Company today   22 h 15 m tracked                                    │
└────────────────────────────────────────────────────────────────────────┘

  WORK ORDER PIPELINE                                     312 live

  Created ───── Assigned ──── In-Prog ──── Ready ──── Completed ──── Review
     12            30             8          5 ⚠         14             3
                                            ^ waiting on a supervisor

┌────────────────────────────────────┐ ┌────────────────────────────────┐
│  EXCEPTIONS                        │ │  BILLING · this week           │
│                                    │ │                                │
│   Inventory recounts        3 open │ │   Materials         $ 4,210    │
│   Missing price / link      7 open │ │   Labor             $ 6,875    │
│   Item requests             2 open │ │   ─────────────────────────    │
│   Admin review queue        3      │ │   Total             $11,085    │
│   Stale > 3 days            6      │ │                                │
│                                    │ │   Avg time to complete  2.4 d  │
│                                    │ │   Completed / day              │
│                                    │ │     ▁▃▆▅▇▄▆▃▅▇▆▄▂▅             │
└────────────────────────────────────┘ └────────────────────────────────┘
```

- The pipeline is a **row of counts, not a funnel chart.** Work orders do not flow
  monotonically — `ready_to_complete` can be sent back to `in_progress`, statuses
  roll back — so funnel geometry would assert a monotonic decline that isn't true.
  Each count links to the Work Orders page pre-filtered.
- `Ready to complete` carries the attention flag: it is the one status where the
  work is done and the *supervisor* is the bottleneck.
- **Billing figures use the billed number** (30-min rounding, 15% material mark-up)
  and are labeled billing — the one place a billed figure legitimately appears
  next to time. Materials total is `effective_billable × current Item.price`,
  matching the receipt.
- Sparkline is a single series → **no legend**, title carries it. 14 points.
- **Owner only:** an extra row for the hidden legacy re-archive count, matching
  the existing Owner-exactly gate.
- **The crew board section (§5.3) also renders here when the viewer is the routed
  supervisor on at least one live work order** (D16), below the tiles above. It is
  absent — not empty — otherwise, so a pure office TechFM OA never sees it. The
  condition is the `/hub/crew` result being non-empty; no role special-case.

**Tab 2 — Crew & Timesheets**

```
  Week of Aug 17 – Aug 23      [ ◀ ]  [ ▶ ]      [ Export CSV ]

  Technician        Mon    Tue    Wed    Thu    Fri    Sat    Sun    Total
  ───────────────────────────────────────────────────────────────────────
  J. Rivera        7:05   6:20   4:10●    —      —      —      —    17:35
  M. Chen          8:00   7:45   6:10   ...                         21:55
  D. Ortiz         6:30   0:00⚠  8:15   ...                         14:45
  ───────────────────────────────────────────────────────────────────────
  Crew total      21:35  14:05  18:35                               54:15

  › click any cell to expand that day
```

Expanding one cell:

```
  J. Rivera · Wednesday Aug 19                            4 h 10 m total

    8:12 AM – 10:31 AM    WO 88214  Commons B3           2 h 19 m
   10:47 AM – 11:52 AM    WO 88190  Scholars 2A          1 h 05 m
    1:15 PM –  (running)  WO 88233  Young Hall           0 h 16 m
   ─────────────────────────────────────────────────────────────
                                    Tracked              3 h 40 m
    Adjustment            WO 88190  by M. Chen           0 h 30 m
   ─────────────────────────────────────────────────────────────
                                    Total                4 h 10 m
```

**Every total on this grid includes adjustments** (D15) — the cell, the row total,
the crew total, and the CSV. Rivera's Wednesday reads `4:10`, not `3:40`, and it
matches what Rivera's own hub showed them that day. The split is never hidden,
only collapsed: expanding any cell separates tracked from adjusted and names who
recorded it. A single number that means one thing on every screen is worth more
than a grid that quietly measures something narrower than the hub does.

This is the audit surface D2 promised. Every row traces to a session with a real
start, a real stop, and a work order. `⚠` marks a zero day where work was
assigned; `●` marks a running clock; an auto-closed session is labeled as an
estimate.

**Tab 3 — Work Orders** — embedded card list, unscoped.

---

## 6. Real-time

### 6.1 Ticking without polling

The requirement is minute-by-minute counting that a user watches climb. Polling
for that would be wasteful and would fight the 60 req/s rate cap.

**Server sends anchors; the client does the arithmetic.**

```json
{
  "server_now": "2026-08-20T15:47:12Z",
  "closed_minutes_today": 320,
  "adjustment_minutes_today": 30,
  "running_session": {
    "work_order_id": "…",
    "work_order_number": "88214",
    "started_at": "2026-08-20T13:12:00Z"
  }
}
```

The client records `skew = server_now − Date.now()` at fetch time and renders
`elapsed = (Date.now() + skew) − started_at` on a 1-second interval, displayed to
the minute. A phone with a wrong system clock still shows the right elapsed time,
which matters on shared field devices.

The same anchor mechanism drives every other person's clock on the crew board and
the admin board — each card carries its own `started_at` and ticks locally. **One
interval timer for the whole page**, not one per card.

The interval is cleared on tab-hide and on page-leave, and a fresh fetch runs on
tab-show. Nothing ticks in a background tab.

### 6.2 What still needs a server signal

Local ticking cannot know that *someone else* clocked in or out. That is a
membership change, so it needs an event.

**New realtime event:** `labor.session.changed`, audience `supervisor+`
(`_AUDIENCE_MIN_ROLE` in `domain/realtime.py`), `id: null` — it is a membership
change, so the client refetches the board rather than targeting a card. Same
reasoning the existing `restore` case already uses for `work_order.status.changed`.

Emitted after the mutating service returns, from exactly two sites:
`start_labor_session` and `stop_labor_session`. Best-effort and non-blocking, like
every existing emission — a dropped envelope never affects the durable write.

Personal clock changes need no event: the acting client already knows.

**Safety net:** while the hub is the active page and the tab is visible, a full
refetch every 60 seconds. This costs 1 request/minute/user — three orders of
magnitude under the 60/s cap — and covers a dropped envelope or a missed
reconnect.

`docs/notification-events.md` is the living register of realtime and notification
events; adding `labor.session.changed` updates it **in the same commit**, and
`test_realtime_emit.py`'s exact emitter-set assertion must be extended.

**No push notification.** This event is a screen refresh, not something worth a
lock screen.

### 6.3 Attention thresholds — `domain/hub.py`

Pure constants and predicates, so they are testable and tunable in one place.

| Flag | Rule | Constant |
|---|---|---|
| Long-running clock | running > 8 h (early warning ahead of the 12 h cap) | `LONG_SESSION_WARN_MINUTES = 480` |
| Approaching the cap | running > 11 h — the last hour before 12 h truncates recorded time | `SESSION_CAP_WARN_MINUTES = 660` |
| Assigned but idle | ≥ 1 assigned work order, 0 tracked minutes today, and it is past 10:00am Central | `IDLE_CHECK_HOUR = 10` |
| Stale work order | `in_progress` or `on_hold`, no labor session for 3 days | `STALE_WORK_ORDER_DAYS = 3` |

The 10:00am guard exists so the board is not solid warnings at 7:00am.

---

## 7. API contracts

All four are `GET`, all scoped server-side. Response shapes below are abbreviated
to their distinctive fields.

**They are not all side-effect-free.** `GET /hub` and `GET /hub/admin` run the
lazy session sweep (§3.5) and therefore commit when they find an over-cap session.
This follows existing precedent rather than inventing it: `get_work_order` already
both sweeps sessions and self-heals orphaned material lines on a read. The sweep
is idempotent — a second concurrent caller finds nothing left to close — and it
takes the same row lock the stop path does, so two admins loading the board at
once cannot double-close a session.

### `GET /hub` — any authenticated

```
{ user: {id, first_name, last_name, role},
  server_now,
  clock: { running_session | null, closed_minutes_today, adjustment_minutes_today,
           adjustments: [ {minutes, recorded_by_name, work_order_number} ] },
  timeline: [ {work_order_id, number, started_at, ended_at|null, auto_closed} ],
  counts: { assigned, in_progress, ready_to_complete },   // see note below
  startable: [ {work_order_id, number, location, status} ],
  tools_out: [ {tool_id, name, quantity, since} ] }
```

**`counts` are a total and two subsets, not three disjoint buckets.** `assigned`
is every non-archived work order where the caller is an assigned technician,
whatever its status. `in_progress` and `ready_to_complete` count the members of
that same set currently in those statuses. So `8 assigned · 1 in progress ·
2 ready` describes 8 work orders, not 11. The tiles are labeled to match —
`Assigned to me / 8 work orders` reads as the total, and the other two read as
slices of it. The same convention applies to the per-technician counts on the
crew board.

### `GET /hub/crew` — supervisor+

```
{ server_now,
  led: { total, in_progress, ready_to_complete },
  crew_on_clock, crew_total, crew_minutes_today,
  technicians: [ { user, running_session|null, minutes_today,
                   assigned, in_progress, ready_to_complete,
                   last_worked, flags[] } ],
  attention: [ {kind, subject, detail} ] }
```

### `GET /hub/admin` — techfm_oa+

```
{ server_now,
  on_clock: [ {user, work_order_number, location, started_at, flags[]} ],
  company_minutes_today,
  pipeline: { created, assigned, in_progress, ready_to_complete, completed, review },
  exceptions: { recounts_open, missing_price_open, item_requests_open,
                review_queue, stale_work_orders },
  billing: { range, materials_total, labor_total, avg_days_to_complete,
             completed_per_day: [ {date, count} ] } }
```

`billing.range` **defaults to the current Central week** (D12), the same week the
Timesheets tab opens on, so the two Admin tabs describe one period and their
numbers can be read against each other. The endpoint accepts an explicit range;
no range control ships in iteration 1.

### `GET /hub/timesheets?start=&end=&user_id=` — techfm_oa+

```
{ range: {start, end},
  rows: [ { user, days: [ {date, tracked_minutes, adjustment_minutes, flags[]} ],
            total_minutes } ],
  crew_totals_by_day: [ {date, minutes} ] }
```

`start`/`end` are Central calendar dates, inclusive, defaulting to the current
week. Range is capped at **92 days** to bound the query; over it returns 422 with
a `detail` naming the limit, which `api.js` already surfaces into the existing
error UI with no frontend code.

A day's session detail is expanded from the same payload — no extra round trip —
because a week of one crew's sessions is a few hundred rows at this scale.

**List ceiling.** The existing `MAX_LIST_ROWS = 5000` safety cap and its
`event=list.truncated` log line apply to `/hub/timesheets` via
`services/_list_cap.py`, consistent with the other six capped lists.

**CSV filename** (D14). The export is named for the period it covers, in ISO
order, so a folder of them sorts chronologically and the name still means
something after it has been emailed to a bookkeeper:

```
timesheet_2026-08-17_to_2026-08-23.csv           whole crew
timesheet_2026-08-17_to_2026-08-23_j-rivera.csv  filtered to one user
```

This **deliberately departs** from the `MM-DD-YY_HH-MM_filter.csv` UTC convention
used by the two work-order exports. That convention encodes the *export moment*
and the active filters, which is right for an operational snapshot of a filtered
card list; a timesheet is defined by the period it covers, and a leading `MM-`
sorts a payroll folder into nonsense. The user suffix is the slugified full name.
Dates are Central calendar dates, matching every other date in this spec.

---

## 8. Visual language

Bound by `docs/design-system.md`. The hub introduces no new tokens.

- **Frosted panel** (`--panel-*`) for every tile — the app-wide default. Never the
  `--glass-*` tokens: composited over `--color-canvas` they land back on the
  canvas and the panel vanishes.
- Nested content inside a tile uses `--panel-nested`; the timeline track and
  timesheet zebra rows use `--panel-well`; hairlines use `--panel-rule`.
- **Red is the primary action color, not a status color.** `Stop` and `Start` are
  brand red. On-the-clock state is **not** red.
- Status: on-clock `--color-success` as text plus a `●` glyph; attention
  `--color-error` as text or a left-accent rule — **never a fill**, per the token
  rules. Every flag carries an icon and a word, so state is never color-alone.
- On a panel use `--color-brand-light` for red text (5.5:1); `--color-brand`
  survives only as a fill. Never brand red as text on the canvas — 2.6:1, under
  the minimum.

**Charts.** The red/black/white/gray constraint rules out a categorical hue set,
which is fine because **none of the hub's charts are categorical**:

| Element | Form | Color |
|---|---|---|
| Stat tiles | label · value · optional delta | text tokens only |
| Hero figure | one per view, ≥48px, proportional figures (not `tabular-nums`) | `--text-panel` |
| Timeline strip | interval blocks | uniform white-at-alpha fill; the **running** block in `--color-brand`; identity from direct labels |
| Sparkline | single series, 14 points, 2px line | one hue; no legend |
| Timesheet grid | numeric table, `tabular-nums` in columns | text tokens |

Because there is no categorical palette, the palette validator's adjacent-pair CVD
checks do not apply. What **does** apply and must be verified at implementation:
2px surface gaps between touching timeline blocks, ≤24px mark thickness, hairline
recessive gridlines, values labeled selectively rather than on every point, and a
hover tooltip on the timeline and sparkline.

---

## 9. Role and visibility matrix

| Surface | Tech | Supv | TechFM OA | Admin | Owner |
|---|:--:|:--:|:--:|:--:|:--:|
| Clock widget | ✓ | ✓ | ✓ | ✓ | ✓ |
| Own counts / timeline / tools | ✓ | ✓ | ✓ | ✓ | ✓ |
| Crew board (cards, routed crew) | — | ✓ | ✓ if routed | ✓ if routed | ✓ if routed |
| Live "on the clock" tile (global) | — | — | ✓ | ✓ | ✓ |
| Pipeline / exceptions | — | — | ✓ | ✓ | ✓ |
| Billing tile | — | — | ✓ | ✓ | ✓ |
| Timesheets tab | — | ✓ own crew | ✓ all | ✓ all | ✓ all |
| Timesheet CSV export | — | ✓ own crew | ✓ all | ✓ all | ✓ all |
| Legacy re-archive count | — | — | — | — | ✓ |

Cost figures are redacted server-side below TechFM OA — the existing rule, not a
new one. A Supervisor's crew board shows **minutes, never dollars.**

`PAGE_ACCESS["user-hub"]` lists all five roles; the rank gates on the four
payload endpoints do the real work, and the backend remains authoritative.

### 9.1 The crew board is not the same thing as the on-the-clock tile

An earlier draft of this matrix claimed TechFM OA / Admin / Owner see the crew
board "all" — which conflated two different surfaces and contradicted §4.1.

- The **crew board** (§5.3) is *cards*: per-technician clock, today's minutes,
  work-order counts, attention flags — scoped by D6 to technicians on work orders
  **routed to the viewer**.
- The **on-the-clock tile** (§5.4) is a global list of everyone currently working,
  with no per-technician counts and no flags.

They answer different questions, and D3 sends TechFM OA / Admin / Owner to the
Admin page, which has the second and not the first.

**Resolved as D16.** An Admin or TechFM OA *can* be the routed supervisor on a
work order (`roles.canBeWorkOrderSupervisor` admits both), so such a person has a
real crew. The Admin dashboard therefore renders the crew board section too —
**but only when the viewer is the routed supervisor on at least one live work
order**, and it is absent entirely otherwise. A pure office TechFM OA never sees
it; an Admin who actually runs crews gets the same cards a Supervisor does.

The condition is data-driven, not role-driven: `GET /hub/crew` already computes
membership from routing, so an empty result *is* the signal to hide the section.
No new flag, no role special-case, and the section appears and disappears on its
own as routing changes.

---

## 10. Edge cases

| Case | Behavior |
|---|---|
| Session crosses midnight | Split; each day gets its overlap (§3.2) |
| Session running > 12 h | Swept, closed at `started_at + 720min`, flagged as an estimate; **no auto-hold** |
| Two clocks at once | Impossible — partial unique index. Starting closes the other after a confirm |
| Client clock wrong | Corrected by `server_now` skew (§6.1) |
| Tech assigned to an archived WO | Excluded from counts and the `Start on…` picker |
| Supervisor with no routed work | Crew board shows an empty state, not an error |
| Labor row with no session | Reported as an Adjustment; absent from the timeline |
| DST spring-forward / fall-back | `zoneinfo` handles it; the day is 23 or 25 h and overlap math is instant-based |
| Tab backgrounded for hours | Interval cleared; fresh fetch on tab-show |
| Socket down | 60 s safety refetch covers it; REST stays the source of truth |
| Hub payload fails to load | Tile shows an inline retry; **a failed refresh never blanks a usable board** — the existing Admin Review rule |

---

## 11. Testing

No frontend test harness exists; that boundary is unchanged.

**Pure domain — no database, the highest-value tests here:**
- `test_labor_day.py` — overlap arithmetic, midnight split, DST both directions,
  running sessions, sessions wholly outside the window, the no-floor rule.
- `test_hub_flags.py` — each attention threshold at, above, and below its edge;
  the 10:00am idle guard.

**Service, database-backed:**
- `test_labor_summary.py` — daily totals per user, adjustments separated from
  tracked, the global sweep closing at the capped instant and **not** auto-holding.

**Route gates:**
- `test_route_role_gates.py` extended with all four routes — a technician gets 403
  on `/hub/crew`, `/hub/admin`, `/hub/timesheets`; a supervisor gets 403 on the
  last two.

**Realtime:**
- `test_realtime_emit.py` — its exact emitter-set assertion must be extended for
  `labor.session.changed`, or it will fail. This is intentional: that test is the
  tripwire that stops an event being added without an audience decision.

**Regression:**
- The Work Orders page must behave identically after the `mountWorkOrderList`
  extraction — the acceptance bar for §4.4.

**Manual, by the owner:** two-browser live tick, a clock crossing midnight, the
crew board updating when another user clocks in, the `Start on…` popover rendering
correctly on Windows/Chromium (the native-`<select>` trap), and the hub on a phone.

---

## 12. Phasing

**This spec is too large for one implementation plan.** Four endpoints, three new
domain/service modules, six new frontend modules, a refactor of the most
behaviorally dense file in the app, and a new realtime event is not one sitting.
It decomposes cleanly along a natural seam — the time engine is independent of
every dashboard that reads it.

| Phase | Scope | Independently shippable? |
|---|---|---|
| **P1 · Time engine** | `domain/labor_day.py`, `services/labor_summary.py`, the global sweep, `GET /hub`. No UI. | Yes — provable entirely by tests |
| **P2 · Technician hub** | The page, tab shell, clock widget, technician dashboard, embedded work-order list (§4.4 refactor), nav + landing changes | Yes — a complete, useful feature on its own |
| **P3 · Supervisor hub** | `GET /hub/crew`, crew board, attention flags, `labor.session.changed` + the register update, **plus `GET /hub/timesheets` and the timesheet grid** | Yes |
| **P4 · Admin hub** | `GET /hub/admin`, the four tile groups, the conditional crew board (D16), timesheet scope widened to everyone | Yes |

**D17 moved the timesheet grid from P4 into P3.** Making timesheets `supervisor+`
means the grid, its drill-down, and the CSV export all ship with the Supervisor
hub; P4 then only widens the row scope from "my crew" to "everyone", which is a
service-layer change and not a new surface. This makes P3 the larger phase and P4
the smaller one — the reverse of the original estimate, and worth knowing before
sequencing the work.

Each phase gets its own implementation plan. **P1 is the one to be strictest
about** — every number in every later phase is only as correct as its overlap
arithmetic, and it is the only part that is cheap to test exhaustively because it
touches no database.

P2 carries the schedule risk, because of the `workOrders.js` extraction (§4.4).
If that proves messier than expected, the read-only fallback list keeps P2
shippable without blocking P3 and P4.

**Recommendation:** approve this spec as a whole, then plan and build P1 + P2
before revisiting the spec for P3 and P4. Building the technician hub first will
teach us things about the layout that are cheaper to learn on the simplest role.

---

## 13. Deferred

Named so they are decisions rather than oversights.

- **Work-date on hand-entered labor** (§3.4). Would fix corrections filing under
  the wrong day. Changes a shipped endpoint contract.
- **Timesheet approval / lock.** Explicitly rejected for iteration 1 (D2). If these
  hours ever feed payroll, revisit — that is a `daily_timesheet` table with
  `open/submitted/approved`, and it needs its own spec.
- **Nightly snapshot table.** Rejected: needs a scheduler this app does not have.
  If a supervisor ever edits historical sessions, derived totals shift retroactively.
  Acceptable today because sessions are not currently editable.
- **Technician week view and "my open requests" tiles** — offered and cut.
- **Notifications on attention flags.** The flags are a screen state, not an event.
- **Cross-role dollar visibility.** Supervisors stay on minutes.

---

## 14. Open questions for iteration 2

**All five are resolved as of 2026-08-20**, as D10–D14 in §2. Recorded here with
where each landed, so a later reader sees the question and not just the answer.

| Was | Resolution | Detail |
|---|---|---|
| Nav entry | **D10** — no nav button; the header user/role indicator becomes it | §4.5 |
| `last_seen` semantics | **D11** — last clock-out only, labeled "Last worked" | §5.3 |
| Billing tile range | **D12** — current Central week | §5.4, §7 |
| Supervisor's own time | **D13** — clock widget only, excluded from crew totals | §5.3 |
| Timesheet CSV name | **D14** — `timesheet_<start>_to_<end>[_<user>].csv` | §7 |

The compact-nav concern that opened this section is moot: no button is added to
`#main-nav`, and excluding `user-hub` from `visiblePageCount` keeps a Technician
at 4 with headroom to spare.

### 14.1 Second audit pass — 2026-08-20

A cold read of the whole spec found nine defects and four undecided questions.
All thirteen are closed. Recorded because several were cross-references that had
silently rotted when §12 was inserted, and that class of error will recur.

**Fixed without needing a decision:**

| # | Defect |
|---|---|
| 1 | §3.4 pointed at "§12" for the deferred item; inserting Phasing had shifted it to §13 |
| 2 | §4.2 said `services/hub.py` composes "three payloads"; there are four |
| 3 | §4.2 cited §7 for the realtime event (it is §6.2) and §6.2 for the thresholds (§6.3) |
| 4 | §6.3 shipped a literal `N days` placeholder next to a constant of 3 |
| 5 | §7 claimed all four endpoints are "read-only", contradicting §3.5's sweep |
| 6 | `adjustment_recorded_by[]` had no defined element shape |
| 7 | **`app/main.py` was missing from every file list** — the shell assembles from an explicit fragment list, so the page would never have entered the DOM |
| 8 | **`GET /hub` did not sweep the caller's own session** — a forgotten Tuesday clock would show a 20-hour running total on Wednesday |
| 9 | §9's matrix conflated the crew board with the on-the-clock tile and said "three payload endpoints" |

**Verified rather than assumed:** D4 does *not* break deep links or resumed scan
batches. `views/auth.js:114–132` evaluates both before `landingPageForRole` is
called. The precedence chain is now written down in §4.6 so nobody flattens it.

**Decided (D15–D18):** adjustments included in every displayed total; the crew
board appears on the Admin page when the viewer has routed work; timesheets drop
to `supervisor+` scoped to their own crew; the technician sees their own 8 h and
11 h warnings.

**Nothing blocks planning.** The only remaining open items are the six in §13,
deferred by choice, and none are needed for P1 or P2.
