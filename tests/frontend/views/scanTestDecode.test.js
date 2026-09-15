// Characterization coverage for `scan-test.js`'s decode loop: the
// requestAnimationFrame tick, the aim-box crop, the rolling instrumentation
// the diagnostics table reads, and the two debounce modes.
//
// A "frame" is `raf.flush()` -- the fake rAF runs everything queued at call
// time as one frame, and the tick re-queues itself into the next. The clock is
// `vi.advanceTimersByTime`, which moves `performance.now` under Vitest 5's
// fake timers, so attempts-per-second, mean latency and time-to-accept are
// exact rather than approximate (`helpers/scanTest.js`).
//
// The page's own surface -- boot, knobs, start/stop, torch, copy -- is
// `scanTest.test.js`.

import { afterEach, describe, expect, it, vi } from "vitest";
import {
  BARCODE_FORMAT, DEFAULT_SETTINGS, click, decodeNext, logLines, mountScanTest,
  restoreScanTest, startStreaming,
} from "../helpers/scanTest.js";

afterEach(async () => {
  if (vi.isFakeTimers()) {
    await vi.runOnlyPendingTimersAsync();
    expect(vi.getTimerCount()).toBe(0);
  }
  restoreScanTest();
});

// The aim-box crop for a 1280x720 frame: 80 % of the width, 3:1, centred.
const CROP_720P = { sx: 128, sy: 190, sw: 1024, sh: 341 };

describe("the frame loop", () => {
  it("re-queues without drawing until the video reports an intrinsic size", async () => {
    const m = await mountScanTest({ video: { width: 0, height: 0 } });
    await startStreaming(m);
    m.raf.flush();
    expect(m.canvas.ctx.drawImage).not.toHaveBeenCalled();
    expect(m.zxing.reader.decodeFromCanvas).not.toHaveBeenCalled();
    expect(m.raf.pending()).toBe(1);
    expect(m.els.region.textContent).toBe("—");
  });

  it("crops to the aim box and draws it at the canvas origin", async () => {
    const m = await mountScanTest();
    await startStreaming(m);
    m.raf.flush();
    const { sx, sy, sw, sh } = CROP_720P;
    expect(m.canvas.ctx.drawImage).toHaveBeenCalledWith(m.els.video, sx, sy, sw, sh, 0, 0, sw, sh);
    expect(m.els.canvas.width).toBe(sw);
    expect(m.els.canvas.height).toBe(sh);
  });

  it("rounds the crop on an odd frame size", async () => {
    const m = await mountScanTest({ video: { width: 999, height: 501 } });
    await startStreaming(m);
    m.raf.flush();
    // sw = round(799.2) = 799; sh = round(266.33) = 266;
    // sx = round(100) = 100; sy = round(117.5) = 118.
    expect(m.canvas.ctx.drawImage).toHaveBeenCalledWith(m.els.video, 100, 118, 799, 266, 0, 0, 799, 266);
  });

  it("crop off reads the whole frame", async () => {
    const m = await mountScanTest();
    m.els.expCrop.checked = false;
    await startStreaming(m);
    m.raf.flush();
    expect(m.canvas.ctx.drawImage).toHaveBeenCalledWith(m.els.video, 0, 0, 1280, 720, 0, 0, 1280, 720);
    expect(m.els.region.textContent).toBe("1280 x 720  (100% of frame)");
  });

  it("resizes the canvas only when the region changes", async () => {
    const m = await mountScanTest();
    await startStreaming(m);
    const widths = [];
    let width = m.els.canvas.width;
    Object.defineProperty(m.els.canvas, "width", {
      configurable: true,
      get: () => width,
      set: (value) => { width = value; widths.push(value); },
    });
    m.raf.flush(3);
    expect(widths).toEqual([CROP_720P.sw]);          // the first frame only

    m.els.expCrop.checked = false;                    // a new region
    m.raf.flush();
    expect(widths).toEqual([CROP_720P.sw, 1280]);
  });

  it("a miss records an attempt and no hit", async () => {
    const m = await mountScanTest();
    await startStreaming(m);
    m.raf.flush();
    expect(m.zxing.reader.decodeFromCanvas).toHaveBeenCalledWith(m.els.canvas);
    expect(m.els.success.textContent).toBe("0%  (0/1)");
    expect(m.els.latest.textContent).toBe("—");
    expect(m.els.window.textContent).toBe("(empty)");
  });

  it("a hit records the decode and logs it", async () => {
    const m = await mountScanTest();
    await startStreaming(m);
    decodeNext(m, "0123456789012", BARCODE_FORMAT.EAN_13);
    m.raf.flush();
    expect(m.els.latest.textContent).toBe("0123456789012 (EAN_13) [supported]");
    expect(m.els.success.textContent).toBe("100%  (1/1)");
    expect(logLines(m.els)).toContain('[info] hit text="0123456789012" format=EAN_13 supported=true');
  });
});

describe("the diagnostics table", () => {
  it("reports the granted resolution, facing mode and focus from the track", async () => {
    const m = await mountScanTest({ media: { capabilities: { focusMode: ["manual", "continuous"] } } });
    await startStreaming(m);
    m.raf.flush();
    expect(m.els.resolution.textContent).toBe("1280 x 720");
    expect(m.els.facing.textContent).toBe("environment");
    expect(m.els.focus.textContent).toBe("continuous / manual,continuous");
    expect(m.els.region.textContent).toBe("1024 x 341  (38% of frame)");
  });

  it("names the sides it was not given", async () => {
    const m = await mountScanTest({ media: { settings: { height: 720 } } });
    await startStreaming(m);
    m.raf.flush();
    expect(m.els.resolution.textContent).toBe("? x 720");
    expect(m.els.facing.textContent).toBe("(not reported)");
    expect(m.els.focus.textContent).toBe("(not reported) / (not exposed)");
  });

  it("a getCapabilities that throws leaves the capable half unknown", async () => {
    const m = await mountScanTest({ media: { getCapabilities: () => { throw new Error("not implemented"); } } });
    await startStreaming(m);
    m.raf.flush();
    expect(m.els.focus.textContent).toBe("continuous / unknown");
  });

  it("attempts per second come from the spacing of the last frames", async () => {
    const m = await mountScanTest();
    await startStreaming(m);
    m.raf.flush();
    expect(m.els.attempts.textContent).toBe("—");        // one sample is not a rate
    vi.advanceTimersByTime(100);
    m.raf.flush();
    expect(m.els.attempts.textContent).toBe("10.0");
  });

  it("mean latency is the time spent inside the decoder", async () => {
    const m = await mountScanTest();
    await startStreaming(m);
    m.zxing.reader.decodeFromCanvas.mockImplementation(() => {
      vi.advanceTimersByTime(7);
      throw new Error("NotFoundException");
    });
    m.raf.flush();
    expect(m.els.latency.textContent).toBe("7.0 ms");
  });

  it("every rolling list is capped at 30 samples", async () => {
    const m = await mountScanTest();
    await startStreaming(m);
    m.raf.flush(31);                                     // 31 misses
    decodeNext(m, "A");
    m.raf.flush();                                       // one hit, 32 attempts
    expect(m.els.success.textContent).toBe("3%  (1/30)");
  });

  it("counts the rolling window by text", async () => {
    const m = await mountScanTest();
    await startStreaming(m);
    decodeNext(m, "A");
    m.raf.flush(2);
    decodeNext(m, "B");
    m.raf.flush();
    expect(m.els.window.textContent).toBe("2× A  |  1× B");
  });
});

describe("hit annotation", () => {
  const cases = [
    [BARCODE_FORMAT.UPC_A, "UPC_A", true],
    [BARCODE_FORMAT.CODE_128, "CODE_128", true],
    [11, "QR_CODE", false],
    [99, "UNKNOWN(99)", false],
  ];
  for (const [format, name, supported] of cases) {
    it(`${name} is ${supported ? "supported" : "flagged UNSUPPORTED"}`, async () => {
      const m = await mountScanTest();
      await startStreaming(m);
      decodeNext(m, "X1", format);
      m.raf.flush();
      expect(m.els.latest.textContent).toBe(`X1 (${name})${supported ? " [supported]" : " [UNSUPPORTED]"}`);
    });
  }
});

describe("the 5-of-10 window", () => {
  it("holds the last ten hits only", async () => {
    const m = await mountScanTest();
    await startStreaming(m);
    decodeNext(m, "A");
    m.raf.flush(4);
    decodeNext(m, "B");
    m.raf.flush(8);                                      // 12 hits, window of 10
    expect(m.els.window.textContent).toBe("2× A  |  8× B");
  });

  it("accepts on the fifth identical hit and reports the time it took", async () => {
    const m = await mountScanTest();
    await startStreaming(m);
    decodeNext(m, "0123456789012");
    for (let i = 0; i < 5; i += 1) {
      vi.advanceTimersByTime(40);
      m.raf.flush();
    }
    expect(m.els.accepted.textContent).toBe("0123456789012  (count=5/10)");
    expect(m.els.tta.textContent).toBe("200 ms");
    expect(logLines(m.els)).toContain('[accept] ACCEPTED "0123456789012" after 200 ms (count=5/10)');
  });

  it("the accept is sticky: later hits move `latest` but not `accepted`", async () => {
    const m = await mountScanTest();
    await startStreaming(m);
    decodeNext(m, "A");
    m.raf.flush(5);
    expect(m.els.accepted.textContent).toBe("A  (count=5/10)");
    decodeNext(m, "B");
    m.raf.flush(6);
    expect(m.els.latest.textContent).toBe("B (CODE_128) [supported]");
    expect(m.els.accepted.textContent).toBe("A  (count=5/10)");
  });

  it("four of one text and four of another accept neither", async () => {
    const m = await mountScanTest();
    await startStreaming(m);
    decodeNext(m, "A");
    m.raf.flush(4);
    decodeNext(m, "B");
    m.raf.flush(4);
    expect(m.els.accepted.textContent).toBe("—");
    expect(m.els.tta.textContent).toBe("—");
  });
});

describe("3-consecutive mode", () => {
  const consecutive = (m) => { m.els.debounce("consecutive").checked = true; };

  it("accepts on the third hit in a row", async () => {
    const m = await mountScanTest();
    await startStreaming(m);
    consecutive(m);
    decodeNext(m, "A");
    m.raf.flush(3);
    expect(m.els.accepted.textContent).toBe("A  (consecutive=3)");
  });

  it("a different text resets the streak", async () => {
    const m = await mountScanTest();
    await startStreaming(m);
    consecutive(m);
    decodeNext(m, "A");
    m.raf.flush(2);
    decodeNext(m, "B");
    m.raf.flush(1);
    expect(m.els.accepted.textContent).toBe("—");
    decodeNext(m, "A");
    m.raf.flush(2);
    expect(m.els.accepted.textContent).toBe("—");        // the streak restarted at B
    m.raf.flush(1);
    expect(m.els.accepted.textContent).toBe("A  (consecutive=3)");
  });

  it("misses between identical hits do NOT reset it -- focus flicker tolerance", async () => {
    const m = await mountScanTest();
    await startStreaming(m);
    consecutive(m);
    decodeNext(m, "A");
    m.raf.flush(2);
    decodeNext(m, null);
    m.raf.flush(5);
    decodeNext(m, "A");
    m.raf.flush(1);
    expect(m.els.accepted.textContent).toBe("A  (consecutive=3)");
  });
});

describe("resetting the window mid-stream", () => {
  it("clears the standing accept and lets the next one land", async () => {
    const m = await mountScanTest();
    await startStreaming(m);
    decodeNext(m, "A");
    vi.advanceTimersByTime(100);
    m.raf.flush(5);
    expect(m.els.accepted.textContent).toBe("A  (count=5/10)");

    await click(m.els.resetBtn);
    expect(m.els.accepted.textContent).toBe("—");
    expect(m.els.tta.textContent).toBe("—");
    expect(m.els.window.textContent).toBe("(empty)");

    decodeNext(m, "B");
    vi.advanceTimersByTime(60);
    m.raf.flush(5);
    // N-P7-CHARACTERIZED: the "n/a" branch of the time-to-accept is
    // unreachable. A hit requires `streaming`, and `resetWindow` re-stamps
    // `startTimestamp` in exactly that state -- so the clock is never null
    // when an accept reads it, and the accept is timed from the RESET, not
    // from Start.
    expect(m.els.accepted.textContent).toBe("B  (count=5/10)");
    expect(m.els.tta.textContent).toBe("60 ms");
  });
});
