// View: Web Push opt-in and the Owner's test trigger.
//
// Layer: views. Owns the header's `#push-test-btn`, the login-time
// permission request (requestPermissionAtLogin, called from views/auth.js
// before login), the service-worker registration, and the browser
// subscription lifecycle. There is no in-app way to turn notifications back
// off short of logging out -- `unsubscribeThisDevice` (called from
// views/auth.js on logout) is the opt-out path.
//
// The iOS constraint shapes this whole module. On iPhone, Web Push works
// **only inside a PWA installed to the Home Screen** -- in a plain Safari
// tab `window.Notification` does not exist, and no amount of prompting
// creates it.

import { apiPushConfig, apiPushSubscribe, apiPushTest, apiPushUnsubscribe } from "../api.js";
import { messageDialog } from "../dom.js";
import { friendlyError } from "../format.js";
import { getRole } from "../state.js";
import { roleAtLeast } from "../roles.js";

const testBtn = document.getElementById("push-test-btn");

// Who may hold a push subscription, mirroring SUBSCRIBE_MIN_ROLE in
// `routers/push.py`. `/push/subscribe` is not role-gated on the server --
// holding a subscription grants no authority -- so this constant is the
// whole gate, and it is the only thing that kept technicians from
// receiving their own assignment notifications. Gates the silent
// re-subscribe in initPushForUser below.
const SUBSCRIBE_MIN_ROLE = "technician";

// Whether this browser can do push at all. On iOS this is false in a
// Safari tab and true in the installed PWA.
function pushSupported() {
  return (
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    typeof window.Notification !== "undefined"
  );
}

// `applicationServerKey` must be raw bytes. The server sends the key in
// the base64url form the Web Push specs use, which `atob` cannot read
// until the URL-safe characters are put back and the padding restored.
function vapidKeyToBytes(base64url) {
  const padded = base64url.padEnd(base64url.length + ((4 - (base64url.length % 4)) % 4), "=");
  const binary = atob(padded.replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(binary, (char) => char.charCodeAt(0));
}

async function ensureRegistration() {
  // Registered at `/service-worker.js` so its scope is the whole app;
  // see the route in `app/main.py`.
  return navigator.serviceWorker.register("/service-worker.js");
}

// Create or reuse this browser's subscription and bind it to whoever is
// currently logged in. Returns the PushSubscription.
async function subscribeThisDevice() {
  const registration = await ensureRegistration();
  const { public_key: publicKey } = await apiPushConfig();
  const applicationServerKey = vapidKeyToBytes(publicKey);

  let subscription = await registration.pushManager.getSubscription();

  // An existing subscription minted against a different VAPID key can
  // never be delivered to, and `subscribe()` refuses to replace it.
  // Dropping it here is what makes a key rotation recoverable without
  // the user clearing site data.
  if (subscription) {
    const current = new Uint8Array(subscription.options.applicationServerKey || []);
    const matches =
      current.length === applicationServerKey.length &&
      current.every((byte, i) => byte === applicationServerKey[i]);
    if (!matches) {
      await subscription.unsubscribe();
      subscription = null;
    }
  }

  if (!subscription) {
    subscription = await registration.pushManager.subscribe({
      // Required, and required to be true: a subscription that could
      // deliver silently is not permitted by any current browser.
      userVisibleOnly: true,
      applicationServerKey,
    });
  }

  // Posted even when the subscription already existed. That re-POST is
  // the shared-device fix: it reassigns the endpoint row to the current
  // user, so the previous account stops receiving on this phone.
  await apiPushSubscribe(subscription);
  return subscription;
}

// Drop this device's subscription, server-side first. Called on logout.
// Failures are swallowed: a logout must not be blocked by a push
// problem, and the row is scoped to a user who is about to lose their
// session anyway.
export async function unsubscribeThisDevice() {
  if (!pushSupported()) return;
  try {
    const registration = await navigator.serviceWorker.getRegistration();
    if (!registration) return;
    const subscription = await registration.pushManager.getSubscription();
    if (!subscription) return;

    await apiPushUnsubscribe(subscription.endpoint);
    await subscription.unsubscribe();
  } catch (err) {
    // Deliberately quiet. See above.
  }
}

// Called after login. Silently (re-)subscribes this device so its
// endpoint is bound to whoever just logged in, and decides whether the
// Owner's test button shows.
export async function initPushForUser() {
  const role = getRole();
  const eligible = role && roleAtLeast(role, SUBSCRIBE_MIN_ROLE);

  if (testBtn) testBtn.hidden = !(role && roleAtLeast(role, "owner"));

  if (!eligible || !pushSupported()) return;

  // Only subscribe when permission is already granted -- calling
  // `subscribe()` without it would trigger the permission prompt on page
  // load, and iOS gives no second chance after a denial. Permission is
  // requested earlier, at login (see requestPermissionAtLogin).
  if (window.Notification.permission !== "granted") return;

  try {
    await subscribeThisDevice();
  } catch {
    // Nothing further to do -- the device just stays unsubscribed until
    // the next login retries it.
  }
}

// Hide the test control when the app returns to the login screen.
export function resetPushView() {
  if (testBtn) testBtn.hidden = true;
}

// Called synchronously from the login button's click handler, before any
// awaited network call. That is the only place the login click's user
// gesture is still valid for `requestPermission()` -- iOS refuses the
// prompt outright once an `await` (e.g. the login request itself) has run
// first, with no second chance after. A no-op when unsupported or already
// decided, so a checked box never blocks or delays the login it's attached
// to: initPushForUser (after login) re-checks permission and simply won't
// subscribe if this was denied or skipped.
export async function requestPermissionAtLogin() {
  if (!pushSupported() || window.Notification.permission !== "default") return;
  try {
    await window.Notification.requestPermission();
  } catch {
    // Swallowed -- see above.
  }
}

async function onTestClick() {
  testBtn.disabled = true;
  try {
    const result = await apiPushTest();
    await messageDialog(
      `Sent to ${result.sent} device(s). ` +
        `${result.dropped} stale subscription(s) removed, ${result.failed} failed.`
    );
  } catch (err) {
    await messageDialog(friendlyError(err));
  } finally {
    testBtn.disabled = false;
  }
}

if (testBtn) testBtn.addEventListener("click", onTestClick);
