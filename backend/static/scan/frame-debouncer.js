// Pure rolling-window debouncer for live barcode decode.
//
// Layer: scan helpers. No DOM, no ZXing, no async -- the live-mode
// callback in `views/scan.js` feeds every decoded text in, and gets
// back the accepted text once any single text appears `threshold`
// times within the last `windowSize` pushes. Once accepted, every
// subsequent `pushAndCheck` returns that same text until `reset()`
// is called -- this prevents the live UI from re-firing on every
// frame after the user has been shown the match.
//
// Default ratio is 5-of-10, per docs/plan-live-capture.md decision #18.

export class FrameDebouncer {
  constructor(windowSize = 10, threshold = 5) {
    this.windowSize = windowSize;
    this.threshold = threshold;
    this._window = [];
    this._accepted = null;
  }

  pushAndCheck(text) {
    if (this._accepted !== null) return this._accepted;

    this._window.push(text);
    if (this._window.length > this.windowSize) this._window.shift();

    const counts = new Map();
    for (const t of this._window) {
      const next = (counts.get(t) || 0) + 1;
      if (next >= this.threshold) {
        this._accepted = t;
        return t;
      }
      counts.set(t, next);
    }
    return null;
  }

  reset() {
    this._window = [];
    this._accepted = null;
  }
}
