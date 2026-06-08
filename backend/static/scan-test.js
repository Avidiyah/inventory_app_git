// Phase 1 decoder spike. Pairs with scan-test.html. Deleted in the
// Phase 3 ship PR. See docs/plan-live-capture.md.
//
// Purpose: answer the seven Phase 1 questions on real phones and labels.
// Specifically, no integration with the real scan flow, no API calls.
//
// ZXing comes from a vendored UMD bundle loaded via a plain <script> tag,
// which attaches `ZXingBrowser` to `window`. This module references it
// from the global.

const ZXingBrowser = window.ZXingBrowser;
if (!ZXingBrowser) {
  document.body.insertAdjacentHTML(
    "afterbegin",
    '<p style="color:#800;font-weight:bold">ZXing UMD failed to load. ' +
      "Check /static/vendor/ contents.</p>"
  );
  throw new Error("ZXingBrowser global missing");
}

// --- DOM handles ---
const els = {
  video: document.getElementById("scan-test-video"),
  aimbox: document.getElementById("scan-test-aimbox"),
  startBtn: document.getElementById("scan-test-start-btn"),
  stopBtn: document.getElementById("scan-test-stop-btn"),
  resetBtn: document.getElementById("scan-test-reset-window-btn"),
  torchBtn: document.getElementById("scan-test-torch-btn"),
  copyBtn: document.getElementById("scan-test-copy-logs-btn"),
  phone: document.getElementById("scan-test-phone"),
  conditions: document.getElementById("scan-test-conditions"),
  log: document.getElementById("scan-test-log"),
  state: document.getElementById("diag-state"),
  resolution: document.getElementById("diag-resolution"),
  facing: document.getElementById("diag-facing"),
  torch: document.getElementById("diag-torch"),
  focus: document.getElementById("diag-focus"),
  fps: document.getElementById("diag-fps"),
  latency: document.getElementById("diag-latency"),
  latest: document.getElementById("diag-latest"),
  window: document.getElementById("diag-window"),
  accepted: document.getElementById("diag-accepted"),
  tta: document.getElementById("diag-tta"),
};

// --- State ---
const WINDOW_SIZE = 10;
const ACCEPT_THRESHOLD = 5;
const SAMPLES = 30; // rolling samples for FPS / latency
const LOG_MAX_LINES = 200;

const state = {
  reader: null,
  controls: null, // IScannerControls from ZXing decodeFromStream
  stream: null,
  videoTrack: null,
  cameraState: "idle",
  startBtnLock: false,
  window: [], // last N decoded texts
  accepted: null,
  startTimestamp: null,
  decodeTimestamps: [], // wall-clock per decode callback
  decodeLatencies: [], // ms per decode (lastFrameStart -> now)
  lastFrameStart: null,
  torchOn: false,
  logLines: [],
};

// --- Logging ---
function log(msg, level = "info") {
  const ts = new Date().toISOString().substring(11, 23); // HH:MM:SS.mmm
  const line = `[${ts}] [${level}] ${msg}`;
  state.logLines.push(line);
  if (state.logLines.length > LOG_MAX_LINES) {
    state.logLines.shift();
  }
  els.log.textContent = state.logLines.join("\n");
  els.log.scrollTop = els.log.scrollHeight;
}

// --- State transitions ---
function setCameraState(next) {
  state.cameraState = next;
  els.state.textContent = next;
  els.state.className =
    "pill " +
    (next === "streaming" ? "ok" : next === "error" || next === "blocked" ? "err" : "");
  els.startBtn.disabled = next !== "idle" && next !== "error" && next !== "blocked";
  els.stopBtn.disabled = next === "idle" || next === "blocked";
  log(`camera state -> ${next}`);
}

// --- Diagnostics renderer ---
function renderDiag() {
  // Resolution + facingMode pulled live each render in case the track
  // renegotiates (rare but possible).
  if (state.videoTrack) {
    const s = state.videoTrack.getSettings();
    els.resolution.textContent = `${s.width || "?"} x ${s.height || "?"}`;
    els.facing.textContent = s.facingMode || "(not reported)";
    const grantedFocus = s.focusMode || "(not reported)";
    let capableFocus = "unknown";
    try {
      const caps = state.videoTrack.getCapabilities ? state.videoTrack.getCapabilities() : {};
      capableFocus = Array.isArray(caps.focusMode) ? caps.focusMode.join(",") : "(not exposed)";
    } catch (_) { /* swallow -- already logged in start() */ }
    els.focus.textContent = `${grantedFocus} / ${capableFocus}`;
  } else {
    els.resolution.textContent = "—";
    els.facing.textContent = "—";
    els.focus.textContent = "—";
  }

  // FPS over last (up to) SAMPLES callbacks.
  if (state.decodeTimestamps.length >= 2) {
    const first = state.decodeTimestamps[0];
    const last = state.decodeTimestamps[state.decodeTimestamps.length - 1];
    const seconds = (last - first) / 1000;
    const fps = seconds > 0 ? (state.decodeTimestamps.length - 1) / seconds : 0;
    els.fps.textContent = fps.toFixed(1);
  } else {
    els.fps.textContent = "—";
  }

  // Mean decode latency over last SAMPLES.
  if (state.decodeLatencies.length > 0) {
    const sum = state.decodeLatencies.reduce((a, b) => a + b, 0);
    els.latency.textContent = `${(sum / state.decodeLatencies.length).toFixed(1)} ms`;
  } else {
    els.latency.textContent = "—";
  }

  // Window: text -> count.
  if (state.window.length === 0) {
    els.window.textContent = "(empty)";
  } else {
    const counts = new Map();
    for (const t of state.window) counts.set(t, (counts.get(t) || 0) + 1);
    els.window.textContent = [...counts.entries()]
      .map(([t, c]) => `${c}× ${t}`)
      .join("  |  ");
  }
}

// --- Decode callback ---
function onDecode(result, error) {
  const now = performance.now();
  if (state.lastFrameStart != null) {
    const latency = now - state.lastFrameStart;
    state.decodeLatencies.push(latency);
    if (state.decodeLatencies.length > SAMPLES) state.decodeLatencies.shift();
  }
  state.lastFrameStart = now;

  state.decodeTimestamps.push(now);
  if (state.decodeTimestamps.length > SAMPLES) state.decodeTimestamps.shift();

  if (result) {
    const text = result.getText();
    const format = formatName(result.getBarcodeFormat());
    const supported = SUPPORTED_FORMATS.has(format);
    els.latest.innerHTML = ""; // safe -- replaced by textContent on next line
    els.latest.textContent = `${text} (${format})${supported ? " [supported]" : " [UNSUPPORTED]"}`;

    state.window.push(text);
    if (state.window.length > WINDOW_SIZE) state.window.shift();

    log(`decoded text="${text}" format=${format} supported=${supported}`);

    // Check 5-of-10.
    if (!state.accepted) {
      const counts = new Map();
      for (const t of state.window) counts.set(t, (counts.get(t) || 0) + 1);
      for (const [t, c] of counts) {
        if (c >= ACCEPT_THRESHOLD) {
          state.accepted = t;
          const tta = state.startTimestamp != null
            ? (performance.now() - state.startTimestamp).toFixed(0) + " ms"
            : "n/a";
          els.accepted.textContent = `${t}  (count=${c})`;
          els.accepted.className = "";
          els.tta.textContent = tta;
          log(`ACCEPTED "${t}" after ${tta} (count=${c}/${WINDOW_SIZE})`, "accept");
          break;
        }
      }
    }
  }

  // error is a NotFoundException for "no barcode this frame" -- expected
  // during normal scanning, do not log.

  renderDiag();
}

// --- Format name lookup ---
// ZXing returns numeric BarcodeFormat enum values. Map to readable names
// for diagnostics. Names mirror @zxing/library's BarcodeFormat enum.
const FORMAT_NAMES = {
  0: "AZTEC",
  1: "CODABAR",
  2: "CODE_39",
  3: "CODE_93",
  4: "CODE_128",
  5: "DATA_MATRIX",
  6: "EAN_8",
  7: "EAN_13",
  8: "ITF",
  9: "MAXICODE",
  10: "PDF_417",
  11: "QR_CODE",
  12: "RSS_14",
  13: "RSS_EXPANDED",
  14: "UPC_A",
  15: "UPC_E",
  16: "UPC_EAN_EXTENSION",
};
function formatName(n) {
  return FORMAT_NAMES[n] || `UNKNOWN(${n})`;
}

// Mirrors the five formats the backend accepts in services/barcodes.py.
const SUPPORTED_FORMATS = new Set(["UPC_A", "UPC_E", "EAN_13", "EAN_8", "CODE_128"]);

// --- Start ---
async function start() {
  if (state.startBtnLock) return;
  state.startBtnLock = true;
  try {
    setCameraState("requesting");

    const constraints = {
      video: {
        facingMode: { ideal: "environment" },
        width: { ideal: 1920 },
        height: { ideal: 1080 },
        // Request continuous autofocus up front. Android Chrome/Edge
        // default to a single AF pass at stream start and lock; on iOS
        // Safari this key is unrecognised and silently ignored. Setting
        // it here (as a basic best-effort constraint, not under
        // `advanced`) is more reliable than calling applyConstraints
        // after the stream is already running -- which on Chrome Android
        // is documented to be accepted but ignored on many devices.
        focusMode: { ideal: "continuous" },
      },
      audio: false,
    };
    log(`getUserMedia(${JSON.stringify(constraints.video)})`);

    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia(constraints);
    } catch (err) {
      log(`getUserMedia rejected: ${err.name} -- ${err.message}`, "err");
      setCameraState(err.name === "NotAllowedError" ? "blocked" : "error");
      return;
    }

    state.stream = stream;
    state.videoTrack = stream.getVideoTracks()[0] || null;

    // Settings + capabilities (browser support varies).
    if (state.videoTrack) {
      const s = state.videoTrack.getSettings();
      log(`track settings: ${JSON.stringify(s)}`);
      try {
        const caps = state.videoTrack.getCapabilities
          ? state.videoTrack.getCapabilities()
          : {};
        log(`track capabilities keys: ${Object.keys(caps).join(",")}`);
        log(`focusMode capabilities: ${JSON.stringify(caps.focusMode || null)}; granted: ${s.focusMode || "(not reported)"}`);
        if (caps.torch === true) {
          els.torch.textContent = "yes";
          els.torch.className = "";
          els.torchBtn.hidden = false;
        } else {
          els.torch.textContent = caps.torch === false ? "exposed but unsupported" : "no";
          els.torchBtn.hidden = true;
        }
      } catch (err) {
        log(`getCapabilities() threw: ${err.message}`, "warn");
        els.torch.textContent = "n/a (threw)";
      }

      // Fallback if the initial constraint didn't move us off `manual`.
      // Some Chrome-on-Android cameras only honour focusMode via
      // applyConstraints once a frame has been delivered. Retry after a
      // short delay; log both attempts so we can tell which (if either)
      // worked.
      try {
        const initialFocus = state.videoTrack.getSettings().focusMode;
        const caps2 = state.videoTrack.getCapabilities ? state.videoTrack.getCapabilities() : {};
        const supportsContinuous = Array.isArray(caps2.focusMode) && caps2.focusMode.includes("continuous");
        if (initialFocus !== "continuous" && supportsContinuous) {
          log("focus not continuous after initial constraint; will retry via applyConstraints in 500ms");
          setTimeout(async () => {
            try {
              await state.videoTrack.applyConstraints({ advanced: [{ focusMode: "continuous" }] });
              const after = state.videoTrack.getSettings().focusMode;
              log(`focusMode after retry applyConstraints: ${after || "(not reported)"}`);
            } catch (err) {
              log(`retry applyConstraints(focusMode) threw: ${err.name} -- ${err.message}`, "warn");
            }
          }, 500);
        }
      } catch (err) {
        log(`focus fallback check threw: ${err.message}`, "warn");
      }
    }

    els.aimbox.hidden = false;
    state.startTimestamp = performance.now();
    state.reader = new ZXingBrowser.BrowserMultiFormatReader();

    // decodeFromStream attaches the existing stream to our video element
    // and invokes onDecode after every decode attempt.
    state.controls = await state.reader.decodeFromStream(stream, els.video, onDecode);
    setCameraState("streaming");
    log("streaming started");
  } finally {
    state.startBtnLock = false;
  }
}

// --- Stop ---
function stop() {
  if (state.cameraState === "idle") return;
  setCameraState("stopping");

  try {
    if (state.controls && typeof state.controls.stop === "function") {
      state.controls.stop();
    }
  } catch (err) {
    log(`controls.stop() threw: ${err.message}`, "warn");
  }

  if (state.stream) {
    for (const track of state.stream.getTracks()) {
      try {
        track.stop();
      } catch (err) {
        log(`track.stop() threw: ${err.message}`, "warn");
      }
    }
  }

  try {
    els.video.srcObject = null;
  } catch (err) {
    log(`video.srcObject = null threw: ${err.message}`, "warn");
  }

  state.reader = null;
  state.controls = null;
  state.stream = null;
  state.videoTrack = null;
  state.lastFrameStart = null;
  state.torchOn = false;
  els.torchBtn.textContent = "Torch: off";
  els.aimbox.hidden = true;

  setCameraState("idle");
}

// --- Reset rolling window ---
function resetWindow() {
  state.window = [];
  state.accepted = null;
  state.startTimestamp = state.cameraState === "streaming" ? performance.now() : null;
  els.accepted.textContent = "—";
  els.tta.textContent = "—";
  renderDiag();
  log("window reset");
}

// --- Torch toggle ---
async function toggleTorch() {
  if (!state.videoTrack) return;
  const next = !state.torchOn;
  try {
    await state.videoTrack.applyConstraints({ advanced: [{ torch: next }] });
    state.torchOn = next;
    els.torchBtn.textContent = `Torch: ${next ? "on" : "off"}`;
    log(`torch -> ${next ? "on" : "off"}`);
  } catch (err) {
    log(`applyConstraints(torch=${next}) threw: ${err.name} -- ${err.message}`, "err");
  }
}

// --- Copy logs ---
async function copyLogs() {
  const snapshot = {
    capturedAt: new Date().toISOString(),
    userAgent: navigator.userAgent,
    phone: els.phone.value || "(unset)",
    conditions: els.conditions.value || "(unset)",
    cameraState: state.cameraState,
    resolutionGranted: els.resolution.textContent,
    facingModeGranted: els.facing.textContent,
    torchCapability: els.torch.textContent,
    fps: els.fps.textContent,
    meanDecodeLatency: els.latency.textContent,
    rollingWindow: [...state.window],
    accepted: state.accepted,
    timeToAccept: els.tta.textContent,
    logTail: [...state.logLines],
  };
  const text = JSON.stringify(snapshot, null, 2);
  try {
    await navigator.clipboard.writeText(text);
    log("logs copied to clipboard", "info");
  } catch (err) {
    log(`clipboard.writeText threw: ${err.message} -- dumping to log instead`, "warn");
    log("\n" + text);
  }
}

// --- Permissions pre-check (where supported) ---
async function permissionsPrecheck() {
  if (!navigator.permissions || !navigator.permissions.query) {
    log("navigator.permissions unsupported; will rely on getUserMedia result");
    return;
  }
  try {
    const status = await navigator.permissions.query({ name: "camera" });
    log(`permissions.query(camera) -> ${status.state}`);
    if (status.state === "denied") {
      setCameraState("blocked");
      log("camera permission is denied. Re-enable via the address-bar lock icon.", "err");
    }
  } catch (err) {
    // Safari throws TypeError for { name: 'camera' } on some versions.
    log(`permissions.query(camera) threw: ${err.message}`, "warn");
  }
}

// --- Visibility / lifecycle ---
document.addEventListener("visibilitychange", () => {
  if (document.hidden && state.cameraState === "streaming") {
    log("visibilitychange -> hidden; stopping");
    stop();
  }
});
window.addEventListener("beforeunload", () => {
  if (state.stream) {
    for (const t of state.stream.getTracks()) {
      try { t.stop(); } catch (_) { /* swallow */ }
    }
  }
});

// --- Wire ---
els.startBtn.addEventListener("click", () => start());
els.stopBtn.addEventListener("click", () => stop());
els.resetBtn.addEventListener("click", () => resetWindow());
els.torchBtn.addEventListener("click", () => toggleTorch());
els.copyBtn.addEventListener("click", () => copyLogs());

// --- Boot ---
log(`spike loaded -- ZXingBrowser keys: ${Object.keys(ZXingBrowser).slice(0, 10).join(",")}`);
log(`userAgent: ${navigator.userAgent}`);
permissionsPrecheck();
renderDiag();
