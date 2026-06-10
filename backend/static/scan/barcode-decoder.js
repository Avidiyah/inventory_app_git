// ZXing wrapper. The only file in the codebase that names
// `window.ZXingBrowser`. Lets a future Web Worker / different decoder
// swap in behind the same public API. See docs/plan-live-capture.md
// decision #7 and docs/plan-scan-tuning.md.
//
// Decode model: a manual `requestAnimationFrame` loop that draws the
// aim-box region of the video into an offscreen canvas and decodes it
// via ZXing's `decodeFromCanvas` (synchronous; throws NotFoundException
// on a miss). This replaced ZXing's `decodeFromStream` so we can:
//   - crop to the aim-box (faster decode + no background-label misreads),
//   - apply the TRY_HARDER hint affordably (smaller region),
//   - measure/own the frame cadence.
// The winning configuration was validated on the fleet via
// backend/static/scan-test.html. See docs/plan-scan-tuning.md.
//
// Lifecycle ownership: this class does NOT call `getUserMedia` and does
// NOT stop `MediaStreamTrack`s. The caller (`views/scan.js`) owns stream
// acquisition and release. `start()` attaches the stream to the video
// element (ZXing used to do this); `stop()` only halts the decode loop,
// leaving the stream live and attached so the caller can hand it straight
// back to `start()` after a transient pause.

// DecodeHintType enum values (not exported on the UMD global; mirrored
// from @zxing/library's DecodeHintType). TRY_HARDER trades a little speed
// for a more exhaustive search per frame -- affordable here because the
// cropped region is small. No POSSIBLE_FORMATS hint: the warehouse uses
// many symbologies, so the decoder stays all-formats (see plan-scan-tuning).
const HINT_TRY_HARDER = 3;

// Aim-box geometry as fractions of the video frame. MUST stay in sync
// with `.scan-aimbox` in backend/static/styles.css (width: 80%;
// aspect-ratio: 3 / 1; centred). `.scan-video` is width:100% with no
// object-fit, so the displayed frame is the full intrinsic frame scaled
// -- 80% of display width equals 80% of intrinsic width, and this maps
// straight to intrinsic pixels.
const AIMBOX_WIDTH_FRAC = 0.8;
const AIMBOX_ASPECT = 3; // width : height

export class BarcodeDecoder {
  constructor() {
    this._reader = null;
    this._canvas = null;
    this._ctx = null;
    this._video = null;
    this._onDecode = null;
    this._running = false;
    this._rafId = null;
  }

  // True if live decoding is viable in this browser/state. Does NOT
  // request the camera; only checks API existence and explicit deny.
  static async supports() {
    if (!navigator.mediaDevices || typeof navigator.mediaDevices.getUserMedia !== "function") {
      return false;
    }
    if (!window.ZXingBrowser) return false;
    if (navigator.permissions && typeof navigator.permissions.query === "function") {
      try {
        const status = await navigator.permissions.query({ name: "camera" });
        if (status && status.state === "denied") return false;
      } catch (_err) {
        // Some browsers throw on `name: "camera"`; treat as "unknown",
        // which is permissive -- the actual `getUserMedia` call will
        // surface the real denial if any.
      }
    }
    return true;
  }

  // True ONLY when camera permission is already granted, so a caller can
  // start the camera without ever triggering a permission prompt. Returns
  // false when the Permissions API is missing or rejects a `camera` query
  // (Firefox, older Safari) -- callers must then fall back to a user gesture.
  static async permissionGranted() {
    if (!navigator.permissions || typeof navigator.permissions.query !== "function") {
      return false;
    }
    try {
      const status = await navigator.permissions.query({ name: "camera" });
      return !!status && status.state === "granted";
    } catch (_err) {
      return false;
    }
  }

  // Begin continuous decoding against an already-acquired MediaStream.
  // Idempotent: a second call while running stops the existing loop first
  // so the caller can re-attach to a fresh stream without double-running.
  //
  //   videoEl  - HTMLVideoElement to attach the stream to and read frames from
  //   stream   - MediaStream from getUserMedia (caller-owned)
  //   onDecode - (text: string, format: string) => void, fired once per
  //              successful decode (NotFoundException misses are swallowed).
  async start(videoEl, stream, onDecode) {
    if (!window.ZXingBrowser) {
      throw new Error("ZXingBrowser global missing");
    }
    if (this._running) this.stop();

    // Build the reader with our hints. TRY_HARDER on; no format restriction.
    const hints = new Map();
    hints.set(HINT_TRY_HARDER, true);
    this._reader = new window.ZXingBrowser.BrowserMultiFormatReader(hints);

    // Offscreen scratch canvas -- ZXing's own decodeFromStream uses an
    // in-memory canvas too, so a detached one decodes fine on iOS Safari.
    this._canvas = document.createElement("canvas");
    this._ctx = this._canvas.getContext("2d", { willReadFrequently: true });

    this._video = videoEl;
    this._onDecode = onDecode;

    // Attach the stream to the preview element (ZXing used to do this).
    videoEl.srcObject = stream;
    try {
      await videoEl.play();
    } catch (_err) {
      // Autoplay attributes (playsinline muted autoplay) usually cover
      // this; an explicit play() rejection is non-fatal -- the loop guards
      // on videoWidth until frames arrive.
    }

    this._running = true;
    this._rafId = requestAnimationFrame(() => this._tick());
  }

  // One decode attempt: crop the aim-box region into the canvas and decode.
  _tick() {
    if (!this._running) return;

    const video = this._video;
    const vw = video ? video.videoWidth : 0;
    const vh = video ? video.videoHeight : 0;
    if (!vw || !vh) {
      // Metadata not ready yet; try again next frame.
      this._rafId = requestAnimationFrame(() => this._tick());
      return;
    }

    const sw = Math.round(vw * AIMBOX_WIDTH_FRAC);
    const sh = Math.round(sw / AIMBOX_ASPECT);
    const sx = Math.round((vw - sw) / 2);
    const sy = Math.round((vh - sh) / 2);
    if (this._canvas.width !== sw) this._canvas.width = sw;
    if (this._canvas.height !== sh) this._canvas.height = sh;
    this._ctx.drawImage(video, sx, sy, sw, sh, 0, 0, sw, sh);

    let result = null;
    try {
      result = this._reader.decodeFromCanvas(this._canvas);
    } catch (_err) {
      // NotFoundException on a miss is expected during normal scanning.
      result = null;
    }

    if (result && this._onDecode) {
      this._onDecode(result.getText(), String(result.getBarcodeFormat()));
    }

    // Re-check `_running`: onDecode may have triggered stop() (accept path).
    if (this._running) {
      this._rafId = requestAnimationFrame(() => this._tick());
    }
  }

  // Halt the decode loop. Safe from any state. Does NOT stop the
  // MediaStream tracks or detach the video; the caller owns the stream.
  stop() {
    this._running = false;
    if (this._rafId != null) {
      cancelAnimationFrame(this._rafId);
      this._rafId = null;
    }
    this._reader = null;
    this._canvas = null;
    this._ctx = null;
    this._video = null;
    this._onDecode = null;
  }
}
