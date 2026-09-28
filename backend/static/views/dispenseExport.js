// Weekly export (Saved Items page actions, TechFM OA+): download every item
// dispensed since the previous export, or reprint the last one. The server
// owns the window; this module only triggers the download.

import { apiCreateDispenseExport, apiReprintDispenseExport } from "../api.js";
import { friendlyError } from "../format.js";
import { setMessage } from "../dom.js";

const exportBtn = document.getElementById("dispense-export-btn");
const reprintBtn = document.getElementById("dispense-reprint-btn");
const message = document.getElementById("dispense-export-message");

export function showDispenseExport(visible) {
  exportBtn.hidden = reprintBtn.hidden = !visible;
}

async function download(request, fallback) {
  exportBtn.disabled = reprintBtn.disabled = true;
  setMessage(message, "Preparing export…", "");
  try {
    const { blob, filename } = await request();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 0);
    setMessage(message, `Downloaded ${filename}.`, "success");
  } catch (err) {
    setMessage(message, friendlyError(err, fallback), "error");
  } finally {
    exportBtn.disabled = reprintBtn.disabled = false;
  }
}

exportBtn.addEventListener("click", () =>
  download(apiCreateDispenseExport, "Could not create the weekly export."));
reprintBtn.addEventListener("click", () =>
  download(apiReprintDispenseExport, "Could not reprint the last export."));
