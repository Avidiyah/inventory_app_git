// Live-decoder reliability/speed experiment harness. Pairs with
// scan-test.html. Originally the Phase 1 spike (deleted in the Phase 3
// ship PR); restored and repurposed to measure the reliability/speed
// levers before they touch production. See docs/plan-live-capture.md.
//
// Difference from production (`views/scan.js` + `scan/barcode-decoder.js`):
// production uses ZXing's `decodeFromStream`, which owns its own canvas
// and only surfaces SUCCESSFUL decodes. That hides two things this
// harness needs to measure: the per-frame decode-success RATE, and the
// effect of decoding only a cropped region. So this harness drives its
// own requestAnimationFrame loop, draws each frame (optionally cropped to
// the aim-box) into a scratch canvas, and decodes via `decodeFromCanvas`,
// which throws NotFoundException on a miss -- letting us count attempts
// vs hits directly.
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

// DecodeHintType enum values (not exported on the UMD global; mirrored
// from @zxing/library's DecodeHintType). POSSIBLE_FORMATS restricts the
// decoder to a format allow-list; TRY_HARDER trades speed for a more
// exhaustive search per frame.
const HINT_POSSIBLE_FORMATS = 2;
const HINT_TRY_HARDER = 3;

// The five formats the backend accepts in services/barcodes.py. Used both
// for the POSSIBLE_FORMATS hint and the "[supported]" annotation.
const BF = ZXingBrowser.BarcodeFormat;
const SUPPORTED_BARCODE_FORMATS = [BF.UPC_A, BF.UPC_E, BF.EAN_13, BF.EAN_8, BF.CODE_128];
const SUPPORTED_FORMAT_NAMES = new Set(["UPC_A", "UPC_E", "EAN_13", "EAN_8", "CODE_128"]);

// --- DOM handles ---
const els = {
  video: document.getElementById("scan-test-video"),
  canvas: document.getElementById("scan-test-canvas"),
  aimbox: document.getElementById("scan-test-aimbox"),
  startBtn: document.getElementById("scan-test-start-btn"),
  stopBtn: document.getElementById("scan-test-stop-btn"),
  resetBtn: document.getElementById("scan-test-reset-window-btn"),
  torchBtn: document.getElementById("scan-test-torch-btn"),
  copyBtn: document.getElementById("scan-test-copy-logs-btn"),
  phone: document.getElementById("scan-test-phone"),
  conditions: document.getElementById("scan-test-conditions"),
  log: document.getElementById("scan-test-log"),
  // experiment knobs
  expFormats: document.getElementById("experiment-formats"),
  expCrop: document.getElementById("experiment-crop"),
  expTryHarder: document.getElementById("experiment-tryharder"),
  // diagnostics
  state: document.getElementById("diag-state"),
  config: document.getElementById("diag-config"),
  resolution: document.getElementById("diag-resolution"),
  facing: document.getElementById("diag-facing"),
  torch: document.getElementById("diag-torch"),
  focus: document.getElementById("diag-focus"),
  region: document.getElementById("diag-region"),
  attempts: document.getElementById("diag-attempts"),
  success: document.getElementById("diag-success"),
  latency: document.getElementById("diag-latency"),
  latest: document.getElementById("diag-latest"),
  window: document.getElementById("diag-window"),
  accepted: document.getElementById("diag-accepted"),
  tta: document.getElementById("diag-tta"),
};

// --- Tunables ---
const WINDOW_SIZE = 10;
const ACCEPT_THRESHOLD = 5; // 5-of-10 window mode
const CONSECUTIVE_THRESHOLD = 3; // consecutive mode
const SAMPLES = 30; // rolling samples for attempts/sec, latency, success rate
// Aim-box geometry, in fractions of the video frame. Mirrors the CSS box
// in scan-test.html (80% width, 3:1 aspect, centred) so the cropped
// decode region matches what the user sees.
const AIMBOX_WIDTH_FRAC = 0.8;
const AIMBOX_ASPECT = 3; // width : height
const LOG_MAX_LINES = 200;

// --- State ---
const state = {
  reader: null,
  ctx: els.canvas.getContext("2d", { willReadFrequently: true }),
  stream: null,
  videoTrack: null,
  cameraState: "idle",
  startBtnLock: false,
  rafId: null,

  // debounce
  window: [], // last N decoded texts (hits only)
  consecutiveText: null,
  consecutiveCount: 0,
  accepted: null,

  // instrumentation
  startTimestamp: null,
  attemptTimestamps: [], // wall-clock per decode attempt (hit or miss)
  attemptLatencies: [], // ms spent inside decodeFromCanvas per attempt
  attemptOutcomes: [], // booleans: true = hit, false = miss
  lastRegion: null,

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

// --- Experiment config readers ---
function cfgFormatsRestricted() {
  return els.expFormats.checked;
}
function cfgCrop() {
  return els.expCrop.checked;
}
function cfgTryHarder() {
  return els.expTryHarder.checked;
}
function cfgResolution() {
  const checked = document.querySelector('input[name="experiment-res"]:checked');
  return checked && checked.value === "720" ? { width: 1280, height: 720 } : { width: 1920, height: 1080 };
}
function cfgDebounceMode() {
  const checked = document.querySelector('input[name="experiment-debounce"]:checked');
  return checked ? checked.value : "window";
}
function configSummary() {
  const res = cfgResolution();
  return [
    cfgFormatsRestricted() ? "formats:5" : "formats:all",
    cfgCrop() ? "crop:on" : "crop:off",
    cfgTryHarder() ? "tryHarder:on" : "tryHarder:off",
    `res:${res.height}p`,
    `debounce:${cfgDebounceMode() === "consecutive" ? CONSECUTIVE_THRESHOLD + "-consec" : ACCEPT_THRESHOLD + "-of-" + WINDOW_SIZE}`,
  ].join("  ");
}

// --- Reader construction (format + TRY_HARDER hints) ---
// Rebuilt on Start and whenever the format/TRY_HARDER toggles change,
// so the next decode attempt uses the new hints without a camera restart.
function buildReader() {
  const hints = new Map();
  if (cfgFormatsRestricted()) hints.set(HINT_POSSIBLE_FORMATS, SUPPORTED_BARCODE_FORMATS);
  if (cfgTryHarder()) hints.set(HINT_TRY_HARDER, true);
  state.reader = new ZXingBrowser.BrowserMultiFormatReader(hints);
  log(`reader built: ${configSummary()}`);
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

// --- Crop geometry ---
// Returns the source rectangle (in intrinsic video pixels) the decoder
// should read this frame. Crop on -> the aim-box region; crop off -> the
// whole frame.
function decodeRegion() {
  const vw = els.video.videoWidth;
  const vh = els.video.videoHeight;
  if (!cfgCrop()) return { sx: 0, sy: 0, sw: vw, sh: vh };
  const sw = Math.round(vw * AIMBOX_WIDTH_FRAC);
  const sh = Math.round(sw / AIMBOX_ASPECT);
  const sx = Math.round((vw - sw) / 2);
  const sy = Math.round((vh - sh) / 2);
  return { sx, sy, sw, sh };
}

// --- Decode loop (requestAnimationFrame-driven) ---
function tick() {
  if (state.cameraState !== "streaming") return;
  const vw = els.video.videoWidth;
  const vh = els.video.videoHeight;
  if (!vw || !vh) {
    state.rafId = requestAnimationFrame(tick);
    return; // metadata not ready yet
  }

  const region = decodeRegion();
  state.lastRegion = region;
  if (els.canvas.width !== region.sw) els.canvas.width = region.sw;
  if (els.canvas.height !== region.sh) els.canvas.height = region.sh;
  state.ctx.drawImage(
    els.video,
    region.sx, region.sy, region.sw, region.sh,
    0, 0, region.sw, region.sh,
  );

  const t0 = performance.now();
  let result = null;
  try {
    result = state.reader.decodeFromCanvas(els.canvas);
  } catch (_err) {
    // NotFoundException on a miss is expected during normal scanning.
    result = null;
  }
  const latency = performance.now() - t0;

  recordAttempt(latency, !!result);
  if (result) onHit(result);

  renderDiag();
  state.rafId = requestAnimationFrame(tick);
}

// --- Instrumentation bookkeeping ---
function recordAttempt(latency, isHit) {
  const now = performance.now();
  state.attemptTimestamps.push(now);
  if (state.attemptTimestamps.length > SAMPLES) state.attemptTimestamps.shift();
  state.attemptLatencies.push(latency);
  if (state.attemptLatencies.length > SAMPLES) state.attemptLatencies.shift();
  state.attemptOutcomes.push(isHit);
  if (state.attemptOutcomes.length > SAMPLES) state.attemptOutcomes.shift();
}

// --- Successful decode handling + debounce ---
function onHit(result) {
  const text = result.getText();
  const format = formatName(result.getBarcodeFormat());
  const supported = SUPPORTED_FORMAT_NAMES.has(format);
  els.latest.textContent = `${text} (${format})${supported ? " [supported]" : " [UNSUPPORTED]"}`;

  // Rolling window (for 5-of-10 mode + display).
  state.window.push(text);
  if (state.window.length > WINDOW_SIZE) state.window.shift();

  // Consecutive streak (for fast-path mode). A differing hit resets the
  // streak; misses between identical hits do NOT (focus flicker tolerance).
  if (text === state.consecutiveText) {
    state.consecutiveCount += 1;
  } else {
    state.consecutiveText = text;
    state.consecutiveCount = 1;
  }

  log(`hit text="${text}" format=${format} supported=${supported}`);

  if (state.accepted) return;
  const accepted = checkAccept();
  if (accepted) {
    state.accepted = accepted.text;
    const tta = state.startTimestamp != null
      ? (performance.now() - state.startTimestamp).toFixed(0) + " ms"
      : "n/a";
    els.accepted.textContent = `${accepted.text}  (${accepted.reason})`;
    els.tta.textContent = tta;
    log(`ACCEPTED "${accepted.text}" after ${tta} (${accepted.reason})`, "accept");
  }
}

// Returns { text, reason } when the current debounce mode is satisfied,
// else null.
function checkAccept() {
  if (cfgDebounceMode() === "consecutive") {
    if (state.consecutiveCount >= CONSECUTIVE_THRESHOLD) {
      return { text: state.consecutiveText, reason: `consecutive=${state.consecutiveCount}` };
    }
    return null;
  }
  const counts = new Map();
  for (const t of state.window) {
    const next = (counts.get(t) || 0) + 1;
    if (next >= ACCEPT_THRESHOLD) return { text: t, reason: `count=${next}/${WINDOW_SIZE}` };
    counts.set(t, next);
  }
  return null;
}

// --- Diagnostics renderer ---
function renderDiag() {
  els.config.textContent = configSummary();

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

  // Decode region (px) and what fraction of the frame it is.
  if (state.lastRegion && els.video.videoWidth) {
    const r = state.lastRegion;
    const fullPx = els.video.videoWidth * els.video.videoHeight;
    const regionPx = r.sw * r.sh;
    const pct = fullPx > 0 ? ((regionPx / fullPx) * 100).toFixed(0) : "?";
    els.region.textContent = `${r.sw} x ${r.sh}  (${pct}% of frame)`;
  } else {
    els.region.textContent = "—";
  }

  // Attempts/sec over the rolling sample window.
  if (state.attemptTimestamps.length >= 2) {
    const first = state.attemptTimestamps[0];
    const last = state.attemptTimestamps[state.attemptTimestamps.length - 1];
    const seconds = (last - first) / 1000;
    const rate = seconds > 0 ? (state.attemptTimestamps.length - 1) / seconds : 0;
    els.attempts.textContent = rate.toFixed(1);
  } else {
    els.attempts.textContent = "—";
  }

  // Decode success rate = hits / attempts over the rolling window.
  if (state.attemptOutcomes.length > 0) {
    const hits = state.attemptOutcomes.reduce((a, b) => a + (b ? 1 : 0), 0);
    const total = state.attemptOutcomes.length;
    const pct = ((hits / total) * 100).toFixed(0);
    els.success.textContent = `${pct}%  (${hits}/${total})`;
  } else {
    els.success.textContent = "—";
  }

  // Mean attempt latency (time inside decodeFromCanvas, hits + misses).
  if (state.attemptLatencies.length > 0) {
    const sum = state.attemptLatencies.reduce((a, b) => a + b, 0);
    els.latency.textContent = `${(sum / state.attemptLatencies.length).toFixed(1)} ms`;
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

// --- Start ---
async function start() {
  if (state.startBtnLock) return;
  state.startBtnLock = true;
  try {
    setCameraState("requesting");

    const res = cfgResolution();
    const constraints = {
      video: {
        facingMode: { ideal: "environment" },
        width: { ideal: res.width },
        height: { ideal: res.height },
        // Request continuous autofocus up front. Android Chrome/Edge
        // default to a single AF pass at stream start and lock; on iOS
        // Safari this key is unrecognised and silently ignored. Setting
        // it here (as a basic best-effort constraint, not under
        // `advanced`) is more reliable than calling applyConstraints
        // after the stream is already running.
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

    // Attach the stream to the preview <video> ourselves (production uses
    // ZXing's decodeFromStream for this; the manual loop does it directly).
    els.video.srcObject = stream;
    try {
      await els.video.play();
    } catch (err) {
      log(`video.play() threw: ${err.name} -- ${err.message}`, "warn");
    }

    els.aimbox.hidden = false;
    buildReader();
    state.startTimestamp = performance.now();
    setCameraState("streaming");
    log(`streaming started: ${configSummary()}`);
    state.rafId = requestAnimationFrame(tick);
  } finally {
    state.startBtnLock = false;
  }
}

// --- Stop ---
function stop() {
  if (state.cameraState === "idle") return;
  setCameraState("stopping");

  if (state.rafId != null) {
    cancelAnimationFrame(state.rafId);
    state.rafId = null;
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
  state.stream = null;
  state.videoTrack = null;
  state.lastRegion = null;
  state.attemptTimestamps = [];
  state.attemptLatencies = [];
  state.attemptOutcomes = [];
  state.torchOn = false;
  els.torchBtn.textContent = "Torch: off";
  els.aimbox.hidden = true;

  setCameraState("idle");
}

// --- Reset rolling window ---
function resetWindow() {
  state.window = [];
  state.consecutiveText = null;
  state.consecutiveCount = 0;
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
  const hits = state.attemptOutcomes.reduce((a, b) => a + (b ? 1 : 0), 0);
  const snapshot = {
    capturedAt: new Date().toISOString(),
    userAgent: navigator.userAgent,
    phone: els.phone.value || "(unset)",
    conditions: els.conditions.value || "(unset)",
    experimentConfig: configSummary(),
    cameraState: state.cameraState,
    resolutionGranted: els.resolution.textContent,
    facingModeGranted: els.facing.textContent,
    torchCapability: els.torch.textContent,
    decodeRegion: els.region.textContent,
    attemptsPerSec: els.attempts.textContent,
    decodeSuccessRate: els.success.textContent,
    successCount: `${hits}/${state.attemptOutcomes.length}`,
    meanAttemptLatency: els.latency.textContent,
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

// Format / TRY_HARDER toggles rebuild the reader live (no restart needed).
els.expFormats.addEventListener("change", () => {
  if (state.cameraState === "streaming") buildReader();
});
els.expTryHarder.addEventListener("change", () => {
  if (state.cameraState === "streaming") buildReader();
});
// Crop applies on the next tick automatically; just log + refresh.
els.expCrop.addEventListener("change", () => {
  log(`crop -> ${cfgCrop() ? "on" : "off"}`);
  renderDiag();
});
// Debounce-mode change invalidates any standing accept; reset cleanly.
for (const r of document.querySelectorAll('input[name="experiment-debounce"]')) {
  r.addEventListener("change", () => {
    log(`debounce mode -> ${cfgDebounceMode()}`);
    resetWindow();
  });
}
// Resolution change only takes effect on restart; remind the user.
for (const r of document.querySelectorAll('input[name="experiment-res"]')) {
  r.addEventListener("change", () => {
    log(`resolution -> ${cfgResolution().height}p (Stop + Start to apply)`, "warn");
  });
}

// --- Boot ---
log(`harness loaded -- ZXingBrowser keys: ${Object.keys(ZXingBrowser).slice(0, 10).join(",")}`);
log(`userAgent: ${navigator.userAgent}`);
permissionsPrecheck();
renderDiag();
