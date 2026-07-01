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
import { friendlyError } from "../format.js";
import { getRole } from "../state.js";
import { roleAtLeast } from "../roles.js";
import { commitScannedItem, scanGoArmed } from "./transactions.js";
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
 * @param {(barcode: string) => void} [opts.onAddBarcode] - offer an "Add Barcode to an existing item"
 *                                              shortcut on 404 (Admin+ only); the callback opens the
 *                                              by-name add-barcode flow for the scanned code
 * @param {boolean} [opts.continuous=false]   - scan-and-go batch mode: a successful decode is
 *                                              committed via `onCommit` instead of opening a form,
 *                                              and the live camera stays running between scans.
 * @param {(item: object) => Promise<{committed: boolean}>} [opts.onCommit] - records the transaction
 *                                              for a resolved item (continuous mode only) and reports
 *                                              whether it was actually committed.
 * @param {() => boolean} [opts.canScan]       - continuous-mode gate: return false to refuse a scan
 *                                              (e.g. no quantity entered yet) with a prompt.
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
  onAddBarcode,
  liveEls,
  continuous = false,
  onCommit,
  canScan,
}) {
  // Scan-and-go tuning. After a commit the live decoder keeps running, so
  // two guards stop the same label (still in frame) from being counted
  // twice: a short DWELL where every decode is ignored, plus a longer
  // COOLDOWN during which only the *just-committed* barcode is suppressed
  // (a different item commits immediately). See docs/current-state.md.
  const DWELL_MS = 1200;
  const COOLDOWN_MS = 3000;

  // Short haptic confirmation for field use; silent no-op where the
  // Vibration API is absent (desktop, iOS Safari).
  function buzz(ok) {
    if (typeof navigator === "undefined" || typeof navigator.vibrate !== "function") return;
    try {
      navigator.vibrate(ok ? 60 : [40, 40, 40]);
    } catch (_err) {
      /* vibrate can throw if the document is not focused; nothing actionable */
    }
  }
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
      setMessage(messageEl, friendlyError(err, "Could not read that image. Try again."), "error");
      return;
    }

    const barcodes = (result && result.barcodes) || [];
    if (barcodes.length === 0) {
      setMessage(messageEl, "Could not read that barcode. Move closer, hold steady, and try again.", "error");
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

    // Scan-and-go: look up the item and commit the transaction in place
    // rather than opening a form. Used by both the upload path (via
    // handleFile / the chooser) and the live path (via handleLiveAccept).
    if (continuous) {
      return resolveAndCommit(barcode);
    }

    setMessage(messageEl, "Looking up item…", "");

    let item;
    try {
      item = await apiGetItemByBarcode(barcode);
    } catch (err) {
      if (err && err.status === 404) {
        handleUnknownBarcode(barcode);
      } else {
        setMessage(messageEl, friendlyError(err, "Lookup failed. Try again."), "error");
      }
      return;
    }

    setMessage(messageEl, `Matched ${item.name} (${barcode}).`, "success");
    onItemFound(item);
  }

  // Scan-and-go commit path. Returns `{committed}` so the live handler
  // can decide whether to start the same-barcode cooldown. Buzzes on
  // every outcome (success once, error pattern on any failure) and never
  // throws -- the camera keeps running regardless.
  async function resolveAndCommit(barcode) {
    if (canScan && !canScan()) {
      setMessage(messageEl, "Enter a quantity first, then scan.", "error");
      buzz(false);
      return { committed: false };
    }

    setMessage(messageEl, "Looking up item…", "");

    let item;
    try {
      item = await apiGetItemByBarcode(barcode);
    } catch (err) {
      // No Create-Item shortcut in scan-and-go: it would derail a hands-busy
      // batch, and the floor crew cannot create items anyway.
      setMessage(
        messageEl,
        err && err.status === 404
          ? "No item matches that barcode."
          : friendlyError(err, "Lookup failed. Try again."),
        "error",
      );
      buzz(false);
      return { committed: false };
    }

    const result = onCommit ? await onCommit(item) : { committed: false };
    // Buzz success on a commit and the error pattern on a real failure (e.g.
    // overdraw), but stay silent on a user decline -- saying No is not an error.
    if (result && result.committed) {
      buzz(true);
    } else if (!(result && result.declined)) {
      buzz(false);
    }
    return result;
  }

  function handleUnknownBarcode(barcode) {
    setMessage(messageEl, "No item matches that barcode.", "error");

    // Both shortcuts (Create Item, Add Barcode) hit Owner/Admin-only
    // backend routes, so gate the whole chooser to Admin+. Lower roles
    // just see the message above.
    if (!roleAtLeast(getRole(), "admin")) return;

    chooserEl.innerHTML = "";

    if (allowCreate) {
      const createBtn = document.createElement("button");
      createBtn.type = "button";
      createBtn.className = "scan-create-btn";
      createBtn.dataset.barcode = barcode;
      createBtn.textContent = `Create a new item for ${barcode}`;
      chooserEl.appendChild(createBtn);
    }

    if (onAddBarcode) {
      const addBtn = document.createElement("button");
      addBtn.type = "button";
      addBtn.className = "scan-addbarcode-btn";
      addBtn.dataset.barcode = barcode;
      addBtn.textContent = `Add ${barcode} to an existing item`;
      chooserEl.appendChild(addBtn);
    }

    if (!chooserEl.children.length) return; // nothing to offer this role
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
      return;
    }
    if (target.classList.contains("scan-addbarcode-btn") && onAddBarcode) {
      onAddBarcode(target.dataset.barcode);
      reset();
    }
  });

  // --- Live-camera mode -----------------------------------------
  //
  // Wired only when `liveEls` is provided. The decoder is push-based
  // (`BarcodeDecoder` runs a crop loop and fires a callback per decode);
  // decoded texts feed into a 3-consecutive debouncer (`FrameDebouncer`).
  // On accept we stop the camera and funnel the text through the same
  // `resolveBarcode` path the upload flow uses -- live mode never calls
  // `/barcodes/decode`. See docs/current-state.md.
  //
  // Mutual exclusion: clicking Upload tears the camera down first so
  // we never hold a video track while the file picker is open.

  const decoder = liveEls ? new BarcodeDecoder() : null;
  const debouncer = liveEls ? new FrameDebouncer() : null;
  let liveStream = null;
  let liveTrack = null;
  let liveRunning = false;
  let torchOn = false;

  // Continuous-mode guard state (see DWELL_MS / COOLDOWN_MS above).
  // `livePaused` swallows every decode during the post-commit dwell;
  // `cooldownBarcode` + `cooldownUntil` suppress only a repeat of the
  // just-committed code for the longer window.
  let livePaused = false;
  let cooldownBarcode = null;
  let cooldownUntil = 0;

  // Continuous live accept: debounce, suppress immediate repeats, commit,
  // then dwell. The camera is never stopped here -- it stays live for the
  // next item.
  async function handleLiveAccept(text) {
    if (livePaused) return;

    const accepted = debouncer.pushAndCheck(text);
    if (!accepted) return;
    debouncer.reset(); // consume this streak; the next item needs a fresh one

    if (accepted === cooldownBarcode && Date.now() < cooldownUntil) return;

    livePaused = true; // ignore decodes while we look up + confirm + commit + dwell
    try {
      const result = await resolveBarcode(accepted);
      // Cool down on a commit *or* a decline so a label still in frame isn't
      // immediately re-committed or re-prompted; a different item is unaffected.
      if (result && (result.committed || result.declined)) {
        cooldownBarcode = accepted;
        cooldownUntil = Date.now() + COOLDOWN_MS;
      }
    } finally {
      setTimeout(() => {
        livePaused = false;
        debouncer.reset();
      }, DWELL_MS);
    }
  }

  function setAimboxVisible(visible) {
    if (liveEls && liveEls.aimboxEl) liveEls.aimboxEl.hidden = !visible;
  }

  function setUploadDisabled(disabled) {
    if (liveEls && liveEls.uploadBtn) liveEls.uploadBtn.disabled = disabled;
  }

  function stopLive() {
    if (!liveEls) return;
    liveRunning = false;
    livePaused = false;
    cooldownBarcode = null;
    cooldownUntil = 0;
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
          // 720p, not 1080p: with the aim-box crop the cropped region has
          // ample pixels for a label that fills the box, and smaller frames
          // decode faster. Validated on the fleet; see docs/current-state.md.
          // (supersedes the earlier full-frame decode approach).
          width: { ideal: 1280 },
          height: { ideal: 720 },
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
    // leave the actual setting on `manual`.
    if (liveTrack && typeof liveTrack.applyConstraints === "function") {
      setTimeout(() => {
        if (!liveRunning || !liveTrack) return;
        liveTrack
          .applyConstraints({ advanced: [{ focusMode: "continuous" }] })
          .catch(() => { /* expected on devices without driver support */ });
      }, 500);
    }

    // Expose the torch button only if the track advertises the
    // capability. Hidden by default; flip it on once we know it works.
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
        // Scan-and-go: keep the camera live and commit in place.
        if (continuous) {
          handleLiveAccept(text);
          return;
        }
        // Default: first accepted code stops the camera and opens a form.
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

  // Start the live camera without a user tap, but ONLY when permission is
  // already granted -- never trigger a permission prompt from here. Used by
  // the scan-and-go flow so beginning a work order shows a live camera ready
  // to scan; on first use / denied / unsupported the manual "Scan Barcode"
  // button stays the path. No-op if already running.
  async function autoStartIfPermitted() {
    if (!liveEls || liveRunning) return;
    if (!(await BarcodeDecoder.supports())) return;
    if (!(await BarcodeDecoder.permissionGranted())) return;
    await startLive();
  }

  return {
    reset,
    startLive: liveEls ? startLive : () => {},
    stopLive: liveEls ? stopLive : () => {},
    refreshPermissionState: liveEls ? refreshPermissionState : () => {},
    autoStartIfPermitted: liveEls ? autoStartIfPermitted : () => {},
  };
}

// --- Auto-mount: Transaction-page scanner -----------------------
//
// Preserves the existing `import "./views/scan.js"` side-effect plus
// the `resetScan` named export `main.js` wires into
// `setScanResetter`.

const txnScanInput = document.getElementById("txn-scan-input");
const txnScanMessage = document.getElementById("txn-scan-message");
const txnScanChooser = document.getElementById("txn-scan-chooser");

// Exported so `views/nav.js` can drive page-level camera lifecycle:
// stop on tab-hide / page-leave, refresh permission state on page-enter.
// The Transaction-page scanner runs in scan-and-go (continuous) mode: a
// successful decode is committed straight into the active work order via
// `commitScannedItem`, gated by `scanGoArmed` (a quantity must be set).
export const txnScanner = mountScanner({
  inputEl: txnScanInput,
  messageEl: txnScanMessage,
  chooserEl: txnScanChooser,
  continuous: true,
  onCommit: commitScannedItem,
  canScan: scanGoArmed,
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

// Auto-start the Transaction-page camera when a batch begins -- only if
// permission is already granted (never prompts). Injected into
// transactions.js via main.js to keep the dependency one-way (scan ->
// transactions).
export function autoStartTxnScan() {
  txnScanner.autoStartIfPermitted();
}
