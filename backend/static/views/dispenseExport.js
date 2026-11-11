// Weekly export (Saved Items page actions, TechFM OA+): download every item
// dispensed since the previous export, or reprint the last one. The server
// owns the window; this module only triggers the download. Admin+ also get the
// items CSV and the distributor pricing sheet.

import {
  apiCreateDispenseExport, apiExportItemsCsv, apiExportPricing, apiReprintDispenseExport,
} from "../api.js";
import { friendlyError } from "../format.js";
import { setMessage } from "../dom.js";

const exportBtn = document.getElementById("dispense-export-btn");
const reprintBtn = document.getElementById("dispense-reprint-btn");
const csvBtn = document.getElementById("items-csv-btn");
const pricingBtn = document.getElementById("items-pricing-btn");
const message = document.getElementById("dispense-export-message");
const buttons = [exportBtn, reprintBtn, csvBtn, pricingBtn];

export function showDispenseExport(visible, csvVisible = false) {
  exportBtn.hidden = reprintBtn.hidden = !visible;
  csvBtn.hidden = pricingBtn.hidden = !csvVisible;
}

async function download(request, fallback) {
  buttons.forEach((btn) => { btn.disabled = true; });
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
    buttons.forEach((btn) => { btn.disabled = false; });
  }
}

exportBtn.addEventListener("click", () =>
  download(apiCreateDispenseExport, "Could not create the weekly export."));
reprintBtn.addEventListener("click", () =>
  download(apiReprintDispenseExport, "Could not reprint the last export."));
csvBtn.addEventListener("click", () =>
  download(apiExportItemsCsv, "Could not export the items."));
pricingBtn.addEventListener("click", () =>
  download(apiExportPricing, "Could not export the pricing."));
