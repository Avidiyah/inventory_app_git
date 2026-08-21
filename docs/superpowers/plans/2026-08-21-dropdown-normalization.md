# Dropdown Normalization (Find Item / Add Item) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace every native `<select>` whose popup must match the theme with a themed popup menu, and fix the white-on-white hover on the Find Item results table.

**Architecture:** A native `<select>`'s open popup is drawn by the OS on some Windows/Chromium builds and ignores page CSS entirely — this is already diagnosed and field-confirmed in `docs/design-system.md` (2026-08-20), which prescribes building a custom listbox instead. That pattern already exists once, as `.wo-combo-*` in `views/workOrders.js`. This plan promotes it to a shared foundation module `backend/static/menus.js` with two shapes — a fire-and-close **action menu** (`role="menu"`) and a value-picking **combo** (`role="listbox"` + hidden real `<select>`) — then migrates all four remaining native-select sites onto it and deletes the page-local copy.

**Tech Stack:** Plain ES modules served statically (no build step, no bundler, CSP `default-src 'self'`), CSS custom properties in `backend/static/styles.css`, pytest for verification.

**Spec:** `docs/design-system.md` — specifically the "Two surface types" section's note on OS-rendered `<select>` popups, and the "Color on a dark surface" contrast table.

**Brief (verbatim from the owner):** *"Find Item and Add Item pages, dropdowns need to be stylized in accordance with normative principles throughout the rest of the page. Hovering makes text white with white background. BAD. Normalized Action Dropdown menus. Check for other aesthetic or design anomalies present."* Scope confirmed as **all** phases.

## Global Constraints

- **No new dependencies, no build step.** The app serves `backend/static/` as-is under CSP `default-src 'self'`. No npm, no bundler, no CDN.
- **There is no JavaScript test harness in this repo** — no `package.json`, no `node_modules`, no JS test runner. The 85-file suite in `backend/tests/` is all pytest. Frontend invariants are verified the way `test_work_order_status_parity.py` and `test_role_mirror_parity.py` already do it: read the static source as text and assert on it. Do **not** introduce a JS test runner to satisfy the TDD steps below.
- **Test command** (run from `backend/`, never the repo root): `venv/Scripts/python.exe -m pytest tests/<file> -v`. From the repo root, every test that imports `app.main` fails at *collection* with `RuntimeError: Directory 'static' does not exist`, because `main.py` mounts static with a relative path. Always invoke `python.exe -m pytest`, never the bare `pytest.exe` shim — this venv is a copy and its console-script launchers hard-code another checkout's interpreter.
- **If working in a git worktree:** worktrees have no venv of their own. Use the main checkout's `backend/venv/Scripts/python.exe` but keep cwd in the *worktree's* `backend/`, so pytest's rootdir resolves the worktree's code. Three idle worktrees already exist (`add-items-page-branding`, `find-item-page-branding`, `navbar-compact`), all sitting at `main`.
- **Never introduce a second brand red.** `--color-brand` (`#C8102E`) is the one red; `--color-brand-light` (`#FF7585`) is its lifted variant for text/outlines only.
- **Text on a panel must clear 4.5:1** against the composited panel color `#2A2B2D`.
- **All page fragments live in one document.** `read_root` assembles `shell-head.html` + every `pages/*.html` + `shell-tail.html` into a single DOM with `.page` divs toggled. Element IDs must be globally unique, and a `document`-level delegated listener sees every page.
- **Design-system doc is living.** A change that adds a surface type, a token, or overturns a rule updates `docs/design-system.md` in the same commit (Task 7).
- **Do not weaken the CI gate.** Merging to `main` deploys to production.

---

## Anomaly Audit (what this plan does and does not fix)

Found by reading `styles.css`, `views/items.js`, `views/tools.js`, `views/notes.js`, `pages/saved-items.html`, `pages/create-item.html`:

| # | Finding | Verdict |
|---|---|---|
| 1 | `#items-table tbody tr:hover` fills with `--gray-50` (`#F7F7F7`) while row text is `--text-panel` (`#EDEEF0`) — **near-white text on a near-white fill**. The code comment admits it: *"the other `.stack-table` users get it in their own branding pass."* This is the reported bug. | **Task 1** |
| 2 | Find Item's Actions column is a native `<select>` (`views/items.js:214-219`). Closed box is themed; open popup is OS-drawn and white. | **Tasks 2-3** |
| 3 | Tools page Actions column — identical native `<select>` (`views/tools.js:419-432`). | **Task 4** |
| 4 | Notes editor (a Find Item sub-flow) has two native selects: `.note-type` (`views/notes.js:80-84`) and the boolean value picker (`views/notes.js:105-108`). | **Tasks 5-6** |
| 5 | `.empty-state` uses `--gray-500` (`#6B6B6B`) on the composited panel `#2A2B2D` — **2.66:1**, far under the 4.5:1 floor. This is Find Item's "nothing searched yet" / "no items match" text, i.e. the first thing a user sees on the page. | **Task 7** |
| 6 | `styles.css` has **no `prefers-reduced-motion` block at all**, while `input`, `.menu-chevron`, `.wo-card` and others animate. | **Task 7** |
| 7 | `--gray-600` is used at `styles.css:1261` but **never defined** in `:root` (`grep -c "gray-600:"` → 0). The declaration is invalid at computed-value time, so `.user-request-resolved .user-request-status` silently inherits instead of going muted. | **Noted, not fixed** — User Requests page, outside this brief. Log to `docs/open-work.md` in Task 7. |
| 8 | `.lu-card-body` (`styles.css:3434-3445`) uses `--color-ink` (`#1A1A1A`) and `--gray-300` borders — the design system says `--color-ink` "disappears" on dark. | **Noted, not fixed** — work-order lookup card, outside this brief. Log to `docs/open-work.md` in Task 7. |
| 9 | `.wo-mode-select` (`styles.css:3479`) is another native `<select>` with the same OS-popup problem, on the Work Orders page. | **Noted, not fixed** — `menus.js` from Task 2 makes it a cheap follow-up. Log to `docs/open-work.md` in Task 7. |

**The Add Item page has no `<select>` at all.** Every field in `pages/create-item.html` is `text` / `number` / `url`. It is in scope only via the shared CSS and the `prefers-reduced-motion` fix; there is no dropdown there to normalize.

**Verified non-issues** (checked, do not "fix"):
- `views/tools.js:445` reads `"<th>Actions</th>"` correctly. A `<\th>` in grep output was a tool rendering artifact, confirmed with `sed | cat -A`.
- `#items-table` has **no** `overflow` ancestor, so an absolutely-positioned popover inside a `<td>` will not be clipped.
- The only `change` listener on the work-orders list filters for `.wo-mode-select` (`views/workOrders.js:1990-1992`). Dispatching `change` from the combo's hidden native select in Task 5 is therefore safe.

---

## File Structure

| File | Responsibility |
|---|---|
| **Create** `backend/static/menus.js` | Foundation layer, sibling of `dom.js` / `format.js` / `roles.js`. Owns both popup-menu shapes, their open/close state, one document-level delegated listener, and keyboard handling. No page knowledge. |
| **Create** `backend/tests/test_menu_parity.py` | Source-parity guards: no native row-action selects remain, no light fill is used as a hover, rendered `data-value`s all have handlers, required CSS rules exist, text tokens clear 4.5:1. |
| **Modify** `backend/static/styles.css` | Add the `.menu-*` block; delete `.row-actions-select` and `.wo-combo-*`; fix the row hover and `.empty-state`; add `prefers-reduced-motion`. |
| **Modify** `backend/static/views/items.js` | Find Item Actions column: render via `actionMenuHtml`, handle via `initActionMenus` instead of a `change` listener. |
| **Modify** `backend/static/views/tools.js` | Same migration for the Tools Actions column. |
| **Modify** `backend/static/views/workOrders.js` | Delete the local `comboHtml` / `comboListHtml` / `closeCombo` and their `toggle-combo` / `pick-combo-option` branches; import from `menus.js`. |
| **Modify** `backend/static/views/notes.js` | `.note-type` and the boolean value picker become combos. |
| **Modify** `docs/design-system.md` | Record that the shared menu is now the app-wide answer, superseding the `.wo-combo-*` pointer. |
| **Modify** `docs/open-work.md` | Log findings 7, 8, 9. |

---

### Task 1: Fix the white-on-white row hover

The reported bug, isolated and independently shippable. Ship it first so it is not gated behind the component work.

**Files:**
- Modify: `backend/static/styles.css:797-804`
- Test: `backend/tests/test_menu_parity.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `backend/tests/test_menu_parity.py` with helpers `_css()` and `_root_token(name)`, both reused by later tasks.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_menu_parity.py`:

```python
"""Guards for the themed popup menus and the dark-surface color rules.

Layer: unit (no DB, no browser). There is no JavaScript test harness in
this repo, so front-end invariants are checked the way
`test_work_order_status_parity.py` checks the status vocabulary: read the
static source as text and assert on it. Parsing CSS and JS with regexes is
crude, but the alternative is trusting hand-edited files to stay in step,
which is exactly what silently regressed here -- `#items-table`'s row hover
kept a light `--gray-50` fill through the flip to a dark canvas, so hovering
a row painted near-white text (`--text-panel`) on a near-white background.
"""

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

STATIC = Path(__file__).resolve().parents[1] / "static"
STYLES_CSS = STATIC / "styles.css"

# The panel color the app's text actually sits on: --panel-bg composited over
# --color-canvas. Contrast in docs/design-system.md is measured against this,
# not against the canvas.
COMPOSITED_PANEL = "#2A2B2D"

# Light neutrals from the pre-dark-canvas design. Any of these as a *fill*
# behind panel text reproduces the white-on-white bug.
LIGHT_FILLS = ("--gray-50", "--gray-100", "--gray-200", "--color-white")


def _css() -> str:
    return STYLES_CSS.read_text(encoding="utf-8")


def _root_token(name: str) -> str:
    """The hex value of a custom property declared in :root."""
    match = re.search(rf"{re.escape(name)}:\s*(#[0-9A-Fa-f]{{3,8}})", _css())
    assert match, f"{name} is not declared with a hex value in :root"
    return match.group(1)


def _rule_body(selector: str) -> str:
    """The declarations inside the first rule matching `selector`."""
    match = re.search(
        rf"{re.escape(selector)}\s*\{{(.*?)\}}", _css(), re.DOTALL
    )
    assert match, f"no CSS rule found for {selector!r}"
    return match.group(1)


def _relative_luminance(hex_color: str) -> float:
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 3:
        hex_color = "".join(ch * 2 for ch in hex_color)
    channels = []
    for offset in (0, 2, 4):
        value = int(hex_color[offset : offset + 2], 16) / 255
        channels.append(
            value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
        )
    red, green, blue = channels
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast(foreground: str, background: str) -> float:
    light = _relative_luminance(foreground)
    dark = _relative_luminance(background)
    if light < dark:
        light, dark = dark, light
    return (light + 0.05) / (dark + 0.05)


def test_the_contrast_helper_agrees_with_the_design_system_table():
    """docs/design-system.md publishes measured ratios. If this helper does
    not reproduce them, every other contrast assertion here is meaningless."""
    assert round(_contrast(_root_token("--color-brand"), COMPOSITED_PANEL), 1) == 2.4
    assert round(_contrast(_root_token("--color-brand-light"), COMPOSITED_PANEL), 1) == 5.5


def test_the_items_row_hover_is_not_a_light_fill():
    """Find Item's results row. Row text is --text-panel (#EDEEF0); a light
    fill here is near-white text on a near-white background."""
    body = _rule_body("#items-table tbody tr:hover")
    for token in LIGHT_FILLS:
        assert token not in body, (
            f"#items-table row hover fills with {token}, which is near-white; "
            "row text is --text-panel and becomes unreadable"
        )
    assert "--panel-hover" in body


def test_no_light_neutral_is_used_as_a_background_anywhere():
    """docs/design-system.md: 'nothing in the app reads them as a background
    anymore'. This is the guard that makes that sentence true."""
    offenders = [
        line.strip()
        for line in _css().splitlines()
        if re.search(r"background(-color)?:\s*var\(--gray-(50|100|200)\)", line)
    ]
    assert offenders == [], f"light neutral used as a fill on a dark surface: {offenders}"
```

- [ ] **Step 2: Run the tests to verify the new ones fail**

Run (from `backend/`):
```bash
venv/Scripts/python.exe -m pytest tests/test_menu_parity.py -v
```
Expected: `test_the_contrast_helper_agrees_with_the_design_system_table` PASSES (it validates the helper against already-shipped values). `test_the_items_row_hover_is_not_a_light_fill` and `test_no_light_neutral_is_used_as_a_background_anywhere` both FAIL, each naming `--gray-50`.

- [ ] **Step 3: Fix the hover**

In `backend/static/styles.css`, replace the rule at lines 797-804:

```css
/* Find Item results: row hover, gated on a real pointer so a tapped row on a
   phone doesn't keep the highlight stuck to it.
   --panel-hover, not --gray-50: this rule survived the flip to a dark canvas
   unchanged, and a #F7F7F7 fill under --text-panel (#EDEEF0) row text made a
   hovered row white-on-white. */
@media (hover: hover) {
    #items-table tbody tr:hover {
        background-color: var(--panel-hover);
    }
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (from `backend/`):
```bash
venv/Scripts/python.exe -m pytest tests/test_menu_parity.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Confirm no other test read that rule**

Run (from `backend/`):
```bash
venv/Scripts/python.exe -m pytest tests/ -q
```
Expected: the full suite passes, same count as before the change.

- [ ] **Step 6: Commit**

```bash
git add backend/static/styles.css backend/tests/test_menu_parity.py
git commit -m "fix(find-item): row hover no longer paints white text on a white fill"
```

---

### Task 2: Build the shared action menu

The component, with no consumers yet, so it can be reviewed on its own.

**Files:**
- Create: `backend/static/menus.js`
- Modify: `backend/static/styles.css` (add the `.menu-*` block)
- Test: `backend/tests/test_menu_parity.py`

**Interfaces:**
- Consumes: `escapeHtml` from `backend/static/format.js`.
- Produces:
  - `actionMenuHtml({ id, triggerLabel, ariaLabel, itemId, options }) -> string` where `options` is `Array<{ value: string, label: string, danger?: boolean }>`. Returns `""` when `options` is empty.
  - `initActionMenus(root: Element, onPick: (value: string, itemId: string) => void) -> void`
  - `closeMenu(menu: Element) -> void`
  - `closeAllMenus(root?: ParentNode) -> void`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_menu_parity.py`:

```python
MENUS_JS = STATIC / "menus.js"


def test_the_shared_menu_module_exists_and_exports_its_api():
    """items.js, tools.js, workOrders.js and notes.js all import from here.
    A rename that misses one is a dead dropdown with no error anywhere."""
    source = MENUS_JS.read_text(encoding="utf-8")
    for export in (
        "export function actionMenuHtml",
        "export function initActionMenus",
        "export function closeMenu",
        "export function closeAllMenus",
    ):
        assert export in source, f"menus.js is missing: {export}"


def test_the_action_menu_is_a_menu_not_a_listbox():
    """A fire-and-close command menu. role=listbox + aria-selected would
    promise a persistent selection the Actions column never has."""
    source = MENUS_JS.read_text(encoding="utf-8")
    action_menu = re.search(
        r"export function actionMenuHtml\(.*?\n\}", source, re.DOTALL
    )
    assert action_menu, "actionMenuHtml was not found in menus.js"
    body = action_menu.group(0)
    assert 'role="menu"' in body
    assert 'role="menuitem"' in body
    assert 'aria-haspopup="menu"' in body
    assert "aria-selected" not in body


def test_the_menu_has_the_css_it_renders_against():
    """menus.js writes these class names; without a rule each one falls back
    to the global `button` style, which is a solid brand-red block."""
    css = _css()
    for selector in (
        ".menu {",
        ".menu-trigger {",
        ".menu-trigger:hover",
        ".menu-list {",
        ".menu-list[hidden]",
        ".menu-option {",
        ".menu-option-danger {",
        ".menu-chevron {",
    ):
        assert selector in css, f"menus.js renders markup with no rule for {selector!r}"


def test_the_menu_popover_is_readable_on_its_own_background():
    """The popover is --color-header, darker than a panel, so panel text
    tokens have to be re-checked against it rather than assumed."""
    header = _root_token("--color-header")
    assert _contrast(_root_token("--text-panel"), header) >= 4.5
    assert _contrast(_root_token("--color-brand-light"), header) >= 4.5


def test_the_hidden_menu_list_actually_hides():
    """.menu-list sets display:flex, and [hidden] is only display:none in the
    UA sheet -- the flex wins unless this rule exists to outrank it."""
    assert re.search(r"\.menu-list\[hidden\]\s*\{\s*display:\s*none", _css())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `backend/`):
```bash
venv/Scripts/python.exe -m pytest tests/test_menu_parity.py -v
```
Expected: the five new tests FAIL. The first errors with `FileNotFoundError` for `menus.js`; the CSS ones fail on the missing selectors.

- [ ] **Step 3: Create the module**

Create `backend/static/menus.js`:

```js
// Foundation: themed popup menus that replace native <select> controls.
//
// Layer: foundation. Sits below the views, like dom.js and format.js, so any
// page can open a themed menu without importing another page's module.
//
// Why this exists: a native <select>'s open popup is drawn by the OS on some
// Windows/Chromium builds and ignores page CSS entirely, so it renders as a
// white system list on our dark UI. `color-scheme: dark` and
// `select option { background-color }` do not reach that path -- confirmed by
// field testing on 2026-08-20. See docs/design-system.md. Anything whose popup
// must match the theme is built here instead of with a real <select>.
//
// One shape for now; comboHtml (a value picker that keeps a hidden real
// <select>) moves in alongside it in a later task.
//
//   actionMenuHtml()  fire-and-close command menu (role="menu"). Picking an
//                     option runs an action; nothing stays selected.

import { escapeHtml } from "./format.js";

const CHEVRON =
  '<svg class="menu-chevron" viewBox="0 0 20 20" aria-hidden="true">' +
  '<path d="M5 8l5 5 5-5" fill="none" stroke="currentColor" stroke-width="2" ' +
  'stroke-linecap="round" stroke-linejoin="round"/></svg>';

// `options`: [{ value, label, danger? }]. `danger` puts the item below a
// hairline in ghost red -- the treatment .delete-user-btn already uses for an
// archive action. It is a signal, not the safeguard; the caller still
// confirms.
export function actionMenuHtml({ id, triggerLabel = "Actions", ariaLabel, itemId, options }) {
  if (!options || options.length === 0) return "";
  const items = options
    .map(
      ({ value, label, danger }) =>
        `<button type="button" role="menuitem" class="menu-option${danger ? " menu-option-danger" : ""}" data-menu-action="pick" data-value="${escapeHtml(value)}">${escapeHtml(label)}</button>`
    )
    .join("");
  return `<div class="menu action-menu" data-menu data-id="${escapeHtml(itemId)}">
            <button type="button" class="menu-trigger" data-menu-action="toggle"
                    aria-haspopup="menu" aria-expanded="false"
                    aria-controls="${escapeHtml(id)}" aria-label="${escapeHtml(ariaLabel)}">
              <span class="menu-trigger-label">${escapeHtml(triggerLabel)}</span>
              ${CHEVRON}
            </button>
            <div class="menu-list" id="${escapeHtml(id)}" role="menu" aria-label="${escapeHtml(ariaLabel)}" hidden>
              ${items}
            </div>
          </div>`;
}

function listOf(menu) {
  return menu ? menu.querySelector(".menu-list") : null;
}

function triggerOf(menu) {
  return menu ? menu.querySelector(".menu-trigger") : null;
}

export function closeMenu(menu) {
  const list = listOf(menu);
  const trigger = triggerOf(menu);
  if (list) list.hidden = true;
  if (trigger) trigger.setAttribute("aria-expanded", "false");
}

export function closeAllMenus(root = document) {
  root.querySelectorAll("[data-menu]").forEach(closeMenu);
}

function openMenu(menu) {
  // Document-wide, not root-wide: every page fragment shares one DOM, so a
  // menu left open on a hidden page would still be open when it comes back.
  closeAllMenus();
  const list = listOf(menu);
  const trigger = triggerOf(menu);
  if (list) list.hidden = false;
  if (trigger) trigger.setAttribute("aria-expanded", "true");
}

// Registry rather than a listener per table: rows are rebuilt by innerHTML on
// every render, so a listener bound to a button would not survive. One
// document-level listener below reads this to find whose callback to run.
const pickHandlers = [];

export function initActionMenus(root, onPick) {
  pickHandlers.push({ root, onPick });
}

function optionsOf(menu) {
  return Array.from(menu.querySelectorAll(".menu-option"));
}

document.addEventListener("click", (event) => {
  const btn = event.target.closest("[data-menu-action]");
  if (!btn) {
    // A click anywhere else dismisses. Cheap, and it covers the backdrop,
    // another row, and the page chrome in one rule.
    closeAllMenus();
    return;
  }

  const menu = btn.closest("[data-menu]");
  if (!menu) return;

  if (btn.dataset.menuAction === "toggle") {
    if (listOf(menu).hidden) openMenu(menu);
    else closeMenu(menu);
    return;
  }

  if (btn.dataset.menuAction === "pick") {
    closeMenu(menu);
    triggerOf(menu)?.focus();
    const entry = pickHandlers.find((handler) => handler.root.contains(menu));
    entry?.onPick(btn.dataset.value, menu.dataset.id);
  }
});

document.addEventListener("keydown", (event) => {
  const menu = event.target.closest?.("[data-menu]");
  if (!menu) return;

  if (event.key === "Escape") {
    closeMenu(menu);
    triggerOf(menu)?.focus();
    return;
  }

  const isTrigger = event.target.classList.contains("menu-trigger");

  // role="menu" promises arrow-key navigation; without it the role is a lie
  // to a screen reader that a mouse user would never notice.
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    event.preventDefault();
    if (isTrigger && listOf(menu).hidden) {
      openMenu(menu);
      optionsOf(menu)[0]?.focus();
      return;
    }
    const options = optionsOf(menu);
    const current = options.indexOf(event.target);
    const step = event.key === "ArrowDown" ? 1 : -1;
    const next = (current + step + options.length) % options.length;
    options[next]?.focus();
    return;
  }

  if (event.key === "Home" || event.key === "End") {
    if (isTrigger) return;
    event.preventDefault();
    const options = optionsOf(menu);
    (event.key === "Home" ? options[0] : options[options.length - 1])?.focus();
  }
});

// Tab out of the menu entirely -- not caught by the click or Escape paths.
document.addEventListener("focusout", (event) => {
  const menu = event.target.closest?.("[data-menu]");
  if (!menu) return;
  setTimeout(() => {
    if (!menu.contains(document.activeElement)) closeMenu(menu);
  }, 0);
});
```

- [ ] **Step 4: Add the CSS**

In `backend/static/styles.css`, add a new block immediately **before** the `/* =================== TABLES =================== */` comment (line 773):

```css
/* =================== POPUP MENUS =================== */
/* Shared trigger + popover for anything that used to be a native <select>.
   A native select's open popup is drawn by the OS on some Windows/Chromium
   builds and ignores page CSS, so it renders as a white system list on our
   dark UI -- see docs/design-system.md. Rendered by static/menus.js.
   Every rule here has to out-specify the global `button` style, which is a
   solid brand-red block; `.menu-trigger` (0,1,0) beats `button` (0,0,1) and
   `.menu-trigger:hover` (0,2,0) beats `button:hover` (0,1,1). */
.menu { position: relative; }

.menu-trigger {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    width: 100%;
    min-height: var(--control-h);
    padding: 0 var(--space-3);
    margin-top: 0;
    border: var(--border-input);
    border-radius: var(--radius-md);
    background-color: var(--input-bg);
    color: var(--text-panel);
    font-size: var(--fs-base);
    font-family: inherit;
    font-weight: normal;
    text-align: left;
    cursor: pointer;
    /* Matches the inset well on input/select/textarea so a menu trigger and a
       text field read as the same class of control. */
    box-shadow: inset 0 1px 3px rgba(0, 0, 0, .35);
}

.menu-trigger:hover { background-color: var(--panel-hover); }

.menu-chevron {
    width: 16px;
    height: 16px;
    flex: 0 0 auto;
    color: var(--text-panel-mute);
    transition: transform .12s ease;
}

.menu-trigger[aria-expanded="true"] .menu-chevron { transform: rotate(180deg); }

/* Right-aligned with min-width rather than left/right pinned: the Actions
   column is the last one, so a left-aligned popover would run off the
   viewport, while a full-width trigger still gets a full-width popover. */
.menu-list {
    position: absolute;
    z-index: 20;
    top: calc(100% + var(--space-1));
    right: 0;
    min-width: 100%;
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    max-height: 240px;
    overflow-y: auto;
    padding: var(--space-2);
    border: 1px solid var(--gray-700);
    border-radius: var(--radius-sm);
    /* --color-header, not --panel-bg: a translucent popover over a
       translucent panel composites to mud and the text behind shows through. */
    background-color: var(--color-header);
    box-shadow: var(--shadow-md);
    scrollbar-width: thin;
    scrollbar-color: var(--gray-700) transparent;
}

/* [hidden] is only display:none in the UA sheet, which the display:flex above
   outranks. Without this the popover is always open. */
.menu-list[hidden] { display: none; }

.menu-option {
    display: flex;
    align-items: center;
    justify-content: flex-start;
    width: 100%;
    min-height: var(--btn-h-sm);
    margin-top: 0;
    padding: 0 var(--space-3);
    border: none;
    border-radius: var(--radius-sm);
    background-color: transparent;
    color: var(--text-panel);
    font-size: var(--fs-sm);
    font-family: inherit;
    font-weight: normal;
    text-align: left;
    white-space: nowrap;
    cursor: pointer;
}

.menu-option:hover,
.menu-option:focus-visible { background-color: var(--panel-hover); }

/* Archive/remove. Ghost red below a hairline -- the treatment
   .delete-user-btn already uses for exactly this action. Red here is the
   brand red doing double duty as emphasis, not a "delete hue": the real
   safeguard is the separating rule plus confirmDialog().
   Hover keeps --color-brand-light rather than dropping to
   --color-brand-hover the way .note-remove-btn does; #A50D25 on this
   near-black popover is about 2:1, whereas .note-remove-btn sits on a
   lighter panel. */
.menu-option-danger {
    margin-top: var(--space-1);
    padding-top: var(--space-1);
    border-top: 1px solid var(--panel-rule);
    border-radius: 0 0 var(--radius-sm) var(--radius-sm);
    color: var(--color-brand-light);
}

.menu-option-danger:hover,
.menu-option-danger:focus-visible {
    background-color: var(--color-brand-tint);
    color: var(--color-brand-light);
}

/* In a table cell the trigger is a compact control, not a full-width field. */
.action-menu { display: inline-block; }

.action-menu .menu-trigger {
    width: auto;
    min-height: var(--btn-h-sm);
    padding: 0 var(--space-2);
    font-size: var(--fs-sm);
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run (from `backend/`):
```bash
venv/Scripts/python.exe -m pytest tests/test_menu_parity.py -v
```
Expected: 9 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/static/menus.js backend/static/styles.css backend/tests/test_menu_parity.py
git commit -m "feat(ui): add shared themed action menu to replace native selects"
```

---

### Task 3: Migrate Find Item's Actions column

**Files:**
- Modify: `backend/static/views/items.js:16-47` (imports), `:202-219` (`actionsCell`), `:389-400` (the `change` listener)
- Modify: `backend/static/styles.css` (drop `.row-actions-select`, update the mobile rule at `:4062`)
- Test: `backend/tests/test_menu_parity.py`

**Interfaces:**
- Consumes: `actionMenuHtml`, `initActionMenus` from Task 2.
- Produces: nothing new for later tasks.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_menu_parity.py`:

```python
ITEMS_JS = STATIC / "views" / "items.js"
TOOLS_JS = STATIC / "views" / "tools.js"


def _rendered_menu_values(source: str) -> set:
    return set(re.findall(r'value:\s*"([a-z-]+)"', source))


def _handled_action_values(source: str) -> set:
    return set(re.findall(r'action === "([a-z-]+)"', source))


def test_find_item_no_longer_uses_a_native_select_for_row_actions():
    """The one control on this page whose popup the OS may draw itself."""
    source = ITEMS_JS.read_text(encoding="utf-8")
    assert "row-actions-select" not in source
    assert "<select" not in source
    assert "actionMenuHtml" in source


def test_find_items_menu_options_all_have_handlers():
    """actionsCell writes value strings that the pick callback reads back by
    string. A rename in one place and not the other is a dead menu item with
    no error anywhere -- same guard as the work-order walkthrough actions."""
    source = ITEMS_JS.read_text(encoding="utf-8")
    assert _rendered_menu_values(source) <= _handled_action_values(source)


def test_find_items_archive_option_is_marked_dangerous():
    """Archive is the one irreversible-looking action in the menu; it gets
    the separating rule and the ghost-red treatment."""
    source = ITEMS_JS.read_text(encoding="utf-8")
    archive = re.search(r'\{[^}]*value:\s*"delete"[^}]*\}', source)
    assert archive, 'no menu option with value "delete" found in items.js'
    assert "danger: true" in archive.group(0)


def test_the_dead_row_action_select_style_is_gone():
    assert ".row-actions-select" not in _css()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `backend/`):
```bash
venv/Scripts/python.exe -m pytest tests/test_menu_parity.py -v
```
Expected: the four new tests FAIL — `items.js` still contains `row-actions-select` and `<select`, and `styles.css` still has `.row-actions-select`.

- [ ] **Step 3: Import the component**

In `backend/static/views/items.js`, add after the `subnav.js` import (line 46):

```js
import { actionMenuHtml, initActionMenus } from "../menus.js";
```

- [ ] **Step 4: Replace `actionsCell`**

Replace `backend/static/views/items.js:202-219` with:

```js
  // Per-row Actions menu (only the actions this role can perform). Returns
  // the empty string for a role with no actions, so the column is omitted.
  // A themed menu rather than a <select>: the OS draws a select's popup
  // itself on some Windows/Chromium builds, in white (docs/design-system.md).
  function actionsCell(item) {
    const options = [];
    if (canAdmin) options.push({ value: "edit", label: "Edit Details" });
    if (canNotes) options.push({ value: "notes", label: "Notes" });
    if (canAdmin) {
      options.push({ value: "correct", label: "Correct Count" });
      options.push({ value: "delete", label: "Archive Item", danger: true });
    }
    return actionMenuHtml({
      id: `row-actions-${item.id}`,
      ariaLabel: `Actions for ${item.name}`,
      itemId: item.id,
      options,
    });
  }
```

Note: `actionMenuHtml` returns `""` for an empty `options`, so the `if (options.length === 0) return ""` guard is no longer needed here. The `<label class="sr-only">` is gone too — the trigger carries `aria-label` directly, so the extra label was naming a control that no longer exists.

- [ ] **Step 5: Replace the change listener with a pick handler**

Replace `backend/static/views/items.js:389-402` — the `itemsTbody.addEventListener("change", ...)` opening through the `if (!item) return;` line — with:

```js
initActionMenus(itemsTbody, async (action, itemId) => {
  if (!action || !itemId) return;
  const item = getItems().find(i => i.id === itemId);
  if (!item) return;
```

Leave the rest of the function body (the `if (action === "edit")` chain onward) exactly as it is, and keep its closing `});`.

The comment about resetting `target.value` is deleted with the listener: a fire-and-close menu has no value to remember, which is the behavior that comment was working around.

- [ ] **Step 6: Update the CSS**

In `backend/static/styles.css`, delete the `.row-actions-select` rule (lines 870-880). Keep `.row-actions` above it — it is a separate flex wrapper still used elsewhere.

Then replace the mobile rule at line 4062:

```css
    .stack-table .action-menu,
    .stack-table .action-menu .menu-trigger { width: 100%; }
```

- [ ] **Step 7: Run the tests to verify they pass**

Run (from `backend/`):
```bash
venv/Scripts/python.exe -m pytest tests/test_menu_parity.py -v
```
Expected: 13 passed.

- [ ] **Step 8: Manual check**

The owner validates UI manually and prefers the preview server not be auto-started. Hand off with: on the **Find Item** page as an Admin/Owner, search for an item, open the row's Actions menu, and confirm the popover is dark, hovering an option shows a subtle light wash (not white-on-white), Archive sits below a hairline in red, Escape closes and returns focus to the trigger, and Archive still asks for confirmation.

- [ ] **Step 9: Commit**

```bash
git add backend/static/views/items.js backend/static/styles.css backend/tests/test_menu_parity.py
git commit -m "feat(find-item): replace the Actions select with the themed menu"
```

---

### Task 4: Migrate the Tools Actions column

Identical bug, and the component from Task 2 makes it nearly free.

**Files:**
- Modify: `backend/static/views/tools.js` (imports, `actionsCell` at `:419-432`, the `change` listener at `:489-499`)
- Test: `backend/tests/test_menu_parity.py`

**Interfaces:**
- Consumes: `actionMenuHtml`, `initActionMenus` from Task 2.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_menu_parity.py`:

```python
def test_tools_no_longer_uses_a_native_select_for_row_actions():
    source = TOOLS_JS.read_text(encoding="utf-8")
    assert "row-actions-select" not in source
    assert "actionMenuHtml" in source


def test_tools_menu_options_all_have_handlers():
    source = TOOLS_JS.read_text(encoding="utf-8")
    assert _rendered_menu_values(source) <= _handled_action_values(source)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `backend/`):
```bash
venv/Scripts/python.exe -m pytest tests/test_menu_parity.py -v
```
Expected: the two new tests FAIL on `row-actions-select` still being present in `tools.js`.

- [ ] **Step 3: Import the component**

In `backend/static/views/tools.js`, add to the import block:

```js
import { actionMenuHtml, initActionMenus } from "../menus.js";
```

- [ ] **Step 4: Replace `actionsCell`**

Replace `backend/static/views/tools.js:419-432` with:

```js
function actionsCell(tool) {
  if (!canManageCustody()) return "";
  return actionMenuHtml({
    id: "tool-row-actions-" + tool.id,
    ariaLabel: "Actions for " + tool.name,
    itemId: tool.id,
    options: [
      { value: "edit", label: "Edit" },
      { value: "correct", label: "Correct Count" },
      { value: "delete", label: "Archive", danger: true },
    ],
  });
}
```

- [ ] **Step 5: Replace the change listener**

Replace `backend/static/views/tools.js:489-499` — the `toolsTbody.addEventListener("change", ...)` opening through `if (!tool) return;` — with:

```js
initActionMenus(toolsTbody, async (action, toolId) => {
  if (!action || !toolId) return;

  const tool = getTools().find((candidate) => candidate.id === toolId);
  if (!tool) return;
```

Leave the rest of the function body and its closing `});` unchanged.

- [ ] **Step 6: Run the tests to verify they pass**

Run (from `backend/`):
```bash
venv/Scripts/python.exe -m pytest tests/test_menu_parity.py -v
```
Expected: 15 passed.

- [ ] **Step 7: Commit**

```bash
git add backend/static/views/tools.js backend/tests/test_menu_parity.py
git commit -m "feat(tools): replace the Actions select with the themed menu"
```

---

### Task 5: Move the combo into the shared module

Pure refactor, no behavior change. The value picker currently lives in `views/workOrders.js` under a `.wo-` prefix; the Notes editor on the Find Item page needs it in Task 6, and importing a 2000-line page module to get it would be wrong.

**Verified before writing this task:** the only `change` listener on the work-orders list filters for `.wo-mode-select` (`views/workOrders.js:1990-1992`), so the `change` event this task starts dispatching from the hidden native select has no existing listener to disturb.

**Files:**
- Modify: `backend/static/menus.js` (add `comboHtml`)
- Modify: `backend/static/views/workOrders.js` (delete `comboListHtml` `:654-663`, `comboHtml` `:665-681`, `closeCombo` `:683-688`, the `toggle-combo` branch `:1702-1714`, the `pick-combo-option` branch `:1716-1728`, and the combo arms of the `keydown` `:1942-1943` and `focusout` `:1954-1959` listeners)
- Modify: `backend/static/styles.css` (delete `.wo-combo-*` `:3612-3684`; add the combo-specific `.menu-*` rules)
- Test: `backend/tests/test_menu_parity.py`

**Interfaces:**
- Consumes: `escapeHtml`, plus the open/close internals from Task 2.
- Produces: `comboHtml({ id, extraClass, nativeSelectHtml, options, selectedValue, ariaLabel }) -> string` where `options` is `Array<{ value: string, label: string }>`. Same signature as the `comboHtml` currently exported from `workOrders.js`, so its two call sites need no argument changes.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_menu_parity.py`:

```python
WORK_ORDERS_JS = STATIC / "views" / "workOrders.js"
NOTES_JS = STATIC / "views" / "notes.js"


def test_the_combo_lives_in_the_shared_module():
    """Notes (Find Item) needs the value picker too; importing a 2000-line
    page module to get it would drag the whole Work Orders page along."""
    assert "export function comboHtml" in MENUS_JS.read_text(encoding="utf-8")


def test_work_orders_imports_the_combo_rather_than_defining_one():
    source = WORK_ORDERS_JS.read_text(encoding="utf-8")
    assert "function comboHtml" not in source, "workOrders.js still defines its own combo"
    assert "function closeCombo" not in source
    assert "comboHtml" in source, "workOrders.js should still use the shared combo"


def test_the_wo_prefixed_combo_styles_are_gone():
    """A .wo- prefix on a component the Notes editor renders is a lie about
    where it belongs."""
    css = _css()
    for selector in (".wo-combo-trigger", ".wo-combo-list", ".wo-combo-option"):
        assert selector not in css, f"{selector} survived the move to .menu-*"


def test_the_combo_keeps_a_real_select_holding_the_value():
    """The hidden <select> is the whole point: existing save/read code
    (`value('.wo-edit-status')`) keeps working untouched."""
    source = MENUS_JS.read_text(encoding="utf-8")
    combo = re.search(r"export function comboHtml\(.*?\n\}", source, re.DOTALL)
    assert combo, "comboHtml was not found in menus.js"
    assert 'role="listbox"' in combo.group(0)
    assert 'role="option"' in combo.group(0)
    assert "menu-native" in combo.group(0)


def test_the_combo_has_the_css_it_renders_against():
    css = _css()
    assert ".menu-native" in css, "the hidden native select must be display:none"
    assert '.menu-option[aria-selected="true"]' in css
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `backend/`):
```bash
venv/Scripts/python.exe -m pytest tests/test_menu_parity.py -v
```
Expected: the five new tests FAIL — `comboHtml` is still defined in `workOrders.js` and the `.wo-combo-*` rules are still in `styles.css`.

- [ ] **Step 3: Add `comboHtml` to the shared module**

In `backend/static/menus.js`, update the header comment's shape list to name both, then add after `actionMenuHtml`:

```js
// Value picker. A real <select> stays in the DOM, hidden, purely to hold the
// value so existing save/read code (and the class name callers query for) is
// unchanged; the styled trigger and popover are what the user sees and
// clicks. `nativeSelectHtml` must carry the `menu-native` class.
export function comboHtml({ id, extraClass, nativeSelectHtml, options, selectedValue, ariaLabel }) {
  const selected = options.find((opt) => opt.value === selectedValue);
  const triggerLabel = selected ? selected.label : options[0]?.label || "";
  const items = options
    .map(
      ({ value, label }) =>
        `<button type="button" role="option" class="menu-option" data-menu-action="pick" data-value="${escapeHtml(value)}" aria-selected="${value === selectedValue}">${escapeHtml(label)}</button>`
    )
    .join("");
  // The trigger renders before the hidden native select: both are "labelable"
  // and this sits inside a <label>, which forwards a caption click to the
  // first labelable descendant in tree order. Button first means the click
  // opens the combo instead of landing on a select that's hidden and can't
  // respond.
  return `<div class="menu menu-combo${extraClass ? ` ${extraClass}` : ""}" data-menu>
            <button type="button" class="menu-trigger" data-menu-action="toggle"
                    aria-haspopup="listbox" aria-expanded="false" aria-controls="${escapeHtml(id)}">
              <span class="menu-trigger-label">${escapeHtml(triggerLabel)}</span>
              ${CHEVRON}
            </button>
            <div class="menu-list" id="${escapeHtml(id)}" role="listbox" aria-label="${escapeHtml(ariaLabel)}" hidden>
              ${items}
            </div>
            ${nativeSelectHtml}
          </div>`;
}
```

- [ ] **Step 4: Teach the pick handler about combos**

In `backend/static/menus.js`, replace the `if (btn.dataset.menuAction === "pick")` block in the document click listener with:

```js
  if (btn.dataset.menuAction === "pick") {
    // A combo carries a hidden real <select>; an action menu does not. That
    // is the only difference in what a pick means.
    const native = menu.querySelector(".menu-native");
    if (native) {
      native.value = btn.dataset.value;
      const label = menu.querySelector(".menu-trigger-label");
      if (label) label.textContent = btn.textContent;
      optionsOf(menu).forEach((opt) =>
        opt.setAttribute("aria-selected", String(opt === btn))
      );
      // Callers that watch the select for changes (the Notes editor swaps its
      // value input on type change) get the event they already listen for.
      native.dispatchEvent(new Event("change", { bubbles: true }));
    }
    closeMenu(menu);
    triggerOf(menu)?.focus();
    if (!native) {
      const entry = pickHandlers.find((handler) => handler.root.contains(menu));
      entry?.onPick(btn.dataset.value, menu.dataset.id);
    }
    return;
  }
```

- [ ] **Step 5: Strip the local copy out of workOrders.js**

In `backend/static/views/workOrders.js`:

1. Delete `comboListHtml` (lines 654-663), `comboHtml` (665-681) and `closeCombo` (683-688), keeping the explanatory comment block above them only if it still describes something local — it does not, so delete it too.
2. Add to the import block: `import { comboHtml, closeMenu, closeAllMenus } from "../menus.js";`
3. Delete the `if (action === "toggle-combo")` branch (1702-1714) and the `if (action === "pick-combo-option")` branch (1716-1728) — `menus.js` handles both now.
4. In the `keydown` listener, replace the two combo lines (1942-1943) with nothing; `menus.js` owns Escape.
5. In the `focusout` listener, replace the combo arm (1954-1959) with nothing; `menus.js` owns it.
6. In the two `comboHtml` call sites (803, 848), change the native select's class from `wo-combo-native` to `menu-native`, keeping `wo-edit-status` / `wo-edit-supervisor` (the save/read code queries those).
7. If `closeCombo` was called anywhere else, replace with `closeMenu`. Check with: `grep -n "closeCombo\|wo-combo" backend/static/views/workOrders.js` — this must return nothing when the task is done.

- [ ] **Step 6: Move the CSS**

In `backend/static/styles.css`, delete the whole `.wo-combo-*` block (lines 3612-3684) **except** `.wo-tech-result` at 3685, which belongs to the technician picker and stays.

Then check the shared scrollbar rule just above it (3580-3609): it names `.wo-combo-list` alongside `.wo-tech-results` and `.manual-results`. Replace each `.wo-combo-list` occurrence there with `.menu-list`.

Then add to the `POPUP MENUS` block from Task 2:

```css
/* --- Value picker (combo) --------------------------------------------
   Same trigger and popover as the action menu; the difference is that a
   combo persists a selection and keeps a real <select> holding the value. */
.menu-native { display: none; }

.menu-option[aria-selected="true"] {
    background-color: var(--color-brand);
    color: var(--color-white);
}

.menu-option[aria-selected="true"]:hover {
    background-color: var(--color-brand-hover);
}
```

- [ ] **Step 7: Run the full suite**

Run (from `backend/`):
```bash
venv/Scripts/python.exe -m pytest tests/ -q
```
Expected: everything passes. `test_work_order_status_parity.py` in particular must stay green — it parses `data-action` attributes out of `workOrders.js`, and this task removes two of them (`toggle-combo`, `pick-combo-option`). Because that test asserts `rendered == handled`, removing both the rendered attribute and its handler keeps the two sets equal. If it fails, a `data-action="toggle-combo"` string was left behind in the markup.

- [ ] **Step 8: Manual check**

Hand off with: on the **Work Orders** page, open a card as Admin/Owner, change **Status** and **Supervisor** via their dropdowns, save, and confirm the values persist. This is a pure refactor — anything that changed is a regression.

- [ ] **Step 9: Commit**

```bash
git add backend/static/menus.js backend/static/views/workOrders.js backend/static/styles.css backend/tests/test_menu_parity.py
git commit -m "refactor(ui): move the work-order combo into the shared menus module"
```

---

### Task 6: Migrate the Notes editor selects

The last two native selects reachable from Find Item.

**Files:**
- Modify: `backend/static/views/notes.js:75-100` (`addNoteRow`), `:102-129` (`renderNoteValueInput`)
- Modify: `backend/static/styles.css:1490-1494` (`.note-row select`)
- Test: `backend/tests/test_menu_parity.py`

**Interfaces:**
- Consumes: `comboHtml` from Task 5.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_menu_parity.py`:

```python
def test_the_notes_editor_uses_combos_not_native_selects():
    """Reachable from Find Item's row menu, so it inherits the same
    OS-drawn-popup problem."""
    source = NOTES_JS.read_text(encoding="utf-8")
    assert "comboHtml" in source
    # The only <select> left is the hidden one the combo keeps for its value.
    for match in re.findall(r"<select[^>]*>", source):
        assert "menu-native" in match, f"unthemed native select in notes.js: {match}"


def test_the_notes_value_reader_still_finds_the_value():
    """dom.js's getNoteValueRaw() reads `.note-value` off the row. The combo
    puts that class on the hidden native select, so the reader is unchanged."""
    source = NOTES_JS.read_text(encoding="utf-8")
    assert "note-value" in source
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `backend/`):
```bash
venv/Scripts/python.exe -m pytest tests/test_menu_parity.py -v
```
Expected: `test_the_notes_editor_uses_combos_not_native_selects` FAILS on the unthemed `<select class="note-type">`.

- [ ] **Step 3: Import the combo**

In `backend/static/views/notes.js`, add to the import block:

```js
import { comboHtml } from "../menus.js";
```

- [ ] **Step 4: Replace the type select in `addNoteRow`**

Replace `backend/static/views/notes.js:75-100` with:

```js
let noteRowSeq = 0;

const NOTE_TYPES = [
  { value: "string", label: "String" },
  { value: "number", label: "Number" },
  { value: "boolean", label: "Boolean" },
];

function addNoteRow(key = "", type = "string", value = "") {
  const rowId = `note-row-${noteRowSeq++}`;
  const row = document.createElement("div");
  row.className = "note-row";
  row.innerHTML = `
    <input type="text" class="note-key" placeholder="Note name" aria-label="Note name" value="${escapeHtml(key)}">
    ${comboHtml({
      id: `${rowId}-type`,
      ariaLabel: "Note type",
      options: NOTE_TYPES,
      selectedValue: type,
      nativeSelectHtml: `<select class="note-type menu-native" hidden>${NOTE_TYPES.map(
        (option) => `<option value="${option.value}">${option.label}</option>`
      ).join("")}</select>`,
    })}
    <span class="note-value-wrapper"></span>
    <button type="button" class="note-remove-btn" title="Remove" aria-label="Remove note">×</button>
  `;
  const typeSelect = row.querySelector(".note-type");
  typeSelect.value = type;
  const valueWrapper = row.querySelector(".note-value-wrapper");
  renderNoteValueInput(valueWrapper, type, value, rowId);

  // menus.js dispatches `change` on the hidden select when an option is
  // picked, so this listener is unchanged from the native-select version.
  typeSelect.addEventListener("change", () => {
    renderNoteValueInput(valueWrapper, typeSelect.value, getNoteValueRaw(valueWrapper), rowId);
  });

  row.querySelector(".note-remove-btn").addEventListener("click", () => row.remove());

  notesRows.appendChild(row);
}
```

- [ ] **Step 5: Replace the boolean value select**

Replace the `if (type === "boolean")` branch in `renderNoteValueInput` (`backend/static/views/notes.js:102-110`) and widen the signature:

```js
const NOTE_BOOLEANS = [
  { value: "true", label: "true" },
  { value: "false", label: "false" },
];

function renderNoteValueInput(wrapper, type, currentValue, rowId) {
  wrapper.innerHTML = "";
  if (type === "boolean") {
    const selected = (currentValue === true || currentValue === "true") ? "true" : "false";
    wrapper.innerHTML = comboHtml({
      id: `${rowId}-value`,
      ariaLabel: "Note value",
      options: NOTE_BOOLEANS,
      selectedValue: selected,
      // `note-value` stays on the real select: dom.js's getNoteValueRaw()
      // reads `.note-value`.value, and that contract does not change.
      nativeSelectHtml: `<select class="note-value menu-native" hidden><option value="true">true</option><option value="false">false</option></select>`,
    });
    wrapper.querySelector(".note-value").value = selected;
    return;
  }
```

Leave the `number` and text branches exactly as they are.

- [ ] **Step 6: Update the row grid**

In `backend/static/styles.css`, replace `.note-row input, .note-row select` (lines 1490-1494) with:

```css
.note-row input,
.note-row .menu {
    width: 100%;
    margin: 0;
}
```

The grid column widths at `.note-row` (line 1485) stay as they are — the combo trigger fills its column the same way the select did.

- [ ] **Step 7: Run the tests to verify they pass**

Run (from `backend/`):
```bash
venv/Scripts/python.exe -m pytest tests/ -q
```
Expected: the full suite passes.

- [ ] **Step 8: Manual check**

Hand off with: on **Find Item**, open a row's Actions → Notes. Confirm the Type dropdown is dark on open, switching Type to Boolean swaps the value field to a true/false dropdown, switching back to String preserves a sane value, and Save Notes persists.

- [ ] **Step 9: Commit**

```bash
git add backend/static/views/notes.js backend/static/styles.css backend/tests/test_menu_parity.py
git commit -m "feat(notes): replace the note type and boolean selects with combos"
```

---

### Task 7: Fix the remaining contrast and motion anomalies, update the docs

**Files:**
- Modify: `backend/static/styles.css:809-818` (`.empty-state`), plus a new `prefers-reduced-motion` block
- Modify: `docs/design-system.md`
- Modify: `docs/open-work.md`
- Test: `backend/tests/test_menu_parity.py`

**Interfaces:**
- Consumes: `_contrast`, `_root_token`, `COMPOSITED_PANEL` from Task 1.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_menu_parity.py`:

```python
def test_the_empty_state_text_is_readable_on_a_panel():
    """Find Item's opening state -- 'nothing searched yet' -- is the first
    thing on the page. It kept --gray-500 (#6B6B6B, a light-panel secondary
    text color) through the flip to a dark canvas, which lands at 2.7:1."""
    body = _rule_body(".empty-state")
    token = re.search(r"color:\s*var\((--[\w-]+)\)", body)
    assert token, ".empty-state does not set a color token"
    ratio = _contrast(_root_token(token.group(1)), COMPOSITED_PANEL)
    assert ratio >= 4.5, f"{token.group(1)} is {ratio:.1f}:1 on a panel, under the 4.5 floor"


def test_motion_is_reduced_when_the_reader_asks_for_it():
    """styles.css animates inputs, chevrons and cards. The quality floor is
    that a reader who sets prefers-reduced-motion gets none of it."""
    assert "prefers-reduced-motion" in _css()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `backend/`):
```bash
venv/Scripts/python.exe -m pytest tests/test_menu_parity.py -v
```
Expected: both FAIL. The first reports `--gray-500 is 2.7:1 on a panel, under the 4.5 floor`; the second fails because no such block exists.

- [ ] **Step 3: Fix the empty state**

In `backend/static/styles.css`, in the `.empty-state` rule (line 817), change:

```css
    color: var(--gray-500);
```

to:

```css
    /* --text-panel-mute, not --gray-500: #6B6B6B was a secondary-text color
       for a white panel and reads at 2.7:1 on the dark one, under the 4.5
       floor. This is Find Item's opening state, so it is the first text on
       the page. */
    color: var(--text-panel-mute);
```

- [ ] **Step 4: Add the reduced-motion block**

In `backend/static/styles.css`, add at the very end of the file:

```css
/* =================== REDUCED MOTION =================== */
/* Inputs, menu chevrons and cards all transition. A reader who has asked the
   OS for less movement gets the end state immediately instead. Kept as a
   blanket rule rather than per-component opt-outs so a new transition is
   covered the day it lands. */
@media (prefers-reduced-motion: reduce) {
    *,
    *::before,
    *::after {
        animation-duration: .01ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: .01ms !important;
        scroll-behavior: auto !important;
    }
}
```

- [ ] **Step 5: Handle the smooth-scroll calls**

`views/notes.js:65` and its siblings call `scrollIntoView({ behavior: "smooth" })`, which the CSS rule above cannot reach. Search for them:

```bash
grep -rn 'behavior: "smooth"' backend/static/
```

For each hit, leave the call as-is — this is a **noted follow-up, not a fix in this task**, because the call sites are spread across views that this plan does not otherwise touch and each needs its own check. Add it to `docs/open-work.md` in Step 7.

- [ ] **Step 6: Update the design system doc**

In `docs/design-system.md`, in the bullet ending *"Reach for this pattern for any future dropdown that needs to look right rather than a native `<select>`"* (around line 119), replace the last two sentences of that paragraph with:

```markdown
  The **only** dependable fix is to not use a native `<select>` where the
  popup must match the theme. That pattern now lives in `static/menus.js`
  as two shared shapes, and every dropdown in the app is built from one of
  them:

  - `actionMenuHtml()` — a fire-and-close command menu (`role="menu"`).
    The Actions column on Find Item and Tools.
  - `comboHtml()` — a value picker (`role="listbox"`) that keeps a real
    `<select>` in the DOM, hidden, holding the value so existing save/read
    code is untouched. The work-order card's Status and Supervisor fields,
    and the Notes editor's type and boolean fields.

  Both render `.menu-*` classes (`styles.css`, "POPUP MENUS"). The older
  page-local `.wo-combo-*` copy is gone. Reach for one of these rather than
  a native `<select>` for any new dropdown; `select option { }` and
  `color-scheme: dark` remain in the sheet as a fallback for the plain
  `<select>`s that are left, but they do not reach the OS-drawn path.

  One trap when styling either: every rule has to out-specify the global
  `button` style, which is a solid brand-red block.
```

Then in the "Color on a dark surface" section, after the contrast table, add:

```markdown
`backend/tests/test_menu_parity.py` computes these ratios from the `:root`
tokens rather than trusting the table above to be re-measured by hand. A
token that stops clearing 4.5:1 on a panel fails the suite.
```

- [ ] **Step 7: Log the out-of-scope findings**

Add to `docs/open-work.md`, in the style of the existing entries:

```markdown
- **`--gray-600` is used but never defined.** `styles.css:1261`
  (`.user-request-resolved .user-request-status`) reads `var(--gray-600)`;
  `:root` declares 50/100/200/300/400/500/700/900 and no 600. The
  declaration is invalid at computed-value time, so a resolved user request
  silently inherits the panel text color instead of going muted. Either add
  the token or point the rule at `--text-panel-mute`.
- **`.lu-card-body` still uses light-panel colors.** `styles.css:3434-3445`
  sets `--color-ink` text and `--gray-300` borders on the work-order lookup
  card, both of which the design system says disappear on the dark canvas.
- **`.wo-mode-select` is still a native `<select>`.** `styles.css:3479`,
  on the Work Orders page — same OS-drawn-popup problem the rest of the app
  was migrated off. `static/menus.js`'s `comboHtml()` makes it a small fix.
- **`scrollIntoView({ behavior: "smooth" })` ignores reduced-motion.** The
  CSS `prefers-reduced-motion` block cannot reach a scripted scroll. Call
  sites across `views/` need to read the media query and pass `"auto"`.
```

- [ ] **Step 8: Run the full suite**

Run (from `backend/`):
```bash
venv/Scripts/python.exe -m pytest tests/ -q
```
Expected: everything passes.

- [ ] **Step 9: Confirm every native select is accounted for**

```bash
grep -rn "<select" backend/static/views/ backend/static/pages/
```

Expected: every remaining hit is either a `menu-native` hidden select or one of the plain `<select>`s logged as follow-ups in Step 7 (`.wo-mode-select`, the work-orders status filter, and any others outside this brief). No hit should be a themed dropdown on Find Item, Add Item, Tools, Notes, or the work-order card editor.

- [ ] **Step 10: Commit**

```bash
git add backend/static/styles.css backend/tests/test_menu_parity.py docs/design-system.md docs/open-work.md
git commit -m "fix(ui): raise empty-state contrast, honor reduced motion, document the shared menus"
```

---

## Verification Before Handoff

Run from `backend/`:

```bash
venv/Scripts/python.exe -m pytest tests/ -q
```

Then hand the branch to the owner for manual validation with this checklist — the owner validates UI manually and prefers the preview server not be started automatically:

1. **Find Item** → search → hover a result row. The row should darken slightly. It must **not** go white.
2. **Find Item** → a row's Actions menu. Dark popover, subtle hover wash, Archive below a hairline in red, Escape closes and returns focus, Archive still confirms.
3. **Find Item** → Actions → Notes. Type dropdown is dark; switching to Boolean swaps the value field to a themed true/false picker; Save persists.
4. **Find Item** with no search yet. The empty-state text should be legible, not dim gray.
5. **Tools** → a row's Actions menu. Same as (2).
6. **Work Orders** → open a card → Status and Supervisor dropdowns still set and save correctly (Task 5 is a pure refactor; any change is a regression).
7. **Add Item** — no dropdowns here by design. Confirm nothing regressed in the form's inputs.
8. Narrow the window to phone width and repeat (2): the trigger should go full-width and the popover should stay on screen.

**Do not merge to `main` without asking.** Merging deploys to production.
