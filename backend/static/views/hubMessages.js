// View: the User Hub "Messages" tab.
//
// Layer: views. Mounts the shared message panel (no close button) into the
// hub panel while the tab is showing and destroys it on every other tab and
// when the hub page is left, so a chat nobody sees never marks anything read.
// Also the bubble's opener once the bubble is put away: a notification tap
// shows the hub page, selects this tab and opens the chat. Registered at
// import because userHub.js imports this module and main.js imports userHub.js.

import { mountMessagePanel } from "./messagePanel.js";
import { setHubOpener } from "./messageBubble.js";
import { showPage } from "./nav.js";

let host = null;
let handle = null;
// A chat id asked for before the panel exists (the tab is not showing yet).
let pending = null;

export function deactivate() {
  if (!handle) return;
  handle.destroy();
  host.replaceChildren();
  handle = null;
  host = null;
}

// Called by userHub.js's showTab for the Messages tab; safe to repeat.
export function activate(panel) {
  if (handle && host === panel) return;
  deactivate();
  host = panel;
  handle = mountMessagePanel(panel);
  if (pending) {
    handle.openChat(pending);
    pending = null;
  }
}

export function openChat(id) {
  pending = id || null;
  const page = document.getElementById("user-hub-page");
  if (!page?.classList.contains("active")) showPage("user-hub");
  // activeTab is set before loadUserHub's own showTab runs, so the tab sticks.
  document.getElementById("hub-tab-messages")?.click();
  if (handle && pending) {
    handle.openChat(pending);
    pending = null;
  }
}

setHubOpener(openChat);
// Sign-out (messageBubble.unmountMessages): nothing of the last person stays mounted.
document.addEventListener("messages:stop", () => { pending = null; deactivate(); });

// Leaving the hub page (nav.js toggles `.active`) ends the panel; re-entry
// reaches activate again through loadUserHub's showTab.
const hubPage = document.getElementById("user-hub-page");
if (hubPage) {
  new MutationObserver(() => {
    if (!hubPage.classList.contains("active")) deactivate();
  }).observe(hubPage, { attributes: true, attributeFilter: ["class"] });
}
