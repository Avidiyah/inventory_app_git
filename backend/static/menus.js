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
//   actionMenuHtml()  fire-and-close command menu (role="menu"). Picking an
//                     option runs an action; nothing stays selected.
//   comboHtml()       value picker (role="listbox") that keeps a hidden real
//                     <select> holding the value.

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

// Value picker. A real <select> stays in the DOM, hidden, purely to hold the
// value so existing save/read code (and the class name callers query for) is
// unchanged; the styled trigger and popover are what the user sees and
// clicks.
export function comboHtml({ id, extraClass, nativeSelectHtml, options, selectedValue, ariaLabel }) {
  // `nativeSelectHtml` must carry the `menu-native` class (hidden by the CSS
  // rule of that name) -- comboHtml renders it verbatim rather than building
  // it, since the caller owns the real select's other classes and options.
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
