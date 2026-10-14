// View: "You have not clocked in" prompt, shown once after sign-in.
//
// Layer: views. Called by auth.js's enterApp. Self-building modal (reuses the
// shared .modal-overlay / .modal-box chrome). No Esc/backdrop dismiss: the
// operator picks Clock in or "Continue without clocking in". The Owner has no
// shift to punch, so is skipped. A failed lookup stays quiet -- the Hub clock
// widget is still there.

import { apiGetAttendanceMe, apiPunchIn } from "../api.js";
import { friendlyError } from "../format.js";
import { getCurrentUser } from "../state.js";

let current = null;

// Sign-out / session expiry must not leave the prompt over the login screen.
export function closeClockInPrompt() {
  current?.remove();
  current = null;
}

export async function maybePromptClockIn(user) {
  if (!user || user.role === "owner") return;
  let me;
  try {
    me = await apiGetAttendanceMe();
  } catch {
    return;
  }
  // The lookup is async: sign-out or expiry may have landed meanwhile.
  if (me.open_punch || getCurrentUser() !== user) return;
  closeClockInPrompt();

  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.innerHTML = `
    <div class="modal-box clock-in-prompt" role="dialog" aria-modal="true" aria-labelledby="clock-in-prompt-title">
      <p id="clock-in-prompt-title" class="modal-title">You have not clocked in</p>
      <button type="button" class="clock-in-prompt-btn" data-action="clock-in">Clock in</button>
      <p class="clock-in-prompt-message" aria-live="polite"></p>
      <button type="button" class="secondary-btn" data-action="skip">Continue without clocking in</button>
    </div>`;
  document.body.appendChild(overlay);
  current = overlay;
  const close = closeClockInPrompt;
  const clockIn = overlay.querySelector('[data-action="clock-in"]');
  const message = overlay.querySelector(".clock-in-prompt-message");
  clockIn.addEventListener("click", async () => {
    clockIn.disabled = true;
    try {
      await apiPunchIn();
      close();
    } catch (err) {
      message.textContent = friendlyError(err, "Could not clock in.");
      clockIn.disabled = false;
    }
  });
  overlay.querySelector('[data-action="skip"]').addEventListener("click", close);
  clockIn.focus();
}
