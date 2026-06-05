// View: reusable barcode scan / upload widget.
//
// Layer: views. Exposes a `mountScanner({...})` factory so the same
// scan UI can live on the Transaction page (where it auto-opens a
// transaction form for the matched item) and on the Saved Items page
// (where it filters the items table). Both call sites share:
//
//   1. The file input -- camera via `capture`, or a regular file picker.
//   2. POST to `/barcodes/decode` (backend pyzbar decode, in memory).
//   3. Branch on the number of barcodes found:
//        0    -> show an error; caller's table stays usable.
//        1    -> exact lookup via `apiGetItemByBarcode`:
//                  found -> caller's `onItemFound(item)` callback.
//                  404   -> when `allowCreate` is true *and* the
//                          viewer is Owner/Admin, offer a Create-Item
//                          shortcut; the shortcut behaviour is supplied
//                          by `onCreateShortcut(barcode)`.
//        many -> render a chooser; picking one runs the single path.
//
// The Transaction-page instance is auto-mounted at the bottom of this
// module to preserve the existing `import "./views/scan.js"` side-effect
// in `main.js`. The Saved Items page mounts its own instance from
// `views/items.js`.

import { apiDecodeBarcode, apiGetItemByBarcode } from "../api.js";
import { setMessage } from "../dom.js";
import { formatError } from "../format.js";
import { getRole } from "../state.js";
import { roleAtLeast } from "../roles.js";
import { focusItemByBarcode } from "./transactions.js";

/**
 * Mount a scanner widget on a set of DOM elements.
 *
 * @param {Object} opts
 * @param {HTMLInputElement} opts.inputEl     - the file input
 * @param {HTMLElement}      opts.messageEl   - status / error paragraph
 * @param {HTMLElement}      opts.chooserEl   - container for multi-barcode chooser / create shortcut
 * @param {(item: object) => void} opts.onItemFound - called when a barcode resolves to an item
 * @param {boolean} [opts.allowCreate=true]   - offer the "Create item" shortcut on 404 (Admin+ only)
 * @param {(barcode: string) => void} [opts.onCreateShortcut] - what the Create shortcut button does
 * @returns {{ reset: () => void }}
 */
export function mountScanner({
  inputEl,
  messageEl,
  chooserEl,
  onItemFound,
  allowCreate = true,
  onCreateShortcut,
}) {
  function reset() {
    inputEl.value = "";
    chooserEl.innerHTML = "";
    chooserEl.hidden = true;
    setMessage(messageEl, "", "");
  }

  function clearChooser() {
    chooserEl.innerHTML = "";
    chooserEl.hidden = true;
  }

  async function handleFile(file) {
    if (!file) return;
    clearChooser();
    setMessage(messageEl, "Decoding…", "");

    let result;
    try {
      result = await apiDecodeBarcode(file);
    } catch (err) {
      if (err && err.status !== undefined) {
        setMessage(messageEl, formatError(err.detail, "Could not decode the image."), "error");
      } else {
        setMessage(messageEl, "Could not connect to the server.", "error");
      }
      return;
    }

    const barcodes = (result && result.barcodes) || [];
    if (barcodes.length === 0) {
      setMessage(messageEl, "No barcode found in that image. Try again, or use the items table below.", "error");
      return;
    }
    if (barcodes.length === 1) {
      await resolveBarcode(barcodes[0].text);
      return;
    }
    renderChooser(barcodes);
  }

  function renderChooser(barcodes) {
    setMessage(messageEl, "Multiple barcodes found — choose one:", "");
    chooserEl.innerHTML = "";
    barcodes.forEach(b => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "scan-choice-btn";
      btn.dataset.barcode = b.text;
      // textContent (not innerHTML) -- decoded text is untrusted.
      btn.textContent = `${b.text}  ·  ${b.format}`;
      chooserEl.appendChild(btn);
    });
    chooserEl.hidden = false;
  }

  async function resolveBarcode(barcode) {
    clearChooser();
    setMessage(messageEl, "Looking up item…", "");

    let item;
    try {
      item = await apiGetItemByBarcode(barcode);
    } catch (err) {
      if (err && err.status === 404) {
        handleUnknownBarcode(barcode);
      } else if (err && err.status !== undefined) {
        setMessage(messageEl, formatError(err.detail, "Lookup failed."), "error");
      } else {
        setMessage(messageEl, "Could not connect to the server.", "error");
      }
      return;
    }

    setMessage(messageEl, `Matched ${item.name} (${barcode}).`, "success");
    onItemFound(item);
  }

  function handleUnknownBarcode(barcode) {
    setMessage(messageEl, `No item matches barcode ${barcode}.`, "error");

    // The Create Item flow is Owner/Admin only on the backend; only
    // offer the shortcut to roles that can actually use it. Others
    // just see the message above.
    if (!allowCreate) return;
    if (!roleAtLeast(getRole(), "admin")) return;

    chooserEl.innerHTML = "";
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "scan-create-btn";
    btn.dataset.barcode = barcode;
    btn.textContent = `Create a new item for ${barcode}`;
    chooserEl.appendChild(btn);
    chooserEl.hidden = false;
  }

  inputEl.addEventListener("change", () => {
    handleFile(inputEl.files && inputEl.files[0]);
  });

  chooserEl.addEventListener("click", (event) => {
    const target = event.target;
    if (target.classList.contains("scan-choice-btn")) {
      resolveBarcode(target.dataset.barcode);
      return;
    }
    if (target.classList.contains("scan-create-btn") && onCreateShortcut) {
      onCreateShortcut(target.dataset.barcode);
      reset();
    }
  });

  return { reset };
}

// --- Auto-mount: Transaction-page scanner -----------------------
//
// Preserves the existing `import "./views/scan.js"` side-effect plus
// the `resetScan` named export `main.js` wires into
// `setOnTransactionSaved`.

const txnScanInput = document.getElementById("txn-scan-input");
const txnScanMessage = document.getElementById("txn-scan-message");
const txnScanChooser = document.getElementById("txn-scan-chooser");

// Owned by other views; used only to drive the Create-Item shortcut on
// the Transaction page (prefill barcode, jump to the Create Item page).
const createItemNavBtn = document.querySelector('.nav-btn[data-page="create-item"]');
const createBarcodeInput = document.getElementById("barcode");

const txnScanner = mountScanner({
  inputEl: txnScanInput,
  messageEl: txnScanMessage,
  chooserEl: txnScanChooser,
  onItemFound: focusItemByBarcode,
  allowCreate: true,
  onCreateShortcut: (barcode) => {
    // Prefill the barcode, then switch to the Create Item page by
    // triggering the existing nav button (no import of nav.js).
    if (createBarcodeInput) createBarcodeInput.value = barcode;
    if (createItemNavBtn) createItemNavBtn.click();
  },
});

// Reset only the scan UI (input, message, chooser). The table filter is
// owned by transactions.js and cleared when the transaction form closes.
export function resetScan() {
  txnScanner.reset();
}
