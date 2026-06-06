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
import { BarcodeDecoder } from "../scan/barcode-decoder.js";
import { FrameDebouncer } from "../scan/frame-debouncer.js";

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
 * @param {Object} [opts.liveEls]             - optional live-camera DOM handles; when omitted the
 *                                              widget is upload-only (existing behaviour).
 * @param {HTMLVideoElement} opts.liveEls.videoEl
 * @param {HTMLButtonElement} opts.liveEls.scanBtn   - toggles the live decoder on
 * @param {HTMLButtonElement} opts.liveEls.uploadBtn - the visible button that opens the file picker
 * @param {HTMLButtonElement} opts.liveEls.torchBtn  - torch toggle (hidden when capability absent)
 * @param {HTMLElement}      opts.liveEls.aimboxEl   - aim-box overlay; toggled hidden in lockstep with camera state
 * @returns {{ reset: () => void, stopLive: () => void }}
 */
export function mountScanner({
  inputEl,
  messageEl,
  chooserEl,
  onItemFound,
  allowCreate = true,
  onCreateShortcut,
  liveEls,
}) {
  function reset() {
    inputEl.value = "";
    chooserEl.innerHTML = "";
    chooserEl.hidden = true;
    setMessage(messageEl, "", "");
    if (liveEls) stopLive();
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

  // --- Live-camera mode -----------------------------------------
  //
  // Wired only when `liveEls` is provided. The decoder is push-based
  // (ZXing's `decodeFromStream` callback); decoded texts feed into a
  // 5-of-10 debouncer (`FrameDebouncer`). On accept we stop the
  // camera and funnel the text through the same `resolveBarcode`
  // path the upload flow uses -- live mode never calls
  // `/barcodes/decode`. See docs/plan-live-capture.md decision #3.
  //
  // Mutual exclusion: clicking Upload tears the camera down first so
  // we never hold a video track while the file picker is open.

  const decoder = liveEls ? new BarcodeDecoder() : null;
  const debouncer = liveEls ? new FrameDebouncer() : null;
  let liveStream = null;
  let liveTrack = null;
  let liveRunning = false;
  let torchOn = false;

  function setAimboxVisible(visible) {
    if (liveEls && liveEls.aimboxEl) liveEls.aimboxEl.hidden = !visible;
  }

  function setUploadDisabled(disabled) {
    if (liveEls && liveEls.uploadBtn) liveEls.uploadBtn.disabled = disabled;
  }

  function stopLive() {
    if (!liveEls) return;
    liveRunning = false;
    if (decoder) decoder.stop();
    if (debouncer) debouncer.reset();
    if (liveStream) {
      for (const track of liveStream.getTracks()) {
        try { track.stop(); } catch (_err) { /* nothing actionable */ }
      }
    }
    if (liveEls.videoEl) {
      try { liveEls.videoEl.srcObject = null; } catch (_err) { /* nothing actionable */ }
    }
    liveStream = null;
    liveTrack = null;
    torchOn = false;
    setAimboxVisible(false);
    setUploadDisabled(false);
    if (liveEls.torchBtn) {
      liveEls.torchBtn.hidden = true;
      liveEls.torchBtn.disabled = false;
    }
  }

  async function startLive() {
    if (!liveEls || liveRunning) return;
    if (!(await BarcodeDecoder.supports())) {
      setMessage(messageEl, "Live camera is not available in this browser.", "error");
      return;
    }
    clearChooser();
    setMessage(messageEl, "Starting camera…", "");

    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: { ideal: "environment" },
          width: { ideal: 1920 },
          height: { ideal: 1080 },
          focusMode: { ideal: "continuous" },
        },
        audio: false,
      });
    } catch (err) {
      const denied = err && (err.name === "NotAllowedError" || err.name === "SecurityError");
      setMessage(
        messageEl,
        denied
          ? "Camera permission denied. Use Upload instead, or allow camera access in your browser settings."
          : "Could not open the camera. Try Upload instead.",
        "error",
      );
      return;
    }

    liveStream = stream;
    liveTrack = stream.getVideoTracks()[0] || null;
    liveRunning = true;
    setAimboxVisible(true);
    setUploadDisabled(true);
    setMessage(messageEl, "Aim at a barcode…", "");

    // Best-effort post-start retry of focusMode -- iOS ignores this
    // silently, Android Chrome accepts the call but the driver may
    // leave the actual setting on `manual`. See Phase 1 results.
    if (liveTrack && typeof liveTrack.applyConstraints === "function") {
      setTimeout(() => {
        if (!liveRunning || !liveTrack) return;
        liveTrack
          .applyConstraints({ advanced: [{ focusMode: "continuous" }] })
          .catch(() => { /* expected on devices without driver support */ });
      }, 500);
    }

    // Expose the torch button only if the track advertises the
    // capability. Hidden by default in Phase 3 markup; we flip it on
    // here once we know it works.
    if (liveEls.torchBtn) {
      const caps = liveTrack && typeof liveTrack.getCapabilities === "function"
        ? liveTrack.getCapabilities()
        : {};
      liveEls.torchBtn.hidden = !caps.torch;
      liveEls.torchBtn.disabled = false;
    }

    try {
      await decoder.start(liveEls.videoEl, stream, (text, _format) => {
        if (!liveRunning) return;
        const accepted = debouncer.pushAndCheck(text);
        if (accepted) {
          stopLive();
          resolveBarcode(accepted);
        }
      });
    } catch (err) {
      stopLive();
      setMessage(messageEl, `Could not start the decoder: ${err && err.message ? err.message : "unknown error"}.`, "error");
    }
  }

  async function toggleTorch() {
    if (!liveRunning || !liveTrack || typeof liveTrack.applyConstraints !== "function") return;
    const next = !torchOn;
    try {
      await liveTrack.applyConstraints({ advanced: [{ torch: next }] });
      torchOn = next;
    } catch (_err) {
      // Capability lied; disable the button so the user stops trying.
      if (liveEls.torchBtn) liveEls.torchBtn.disabled = true;
    }
  }

  if (liveEls) {
    if (liveEls.scanBtn) {
      liveEls.scanBtn.addEventListener("click", () => {
        if (liveRunning) {
          stopLive();
          setMessage(messageEl, "", "");
        } else {
          startLive();
        }
      });
    }
    if (liveEls.uploadBtn) {
      liveEls.uploadBtn.addEventListener("click", () => {
        if (liveRunning) stopLive();
        inputEl.click();
      });
    }
    if (liveEls.torchBtn) {
      liveEls.torchBtn.hidden = true;
      liveEls.torchBtn.addEventListener("click", toggleTorch);
    }
  }

  // Pre-check the camera permission state (per decision #21). Called
  // by `views/nav.js` whenever the page hosting this scanner becomes
  // active. On `denied`, hide the Scan button and surface the
  // blocked-mode message; Upload remains the only path. On supported,
  // we leave the message untouched -- `reset()` on the previous
  // page-leave already cleared it, so the section presents clean.
  async function refreshPermissionState() {
    if (!liveEls) return;
    const supported = await BarcodeDecoder.supports();
    if (liveEls.scanBtn) liveEls.scanBtn.hidden = !supported;
    if (!supported) {
      setMessage(
        messageEl,
        "Camera blocked. Re-enable it via the lock icon in your browser, or use Upload.",
        "error",
      );
    }
  }

  return {
    reset,
    stopLive: liveEls ? stopLive : () => {},
    refreshPermissionState: liveEls ? refreshPermissionState : () => {},
  };
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

// Exported so `views/nav.js` can drive page-level camera lifecycle:
// stop on tab-hide / page-leave, refresh permission state on page-enter.
// Phase 3 PR1 wires the Transaction page only; Saved Items follows in PR2.
export const txnScanner = mountScanner({
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
  liveEls: {
    videoEl: document.getElementById("txn-scan-video"),
    scanBtn: document.getElementById("txn-scan-scan-btn"),
    uploadBtn: document.getElementById("txn-scan-upload-btn"),
    torchBtn: document.getElementById("txn-scan-torch-btn"),
    aimboxEl: document.getElementById("txn-scan-aimbox"),
  },
});

// Reset only the scan UI (input, message, chooser). The table filter is
// owned by transactions.js and cleared when the transaction form closes.
export function resetScan() {
  txnScanner.reset();
}
