// Pure consecutive-streak debouncer for live barcode decode.
//
// Layer: scan helpers. No DOM, no ZXing, no async -- the live-mode
// callback in `views/scan.js` feeds every decoded text in, and gets back
// the accepted text once the same text decodes `threshold` times in a
// row. A *differing* decode resets the streak. Misses (frames with no
// barcode) never reach here -- the decoder only fires its callback on a
// successful decode -- so a brief unfocused stretch does not break a
// streak of otherwise-identical reads. Once accepted, every subsequent
// `pushAndCheck` returns that same text until `reset()` is called -- this
// prevents the live UI from re-firing on every frame after the match.
//
// Default threshold is 3 consecutive, per docs/plan-scan-tuning.md. This
// superseded the earlier 5-of-10 sliding window (plan-live-capture #18):
// cropping the decode region to the aim-box removed the background-label
// noise that the wider window existed to suppress, so the faster
// consecutive fast path is safe.

export class FrameDebouncer {
  constructor(threshold = 3) {
    this.threshold = threshold;
    this._lastText = null;
    this._count = 0;
    this._accepted = null;
  }

  pushAndCheck(text) {
    if (this._accepted !== null) return this._accepted;

    if (text === this._lastText) {
      this._count += 1;
    } else {
      this._lastText = text;
      this._count = 1;
    }

    if (this._count >= this.threshold) {
      this._accepted = text;
      return text;
    }
    return null;
  }

  reset() {
    this._lastText = null;
    this._count = 0;
    this._accepted = null;
  }
}
