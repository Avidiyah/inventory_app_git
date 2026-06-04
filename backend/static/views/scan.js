// View: barcode scan/upload on the Transaction page.
//
// Layer: views. Owns the `#txn-scan-section` controls. Flow:
//   1. User picks an image (phone camera via `capture`, or a file).
//   2. POST it to `/barcodes/decode` (backend pyzbar decode, in memory).
//   3. Branch on the number of barcodes found:
//        0   -> clear error; the manual items table below stays usable.
//        1   -> exact lookup via `apiGetItemByBarcode`:
//                 found   -> filter the table + auto-open the txn form.
//                 404     -> offer a Create Item shortcut (Owner/Admin only).
//        many -> render a chooser; picking one runs the single-barcode path.
//
// Dependencies are one-way: this view imports `focusItemByBarcode` from
// the transactions view but the transactions view never imports this one
// (its post-save reset is injected via `main.js -> setOnTransactionSaved`).
// Navigation to the Create Item page is done by clicking the existing nav
// button rather than importing `nav.js`, keeping the graph acyclic.

import { apiDecodeBarcode, apiGetItemByBarcode } from "../api.js";
import { setMessage } from "../dom.js";
import { formatError } from "../format.js";
import { getRole } from "../state.js";
import { roleAtLeast } from "../roles.js";
import { focusItemByBarcode } from "./transactions.js";

const scanInput = document.getElementById("txn-scan-input");
const scanMessage = document.getElementById("txn-scan-message");
const scanChooser = document.getElementById("txn-scan-chooser");

// Owned by other views; used only to drive the Create Item shortcut.
const createItemNavBtn = document.querySelector('.nav-btn[data-page="create-item"]');
const createBarcodeInput = document.getElementById("barcode");

// Reset only the scan UI (input, message, chooser). The table filter is
// owned by transactions.js and cleared when the transaction form closes.
export function resetScan() {
  scanInput.value = "";
  scanChooser.innerHTML = "";
  scanChooser.hidden = true;
  setMessage(scanMessage, "", "");
}

function clearChooser() {
  scanChooser.innerHTML = "";
  scanChooser.hidden = true;
}

async function handleFile(file) {
  if (!file) return;
  clearChooser();
  setMessage(scanMessage, "Decoding…", "");

  let result;
  try {
    result = await apiDecodeBarcode(file);
  } catch (err) {
    if (err && err.status !== undefined) {
      setMessage(scanMessage, formatError(err.detail, "Could not decode the image."), "error");
    } else {
      setMessage(scanMessage, "Could not connect to the server.", "error");
    }
    return;
  }

  const barcodes = (result && result.barcodes) || [];
  if (barcodes.length === 0) {
    setMessage(scanMessage, "No barcode found in that image. Try again, or use the items table below.", "error");
    return;
  }
  if (barcodes.length === 1) {
    await resolveBarcode(barcodes[0].text);
    return;
  }
  renderChooser(barcodes);
}

function renderChooser(barcodes) {
  setMessage(scanMessage, "Multiple barcodes found — choose one:", "");
  scanChooser.innerHTML = "";
  barcodes.forEach(b => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "scan-choice-btn";
    btn.dataset.barcode = b.text;
    // textContent (not innerHTML) -- decoded text is untrusted.
    btn.textContent = `${b.text}  ·  ${b.format}`;
    scanChooser.appendChild(btn);
  });
  scanChooser.hidden = false;
}

async function resolveBarcode(barcode) {
  clearChooser();
  setMessage(scanMessage, "Looking up item…", "");

  let item;
  try {
    item = await apiGetItemByBarcode(barcode);
  } catch (err) {
    if (err && err.status === 404) {
      handleUnknownBarcode(barcode);
    } else if (err && err.status !== undefined) {
      setMessage(scanMessage, formatError(err.detail, "Lookup failed."), "error");
    } else {
      setMessage(scanMessage, "Could not connect to the server.", "error");
    }
    return;
  }

  setMessage(scanMessage, `Matched ${item.name} (${barcode}).`, "success");
  focusItemByBarcode(item);
}

function handleUnknownBarcode(barcode) {
  setMessage(scanMessage, `No item matches barcode ${barcode}.`, "error");

  // The Create Item page is Owner/Admin only; only offer the shortcut to
  // roles that can actually use it. Others just see the message above and
  // fall back to the manual table.
  if (!roleAtLeast(getRole(), "admin")) return;

  scanChooser.innerHTML = "";
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "scan-create-btn";
  btn.dataset.barcode = barcode;
  btn.textContent = `Create a new item for ${barcode}`;
  scanChooser.appendChild(btn);
  scanChooser.hidden = false;
}

scanInput.addEventListener("change", () => {
  handleFile(scanInput.files && scanInput.files[0]);
});

scanChooser.addEventListener("click", (event) => {
  const target = event.target;
  if (target.classList.contains("scan-choice-btn")) {
    resolveBarcode(target.dataset.barcode);
    return;
  }
  if (target.classList.contains("scan-create-btn")) {
    // Prefill the barcode, then switch to the Create Item page by
    // triggering the existing nav button (no import of nav.js).
    if (createBarcodeInput) createBarcodeInput.value = target.dataset.barcode;
    if (createItemNavBtn) createItemNavBtn.click();
    resetScan();
  }
});
