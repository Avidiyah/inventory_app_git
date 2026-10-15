# Profile Day Cards, Timesheets Name Links, Work-Order Hand-off Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reach a crew member's weekly profile from the Timesheets grid, read each day as a colour-edged card, open a completed work order from a card, and come straight back to the same profile and week.

**Architecture:** Two new read-only fields on the completed row (`status`, `archived`). One ten-line module (`profileOrigin.js`) remembers the hand-off; the solo card's Back consumes it. The profile mounts in place on both pages; Timesheets guards its week repaint while the profile is open the way it already guards an open drill-down.

**Tech Stack:** FastAPI + SQLAlchemy + Pydantic (`from_attributes`), vanilla ES modules, pytest (`db` fixture), vitest + jsdom + MSW.

**Spec:** `docs/superpowers/specs/2026-10-15-profile-day-cards-and-timesheet-links-design.md` — read it first; this plan does not restate E1–E10.

## Global Constraints

- Paths are relative to `backend/` unless they start with `tests/frontend` or `docs/`.
- `userProfile.js` ≤ 500 lines. No `style=` attributes (CSP drops them). No nested `<button>` (a card is a `<button>`; nothing inside it may be one).
- Targeted tests only before commit. Commit after each task; do not push (pushing main deploys).
- pytest from `backend/` with the venv: `venv/Scripts/python -m pytest <file> -q`. vitest from repo root: `npx vitest run <file>`.
- Day bands from `clocked_minutes`: `0` none · `1–479` short · `480–600` full · `601+` over.
- Profilable roles on the client are exactly `["technician", "supervisor", "techfm_oa"]` (the `PROFILE_ROLES` list `users.js` already holds; "supervisor" is the Team Lead role's stored value).

## Deviations from the spec (decided while reading the code)

| Spec said | Plan does | Why |
|---|---|---|
| E7: `openWorkOrderPage({ id, number })` directly | `focusWorkOrder(id)` then `showPage("work-orders")` | `showPage` runs `loadWorkOrders`, whose first act is `exitSolo()`; a card opened before it is wiped. `focusWorkOrder` is the id path Mass Stage and Transactions already use and lands on the same solo page |
| WO card class `wo-card-status-{status}` | `user-profile-wo-{status}` ladder, border-left from the same `--wo-status-*` tokens | `.wo-card-status-*` sets 3D card chrome (2px border, drop shadow, `:active` lift); the inner card is meant to be minimal |
| Green accent `--status-stock` | `--color-success` | `docs/design-system.md` reserves `--color-success` / `--color-error` for text and left-accent rules; the roster strip's green/yellow/red ladder already uses exactly these tokens |
| Back label fixed as "‹ Back to users" | "‹ Back to users" on Users, "‹ Back to timesheets" on Timesheets | The profile now mounts on two pages |

## Design (frontend-design pass)

- **One bold element:** the seven day cards read as a vertical colour strip down the left edge. Everything else stays the flat panel the profile already is: no fills, no pills, no new type.
- **Tokens:** short `--status-dispense-text` (#F5A524), full `--color-success` (#45D07E), over `--color-error` (#FF7585), none `--panel-rule`. 4px edge, same width as `.hub-roster-card`, so the two surfaces share one vocabulary.
- **Work-order cards:** a full-width row button with its status colour on the same 4px left edge, number first, badge, then location in muted text. The inner list repeats the day-card language at a smaller scale instead of introducing a boxed card.
- **Archived:** the existing muted outline pill (`.wo-legacy-tag` rule, selector widened). Status colour is never replaced, only annotated.
- **Copy:** "Archived", "‹ Back to timesheets", "‹ Back to profile". Sentence case, no icons.

## Review Focus

1. Clocked exactly 480 and exactly 600 minutes must both be green, 479 amber, 601 red. Pinned in Task 3 (`colours each day by clocked minutes`).
2. A completed work order whose `location` is null renders a card without a dangling separator. Pinned in Task 3 (`renders a card without a location`).
3. Opening a profile from Timesheets, then an `attendance.changed` push, must not repaint the week over the profile. Pinned in Task 5 (`leaves an open profile alone on a background refresh`).
4. A stale origin must not hijack a later Back: a nav click clears it. Pinned in Task 7 (`a nav click clears the origin`).
5. Back from the solo card when the origin page is Timesheets but the hub has not loaded yet (cold return) must still land on the profile once the hub paints. Pinned in Task 5 (`openTimesheetsProfile mounts after the hub loads`).

---

### Task 1: Backend fields `status` and `archived`

**Files:**
- Modify: `app/services/person_week.py` (`PersonCompleted`, `_completed_by_day`)
- Modify: `app/schemas/attendance.py:221-227` (`PersonWeekCompleted`)
- Modify: `docs/endpoint-map.md:952` (`PersonWeekResponse` line)
- Test: `tests/test_person_week_service.py`

**Interfaces:**
- Produces: each item of `days[].completed` carries `status: str` and `archived: bool`.

- [ ] **Step 1: Write the failing test** (append to `tests/test_person_week_service.py`)

```python
def test_completed_carries_status_and_archived(db):
    tech = _user(db)
    _wo(db, tech, completed_at=_utc(15, 15), crew=[tech], number="WO-L")
    gone = _wo(db, tech, completed_at=_utc(15, 16), crew=[tech], number="WO-A")
    gone.archived_at = NOW
    db.commit()
    day = _day(_payload(db, tech), MONDAY + timedelta(days=1))
    by_number = {c.number: c for c in day.completed}
    assert (by_number["WO-L"].status, by_number["WO-L"].archived) == ("completed", False)
    assert (by_number["WO-A"].status, by_number["WO-A"].archived) == ("completed", True)
    from app.schemas.attendance import PersonWeekCompleted
    assert PersonWeekCompleted.model_validate(by_number["WO-A"]).archived is True
```

- [ ] **Step 2: Run it** — `venv/Scripts/python -m pytest tests/test_person_week_service.py -q -k status_and_archived` → FAIL (`unexpected keyword` / `AttributeError: status`).

- [ ] **Step 3: Implement**

`person_week.py`, `PersonCompleted`:
```python
@dataclass(frozen=True)
class PersonCompleted:
    work_order_id: uuid.UUID
    number: str
    location: str | None
    completed_at: datetime
    status: str
    archived: bool
```
`_completed_by_day`, the constructor call:
```python
            PersonCompleted(
                work_order_id=work_order.id, number=work_order.number,
                location=work_order.location, completed_at=completed_at,
                status=work_order.status, archived=work_order.archived_at is not None,
            )
```
`schemas/attendance.py`:
```python
class PersonWeekCompleted(BaseModel):
    work_order_id: uuid.UUID
    number: str
    location: Optional[str] = None
    completed_at: datetime
    status: str
    archived: bool

    model_config = {"from_attributes": True}
```
`docs/endpoint-map.md` line 952: after "and the four detail lists)" insert ", each `completed` item carrying `status` and `archived` (archived rows are included)".

- [ ] **Step 4: Run** `venv/Scripts/python -m pytest tests/test_person_week_service.py tests/test_person_week_router.py -q` → all PASS.

- [ ] **Step 5: Commit**
```bash
git add backend/app/services/person_week.py backend/app/schemas/attendance.py backend/tests/test_person_week_service.py docs/endpoint-map.md
git commit -m "feat(hub): person week completed rows carry status and archived"
```

---

### Task 2: `profileOrigin.js`

**Files:**
- Create: `static/views/profileOrigin.js`
- Test: `tests/frontend/unit/profileOrigin.test.js`

**Interfaces:**
- Produces: `setProfileOrigin(origin)`, `peekProfileOrigin()`, `takeProfileOrigin()`, `clearProfileOrigin()`. `origin` is `{ page: "users" | "user-hub", userId: string, week: string | null }`.

- [ ] **Step 1: Write the failing test**

```js
// The remembered profile → work-order hand-off: read many times, taken once.
import { beforeEach, describe, expect, it } from "vitest";
import {
  clearProfileOrigin, peekProfileOrigin, setProfileOrigin, takeProfileOrigin,
} from "../../../backend/static/views/profileOrigin.js";

const ORIGIN = { page: "users", userId: "u1", week: "2026-09-14" };
beforeEach(() => clearProfileOrigin());

describe("profileOrigin", () => {
  it("starts empty and peek does not consume", () => {
    expect(peekProfileOrigin()).toBeNull();
    setProfileOrigin(ORIGIN);
    expect(peekProfileOrigin()).toEqual(ORIGIN);
    expect(peekProfileOrigin()).toEqual(ORIGIN);
  });
  it("take returns the origin once", () => {
    setProfileOrigin(ORIGIN);
    expect(takeProfileOrigin()).toEqual(ORIGIN);
    expect(takeProfileOrigin()).toBeNull();
  });
  it("clear drops it", () => {
    setProfileOrigin(ORIGIN);
    clearProfileOrigin();
    expect(peekProfileOrigin()).toBeNull();
  });
});
```

- [ ] **Step 2: Run** `npx vitest run tests/frontend/unit/profileOrigin.test.js` → FAIL (module not found).

- [ ] **Step 3: Implement** `static/views/profileOrigin.js`

```js
// The remembered hand-off from a crew member's profile to one work order, so
// the solo card's Back can return to that profile at that week (spec
// 2026-10-15-profile-day-cards-and-timesheet-links-design.md, E8).
//
// Layer: views (shared state, no DOM). Module-level and consumed once by the
// Back control; a nav click or logout clears it so a stale origin can never
// hijack a later Back. `{ page: "users" | "user-hub", userId, week }`.

let origin = null;

export function setProfileOrigin(next) { origin = next; }
export function peekProfileOrigin() { return origin; }
export function takeProfileOrigin() {
  const taken = origin;
  origin = null;
  return taken;
}
export function clearProfileOrigin() { origin = null; }
```

- [ ] **Step 4: Run** the test → PASS.

- [ ] **Step 5: Commit**
```bash
git add backend/static/views/profileOrigin.js tests/frontend/unit/profileOrigin.test.js
git commit -m "feat(users): profileOrigin remembers the profile to work-order hand-off"
```

---

### Task 3: Profile day cards, work-order cards, `week` and `page` options

**Files:**
- Modify: `static/views/userProfile.js`
- Modify: `static/styles.css` (after line 5554; widen the selector at line 4481)
- Test: `tests/frontend/views/userProfile.test.js`

**Interfaces:**
- Consumes: Task 1 fields; Task 2 `setProfileOrigin`; `statusBadge` from `./workOrderPresenters.js`; `focusWorkOrder`, `openWorkOrdersByNumberSearch` from `./workOrders.js`.
- Produces: `mountUserProfile(container, user, { onBack, week, page })`. `page` defaults to `"users"`. `user` needs at least `{ id }`; the heading is painted from `payload.user` so a Back-return with only an id still shows the name.

- [ ] **Step 1: Update the test file**

Replace the `vi.hoisted` / `vi.mock` block at the top with:
```js
const { openSearch, focusWorkOrder, showPage } = vi.hoisted(() => ({
  openSearch: vi.fn(), focusWorkOrder: vi.fn(), showPage: vi.fn(),
}));
vi.mock("../../../backend/static/views/workOrders.js", () => ({
  openWorkOrdersByNumberSearch: openSearch, focusWorkOrder,
}));
vi.mock("../../../backend/static/views/nav.js", () => ({ showPage }));
```
Add `import { peekProfileOrigin, clearProfileOrigin } from "../../../backend/static/views/profileOrigin.js";` and, in `beforeEach`, `focusWorkOrder.mockClear(); clearProfileOrigin();`.

Replace the test `hands a work order number to the Work Orders page` with these, and add the rest:
```js
  it("colours each day by clocked minutes", async () => {
    const week = personWeek();
    [0, 479, 480, 600, 601].forEach((m, i) => { week.days[i] = { ...week.days[i], clocked_minutes: m }; });
    serve(week);
    await mount();
    expect(rows().slice(0, 5).map((r) => r.className)).toEqual([
      "user-profile-day user-profile-day-none", "user-profile-day user-profile-day-short",
      "user-profile-day user-profile-day-full", "user-profile-day user-profile-day-full",
      "user-profile-day user-profile-day-over",
    ]);
  });

  it("renders each completed work order as a card with its status badge", async () => {
    serve(personWeek());
    await mount();
    const card = rows()[0].querySelector(".user-profile-wo-card");
    expect(card.tagName).toBe("BUTTON");
    expect(card.classList.contains("user-profile-wo-completed")).toBe(true);
    expect(card.querySelector(".wo-status-completed")).not.toBeNull();
    expect(card.textContent).toContain("WO-1");
    expect(card.textContent).toContain("Bldg 4");
    expect(card.querySelector(".wo-archived-tag")).toBeNull();
    expect(card.querySelector("button")).toBeNull();
  });

  it("renders a card without a location", async () => {
    const week = personWeek();
    week.days[0].completed[0] = { ...week.days[0].completed[0], location: null };
    serve(week);
    await mount();
    expect(rows()[0].querySelector(".user-profile-wo-location")).toBeNull();
  });

  it("tags an archived work order and sends it through the number search", async () => {
    const week = personWeek();
    week.days[0].completed[0] = { ...week.days[0].completed[0], archived: true };
    serve(week);
    await mount();
    const card = rows()[0].querySelector(".user-profile-wo-card");
    expect(card.querySelector(".wo-archived-tag").textContent).toBe("Archived");
    card.click();
    await flush(); await flush();
    expect(openSearch).toHaveBeenCalledWith("WO-1");
    expect(focusWorkOrder).not.toHaveBeenCalled();
    expect(showPage).toHaveBeenCalledWith("work-orders");
  });

  it("opens a live work order by id and records the origin", async () => {
    serve(personWeek());
    await mount(USER, { page: "user-hub" });
    rows()[0].querySelector(".user-profile-wo-card").click();
    await flush(); await flush();
    expect(focusWorkOrder).toHaveBeenCalledWith("wo-1");
    expect(openSearch).not.toHaveBeenCalled();
    expect(showPage).toHaveBeenCalledWith("work-orders");
    expect(peekProfileOrigin()).toEqual({ page: "user-hub", userId: USER.id, week: "2026-09-14" });
  });

  it("still hands charged and adjustment numbers to the number search", async () => {
    serve(personWeek());
    await mount();
    rows()[0].querySelector(".user-profile-wo-btn").click();
    await flush(); await flush();
    expect(openSearch).toHaveBeenCalledWith("WO-1");
  });

  it("fetches the requested week first and labels Back by page", async () => {
    serve(personWeek());
    await mount(USER, { week: "2026-09-07", page: "user-hub" });
    expect(weekQueries()).toEqual([{ week: "2026-09-07" }]);
    expect(host.querySelector(".user-profile-back").textContent).toContain("Back to timesheets");
  });

  it("paints the heading from the payload when only an id is given", async () => {
    serve(personWeek());
    await mount({ id: USER.id });
    expect(host.querySelector("#user-profile-heading").textContent).toContain("Ann Lee");
  });
```
Update the `personWeek` factory's completed item in `tests/frontend/helpers/factories.js:683` to add `status: "completed", archived: false`.

- [ ] **Step 2: Run** `npx vitest run tests/frontend/views/userProfile.test.js` → the new tests FAIL.

- [ ] **Step 3: Implement** in `userProfile.js`

Imports:
```js
import { statusBadge } from "./workOrderPresenters.js";
import { setProfileOrigin } from "./profileOrigin.js";
```
Replace the completed line in `dayBodyHtml` and add helpers:
```js
function dayBand(minutes) {
  if (!minutes) return "none";
  if (minutes < 480) return "short";
  return minutes > 600 ? "over" : "full";
}

// A minimal card: status colour on the edge and the badge, "Archived" as an
// extra tag never a replacement (E6). No element inside may be a button.
function woCard(wo) {
  const location = wo.location ? `<span class="user-profile-wo-location">${escapeHtml(wo.location)}</span>` : "";
  const archived = wo.archived ? `<span class="wo-archived-tag">Archived</span>` : "";
  return `<li><button type="button" class="user-profile-wo-card user-profile-wo-${escapeHtml(wo.status)}" data-id="${escapeHtml(wo.work_order_id)}" data-number="${escapeHtml(wo.number)}" data-archived="${wo.archived ? "1" : ""}">
    <span class="user-profile-wo-number">${escapeHtml(wo.number)}</span>${statusBadge(wo.status)}${location}${archived}
  </button></li>`;
}
```
In `dayBodyHtml`: `const completed = day.completed.map(woCard);`.

In `dayHtml`: `<details class="user-profile-day user-profile-day-${dayBand(day.clocked_minutes)}">`.

Signature and header:
```js
const BACK_LABEL = { users: "‹ Back to users", "user-hub": "‹ Back to timesheets" };

export function mountUserProfile(container, user, { onBack, week: initialWeek = null, page = "users" } = {}) {
  let week = initialWeek;
  let requestId = 0;

  container.innerHTML = `<section class="user-profile" aria-labelledby="user-profile-heading">
    <div class="user-profile-header">
      <button type="button" class="hub-link-btn user-profile-back">${BACK_LABEL[page] || BACK_LABEL.users}</button>
      <h3 id="user-profile-heading"></h3>
      <p class="muted user-profile-role"></p>
    </div>
    <div class="user-profile-body"></div>
  </section>`;
  const body = container.querySelector(".user-profile-body");
  container.querySelector(".user-profile-back").addEventListener("click", () => onBack?.());

  function paintHeading(payload) {
    const who = payload.user ?? user;
    const archived = payload.archived ? ` <span class="muted">(archived)</span>` : "";
    container.querySelector("#user-profile-heading").innerHTML = `${escapeHtml(formatUserName(who))}${archived}`;
    container.querySelector(".user-profile-role").textContent = roleLabel(who.role);
  }
```
Hand-offs (replace `openWorkOrder`):
```js
  async function openByNumber(number) {
    const [{ openWorkOrdersByNumberSearch }, { showPage }] = await Promise.all([
      import("./workOrders.js"), import("./nav.js"),
    ]);
    openWorkOrdersByNumberSearch(number);
    showPage("work-orders");
  }

  // E7: a live card lands on the solo page by id (`focusWorkOrder` is the
  // path Mass Stage uses); an archived one takes the number search so the
  // restore pop-up fires. Either way the origin is remembered first (E8).
  async function openCard(card) {
    setProfileOrigin({ page, userId: user.id, week });
    if (card.dataset.archived) return openByNumber(card.dataset.number);
    const [{ focusWorkOrder }, { showPage }] = await Promise.all([
      import("./workOrders.js"), import("./nav.js"),
    ]);
    focusWorkOrder(card.dataset.id);
    showPage("work-orders");
  }
```
In `wire(payload)` add:
```js
    body.querySelectorAll(".user-profile-wo-btn").forEach((button) => {
      button.addEventListener("click", () => { void openByNumber(button.dataset.number); });
    });
    body.querySelectorAll(".user-profile-wo-card").forEach((card) => {
      card.addEventListener("click", () => { void openCard(card); });
    });
```
In `load`, after `week = payload.week_start;` add `paintHeading(payload);`. The final call stays `void load(week);`.

Remove the old `archived` const and the `${archived}` interpolation in the header (now painted from the payload).

- [ ] **Step 4: Styles** — append after `styles.css:5554`:
```css
/* Day cards: clocked time as a colour on the left edge only (spec E5). Same
   4px edge and tokens as .hub-roster-card so the two read as one system. */
.user-profile-day { border-left: 4px solid var(--panel-rule); }
.user-profile-day-short { border-left-color: var(--status-dispense-text); }
.user-profile-day-full { border-left-color: var(--color-success); }
.user-profile-day-over { border-left-color: var(--color-error); }

/* Completed work orders inside an open day: a row button, status on the
   same edge, no card chrome. */
.user-profile-list:has(.user-profile-wo-card) { list-style: none; padding: 0; margin: 0; }
.user-profile-wo-card {
    display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-2);
    width: 100%; margin: 0 0 var(--space-1); padding: var(--space-2) var(--space-3);
    background: var(--panel-well); border: 1px solid var(--panel-rule);
    border-left: 4px solid var(--card-accent, var(--panel-rule));
    border-radius: var(--radius-sm); color: inherit; font: inherit; text-align: left; cursor: pointer;
}
.user-profile-wo-card:hover, .user-profile-wo-card:focus-visible { border-color: var(--card-accent, var(--panel-rule)); }
.user-profile-wo-number { font-weight: var(--fw-bold); }
.user-profile-wo-location { color: var(--text-panel-mute); }
.user-profile-wo-created { --card-accent: var(--wo-status-created); }
.user-profile-wo-assigned { --card-accent: var(--wo-status-assigned); }
.user-profile-wo-in_progress { --card-accent: var(--wo-status-in-progress); }
.user-profile-wo-on_hold { --card-accent: var(--wo-status-on-hold); }
.user-profile-wo-ready_to_complete { --card-accent: var(--wo-status-ready-to-complete); }
.user-profile-wo-completed { --card-accent: var(--wo-status-completed); }
.user-profile-wo-review { --card-accent: var(--wo-status-review); }
```
And change `styles.css:4481` from `.wo-legacy-tag {` to `.wo-legacy-tag,\n.wo-archived-tag {`.

- [ ] **Step 5: Run** `npx vitest run tests/frontend/views/userProfile.test.js tests/frontend/views/users.test.js` → PASS. `wc -l backend/static/views/userProfile.js` ≤ 500.

- [ ] **Step 6: Commit**
```bash
git add backend/static/views/userProfile.js backend/static/styles.css tests/frontend/views/userProfile.test.js tests/frontend/helpers/factories.js
git commit -m "feat(users): profile day cards by clocked band, work-order cards with status and archived tag"
```

---

### Task 4: Hours grid name link

**Files:**
- Modify: `static/views/hubAttendanceHours.js`
- Test: `tests/frontend/views/hubAttendanceHours.test.js`

**Interfaces:**
- Produces: `mountHubAttendanceHours(container, payload, { ..., onOpenProfile })`; `onOpenProfile(row.user)` fires on a name click. Exported `PROFILABLE_ROLES = ["technician", "supervisor", "techfm_oa"]` (Task 6 makes `users.js` import it).

- [ ] **Step 1: Write the failing tests** (append to the grid describe)

```js
  it("renders a name as a link only with onOpenProfile and a profilable role", () => {
    const onOpenProfile = vi.fn();
    const week = attendanceWeek();
    mountHubAttendanceHours(host, week, { onOpenProfile });
    const link = host.querySelector("th[scope=row] .hub-hours-person");
    expect(link.tagName).toBe("BUTTON");
    link.click();
    expect(onOpenProfile).toHaveBeenCalledWith(week.rows[0].user);
  });

  it("prints a plain name without onOpenProfile or for an Admin row", () => {
    mountHubAttendanceHours(host, attendanceWeek());
    expect(host.querySelector(".hub-hours-person")).toBeNull();
    const week = attendanceWeek();
    week.rows[0].user = { ...week.rows[0].user, role: "admin" };
    mountHubAttendanceHours(host, week, { onOpenProfile: vi.fn() });
    expect(host.querySelector(".hub-hours-person")).toBeNull();
    expect(host.textContent).toContain("Ann Lee");
  });
```

- [ ] **Step 2: Run** `npx vitest run tests/frontend/views/hubAttendanceHours.test.js` → FAIL.

- [ ] **Step 3: Implement**

Top of module:
```js
export const PROFILABLE_ROLES = ["technician", "supervisor", "techfm_oa"];
```
Signature: add `onOpenProfile` to the destructured options. In `render()`, replace the `mainRow` line:
```js
        const nameCell = onOpenProfile && PROFILABLE_ROLES.includes(row.user?.role)
          ? `<button type="button" class="hub-link-btn hub-hours-person" data-row="${rowIndex}">${escapeHtml(name)}</button>`
          : escapeHtml(name);
        const mainRow = `<tr><th scope="row">${nameCell}</th>${cells}<td class="hub-hours-row-total">${formatHm(row.total_minutes)}</td></tr>`;
```
After the `.hub-hours-cell` listeners:
```js
    container.querySelectorAll(".hub-hours-person").forEach((button) => {
      button.addEventListener("click", () => onOpenProfile?.(payload.rows[Number(button.dataset.row)].user));
    });
```

- [ ] **Step 4: Run** the file → PASS.

- [ ] **Step 5: Commit**
```bash
git add backend/static/views/hubAttendanceHours.js tests/frontend/views/hubAttendanceHours.test.js
git commit -m "feat(hub): Hours grid names open a profile when the tab allows it"
```

---

### Task 5: Timesheets mounts the profile in place; `openTimesheetsProfile`

**Files:**
- Modify: `static/views/hubTimesheetsTab.js`
- Modify: `static/views/userHub.js` (one export)
- Test: `tests/frontend/views/hubTimesheetsTab.test.js`

**Interfaces:**
- Consumes: Task 3 `mountUserProfile(mount, user, { week, page: "user-hub", onBack })`; Task 4 `onOpenProfile`.
- Produces: `openTimesheetsProfile(userId, { week })` from `hubTimesheetsTab.js`; `openHubTab(name)` from `userHub.js`.

- [ ] **Step 1: Write the failing tests** (new describe in `hubTimesheetsTab.test.js`; add `import { personWeek } from "../helpers/factories.js";` and extend the factories import)

```js
describe("the profile", () => {
  const profileHandler = () => http.get("/hub/people/:id/week", () => HttpResponse.json(personWeek()));

  async function openProfile(opts = {}) {
    const mounted = await openTimesheets({ role: "admin", handlers: [profileHandler()], ...opts });
    await vi.waitFor(() => expect(panel().querySelector(".hub-hours-table")).not.toBeNull());
    await user().click(panel().querySelector(".hub-hours-person"));
    await vi.waitFor(() => expect(panel().querySelector("#hub-timesheets-profile .user-profile")).not.toBeNull());
    return mounted;
  }

  it("swaps the week area for the profile at the shown week, and Back restores it without a fetch", async () => {
    await openProfile();
    expect(panel().querySelector(".hub-leaderboard-table")).toBeNull();
    expect(panel().querySelector(".hub-hours-table")).toBeNull();
    await vi.waitFor(() => expect(queries("/hub/people/")).toEqual([{ week: "2026-09-14" }]));
    expect(panel().querySelector(".user-profile-back").textContent).toContain("timesheets");
    const before = queries("/hub/attendance/week").length;
    await user().click(panel().querySelector(".user-profile-back"));
    expect(panel().querySelector("#hub-timesheets-profile")).toBeNull();
    expect(panel().querySelector(".hub-leaderboard-table")).not.toBeNull();
    expect(panel().querySelector(".hub-hours-table")).not.toBeNull();
    expect(queries("/hub/attendance/week")).toHaveLength(before);
  });

  it("leaves an open profile alone on a background refresh", async () => {
    const { emit } = await connectHub();
    await openProfile();
    const before = queries("/hub/attendance/week").length;
    emit("attendance.changed");
    await vi.waitFor(() => expect(queries("/hub/attendance/live")).toHaveLength(2));
    expect(queries("/hub/attendance/week")).toHaveLength(before);
    expect(panel().querySelector("#hub-timesheets-profile .user-profile")).not.toBeNull();
  });

  it("does not offer the link to a Team Lead viewer", async () => {
    await openTimesheets({ role: "supervisor" });
    await vi.waitFor(() => expect(panel().querySelector(".hub-hours-table")).not.toBeNull());
    expect(panel().querySelector(".hub-hours-person")).toBeNull();
  });

  it("openTimesheetsProfile mounts after the hub loads", async () => {
    const { mod } = await openHub({ role: "admin", handlers: [profileHandler()] });
    const tab = await import("../../../backend/static/views/hubTimesheetsTab.js");
    tab.openTimesheetsProfile("10000000-0000-4000-8000-000000000001", { week: "2026-09-07" });
    mod.openHubTab("timesheets");
    await vi.waitFor(() => expect(panel().querySelector("#hub-timesheets-profile .user-profile")).not.toBeNull());
    await vi.waitFor(() => expect(queries("/hub/people/")).toEqual([{ week: "2026-09-07" }]));
    expect(panel().querySelector("#user-profile-heading").textContent).toContain("Ann Lee");
  });
});
```
Note: the test imports the tab module by path; `mountView` loaded the same file, so vitest returns the same instance. If `openHub` ever changes to a fresh module graph, read `openTimesheetsProfile` off `mod` instead.

- [ ] **Step 2: Run** `npx vitest run tests/frontend/views/hubTimesheetsTab.test.js` → the four FAIL.

- [ ] **Step 3: Implement** in `hubTimesheetsTab.js`

Imports: `import { mountUserProfile } from "./userProfile.js";` (static: the tab is Admin-only and already heavy; no dynamic import needed).

State, under `weekNotice`:
```js
// The profile mounted in place of the week area (E2): `{ user, week }` or
// null. While set, renderWeek and the background week refresh stand down.
let profileOpen = null;
```
Mount and back:
```js
function renderProfile(panelEl) {
  const area = mountFor(panelEl, "week");
  if (!area || !profileOpen) return;
  if (area.querySelector("#hub-timesheets-profile")) return;
  area.innerHTML = `<div id="hub-timesheets-profile"></div>`;
  mountUserProfile(area.firstElementChild, profileOpen.user, {
    week: profileOpen.week, page: "user-hub",
    onBack: () => {
      profileOpen = null;
      if (weekPayload) renderWeek(panelEl);
      else void loadWeek(panelEl);
    },
  });
}

function openProfile(panelEl, user, week) {
  profileOpen = { user, week };
  renderProfile(panelEl);
}

// The Back path from a work order (E8). The hub may not be on screen yet:
// the request is held in `profileOpen` and painted by the next
// renderTimesheetsTab. `user` is resolved from the cached week when
// possible; otherwise the profile paints its own heading from the payload.
export function openTimesheetsProfile(userId, { week: requested = null } = {}) {
  const row = weekPayload?.rows.find((r) => r.user?.id === userId);
  profileOpen = { user: row?.user ?? { id: userId }, week: requested };
  if (hostPanel && !hostPanel.hidden) renderProfile(hostPanel);
}
```
`renderWeek`: first line `if (profileOpen) { renderProfile(panelEl); return; }`. The Hours mount gains the callback:
```js
  mountHubAttendanceHours(mountFor(panelEl, "hours"), weekPayload, {
    weekNav: false, ...writes,
    onOpenProfile: isAdmin ? (user) => openProfile(panelEl, user, week) : undefined,
  });
```
`refreshTimesheetsLive`: change the last line to
```js
  if (!profileOpen && !panelEl.querySelector(".hub-hours-detail-row")) void loadWeek(panelEl);
```
`loadWeek`: keep caching the payload, but the skeleton must not wipe a mounted profile: `if (!weekPayload && !profileOpen) area.innerHTML = skeletonGrid();`. `renderWeek` already stands down.
`resetTimesheetsTab`: add `profileOpen = null;`.

`userHub.js`, next to `loadUserHub`:
```js
// Select a tab from outside the hub (the work-order Back path, E8).
export function openHubTab(name) { showTab(name); }
```

- [ ] **Step 4: Run** `npx vitest run tests/frontend/views/hubTimesheetsTab.test.js tests/frontend/views/userHub.test.js` → PASS.

- [ ] **Step 5: Commit**
```bash
git add backend/static/views/hubTimesheetsTab.js backend/static/views/userHub.js tests/frontend/views/hubTimesheetsTab.test.js
git commit -m "feat(hub): open a crew member's profile in place from the Timesheets grid"
```

---

### Task 6: `openUserProfile` on the Users page

**Files:**
- Modify: `static/views/users.js:45,166-171`
- Test: `tests/frontend/views/users.test.js`

**Interfaces:**
- Consumes: Task 4 `PROFILABLE_ROLES`.
- Produces: `openUserProfile(userId, { week })` from `users.js`.

- [ ] **Step 1: Write the failing test** (append to `users.test.js`; `mountUsers`/`openUsers` are the file's existing fixtures, `userFactory` makes a row)

`mountUsers` does not call `loadUsers`, so the list cache starts empty and the test proves the self-load. Add `personWeek` to the factories import.
```js
describe("openUserProfile", () => {
  it("loads the list if needed and mounts the profile at the week", async () => {
    const tech = userFactory({ role: "technician", first_name: "Ann", last_name: "Lee" });
    server.use(http.get("/hub/people/:id/week", ({ request }) =>
      HttpResponse.json({ ...personWeek(), week_start: new URL(request.url).searchParams.get("week") })));
    const { mod } = await mountUsers({ role: "admin", users: [tech] });
    await mod.openUserProfile(tech.id, { week: "2026-09-07" });
    const profile = document.getElementById("user-profile");
    await vi.waitFor(() => expect(profile.querySelector(".user-profile")).not.toBeNull());
    expect(document.getElementById("users-table").hidden).toBe(true);
    expect(requestFor("/users/")).toBeDefined();
    await vi.waitFor(() => expect(requestFor("/hub/people/")?.url).toContain("week=2026-09-07"));
  });
});
```

- [ ] **Step 2: Run** `npx vitest run tests/frontend/views/users.test.js -t openUserProfile` → FAIL.

- [ ] **Step 3: Implement**

Leave `PROFILE_ROLES` at line 45 as it is: `users.js` deliberately imports nothing from `views/` (its test fixture relies on that), so the grid's `PROFILABLE_ROLES` is not shared. Replace `showProfile` and add the export:

```js
async function showProfile(user, { week = null } = {}) {
  const { mountUserProfile } = await import("./userProfile.js");
  usersTable.hidden = true;
  userProfile.hidden = false;
  mountUserProfile(userProfile, user, { onBack: hideProfile, week, page: "users" });
}

// The Back path from a work order (E8): re-open a profile without a click.
export async function openUserProfile(userId, { week = null } = {}) {
  if (!getUsers().length) await loadUsers();
  const user = getUsers().find((candidate) => candidate.id === userId) ?? { id: userId };
  await showProfile(user, { week });
}
```

- [ ] **Step 4: Run** `npx vitest run tests/frontend/views/users.test.js tests/frontend/views/usersActions.test.js` → PASS.

- [ ] **Step 5: Commit**
```bash
git add backend/static/views/users.js tests/frontend/views/users.test.js
git commit -m "feat(users): openUserProfile re-opens a profile at a week"
```

---

### Task 7: Solo card Back returns to the profile; origin clearing

**Files:**
- Modify: `static/views/workOrderRouting.js:159-166` (`soloBackControl`)
- Modify: `static/views/workOrderActions.js:216-229` (`back-to-work-orders`)
- Modify: `static/views/nav.js:243-245` (nav click)
- Modify: `static/views/auth.js:62-80` (`showLoginScreen`)
- Modify: `docs/current-state.md:114`
- Test: `tests/frontend/views/workOrders/solo.test.js`

**Interfaces:**
- Consumes: Task 2 `peekProfileOrigin`, `takeProfileOrigin`, `clearProfileOrigin`; Task 5 `openTimesheetsProfile`, `openHubTab`; Task 6 `openUserProfile`.

- [ ] **Step 1: Write the failing tests** (in `solo.test.js`; add at top). The Work Orders fixture mounts `views/workOrders.js` alone, so the four landing modules are mocked and the Back branch's dynamic imports resolve to the mocks.

```js
import {
  clearProfileOrigin, peekProfileOrigin, setProfileOrigin,
} from "../../../backend/static/views/profileOrigin.js";

const { showPage, openUserProfile, openTimesheetsProfile, openHubTab } = vi.hoisted(() => ({
  showPage: vi.fn(), openUserProfile: vi.fn(), openTimesheetsProfile: vi.fn(), openHubTab: vi.fn(),
}));
vi.mock("../../../backend/static/views/nav.js", () => ({ showPage }));
vi.mock("../../../backend/static/views/users.js", () => ({ openUserProfile }));
vi.mock("../../../backend/static/views/hubTimesheetsTab.js", () => ({ openTimesheetsProfile }));
vi.mock("../../../backend/static/views/userHub.js", () => ({ openHubTab }));
```

```js
describe("back-to-work-orders with a profile origin", () => {
  beforeEach(() => { clearProfileOrigin(); vi.clearAllMocks(); });

  it("labels the control and returns to the Users profile at the week", async () => {
    setProfileOrigin({ page: "users", userId: "u1", week: "2026-09-07" });
    await mountOne({ number: "4242" });
    activatePage();
    await openCard(0);
    expect(backBtn().textContent).toBe("‹ Back to profile");
    backBtn().click();
    await vi.waitFor(() => expect(showPage).toHaveBeenCalledWith("users"));
    await vi.waitFor(() => expect(openUserProfile).toHaveBeenCalledWith("u1", { week: "2026-09-07" }));
    expect(peekProfileOrigin()).toBeNull();
    expect(window.location.pathname).toBe("/");
  });

  it("returns to the Timesheets profile", async () => {
    setProfileOrigin({ page: "user-hub", userId: "u1", week: null });
    await mountOne({ number: "4242" });
    activatePage();
    await openCard(0);
    backBtn().click();
    await vi.waitFor(() => expect(showPage).toHaveBeenCalledWith("user-hub"));
    await vi.waitFor(() => expect(openTimesheetsProfile).toHaveBeenCalledWith("u1", { week: null }));
    expect(openHubTab).toHaveBeenCalledWith("timesheets");
  });

  it("keeps today's label and path without an origin", async () => {
    await mountOne({ number: "4242" });
    activatePage();
    await openCard(0);
    expect(backBtn().textContent).toBe("← Back to work orders");
    backBtn().click();
    await vi.waitFor(() => expect(controls().hidden).toBe(false));
    expect(showPage).not.toHaveBeenCalled();
  });
});
```
The nav-click clearing is pinned in `tests/frontend/views/nav.test.js`, which boots the real app through `helpers/app.js` (`bootApp` calls `vi.resetModules()`, so import `profileOrigin.js` dynamically after boot to get the live instance). Append:
```js
describe("a nav click clears the origin", () => {
  it("drops a remembered profile origin", async () => {
    await bootApp({ role: "admin" });
    const origin = await import("../../../backend/static/views/profileOrigin.js");
    origin.setProfileOrigin({ page: "users", userId: "u1", week: null });
    await userEvent.setup().click(document.querySelector('.nav-btn[data-page="work-orders"]'));
    expect(origin.peekProfileOrigin()).toBeNull();
  });
});
```

- [ ] **Step 2: Run** `npx vitest run tests/frontend/views/workOrders/solo.test.js` → the new ones FAIL.

- [ ] **Step 3: Implement**

`workOrderRouting.js`: `import { peekProfileOrigin } from "./profileOrigin.js";` and
```js
function soloBackControl() {
  const wrap = document.createElement("div");
  wrap.className = "wo-solo-back";
  const label = peekProfileOrigin() ? "‹ Back to profile" : "&larr; Back to work orders";
  wrap.innerHTML =
    `<button type="button" class="secondary-btn" data-action="back-to-work-orders">${label}</button>`;
  return wrap;
}
```
`workOrderActions.js`: `import { takeProfileOrigin } from "./profileOrigin.js";` and at the top of the `back-to-work-orders` branch:
```js
    const origin = takeProfileOrigin();
    if (origin) {
      // E8: leave the card the way a nav click would (no history unwind; the
      // stale entry is normalized by the next list render) and re-open the
      // profile where the click came from. Dynamic imports: nav.js imports
      // this page, so a static import would be a cycle.
      exitSolo();
      void (async () => {
        const { showPage } = await import("./nav.js");
        showPage(origin.page);
        if (origin.page === "user-hub") {
          const [{ openTimesheetsProfile }, { openHubTab }] = await Promise.all([
            import("./hubTimesheetsTab.js"), import("./userHub.js"),
          ]);
          openTimesheetsProfile(origin.userId, { week: origin.week });
          openHubTab("timesheets");
        } else {
          const { openUserProfile } = await import("./users.js");
          void openUserProfile(origin.userId, { week: origin.week });
        }
      })();
      return;
    }
```
`nav.js`: `import { clearProfileOrigin } from "./profileOrigin.js";` and
```js
navButtons.forEach(btn => {
  btn.addEventListener("click", () => { clearProfileOrigin(); showPage(btn.dataset.page); });
});
```
`auth.js`: `import { clearProfileOrigin } from "./profileOrigin.js";` and `clearProfileOrigin();` beside `resetToolsView();` in `showLoginScreen`.

`docs/current-state.md` line 114: in the Files column add `static/views/profileOrigin.js`, `hubAttendanceHours.js`, `hubTimesheetsTab.js`, `workOrderRouting.js`, `workOrderActions.js`; in the Tests column add `hubAttendanceHours.test.js`, `hubTimesheetsTab.test.js`, `workOrders/solo.test.js`, `unit/profileOrigin.test.js`; in the notes column append: "Also reachable from the Timesheets Hours grid (mounts in place, Back restores from cache). Days are cards edged by clocked band (0 / <8h amber / 8–10h green / >10h red); completed work orders are cards with the status badge and an Archived tag; a live card opens the solo work order by id, an archived one the number search with restore; the solo Back reads '‹ Back to profile' and returns to that page, person and week (`profileOrigin.js`, cleared by nav click and logout)."

- [ ] **Step 4: Run**
```
npx vitest run tests/frontend/views/workOrders/solo.test.js tests/frontend/views/workOrders/actionCoverage.test.js tests/frontend/views/workOrders/realtime.test.js tests/frontend/views/nav.test.js tests/frontend/views/auth.test.js
```
→ PASS. Then the whole frontend suite once: `npx vitest run` → PASS.

- [ ] **Step 5: Commit**
```bash
git add backend/static/views/workOrderRouting.js backend/static/views/workOrderActions.js backend/static/views/nav.js backend/static/views/auth.js tests/frontend/views/workOrders/solo.test.js tests/frontend/views/nav.test.js docs/current-state.md
git commit -m "feat(work-orders): solo Back returns to the profile that opened it"
```

---

### Task 8: In-app check (user's)

Not automated. Per memory, the user validates manually: open Users → a Technician → confirm edges, open a day, click a live card, Back to profile, same week; then Timesheets → a name → profile in place → Back restores grid with no spinner; an archived card lands on the restore pop-up. Nothing to commit; do not push.

## Self-review

- **Spec coverage:** E1 T4+T5 · E2 T5 · E3/E4/E5 T3 · E6 T3 · E7 T3 (via `focusWorkOrder`, deviation noted) · E8 T2+T7 · E9 unchanged · E10 nothing added. Backend T1. Shared origin T2. `users.js` T6. Styles T3. Docs T1 (endpoint-map) + T7 (current-state). Error table: all existing paths, no new code.
- **Types:** `mountUserProfile(container, user, { onBack, week, page })` used identically in T3, T5, T6. `openTimesheetsProfile(userId, { week })`, `openUserProfile(userId, { week })`, `openHubTab(name)` consistent between T5/T6 and T7. Origin shape `{ page, userId, week }` in T2, T3, T7.
- **Review Focus:** 1 → T3 · 2 → T3 · 3 → T5 · 4 → T7 · 5 → T5.
