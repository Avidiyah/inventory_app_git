// View: app-wide "not connected to the server" prompt.
//
// Layer: views. Shows/hides the blocking #connectivity-overlay
// (shell-tail.html) from connectivity.js's state. No backdrop/Esc
// dismissal -- see that markup's own comment for why -- so the only way
// out is the Reconnect button, or an incidental successful request
// elsewhere in the app clearing the state on its own.

import { checkNow, subscribeConnectivity } from "../connectivity.js";
import { replayPendingDrafts } from "./workOrders.js";

const overlay = document.getElementById("connectivity-overlay");
const reconnectBtn = document.getElementById("connectivity-reconnect");
const spinner = document.getElementById("connectivity-spinner");
const label = document.getElementById("connectivity-reconnect-label");

function setChecking(checking) {
  if (reconnectBtn) reconnectBtn.disabled = checking;
  if (spinner) spinner.hidden = !checking;
  if (label) label.textContent = checking ? "Checking…" : "Reconnect";
}

subscribeConnectivity((online) => {
  if (!overlay) return;
  overlay.hidden = online;
  if (!online) return;
  setChecking(false);
  // A drafted work-order save is exactly what this prompt exists to
  // protect; the moment the app can reach the server again, resend it
  // rather than wait for the next socket reconnect. A no-op on any page
  // with nothing pending.
  void replayPendingDrafts();
});

if (reconnectBtn) {
  reconnectBtn.addEventListener("click", async () => {
    setChecking(true);
    await checkNow();
    // The subscription above already clears this on a state change to
    // online; a repeat failure fires no change, so clear it here too.
    setChecking(false);
  });
}
