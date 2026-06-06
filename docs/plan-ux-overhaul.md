# Plan: Field-Friendly UX/UI Overhaul

Status: **Planned visual and usability overhaul.** No major functional changes are intended. This plan exists to make the current app easier, clearer, and more appealing for a construction crew with low tolerance for technology.

---

## Goal

Make the existing inventory app feel obvious and dependable on a jobsite.

The current feature set should stay intact:

- Same routes and backend behavior.
- Same roles and permissions.
- Same inventory concepts: items, barcode scans, stock, dispense, corrections, notes, users, history.
- Same static HTML/CSS/JS stack unless a separate technical decision changes that later.

The overhaul is about presentation, layout, wording, hierarchy, touch ergonomics, and confidence. The app should require less explanation from a supervisor standing nearby.

---

## Primary Audience

The primary users are construction workers using phones in real jobsite conditions.

Closed audience assumptions:

- Low patience for confusing software.
- Phones used one-handed.
- Gloves, dust, glare, bad lighting, and interruptions.
- Workers may be tired, rushed, or standing away from a desk.
- Users should not need to understand app architecture, database language, or permission terminology.
- Mistakes should be easy to recover from.

Design target: a worker should be able to scan an item, stock/dispense it, and move on without wondering what screen they are on or what the next step is.

---

## Assumptions To Confirm Before Implementation

These are known assumptions in the plan. They are **not automatic final decisions for an AI agent to close on its own**. Before implementing a section that depends on one of these assumptions, the agent must name the assumption, explain why it matters, and ask the owner to choose from concrete options.

| Area | Current assumption | Why it matters | Options to offer |
|---|---|---|---|
| Primary device | Phone in portrait orientation is the main target; desktop remains supported for admin work. | Determines layout density, button sizing, and navigation shape. | Phone-first; desktop-balanced; separate mobile/admin layouts. |
| Main worker role | Technician/Supervisor workflows get first priority; Admin/Owner flows stay usable but secondary. | Determines which screens get the most design attention first. | Technician-first; Supervisor-first; Admin-balanced. |
| Tolerance for instructions | Users should not need training beyond credentials and basic role expectations. | Determines how much helper copy and confirmation feedback to add. | Minimal text; short helper copy; more guided step labels. |
| Network conditions | Messages must account for weak signal. | Determines error wording and retry guidance. | Generic errors; signal-aware errors; retry-oriented errors. |
| Glove use | Touch targets are designed as if gloves or rough one-handed use are common. | Determines minimum control sizes and spacing. | 44px minimum; 52px preferred; extra-large field mode. |
| Lighting | The visual system must use high contrast and avoid relying on faint gray text. | Determines colors, contrast, and type weight. | High contrast; moderate contrast; dark-mode-oriented. |
| Language | English only for this overhaul. | Determines whether wording work needs translation support. | English only; prepare copy for later translation. |
| Visual complexity | Practical, sturdy, high-contrast UI beats decorative polish. | Determines the overall style direction. | Industrial/simple; modern app-like; more branded/polished. |
| Icons | Icons may support labels, but labels remain visible for primary actions. | Determines whether controls are text-first or icon-first. | Text labels only; icon plus text; icons for secondary tools only. |
| Functional scope | Label, copy, layout, focus, responsive behavior, and visual hierarchy may change; backend behavior, route contracts, and permissions do not change. | Prevents the overhaul from becoming a product rewrite. | Visual-only; frontend behavior polish allowed; broader workflow changes. |
| Tables on mobile | Routine worker tables become stacked/list-style layouts on narrow screens; desktop tables remain. | Determines mobile implementation complexity. | Keep tables; stacked rows on worker pages; stacked rows everywhere. |
| Scanner priority | Scan/search is the dominant worker entry point; manual table use remains as fallback. | Determines screen hierarchy. | Scan-first; search-first; equal scan/search. |
| Destructive actions | Delete, password reset, and correction are visually separated from routine actions. | Reduces accidental high-impact taps. | Separate section; confirmation emphasis; keep current placement with stronger styling. |
| Measurements | Use CSS responsive breakpoints, not device-specific branches. | Keeps the static frontend simple. | CSS breakpoints only; device-specific tweaks if needed. |
| Success criteria | Field usability is judged by task completion without coaching, not aesthetics alone. | Determines how the overhaul is evaluated. | Task-completion focus; visual polish focus; mixed scorecard. |
| First screen after login | Owner/Admin land on Add Item; Supervisor/Technician land on Find Item in the first pass. | Determines the first experience after sign-in. | Keep current role landing; all users land on Scan / Stock; all users land on Find Item. |
| Main nav label | Use "Scan / Stock" for the transaction page in the first pass. | Determines whether workers understand the transaction page. | Scan / Stock; Stock / Dispense; Add or Take Stock. |
| Stock language | Use "Add Stock" and "Take Out Stock" as visible labels; keep `stock` and `dispense` as internal values. | Determines whether wording matches crew language. | Add/Take Out Stock; Stock/Dispense; Add/Remove. |
| Find Item layout | Use stacked item rows on mobile; keep desktop tables. | Determines mobile readability and development scope. | Keep tables; mobile stacked rows; card-style item rows. |
| Find Item priority | Put scanning first, then manual search, then results. | Determines top-of-screen hierarchy. | Scan first; search first; side-by-side on larger screens. |
| Correction wording | Use "Correct Count" with a short warning sentence. | Determines whether correction feels distinct from routine stock movement. | Correct Count; Adjust Quantity; Fix Shelf Count. |

---

## Field Trial Validation Points

These are **not blockers** for planning, but they should be observed after the owner chooses the relevant assumptions above.

- Watch whether Supervisor/Technician users hesitate on the Find Item landing page.
- Watch whether "Scan / Stock" is understood as the transaction page.
- Watch whether "Take Out Stock" is clearer than "Dispense" in live use.
- Watch whether stacked mobile rows slow down high-volume item scanning.
- Watch whether scan-first on Find Item helps or gets in the way.
- Watch whether "Correct Count" creates enough caution for Admin users.

Field trial findings should be recorded in this document before making second-round changes.

---

## Non-Goals

This overhaul should **not** change the core function of the app.

Out of scope:

- New backend routes.
- Database schema changes.
- New roles or permission rules.
- New inventory workflows.
- Replacing FastAPI/static JS with React or another frontend framework.
- Changing barcode decoding logic.
- Adding new barcode formats.
- Reworking authentication behavior.
- Turning the app into a PWA/offline app.

Small frontend behavior changes are allowed only when they make the current workflow clearer, such as focusing the next field, improving button labels, or changing where messages appear.

---

## Assumption Handling Rule

When an AI agent finds an unresolved design or product choice, it must not decide silently.

The agent must:

1. Name the assumption.
2. Explain why it matters.
3. Offer 2-4 concrete options.
4. Ask the owner to choose before implementing that part.

This applies especially to:

- Navigation labels.
- Landing pages by role.
- Worker-facing terminology.
- Mobile layout patterns.
- Whether a change is visual-only or changes workflow.
- Any change that could affect how a construction worker understands the app.

If the owner has already made a clear choice in the current conversation or in this document, the agent may proceed with that choice and cite it.

---

## AI Execution Contract

When an AI agent implements this overhaul, it must treat the task as a frontend UX/UI pass, not a product rewrite.

### Must Preserve

- Existing backend routes.
- Existing request and response schemas.
- Existing database models and migrations.
- Existing auth behavior.
- Existing role permissions.
- Existing inventory workflows:
  - Add item.
  - Find item.
  - Scan barcode.
  - Add stock.
  - Take out stock.
  - Correct count.
  - Edit notes.
  - Manage users.
  - View history.
- Existing API request/response shapes.
- Existing DOM IDs used by JavaScript unless the same change also updates `docs/interfaces.md`.
- Existing tests must continue to pass.

### Must Ask Before Changing

- Navigation labels.
- Default landing page by role.
- Any workflow sequence.
- Any backend behavior.
- Any dependency or framework.
- Any destructive-action behavior.
- Any terminology that changes business meaning, such as `dispense`, `correction`, or `work order`.
- Any assumption listed in "Assumptions To Confirm Before Implementation."

### May Change Without Asking

Only when the change stays inside already-approved assumptions and does not alter workflow:

- CSS layout.
- Spacing.
- Typography.
- Colors.
- Responsive behavior.
- Visible helper copy.
- Error and success message wording.
- Button sizing.
- Visual hierarchy.
- Mobile presentation of existing data.
- Placement of existing controls, as long as the same functions remain available and discoverable.

### Required Verification

Before considering implementation complete, the agent should:

- Check mobile portrait layout.
- Check desktop layout.
- Confirm no routine horizontal scrolling on worker-facing pages.
- Confirm scan, stock, dispense/take-out-stock, notes, correction, users, and history still work.
- Run backend tests.
- Update `docs/spec.md` and `docs/interfaces.md` when labels, DOM structure, or behavior-visible copy changes.
- Report any assumption that was left unresolved or deferred.

---

## First Implementation Slice

Do not attempt the entire overhaul in one pass.

The first implementation slice should be limited to:

- Global visual system in `backend/static/styles.css`.
- Login screen.
- Find Item / Saved Items.
- Scan / Stock transaction page.
- Message wording improvements.
- Mobile responsive layout for worker-facing pages.

Do not substantially redesign these areas in Phase 1 unless the owner explicitly chooses to include them:

- Add User.
- Saved Users.
- History.
- Notes.
- Item Editor.
- Correction.

Global styles may affect those screens, but their detailed workflows should wait for later phases.

---

## Design Principles

1. **Make the next action obvious.**  
   Each screen should visually answer: "What do I do now?"

2. **Use plain jobsite language.**  
   Prefer "Add stock," "Take out stock," "Scan item," and "Try again" over technical phrasing.

3. **Big targets, big spacing.**  
   Buttons and inputs should be easy to hit with a thumb. Minimum touch target: 44px tall; preferred: 52px or larger for primary actions.

4. **Show fewer choices at once.**  
   Keep advanced or admin-only actions visually secondary. Field workers should not have to scan a dense table of options.

5. **Confirm what happened.**  
   Successful actions should produce simple, visible feedback: "Stock added," "Item saved," "Quantity corrected."

6. **Errors should tell the user what to do next.**  
   Avoid dead-end messages. Every error should include a recovery action when possible.

7. **Design for phones first.**  
   Desktop can remain functional, but the main experience should be comfortable on a phone in portrait orientation.

8. **Keep dangerous actions visually separate.**  
   Delete, correction, and password reset should not sit next to routine actions without clear separation.

9. **Use consistent visual meanings.**  
   Green means add/stock/success. Amber means dispense/warning. Red means delete/problem. Blue or neutral means navigation/editing.

10. **No training manual required.**  
   Short labels and helpful empty states should make screens self-explanatory without paragraphs of instructions.

---

## Visual Direction

The app should look practical, sturdy, and calm.

Chosen style:

- High contrast.
- Large readable type.
- Simple icon support where helpful.
- Clear section headers.
- Strong primary buttons.
- Less dense table presentation on mobile.
- Cards or list rows for mobile item views, while desktop tables can remain.
- Plain backgrounds with subtle separation.

Avoid:

- Decorative complexity.
- Tiny gray text as the only instruction.
- Dense admin-dashboard styling on phone screens.
- Overly clever icons without labels.
- Low-contrast color palettes.
- Text-heavy help blocks.

---

## Navigation Improvements

Current pages can stay, but labels should be clearer for the crew.

Planned label changes:

| Current | Field-friendly |
|---|---|
| Create Item | Add Item |
| Saved Items | Find Item |
| Create User | Add User |
| Saved Users | Users |
| Transaction | Scan / Stock |
| History | History |

Planned navigation behavior:

- Make the active page unmistakable.
- Put the most common worker workflow first for non-admin roles: Scan / Stock or Find Item.
- Keep admin pages visible only to roles that can use them.
- On mobile, use fewer visible choices per role and make the current page obvious. Start with the existing top navigation unless testing shows it is hard to reach; do not introduce a bottom navigation in the first pass.

No route or permission changes are required.

---

## Screen-by-Screen Plan

### Login

Current function stays the same.

Improvements:

- Larger title and simpler sign-in layout.
- Bigger username/password fields.
- Primary button label: "Sign In."
- Error message rewrite:
  - Current idea: "Invalid username or password."
  - Field-friendly: "That sign-in did not work. Check the username and password, then try again."

### Add Item

Current function stays the same.

Improvements:

- Rename page to "Add Item."
- Make barcode the first, strongest field.
- Add short helper text only where useful:
  - Barcode: "Scan or type the label number."
  - Location: "Where workers will find it."
- Primary button: "Save Item."
- Success message: "Item saved."
- Keep starting quantity, but make default `0` visually clear.

### Find Item / Saved Items

Current function stays the same.

Improvements:

- Rename page to "Find Item."
- Make scan/search the top of the page and visually dominant.
- Search placeholder: "Search name or barcode."
- On mobile, replace the wide table with stacked item rows:
  - Item name large.
  - Barcode and location secondary.
  - Quantity very visible.
  - Actions behind one clear "Actions" control.
- Keep action availability role-based.
- Make Supervisor notes access obvious but not visually mixed with Admin-only edit/delete/correct controls.

Action wording:

| Current | Suggested |
|---|---|
| Edit | Edit Details |
| Edit Notes | Notes |
| Correct | Correct Count |
| Delete | Delete Item |

### Scan / Stock

Current transaction function stays the same.

Improvements:

- Rename page to "Scan / Stock" for the first pass.
- Camera area should be the main visual element.
- Primary button: "Scan Barcode."
- Secondary button: "Upload Photo."
- After scan, show a large confirmation:
  - Item name.
  - Current quantity.
  - Location.
- Transaction form should feel like the active task:
  - Big quantity field.
  - Clear Stock / Dispense selector.
  - Large "Save Transaction" button.
  - Secondary "Cancel."
- Replace the type dropdown visually with two large segmented choices while preserving the same submitted `transaction_type` values:
  - "Add Stock"
  - "Take Out Stock"

No backend change required; this is a frontend presentation change.

### Correction

Current correction function stays the same.

Improvements:

- Label as "Correct Count."
- Explain in one line: "Use this when the shelf count is wrong."
- Show current quantity near the new quantity field.
- Primary button: "Save Correct Count."
- Reason label: "Why are you changing it?"
- Keep Admin+ gate.

### Notes

Current notes function stays the same.

Improvements:

- Rename "Edit Notes" to "Notes."
- Make note rows easier to scan.
- Use clearer labels:
  - "Note name"
  - "Type"
  - "Value"
- Add button label: "Add Another Note."
- Success: "Notes saved."

### Users

Current user function stays the same.

Improvements:

- Keep visually quieter than field workflows.
- Use clear role descriptions:
  - Technician: scan and do basic work.
  - Supervisor: transactions, notes, history.
  - Admin: manage items and corrections.
  - Owner: top-level setup.
- Separate password reset/delete from ordinary viewing.

### History

Current function stays the same.

Improvements:

- Keep as a supervisor/admin-oriented page.
- Make filters look like filters, not another form.
- Rename "Work Order" filter to "Filter by Work Order."
- Copy button label can remain "Copy table," but success should say "Copied history."
- On mobile, use stacked history rows:
  - Date/time.
  - Item.
  - Stock / Dispense / Correct Count.
  - Quantity.
  - Work order or reason.
  - User.

---

## Message Rewrite Guide

Examples:

| Technical / Current | Field-friendly |
|---|---|
| Could not connect to the server. | Could not reach the app. Check signal and try again. |
| Session expired or invalid. | You were signed out. Sign in again. |
| No barcode found in that image. | Could not read that barcode. Move closer, hold steady, and try again. |
| Insufficient stock to dispense. | Not enough stock available. Check the count before taking more out. |
| You do not have permission to perform this action. | Your account cannot do that. Ask a supervisor if this seems wrong. |
| No transactions found. | No history found for those filters. |
| At least one of barcode, name, or location is required. | Change at least one field before saving. |

Rule: message text should be short, direct, and action-oriented.

---

## Mobile Layout Requirements

Minimum requirements for the overhaul:

- Primary buttons at least 52px tall.
- Inputs at least 48px tall.
- Body text at least 16px on mobile.
- Avoid horizontal scrolling for routine worker pages.
- Tables should collapse or transform on narrow screens for worker-facing pages.
- Important buttons should not be side-by-side if accidental taps are likely.
- Form sections should scroll the active task into view after scan/action selection.
- Success/error messages should appear close to the control that caused them.

---

## Accessibility And Durability

Even if this is an internal app, the field conditions make accessibility practical, not optional.

Requirements:

- Strong color contrast.
- Visible focus states.
- Labels tied to inputs.
- Buttons named by visible text, not icon-only controls.
- Do not rely on color alone for meaning.
- Keep `aria-label` for compact controls like action dropdowns.
- Preserve keyboard usability for desktop/admin use.

---

## Implementation Scope

Likely files touched:

- `backend/static/index.html`
- `backend/static/styles.css`
- `backend/static/views/auth.js`
- `backend/static/views/nav.js`
- `backend/static/views/items.js`
- `backend/static/views/transactions.js`
- `backend/static/views/history.js`
- `backend/static/views/users.js`
- `backend/static/views/notes.js`
- `backend/static/views/itemEditor.js`
- `backend/static/views/correction.js`
- `docs/spec.md`
- `docs/interfaces.md`

Expected work type:

- CSS redesign.
- HTML structure adjustments.
- Button/label/message copy changes.
- Responsive mobile layouts.
- Minor frontend-only behavior polish.

Backend changes should be avoided unless a visual requirement exposes a small missing frontend data need. Any backend change should be treated as out of scope unless explicitly approved.

---

## Acceptance Criteria

The overhaul is successful when:

- A Technician can open the app, scan an item, enter quantity, save, and understand the result without coaching.
- A Supervisor can find an item and update notes without hunting through admin controls.
- An Admin can correct a count without confusing correction with stock/dispense.
- Mobile portrait layout has no routine horizontal scrolling.
- Primary actions are visually obvious.
- Error messages tell the user what to do next.
- Existing backend tests still pass.
- Existing app functions remain intact.
- `docs/spec.md` and `docs/interfaces.md` are updated for any changed labels, DOM structure, or frontend behavior.

---

## Suggested Phases

### Phase 1 - Language And Hierarchy

- Rename nav labels.
- Rewrite common messages.
- Make primary actions bigger and clearer.
- Keep layout mostly intact.

### Phase 2 - Mobile Worker Screens

- Improve Login, Find Item, and Scan / Stock first.
- Make scan/search dominant.
- Improve transaction form focus and visual hierarchy.
- Reduce table density on mobile.

### Phase 3 - Admin And History Polish

- Improve Add Item, Users, History, Notes, Correction.
- Keep admin workflows powerful but less visually noisy.

### Phase 4 - Field Trial

- Put it in front of actual crew members.
- Watch for hesitation, wrong taps, and repeated questions.
- Record findings in this document before making further changes.

---

## Field Trial Questions

Ask or observe:

- Can they tell where to tap first?
- Do they understand Stock vs Dispense?
- Do they notice success messages?
- Do they recover from a failed scan without help?
- Are buttons large enough with gloves?
- Do they accidentally tap destructive actions?
- Is the quantity field obvious after scanning?
- Does the app feel too "office software" for the jobsite?

---

## Design Decision Log

| Decision | Rationale |
|---|---|
| Keep function unchanged | The app workflow already works; the problem is clarity and confidence. |
| Design phone-first | The crew will mostly use phones in the field. |
| Prefer plain text labels over icon-only controls | Low-tech-tolerance users should not have to decode symbols. |
| Keep admin actions visually secondary | Most field work is scan, find, stock, dispense, notes. |
| Treat errors as recovery prompts | The user needs next steps, not technical diagnosis. |
