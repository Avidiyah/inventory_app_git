// ZXing wrapper. The only file in the codebase that names
// `window.ZXingBrowser`. Lets a future Web Worker / different decoder
// swap in behind the same public API. See docs/plan-live-capture.md
// decision #7 (amended in Phase 2) and the Phase 2 plan.
//
// Lifecycle ownership: this class does NOT call `getUserMedia` and
// does NOT stop `MediaStreamTrack`s. The caller (`views/scan.js`)
// owns stream acquisition and release. `stop()` only halts ZXing's
// decode loop, leaving the stream live so the caller can hand it
// straight back to `start()` after a transient pause.

export class BarcodeDecoder {
  constructor() {
    this._reader = null;
    this._controls = null;
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

  // Begin continuous decoding against an already-acquired MediaStream.
  // Idempotent: a second call while running stops the existing decode
  // first so the caller can re-attach to a fresh stream without
  // double-bookkeeping.
  //
  //   videoEl  - HTMLVideoElement to attach the stream to
  //   stream   - MediaStream from getUserMedia (caller-owned)
  //   onDecode - (text: string, format: string) => void, fired once
  //              per successful decode (ZXing NotFoundException
  //              between codes is swallowed here).
  async start(videoEl, stream, onDecode) {
    if (!window.ZXingBrowser) {
      throw new Error("ZXingBrowser global missing");
    }
    if (this._controls) this.stop();

    this._reader = new window.ZXingBrowser.BrowserMultiFormatReader();
    this._controls = await this._reader.decodeFromStream(stream, videoEl, (result, _err) => {
      if (!result) return;
      onDecode(result.getText(), String(result.getBarcodeFormat()));
    });
  }

  // Halt the decode loop. Safe from any state. Does NOT stop the
  // MediaStream tracks; the caller owns the stream.
  stop() {
    if (this._controls && typeof this._controls.stop === "function") {
      try {
        this._controls.stop();
      } catch (_err) {
        // ZXing occasionally throws if the underlying video element
        // was already torn down; nothing actionable here.
      }
    }
    this._controls = null;
    this._reader = null;
  }
}
