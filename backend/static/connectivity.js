// Foundation: browser network connectivity state.
//
// Layer: foundation. Three signals feed one online/offline state: the
// browser's own `offline` event (immediate -- fires the moment the OS
// reports the network interface down, e.g. airplane mode), api.js's
// connectivity handler (a real request either reached the server or it
// didn't -- the most trustworthy signal, since "connected to Wi-Fi" and
// "can reach OUR server" are not the same thing), and a periodic probe
// while offline, in case neither of the other two fires on its own.
//
// views/connectivityModal.js is the only subscriber today, but nothing
// here is view-specific -- any page can ask `isOnline()` or subscribe.

import { apiMe, setConnectivityHandler } from "./api.js";

const PROBE_INTERVAL_MS = 8000;

let online = true;
const subscribers = new Set();

function setOnline(next) {
  if (next === online) return;
  online = next;
  for (const handler of subscribers) handler(online);
}

export function isOnline() {
  return online;
}

// Called immediately with the current state, then again on every change.
// Returns an unsubscribe function.
export function subscribeConnectivity(handler) {
  handler(online);
  subscribers.add(handler);
  return () => subscribers.delete(handler);
}

// An explicit probe: fired by the Reconnect button, and on an interval
// while offline. `/auth/me` is cheap and answers regardless of session
// state, so a 401 still counts as "reached the server". The classification
// itself happens in the `setConnectivityHandler` callback below -- it runs
// on every fetch api.js makes, including this one, before apiMe's own
// {status, detail} throw for a non-2xx response, so there is nothing left
// to inspect in the catch here.
export async function checkNow() {
  try {
    await apiMe();
  } catch {
    // Already classified below.
  }
  return online;
}

setConnectivityHandler(setOnline);

if (typeof window !== "undefined") {
  window.addEventListener("offline", () => setOnline(false));
  // The browser's own "online" event is optimistic -- it only knows the
  // network interface is up, not that our server is reachable -- so it
  // triggers a real check rather than clearing the state itself.
  window.addEventListener("online", () => { void checkNow(); });
}

// Keeps polling while offline, in case nothing else (no incidental request,
// no `online` event) would otherwise notice recovery.
let probeTimer = null;
subscribeConnectivity((isNowOnline) => {
  if (isNowOnline) {
    if (probeTimer !== null) {
      clearInterval(probeTimer);
      probeTimer = null;
    }
    return;
  }
  if (probeTimer !== null) return;
  probeTimer = setInterval(() => { void checkNow(); }, PROBE_INTERVAL_MS);
});
