// View: the post-login notification prompt, for people the Sign In click did
// not reach (a resumed "stay signed in" session, a blocked device, an iPhone
// in a Safari tab).
//
// Layer: views. Called by welcome.js after the clock-in prompt. Same
// .modal-overlay / .modal-box chrome as storageWarning.js. The "ask" variant's
// button tap is the user gesture iOS needs for requestPermission(). Shown at
// most once per sign-in ("ask") or once per device ("blocked", "install").

import { getCurrentUser } from "../state.js";
import { enablePush, pushPromptKind } from "./push.js";

const COPY = {
  ask: {
    title: "Get work-order alerts?",
    body: "Turn on notifications to hear about your work orders on this device, even when the app is closed.",
    yes: "Turn on notifications",
    no: "Not now",
  },
  blocked: {
    title: "Notifications are blocked",
    body: "This device is blocking alerts from the app. To get work-order alerts, allow notifications for this app in your phone or browser settings, then reopen the app.",
    no: "OK",
  },
  install: {
    title: "Add to Home Screen for alerts",
    body: "On iPhone and iPad, notifications only work from the Home Screen app. Tap Share, then Add to Home Screen, and open the app from there.",
    no: "OK",
  },
};

let current = null;
let finish = null;

// Sign-out / session expiry must not leave it over the login screen.
export function closePushPrompt() {
  current?.remove();
  current = null;
  finish?.();
  finish = null;
}

// "ask" is per sign-in (session storage); the notices are per device. A
// browser with storage disabled just sees them more often.
function storeFor(kind) {
  try {
    return kind === "ask" ? window.sessionStorage : window.localStorage;
  } catch {
    return null;
  }
}
const keyFor = (kind) => `techfm.pushPrompt.${kind}`;

// Resolves when the prompt closes (or at once when there is nothing to show),
// so welcome.js can queue the next prompt behind it.
export function maybePromptPush(user) {
  const kind = user && pushPromptKind(user.role);
  if (!kind || getCurrentUser() !== user) return Promise.resolve();
  const store = storeFor(kind);
  try {
    if (store?.getItem(keyFor(kind))) return Promise.resolve();
    store?.setItem(keyFor(kind), "1");
  } catch {
    // Storage refused: show it anyway.
  }
  closePushPrompt();

  const c = COPY[kind];
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.innerHTML = `
    <div class="modal-box push-prompt" role="dialog" aria-modal="true" aria-labelledby="push-prompt-title">
      <p id="push-prompt-title" class="modal-title">${c.title}</p>
      <p>${c.body}</p>
      ${c.yes ? `<button type="button" data-action="enable">${c.yes}</button>` : ""}
      <button type="button" class="${c.yes ? "secondary-btn" : ""}" data-action="later">${c.no}</button>
    </div>`;
  document.body.appendChild(overlay);
  current = overlay;
  const done = new Promise((resolve) => { finish = resolve; });
  overlay.querySelector('[data-action="later"]').addEventListener("click", closePushPrompt);
  overlay.querySelector('[data-action="enable"]')?.addEventListener("click", () => {
    closePushPrompt();
    void enablePush();
  });
  (overlay.querySelector('[data-action="enable"]') || overlay.querySelector('[data-action="later"]')).focus();
  return done;
}
