// The camera/haptics/audio stubs, installed at the BROWSER boundary.
//
// `views/scan.js` is never mocked -- the real `mountScanner`, the real
// `BarcodeDecoder.supports()` gate and the real track lifecycle all run. What
// is replaced here is only what jsdom does not implement: `getUserMedia`,
// `navigator.permissions`, `navigator.vibrate`, `AudioContext`, and the ZXing
// UMD global that `shell.js` strips the script tag for.
//
// Nothing here is needed at import time -- `mountScanner` only reaches for
// `navigator.mediaDevices` inside `start()` -- but `views/nav.js` drives
// `reset()` / `refreshPermissionState()` on every page swap, so any test that
// navigates should install them rather than assert against an unsupported
// browser it did not mean to simulate.
//
// Every stub is a `vi.fn()`, so "we released the camera" is an assertion and
// not a hope. `restoreMediaStubs()` puts the originals back; call it in an
// `afterEach`.

import { vi } from "vitest";

const restorers = [];

// Replace an own-or-inherited property that may not exist at all on the
// jsdom object (`navigator.mediaDevices` does not, and is not writable where
// it does), and remember how to put it back.
function define(target, key, value) {
  const had = Object.prototype.hasOwnProperty.call(target, key);
  const original = had ? Object.getOwnPropertyDescriptor(target, key) : null;
  Object.defineProperty(target, key, { configurable: true, writable: true, value });
  restorers.push(() => {
    if (original) Object.defineProperty(target, key, original);
    else delete target[key];
  });
}

// One fake camera track. `stop` is the spy that proves `stopLive()` released
// the hardware; `getCapabilities` decides whether the torch button appears,
// and `applyConstraints` is what the torch toggle and the focus hint call.
export function fakeTrack({ torch = false, capabilities = null } = {}) {
  return {
    kind: "video",
    stop: vi.fn(),
    getCapabilities: vi.fn(() => capabilities ?? (torch ? { torch: true } : {})),
    applyConstraints: vi.fn(async () => {}),
  };
}

// A MediaStream stand-in carrying `tracks`. jsdom has no MediaStream, and the
// module only calls `getTracks()` / `getVideoTracks()` on it plus hands it to
// `video.srcObject` (an unchecked assignment in jsdom), so a plain object is
// honest here. Every track is a video track: `getUserMedia` is called with
// `audio: false`.
export function fakeStream(tracks) {
  return {
    getTracks: () => tracks,
    getVideoTracks: () => tracks.filter((track) => track.kind === "video"),
    getAudioTracks: () => [],
  };
}

// `navigator.mediaDevices.getUserMedia`. Resolves to a one-track stream by
// default; pass `reject` to simulate a denial (`NotAllowedError`, the shape
// the browser actually throws).
export function stubUserMedia({ tracks = null, reject = null, torch = false } = {}) {
  const track = tracks ? null : fakeTrack({ torch });
  const stream = fakeStream(tracks ?? [track]);
  const getUserMedia = vi.fn(async () => {
    if (reject) throw reject === true
      ? Object.assign(new Error("Permission denied"), { name: "NotAllowedError" })
      : reject;
    return stream;
  });
  define(navigator, "mediaDevices", { getUserMedia });
  return { getUserMedia, stream, track, tracks: stream.getTracks() };
}

// `navigator.permissions.query({name: "camera"})`.
//
//   "granted" / "prompt" / "denied" -- the three states the code branches on
//   null                            -- no Permissions API at all
//   "throws"                        -- a browser that rejects `name: "camera"`,
//                                      which `supports()` treats as permissive
//                                      and `permissionGranted()` as false
export function stubPermissions(state = "prompt") {
  if (state === null) {
    define(navigator, "permissions", undefined);
    return null;
  }
  const query = vi.fn(async () => {
    if (state === "throws") throw new TypeError("camera is not a valid permission name");
    return { state, onchange: null };
  });
  define(navigator, "permissions", { query });
  return query;
}

// `navigator.vibrate`. Absent on desktop and on iOS Safari, which is the
// "degrades silently" case -- pass `supported: false` for it.
export function stubVibrate({ supported = true } = {}) {
  if (!supported) {
    define(navigator, "vibrate", undefined);
    return null;
  }
  const vibrate = vi.fn(() => true);
  define(navigator, "vibrate", vibrate);
  return vibrate;
}

// `window.AudioContext`. Same story: `supported: false` is the iOS case the
// scan view's `primeAudio` has to survive.
export function stubAudioContext({ supported = true } = {}) {
  if (!supported) {
    define(window, "AudioContext", undefined);
    define(window, "webkitAudioContext", undefined);
    return null;
  }
  const created = [];
  const Ctx = vi.fn(function FakeAudioContext() {
    const ctx = {
      state: "suspended",
      currentTime: 0,
      destination: {},
      resume: vi.fn(async () => { ctx.state = "running"; }),
      close: vi.fn(async () => { ctx.state = "closed"; }),
      createOscillator: vi.fn(() => ({
        type: "sine",
        frequency: { value: 0, setValueAtTime: vi.fn() },
        connect: vi.fn(),
        start: vi.fn(),
        stop: vi.fn(),
      })),
      createGain: vi.fn(() => ({
        gain: { value: 1, setValueAtTime: vi.fn(), exponentialRampToValueAtTime: vi.fn() },
        connect: vi.fn(),
      })),
    };
    created.push(ctx);
    return ctx;
  });
  define(window, "AudioContext", Ctx);
  define(window, "webkitAudioContext", Ctx);
  return { Ctx, created };
}

// The ZXing UMD global. `shell.js` strips the vendor `<script>` tag (it must,
// or main.js would boot too), so `BarcodeDecoder.supports()` returns false in
// jsdom purely for want of this. A test that wants the supported branch says
// so here rather than loading 300 KB of vendor code.
export function stubZXing(overrides = {}) {
  const reader = {
    decodeFromCanvas: vi.fn(() => { throw new Error("NotFoundException"); }),
    ...overrides,
  };
  const ZXingBrowser = {
    // A `function`, not an arrow: the decoder does `new BrowserMultiFormatReader(hints)`.
    BrowserMultiFormatReader: vi.fn(function BrowserMultiFormatReader() { return reader; }),
    ...overrides.ZXingBrowser,
  };
  define(window, "ZXingBrowser", ZXingBrowser);
  return { ZXingBrowser, reader };
}

// The set a test that merely NAVIGATES wants: a camera that exists, a
// permission state that does not auto-start anything, and haptics/audio that
// record rather than throw. Returns every spy so a caller can still assert.
export function stubMediaEnvironment({
  permission = "prompt",
  torch = false,
  zxing = true,
} = {}) {
  const media = stubUserMedia({ torch });
  const permissions = stubPermissions(permission);
  const vibrate = stubVibrate();
  const audio = stubAudioContext();
  const zx = zxing ? stubZXing() : null;
  return { ...media, permissions, vibrate, audio, zxing: zx };
}

export function restoreMediaStubs() {
  while (restorers.length) restorers.pop()();
}

// --- Web Push --------------------------------------------------------------
//
// `push.js` gates every call on `pushSupported()`: `navigator.serviceWorker` +
// `window.PushManager` + `window.Notification` all present. jsdom has none of
// the three, so the default in this suite is "unsupported" and every push path
// silently no-ops. This stub is what makes the push branches reachable at all.
//
// Kept in its own restorer list (and not in `define`'s) because it reaches for
// `vi.stubGlobal`, which `restoreMediaStubs` has no business undoing.

let pushRestorers = [];

// `permission`   the value `window.Notification.permission` reports. "default"
//                is the only state `requestPermissionAtLogin` will prompt in.
// `subscription` an ALREADY-REGISTERED browser subscription, or null for a
//                device that has never subscribed. Its `options
//                .applicationServerKey` defaults to the bytes of "QUJD" -- the
//                VAPID key the push handlers in the tests answer `/push/config`
//                with -- so `subscribeThisDevice` takes its "the key still
//                matches" branch rather than silently rotating the endpoint.
export function stubPush({ permission = "default", subscription = null } = {}) {
  const requestPermission = vi.fn(async () => permission);
  const unsubscribe = vi.fn(async () => true);
  const endpoint = subscription?.endpoint ?? "https://push.example/abc";
  const sub = subscription && {
    endpoint,
    options: {
      applicationServerKey:
        subscription.applicationServerKey ?? Uint8Array.from("ABC", (c) => c.charCodeAt(0)),
    },
    toJSON: () => ({ endpoint, keys: { p256dh: "p", auth: "a" } }),
    unsubscribe,
  };
  const fresh = {
    endpoint: "https://push.example/new",
    options: { applicationServerKey: Uint8Array.from("ABC", (c) => c.charCodeAt(0)) },
    toJSON: () => ({ endpoint: "https://push.example/new", keys: { p256dh: "p", auth: "a" } }),
    unsubscribe,
  };
  const registration = {
    pushManager: {
      getSubscription: vi.fn(async () => sub),
      subscribe: vi.fn(async () => sub ?? fresh),
    },
  };
  const register = vi.fn(async () => registration);
  const getRegistration = vi.fn(async () => registration);

  Object.defineProperty(navigator, "serviceWorker", {
    configurable: true,
    value: { register, getRegistration },
  });
  pushRestorers.push(() => { delete navigator.serviceWorker; });
  vi.stubGlobal("PushManager", function PushManager() {});
  vi.stubGlobal("Notification", { permission, requestPermission });
  pushRestorers.push(() => vi.unstubAllGlobals());
  return { requestPermission, register, getRegistration, unsubscribe, registration, subscription: sub };
}

export function restorePush() {
  while (pushRestorers.length) pushRestorers.pop()();
}

// --- Decoder frame loop ------------------------------------------------------
//
// `BarcodeDecoder._tick` draws the aim-box crop into an offscreen canvas and
// hands it to ZXing once per animation frame. jsdom has no canvas backend
// (getContext returns null), never sets a video's intrinsic size, and its
// requestAnimationFrame cannot be stepped -- so the loop never reaches a
// decode. These three stubs make a frame a thing a test can advance.

export function stubCanvas() {
  const ctx = { drawImage: vi.fn() };
  // An arrow, so `getContext` inside resolves to the mock (a named function
  // expression would shadow it with the implementation).
  const getContext = vi.fn((kind, options) => {
    getContext.lastOptions = options;
    return kind === "2d" ? ctx : null;
  });
  define(HTMLCanvasElement.prototype, "getContext", getContext);
  return { ctx, getContext };
}

export function stubRaf() {
  let queue = [];
  let nextId = 1;
  const raf = vi.fn((cb) => { const id = nextId++; queue.push({ id, cb }); return id; });
  const caf = vi.fn((id) => { queue = queue.filter((entry) => entry.id !== id); });
  define(window, "requestAnimationFrame", raf);
  define(window, "cancelAnimationFrame", caf);
  return {
    raf, caf,
    pending: () => queue.length,
    // Run everything queued at call time as one frame; callbacks that
    // re-queue land in the NEXT frame, not this one.
    flush(frames = 1) {
      for (let i = 0; i < frames; i += 1) {
        const batch = queue; queue = [];
        batch.forEach(({ cb }) => cb(performance.now()));
      }
    },
  };
}

// Intrinsic size and a resolved `play()` on an element the test owns; the
// element is discarded with the DOM, so nothing to restore.
export function stubVideo(videoEl, { width = 1280, height = 720 } = {}) {
  Object.defineProperty(videoEl, "videoWidth", { configurable: true, get: () => width });
  Object.defineProperty(videoEl, "videoHeight", { configurable: true, get: () => height });
  const play = vi.fn(async () => {});
  Object.defineProperty(videoEl, "play", { configurable: true, value: play });
  return { play };
}

// The shape ZXing's result exposes.
export function decodeResult(text, format = "CODE_128") {
  return { getText: () => text, getBarcodeFormat: () => format };
}
