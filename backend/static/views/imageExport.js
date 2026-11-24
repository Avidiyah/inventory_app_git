// Integrations: the Image export section (spec 2026-11-24 photo export).
//
// Layer: Admin+ wiring for #integrations-image-export. Download is a plain
// navigation to the zip route (the browser saves it); Clear exported asks
// with the count, then deletes the exported photos server-side.

import { apiClearExportedPhotos, apiPhotoStorage } from "../api.js";
import { confirmDialog, setMessage } from "../dom.js";
import { friendlyError } from "../format.js";
import { roleAtLeast } from "../roles.js";
import { getRole } from "../state.js";

export const EXPORT_URL = "/work-order-photos/export.zip";

const section = document.getElementById("integrations-image-export");
const usage = document.getElementById("image-export-usage");
const downloadBtn = document.getElementById("image-export-download-btn");
const clearBtn = document.getElementById("image-export-clear-btn");
const message = document.getElementById("image-export-message");

export function formatBytes(bytes) {
  const mb = bytes / (1024 * 1024);
  if (mb < 1024) return `${Math.round(mb)} MB`;
  return `${Math.round((mb / 1024) * 10) / 10} GB`;
}

export function usageLine(s) {
  const pct = Math.round(s.ratio * 100);
  const waiting = `${s.waiting_photos} photo${s.waiting_photos === 1 ? "" : "s"} waiting`;
  return `Database ${formatBytes(s.used)} of ${formatBytes(s.disk)} (${pct}%) · ${waiting}`;
}

function render(s) {
  usage.textContent = usageLine(s);
  const total = s.waiting_photos + s.exported_photos;
  downloadBtn.textContent = `Download photos (${total})`;
  downloadBtn.disabled = total === 0;
  clearBtn.textContent = `Clear exported (${s.exported_photos})`;
  clearBtn.disabled = s.exported_photos === 0;
  clearBtn.dataset.count = String(s.exported_photos);
}

export async function loadImageExport() {
  if (!section) return;
  section.hidden = !roleAtLeast(getRole(), "admin");
  if (section.hidden) return;
  try {
    render(await apiPhotoStorage());
  } catch (err) {
    setMessage(message, friendlyError(err, "Could not read photo storage."), "error");
  }
}

downloadBtn?.addEventListener("click", () => {
  window.location.assign(EXPORT_URL);
  // The download stamps the new photos exported: refresh the counts after it.
  setTimeout(loadImageExport, 3000);
});

clearBtn?.addEventListener("click", async () => {
  const n = Number(clearBtn.dataset.count || 0);
  const ok = await confirmDialog(
    `Delete ${n} exported photo${n === 1 ? "" : "s"} from the database? Check they are in Google Drive first. This cannot be undone.`,
    { confirmText: "Delete", cancelText: "Cancel" }
  );
  if (!ok) return;
  clearBtn.disabled = true;
  try {
    const result = await apiClearExportedPhotos();
    render(result.storage);
    setMessage(message, `Cleared ${result.deleted} photo${result.deleted === 1 ? "" : "s"}.`, "success");
  } catch (err) {
    setMessage(message, friendlyError(err, "Could not clear the photos."), "error");
    clearBtn.disabled = false;
  }
});
