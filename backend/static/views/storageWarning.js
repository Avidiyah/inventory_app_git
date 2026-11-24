// View: the Admin/Owner photo-storage warning, once per sign-in, queued right
// after the clock-in prompt closes (spec 2026-11-24 photo export).
//
// Layer: views. Called by welcome.js. Same .modal-overlay / .modal-box chrome
// as clockInPrompt.js. At 50% of the disk it warns; at 80% uploads are already
// refused and the title says so. A failed lookup stays quiet.

import { apiPhotoStorage } from "../api.js";
import { escapeHtml } from "../format.js";
import { roleAtLeast } from "../roles.js";
import { getCurrentUser } from "../state.js";
import { formatBytes } from "./imageExport.js";

let current = null;

// Sign-out / session expiry must not leave it over the login screen.
export function closeStorageWarning() {
  current?.remove();
  current = null;
}

export async function goToImageExport() {
  const { showPage } = await import("./nav.js");
  showPage("integrations");
  document.getElementById("integrations-image-export")?.scrollIntoView?.({ block: "start", behavior: "smooth" });
}

export async function maybeWarnStorage(user) {
  if (!user || !roleAtLeast(user.role, "admin")) return;
  let s;
  try {
    s = await apiPhotoStorage();
  } catch {
    return;
  }
  if (!s.warn || getCurrentUser() !== user) return;
  closeStorageWarning();

  const pct = Math.round(s.ratio * 100);
  const title = s.full ? "Photo storage is full — uploads are stopped" : "Photo storage is half full";
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.innerHTML = `
    <div class="modal-box storage-warning" role="dialog" aria-modal="true" aria-labelledby="storage-warning-title">
      <p id="storage-warning-title" class="modal-title">${escapeHtml(title)}</p>
      <p>The database is using ${formatBytes(s.used)} of ${formatBytes(s.disk)} (${pct}%).
         Export the photos and clear them to free space. Photo uploads stop at 80%.</p>
      <button type="button" data-action="go-image-export">Go to Image export</button>
      <button type="button" class="secondary-btn" data-action="later">Later</button>
    </div>`;
  document.body.appendChild(overlay);
  current = overlay;
  overlay.querySelector('[data-action="later"]').addEventListener("click", closeStorageWarning);
  overlay.querySelector('[data-action="go-image-export"]').addEventListener("click", () => {
    closeStorageWarning();
    void goToImageExport();
  });
  overlay.querySelector('[data-action="go-image-export"]').focus();
}
