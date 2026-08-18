// View: Web Push opt-in and the Owner's test trigger.
//
// Layer: views. Owns the two header controls (`#push-enable-btn`,
// `#push-test-btn`), the service-worker registration, and the browser
// subscription lifecycle. `views/auth.js` calls in at login and logout;
// nothing else imports from here.
//
// The iOS constraint shapes this whole module. On iPhone, Web Push works
// **only inside a PWA installed to the Home Screen** -- in a plain Safari
// tab `window.Notification` does not exist, and no amount of prompting
// creates it. iOS also has no `beforeinstallprompt`, so the install
// cannot be offered programmatically; the only honest thing to do is
// detect the tab case and tell the user what to do by hand.

import { apiPushConfig, apiPushSubscribe, apiPushTest, apiPushUnsubscribe } from "../api.js";
import { messageDialog } from "../dom.js";
import { friendlyError } from "../format.js";
import { getRole } from "../state.js";
import { roleAtLeast } from "../roles.js";

const enableBtn = document.getElementById("push-enable-btn");
const testBtn = document.getElementById("push-test-btn");

// Who may hold a subscription, mirroring NOTIFY_MIN_ROLE in
// `routers/push.py`. The backend re-checks; this only decides visibility.
const NOTIFY_MIN_ROLE = "admin";

// Whether this browser can do push at all. On iOS this is false in a
// Safari tab and true in the installed PWA, which is exactly the
// distinction the UI needs to explain.
function pushSupported() {
  return (
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    typeof window.Notification !== "undefined"
  );
}

// True when running as an installed app rather than a browser tab.
// `navigator.standalone` is the iOS-only signal; the media query is the
// standard one every other platform reports.
function isInstalledApp() {
  return (
    window.navigator.standalone === true ||
    window.matchMedia("(display-mode: standalone)").matches
  );
}

function isIOS() {
  return /iPad|iPhone|iPod/.test(navigator.userAgent);
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

function setButtonState(subscribed) {
  if (!enableBtn) return;
  enableBtn.textContent = subscribed ? "Notifications on" : "Enable notifications";
  enableBtn.disabled = subscribed;
}

// Called after login. Decides what the header shows, and silently
// refreshes an existing subscription so the endpoint is re-bound to
// whoever just logged in.
export async function initPushForUser() {
  const role = getRole();
  const eligible = role && roleAtLeast(role, NOTIFY_MIN_ROLE);

  if (enableBtn) enableBtn.hidden = !eligible;
  if (testBtn) testBtn.hidden = !(role && roleAtLeast(role, "owner"));

  if (!eligible || !pushSupported()) return;

  // Only re-subscribe when permission is already granted. Calling
  // `subscribe()` without it would trigger the permission prompt on
  // page load, and iOS gives no second chance after a denial.
  if (window.Notification.permission !== "granted") {
    setButtonState(false);
    return;
  }

  try {
    await subscribeThisDevice();
    setButtonState(true);
  } catch (err) {
    setButtonState(false);
  }
}

// Hide both controls when the app returns to the login screen.
export function resetPushView() {
  if (enableBtn) enableBtn.hidden = true;
  if (testBtn) testBtn.hidden = true;
}

async function onEnableClick() {
  if (!pushSupported()) {
    // The one case worth a specific explanation: on iOS this is not a
    // browser limitation the user can work around by allowing something,
    // it is a missing install step.
    if (isIOS() && !isInstalledApp()) {
      await messageDialog(
        "On iPhone, notifications require this app to be installed. " +
          "Tap the Share button, choose \"Add to Home Screen\", then open " +
          "Inventory from the new icon and log in there."
      );
    } else {
      await messageDialog("This browser cannot receive notifications.");
    }
    return;
  }

  enableBtn.disabled = true;
  try {
    // Must be called from this click. A permission request that is not
    // tied to a user gesture is refused outright on iOS.
    const permission = await window.Notification.requestPermission();

    if (permission !== "granted") {
      // There is no re-prompt after a denial -- the browser will not ask
      // again, so the recovery path is the Settings app.
      await messageDialog(
        "Notifications are blocked for this app. To turn them on, open " +
          "iPhone Settings, find Inventory, and allow Notifications."
      );
      setButtonState(false);
      return;
    }

    await subscribeThisDevice();
    setButtonState(true);
    await messageDialog("Notifications are on for this device.");
  } catch (err) {
    setButtonState(false);
    await messageDialog(friendlyError(err));
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

if (enableBtn) enableBtn.addEventListener("click", onEnableClick);
if (testBtn) testBtn.addEventListener("click", onTestClick);
