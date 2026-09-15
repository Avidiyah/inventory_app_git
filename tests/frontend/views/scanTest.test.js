// Characterization coverage for scan-test.js -- the live-decoder experiment
// harness on its own unauthenticated page. Not the SPA: the module exports
// nothing, captures its elements at import and writes only to the DOM and its
// own log, so every assertion here is a DOM read, a log line or a spy call.
//
// This file owns the boot, the five knobs, the reader hints, the six-state
// camera machine, start/stop, torch, copy-logs and the two lifecycle
// listeners. The rAF decode loop and the debounce live in
// `scanTestDecode.test.js`.
//
// The clock is `vi.advanceTimersByTime`: Vitest 5's fake timers own
// `performance.now`, so the 500 ms focus retry and every measured duration
// share one clock (`helpers/scanTest.js`).

import { afterEach, describe, expect, it, vi } from "vitest";
import {
  BARCODE_FORMAT, DEFAULT_SETTINGS, click, logLines, mountScanTest, restoreScanTest,
  scanTrack, settle, setDocumentHidden, startStreaming,
} from "../helpers/scanTest.js";

afterEach(async () => {
  // The focus retry (500 ms) is the module's only timer and it self-clears;
  // run it out, then anything still armed is a leak.
  if (vi.isFakeTimers()) {
    await vi.runOnlyPendingTimersAsync();
    expect(vi.getTimerCount()).toBe(0);
  }
  restoreScanTest();
});

describe("boot", () => {
  it("without the ZXing UMD global: inserts the failure notice and the import rejects", async () => {
    await expect(mountScanTest({ zxing: false })).rejects.toThrow("ZXingBrowser global missing");
    const notice = document.body.firstElementChild;
    expect(notice.tagName).toBe("P");
    expect(notice.textContent).toContain("ZXing UMD failed to load");
    // Nothing else ran: no log, no element wiring.
    expect(document.getElementById("scan-test-log").textContent).toBe("");
  });

  it("logs the two boot lines and pre-checks the permission", async () => {
    const m = await mountScanTest({ permission: "granted" });
    expect(logLines(m.els)).toEqual([
      "[info] harness loaded -- ZXingBrowser keys: BrowserMultiFormatReader,BarcodeFormat",
      `[info] userAgent: ${navigator.userAgent}`,
      "[info] permissions.query(camera) -> granted",
    ]);
  });

  it("no Permissions API: says so and stays idle", async () => {
    const m = await mountScanTest({ permission: null });
    expect(logLines(m.els)).toContain(
      "[info] navigator.permissions unsupported; will rely on getUserMedia result",
    );
    expect(m.els.state.textContent).toBe("idle");
  });

  it("a denied permission blocks the camera before Start is ever pressed", async () => {
    const m = await mountScanTest({ permission: "denied" });
    expect(m.els.state.textContent).toBe("blocked");
    expect(logLines(m.els)).toContain(
      "[err] camera permission is denied. Re-enable via the address-bar lock icon.",
    );
  });

  it("a throwing permissions.query only warns", async () => {
    const m = await mountScanTest({ permission: "throws" });
    expect(logLines(m.els)).toContain(
      "[warn] permissions.query(camera) threw: camera is not a valid permission name",
    );
    expect(m.els.state.textContent).toBe("idle");
  });

  it("renders the diagnostics table with the config filled and everything else a dash", async () => {
    const m = await mountScanTest();
    expect(m.els.state.textContent).toBe("idle");
    expect(m.els.config.textContent).toBe("formats:5  crop:on  tryHarder:off  res:1080p  debounce:5-of-10");
    for (const key of ["resolution", "facing", "torch", "focus", "region", "attempts", "success", "latency", "latest", "accepted", "tta"]) {
      expect(m.els[key].textContent, key).toBe("—");
    }
    expect(m.els.window.textContent).toBe("(empty)");
  });
});

describe("the experiment config summary", () => {
  it("reads every knob", async () => {
    const m = await mountScanTest();
    const summary = () => {
      m.els.expCrop.dispatchEvent(new Event("change"));   // repaints via renderDiag
      return m.els.config.textContent;
    };
    m.els.expFormats.checked = false;
    m.els.expCrop.checked = false;
    m.els.expTryHarder.checked = true;
    m.els.res("720").checked = true;
    m.els.debounce("consecutive").checked = true;
    expect(summary()).toBe("formats:all  crop:off  tryHarder:on  res:720p  debounce:3-consec");
  });
});

describe("the reader and its hints", () => {
  const hintsOf = (m, call = 0) => m.zxing.ZXingBrowser.BrowserMultiFormatReader.mock.calls[call][0];

  it("built on Start with the five formats and no TRY_HARDER", async () => {
    const m = await mountScanTest();
    await startStreaming(m);
    const hints = hintsOf(m);
    expect(hints.get(2)).toEqual([BARCODE_FORMAT.UPC_A, BARCODE_FORMAT.UPC_E, BARCODE_FORMAT.EAN_13, BARCODE_FORMAT.EAN_8, BARCODE_FORMAT.CODE_128]);
    expect(hints.has(3)).toBe(false);
    expect(logLines(m.els)).toContain("[info] reader built: formats:5  crop:on  tryHarder:off  res:1080p  debounce:5-of-10");
  });

  it("unrestricted formats drop the hint; TRY_HARDER adds its own", async () => {
    const m = await mountScanTest();
    m.els.expFormats.checked = false;
    m.els.expTryHarder.checked = true;
    await startStreaming(m);
    const hints = hintsOf(m);
    expect(hints.has(2)).toBe(false);
    expect(hints.get(3)).toBe(true);
  });

  it("a formats or TRY_HARDER change rebuilds it mid-stream, with no camera restart", async () => {
    const m = await mountScanTest();
    await startStreaming(m);
    m.els.expTryHarder.checked = true;
    m.els.expTryHarder.dispatchEvent(new Event("change"));
    m.els.expFormats.checked = false;
    m.els.expFormats.dispatchEvent(new Event("change"));
    expect(m.zxing.ZXingBrowser.BrowserMultiFormatReader).toHaveBeenCalledTimes(3);
    expect(hintsOf(m, 2).has(2)).toBe(false);
    expect(m.media.getUserMedia).toHaveBeenCalledTimes(1);
  });

  it("the same change while idle builds nothing", async () => {
    const m = await mountScanTest();
    m.els.expTryHarder.checked = true;
    m.els.expTryHarder.dispatchEvent(new Event("change"));
    expect(m.zxing.ZXingBrowser.BrowserMultiFormatReader).not.toHaveBeenCalled();
  });
});

describe("the knobs that only log", () => {
  it("crop logs its new value and repaints the config", async () => {
    const m = await mountScanTest();
    m.els.expCrop.checked = false;
    m.els.expCrop.dispatchEvent(new Event("change"));
    expect(logLines(m.els).at(-1)).toBe("[info] crop -> off");
    expect(m.els.config.textContent).toContain("crop:off");
  });

  it("a debounce-mode change logs and resets the window", async () => {
    const m = await mountScanTest();
    m.els.debounce("consecutive").checked = true;
    m.els.debounce("consecutive").dispatchEvent(new Event("change"));
    expect(logLines(m.els).slice(-2)).toEqual([
      "[info] debounce mode -> consecutive",
      "[info] window reset",
    ]);
  });

  it("a resolution change warns that it needs a restart", async () => {
    const m = await mountScanTest();
    m.els.res("720").checked = true;
    m.els.res("720").dispatchEvent(new Event("change"));
    expect(logLines(m.els).at(-1)).toBe("[warn] resolution -> 720p (Stop + Start to apply)");
  });
});

// A getUserMedia the test resolves by hand, to hold the machine in
// `requesting` -- the one state no settled promise can be observed in.
function deferredCamera(m) {
  let release;
  const pending = new Promise((resolve) => { release = resolve; });
  m.media.getUserMedia.mockImplementation(() => pending);
  return () => { release(m.media.stream); return settle(); };
}

describe("the camera state machine", () => {
  const pill = (m) => [m.els.state.textContent, m.els.state.className];
  const buttons = (m) => [m.els.startBtn.disabled, m.els.stopBtn.disabled];

  it("idle: the pill is plain and only Stop is disabled", async () => {
    const m = await mountScanTest();
    expect(pill(m)).toEqual(["idle", "pill"]);
    expect(buttons(m)).toEqual([false, true]);
  });

  it("requesting: Start is disabled and Stop is NOT", async () => {
    const m = await mountScanTest();
    const release = deferredCamera(m);
    await click(m.els.startBtn);
    expect(pill(m)).toEqual(["requesting", "pill "]);
    expect(buttons(m)).toEqual([true, false]);
    await release();
  });

  it("streaming: the pill goes ok", async () => {
    const m = await mountScanTest();
    await startStreaming(m);
    expect(pill(m)).toEqual(["streaming", "pill ok"]);
    expect(buttons(m)).toEqual([true, false]);
  });

  it("error: the pill goes err and BOTH buttons are usable", async () => {
    const m = await mountScanTest({ media: { reject: Object.assign(new Error("no device"), { name: "NotFoundError" }) } });
    await click(m.els.startBtn);
    expect(pill(m)).toEqual(["error", "pill err"]);
    expect(buttons(m)).toEqual([false, false]);
  });

  it("blocked: the pill goes err and Stop is disabled", async () => {
    const m = await mountScanTest({ permission: "denied" });
    expect(pill(m)).toEqual(["blocked", "pill err"]);
    expect(buttons(m)).toEqual([false, true]);
  });

  it("stopping is passed through synchronously and shows only in the log", async () => {
    const m = await mountScanTest();
    await startStreaming(m);
    await click(m.els.stopBtn);
    expect(logLines(m.els).slice(-2)).toEqual([
      "[info] camera state -> stopping",
      "[info] camera state -> idle",
    ]);
    expect(pill(m)).toEqual(["idle", "pill "]);
  });
});

describe("start", () => {
  it("is reentrancy-locked: a second press while the first is in flight asks the camera once", async () => {
    const m = await mountScanTest();
    m.els.startBtn.click();
    // The button is disabled by `requesting`; re-enable it so the LOCK is the
    // only thing that can stop the second press, not the DOM.
    m.els.startBtn.disabled = false;
    m.els.startBtn.click();
    await settle();
    expect(m.media.getUserMedia).toHaveBeenCalledTimes(1);
  });

  it("asks for the rear camera at 1080p with continuous focus, and logs the constraints", async () => {
    const m = await mountScanTest();
    await startStreaming(m);
    const video = {
      facingMode: { ideal: "environment" },
      width: { ideal: 1920 },
      height: { ideal: 1080 },
      focusMode: { ideal: "continuous" },
    };
    expect(m.media.getUserMedia).toHaveBeenCalledWith({ video, audio: false });
    expect(logLines(m.els)).toContain(`[info] getUserMedia(${JSON.stringify(video)})`);
  });

  it("the 720p radio moves both dimensions", async () => {
    const m = await mountScanTest();
    m.els.res("720").checked = true;
    await startStreaming(m);
    expect(m.media.getUserMedia.mock.calls[0][0].video).toMatchObject({
      width: { ideal: 1280 }, height: { ideal: 720 },
    });
  });

  // One mount per test throughout: the module is cached for the file's
  // lifetime (`vi.resetModules()` runs per test, not per import), so a second
  // `mountScanTest` in one test would hand a fresh document to a module that
  // never re-runs its wiring.
  it("a NotAllowedError blocks", async () => {
    const m = await mountScanTest({ media: { reject: true } });
    await click(m.els.startBtn);
    expect(m.els.state.textContent).toBe("blocked");
    expect(logLines(m.els)).toContain("[err] getUserMedia rejected: NotAllowedError -- Permission denied");
  });

  it("any other rejection is an error", async () => {
    const m = await mountScanTest({ media: { reject: Object.assign(new Error("in use"), { name: "NotReadableError" }) } });
    await click(m.els.startBtn);
    expect(m.els.state.textContent).toBe("error");
    expect(logLines(m.els)).toContain("[err] getUserMedia rejected: NotReadableError -- in use");
  });

  it("reports the track's settings and capability keys", async () => {
    const m = await mountScanTest();
    await startStreaming(m);
    expect(logLines(m.els)).toContain(`[info] track settings: ${JSON.stringify(DEFAULT_SETTINGS)}`);
    expect(logLines(m.els)).toContain("[info] track capabilities keys: ");
    expect(logLines(m.els)).toContain("[info] focusMode capabilities: null; granted: continuous");
  });

  describe("torch capability", () => {
    it("exposed and true: the button appears", async () => {
      const m = await mountScanTest({ media: { capabilities: { torch: true } } });
      await startStreaming(m);
      expect(m.els.torch.textContent).toBe("yes");
      expect(m.els.torch.className).toBe("");
      expect(m.els.torchBtn.hidden).toBe(false);
    });

    it("exposed and false: named as such, button hidden", async () => {
      const m = await mountScanTest({ media: { capabilities: { torch: false } } });
      await startStreaming(m);
      expect(m.els.torch.textContent).toBe("exposed but unsupported");
      expect(m.els.torchBtn.hidden).toBe(true);
    });

    it("not exposed at all: no", async () => {
      const m = await mountScanTest();
      await startStreaming(m);
      expect(m.els.torch.textContent).toBe("no");
      expect(m.els.torchBtn.hidden).toBe(true);
    });

    it("a browser without getCapabilities: also no", async () => {
      const m = await mountScanTest({ media: { getCapabilities: null } });
      await startStreaming(m);
      expect(m.els.torch.textContent).toBe("no");
      expect(logLines(m.els)).toContain("[info] track capabilities keys: ");
    });

    it("a throwing getCapabilities: n/a, warned once per try block", async () => {
      const m = await mountScanTest({ media: { getCapabilities: () => { throw new Error("not implemented"); } } });
      await startStreaming(m);
      expect(m.els.torch.textContent).toBe("n/a (threw)");
      expect(logLines(m.els)).toContain("[warn] getCapabilities() threw: not implemented");
      expect(logLines(m.els)).toContain("[warn] focus fallback check threw: not implemented");
    });
  });

  describe("the continuous-focus fallback", () => {
    const manualFocus = () => ({
      settings: { ...DEFAULT_SETTINGS, focusMode: "manual" },
      capabilities: { focusMode: ["manual", "continuous"] },
    });

    it("retries after 500 ms and reports the focus mode it actually moved to", async () => {
      const media = manualFocus();
      const m = await mountScanTest({ media });
      await startStreaming(m);
      expect(logLines(m.els)).toContain("[info] focus not continuous after initial constraint; will retry via applyConstraints in 500ms");
      expect(m.track.applyConstraints).not.toHaveBeenCalled();

      media.settings.focusMode = "continuous";        // the retry takes effect
      await vi.advanceTimersByTimeAsync(500);
      expect(m.track.applyConstraints).toHaveBeenCalledWith({ advanced: [{ focusMode: "continuous" }] });
      expect(logLines(m.els).at(-1)).toBe("[info] focusMode after retry applyConstraints: continuous");
    });

    it("a rejected retry only warns", async () => {
      const m = await mountScanTest({ media: manualFocus() });
      m.track.applyConstraints.mockRejectedValue(Object.assign(new Error("not supported"), { name: "OverconstrainedError" }));
      await startStreaming(m);
      await vi.advanceTimersByTimeAsync(500);
      expect(logLines(m.els).at(-1)).toBe("[warn] retry applyConstraints(focusMode) threw: OverconstrainedError -- not supported");
      expect(m.els.state.textContent).toBe("streaming");
    });

    it("focus already continuous: no timer is armed at all", async () => {
      const m = await mountScanTest({ media: { capabilities: { focusMode: ["manual", "continuous"] } } });
      await startStreaming(m);
      expect(vi.getTimerCount()).toBe(0);
    });
  });

  it("a rejected play() only warns; the stream still comes up", async () => {
    const m = await mountScanTest({ video: { playRejects: Object.assign(new Error("gesture required"), { name: "NotAllowedError" }) } });
    await startStreaming(m);
    expect(logLines(m.els)).toContain("[warn] video.play() threw: NotAllowedError -- gesture required");
    expect(m.els.aimbox.hidden).toBe(false);
  });

  it("attaches the stream, shows the aim box and queues exactly one frame", async () => {
    const m = await mountScanTest();
    await startStreaming(m);
    expect(m.els.video.srcObject).toBe(m.media.stream);
    expect(m.play).toHaveBeenCalled();
    expect(m.els.aimbox.hidden).toBe(false);
    expect(m.raf.pending()).toBe(1);
    expect(logLines(m.els).at(-1)).toBe("[info] streaming started: formats:5  crop:on  tryHarder:off  res:1080p  debounce:5-of-10");
  });

  // N-P7-CHARACTERIZED. Stop is live during `requesting` (the disabled matrix
  // above), and `start()` never re-checks the state once getUserMedia
  // resolves -- so a Stop press mid-request goes idle and the camera then
  // starts anyway, behind the user's back.
  it("a Stop pressed mid-request is overridden by the stream that arrives after it", async () => {
    const m = await mountScanTest();
    const release = deferredCamera(m);
    await click(m.els.startBtn);
    await click(m.els.stopBtn);
    expect(m.els.state.textContent).toBe("idle");
    await release();
    expect(m.els.state.textContent).toBe("streaming");
    expect(m.els.video.srcObject).toBe(m.media.stream);
  });
});

describe("stop", () => {
  it("while idle: not even a state line", async () => {
    const m = await mountScanTest();
    const before = logLines(m.els).length;
    await click(m.els.stopBtn);
    expect(logLines(m.els).length).toBe(before);
  });

  it("cancels the frame, releases every track, detaches the stream and resets the panel", async () => {
    const m = await mountScanTest({ media: { capabilities: { torch: true } } });
    await startStreaming(m);
    const frameId = m.raf.raf.mock.results[0].value;
    await click(m.els.torchBtn);
    await click(m.els.stopBtn);
    expect(m.raf.caf).toHaveBeenCalledWith(frameId);
    expect(m.raf.pending()).toBe(0);
    expect(m.track.stop).toHaveBeenCalled();
    expect(m.els.video.srcObject).toBeNull();
    expect(m.els.torchBtn.textContent).toBe("Torch: off");
    expect(m.els.aimbox.hidden).toBe(true);
    expect(m.els.state.textContent).toBe("idle");
  });

  it("a throwing track.stop is warned, not raised", async () => {
    const m = await mountScanTest();
    await startStreaming(m);
    m.track.stop.mockImplementation(() => { throw new Error("device gone"); });
    await click(m.els.stopBtn);
    expect(logLines(m.els)).toContain("[warn] track.stop() threw: device gone");
    expect(m.els.state.textContent).toBe("idle");
  });

  // Safari refuses `srcObject = null` on a detached element in some versions;
  // the module swallows it so the rest of the teardown still runs.
  it("a throwing srcObject setter is warned, and teardown continues", async () => {
    const m = await mountScanTest();
    await startStreaming(m);
    Object.defineProperty(m.els.video, "srcObject", {
      configurable: true,
      set() { throw new Error("detached"); },
      get() { return null; },
    });
    await click(m.els.stopBtn);
    expect(logLines(m.els)).toContain("[warn] video.srcObject = null threw: detached");
    expect(m.els.aimbox.hidden).toBe(true);
    expect(m.els.state.textContent).toBe("idle");
  });
});

describe("reset window", () => {
  it("clears the accepted row and logs, in either state", async () => {
    const m = await mountScanTest();
    await click(m.els.resetBtn);
    expect(m.els.accepted.textContent).toBe("—");
    expect(m.els.tta.textContent).toBe("—");
    expect(logLines(m.els).at(-1)).toBe("[info] window reset");
    expect(m.els.window.textContent).toBe("(empty)");
  });
});

describe("torch", () => {
  it("does nothing without a track", async () => {
    const m = await mountScanTest();
    await click(m.els.torchBtn);
    expect(m.track.applyConstraints).not.toHaveBeenCalled();
  });

  it("flips the constraint and the label, both ways", async () => {
    const m = await mountScanTest({ media: { capabilities: { torch: true } } });
    await startStreaming(m);
    await click(m.els.torchBtn);
    expect(m.track.applyConstraints).toHaveBeenCalledWith({ advanced: [{ torch: true }] });
    expect(m.els.torchBtn.textContent).toBe("Torch: on");
    expect(logLines(m.els).at(-1)).toBe("[info] torch -> on");

    await click(m.els.torchBtn);
    expect(m.track.applyConstraints).toHaveBeenLastCalledWith({ advanced: [{ torch: false }] });
    expect(m.els.torchBtn.textContent).toBe("Torch: off");
  });

  it("a refused constraint leaves the label alone and logs an error", async () => {
    const m = await mountScanTest({ media: { capabilities: { torch: true } } });
    await startStreaming(m);
    m.track.applyConstraints.mockRejectedValue(Object.assign(new Error("no torch"), { name: "OverconstrainedError" }));
    await click(m.els.torchBtn);
    expect(logLines(m.els).at(-1)).toBe("[err] applyConstraints(torch=true) threw: OverconstrainedError -- no torch");
    expect(m.els.torchBtn.textContent).toBe("Torch: off");
  });
});

describe("copy logs", () => {
  const snapshotOf = (m) => JSON.parse(m.clipboard.writeText.mock.calls[0][0]);

  it("writes the whole diagnostic snapshot, with the unfilled fields named", async () => {
    const m = await mountScanTest();
    await click(m.els.copyBtn);
    const snap = snapshotOf(m);
    expect(snap).toMatchObject({
      userAgent: navigator.userAgent,
      phone: "(unset)",
      conditions: "(unset)",
      experimentConfig: "formats:5  crop:on  tryHarder:off  res:1080p  debounce:5-of-10",
      cameraState: "idle",
      resolutionGranted: "—",
      facingModeGranted: "—",
      torchCapability: "—",
      decodeRegion: "—",
      attemptsPerSec: "—",
      decodeSuccessRate: "—",
      successCount: "0/0",
      meanAttemptLatency: "—",
      rollingWindow: [],
      accepted: null,
      timeToAccept: "—",
    });
    expect(snap.capturedAt).toMatch(/^\d{4}-\d\d-\d\dT/);
    // The tail is the ring as it stood BEFORE the copy line, timestamps kept.
    expect(snap.logTail.length).toBe(3);
    expect(snap.logTail.at(-1)).toMatch(/^\[\d\d:\d\d:\d\d\.\d{3}\] \[info\] permissions\.query\(camera\) -> prompt$/);
    expect(logLines(m.els).at(-1)).toBe("[info] logs copied to clipboard");
  });

  it("carries the typed phone and conditions and the live camera state", async () => {
    const m = await mountScanTest();
    m.els.phone.value = "iPhone 13";
    m.els.conditions.value = "shop floor, fluorescent";
    await startStreaming(m);
    await click(m.els.copyBtn);
    expect(snapshotOf(m)).toMatchObject({
      phone: "iPhone 13",
      conditions: "shop floor, fluorescent",
      cameraState: "streaming",
      // The snapshot reads the diagnostics CELLS, and `renderDiag` runs only
      // at boot and inside `tick()` -- so a snapshot taken between Start and
      // the first frame reports the granted resolution and facing mode as
      // dashes even though the track has both. `scanTestDecode.test.js` has
      // the filled values.
      resolutionGranted: "—",
      facingModeGranted: "—",
    });
  });

  it("a refused clipboard dumps the same snapshot into the log instead", async () => {
    const m = await mountScanTest({ clipboard: { reject: new Error("not permitted") } });
    await click(m.els.copyBtn);
    expect(logLines(m.els)).toContain("[warn] clipboard.writeText threw: not permitted -- dumping to log instead");
    expect(m.els.log.textContent).toContain("\"phone\": \"(unset)\"");
  });
});

describe("the log ring", () => {
  it("keeps the last 200 lines and scrolls to the bottom", async () => {
    const m = await mountScanTest();
    // jsdom has no layout, so `scrollHeight` is 0 and the assignment would be
    // vacuous; define it and read `scrollTop` back.
    Object.defineProperty(m.els.log, "scrollHeight", { configurable: true, value: 4242 });
    for (let i = 0; i < 210; i += 1) {
      m.els.expCrop.checked = !m.els.expCrop.checked;
      m.els.expCrop.dispatchEvent(new Event("change"));
    }
    const lines = logLines(m.els);
    expect(lines.length).toBe(200);
    expect(lines[0]).toMatch(/^\[info\] crop -> (on|off)$/);   // the boot lines are gone
    expect(m.els.log.scrollTop).toBe(4242);
  });
});

describe("the lifecycle listeners", () => {
  it("a hidden tab stops a running camera", async () => {
    const m = await mountScanTest();
    await startStreaming(m);
    setDocumentHidden(true);
    document.dispatchEvent(new Event("visibilitychange"));
    await settle();
    expect(logLines(m.els)).toContain("[info] visibilitychange -> hidden; stopping");
    expect(m.els.state.textContent).toBe("idle");
    expect(m.track.stop).toHaveBeenCalled();
  });

  it("a hidden tab with no camera running does nothing", async () => {
    const m = await mountScanTest();
    const before = logLines(m.els).length;
    setDocumentHidden(true);
    document.dispatchEvent(new Event("visibilitychange"));
    await settle();
    expect(logLines(m.els).length).toBe(before);
  });

  it("beforeunload releases the camera, and swallows a track that refuses", async () => {
    const m = await mountScanTest();
    await startStreaming(m);
    m.track.stop.mockImplementation(() => { throw new Error("device gone"); });
    expect(() => window.dispatchEvent(new Event("beforeunload"))).not.toThrow();
    expect(m.track.stop).toHaveBeenCalled();
  });
});
