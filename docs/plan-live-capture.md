# Plan: Live Camera Barcode Capture

Status: **Implemented.** Live capture is wired into both the
Transaction page and Saved Items page: video preview, Scan / Upload /
Torch toolbar, aim-box overlay, page-level camera lifecycle
(visibility change, page-leave teardown), and blocked-mode fallback.
Phase 1 spike files (`backend/static/scan-test.html`,
`backend/static/scan-test.js`) were deleted at ship time, then
**restored and repurposed** as a reliability/speed experiment harness
(see [docs/plan-scan-tuning.md](plan-scan-tuning.md)). Upload-mode
regression remains intact.

> **Amended by field testing.** A later on-fleet experiment validated a
> faster/more-reliable configuration. Decisions **#3, #7, #8, #15, #18**
> below were superseded — each amended row points to
> [docs/plan-scan-tuning.md](plan-scan-tuning.md), which is the
> authoritative source for the current decode behaviour.

Upload-mode regression was verified after the reusable scanner
refactor. `mountScanner({...})` accepts optional live-mode DOM
handles, the ZXing wrapper lives in
[backend/static/scan/barcode-decoder.js](backend/static/scan/barcode-decoder.js),
the 5-of-10 debounce lives in
[backend/static/scan/frame-debouncer.js](backend/static/scan/frame-debouncer.js),
and the vendored ZXing UMD is loaded globally from
[backend/static/index.html](backend/static/index.html).

The Saved Items page now passes `liveEls` into its `mountScanner` call
site, has mirrored `#items-scan-*` markup/CSS, exports
`itemsScanner`, and is registered in `views/nav.js` for page-level
camera lifecycle.

---

## Goal

Add a live camera barcode scanner to the Transaction and Saved Items
pages. Today both pages use a still-photo upload via
`<input capture="environment">` in [backend/static/index.html](backend/static/index.html#L103)
and [backend/static/index.html](backend/static/index.html#L245), decoded
server-side by `pyzbar` in [backend/app/services/barcodes.py](backend/app/services/barcodes.py).
Single-shot camera captures are unreliable on hand-held phones (blur,
glare, skew); a live decode loop with visual feedback recovers most of
those failure cases.

Live mode is **experimental** in v1: it ships alongside upload mode,
not as a replacement. Upload mode and its server-side `/barcodes/decode`
contract are unchanged in behaviour — only the auth gate moves (see
decision #2).

---

## Stack readiness (summary)

The stack is well-prepared. Confirmed in earlier discussion:

- HTTPS-only on Render (required for `getUserMedia`).
- Single origin — page, scan endpoint, and static assets all served
  by the same FastAPI app in [backend/app/main.py](backend/app/main.py#L42-L65).
- No CSP middleware to negotiate.
- Scanner already factored as a reusable `mountScanner({...})` factory
  in [backend/static/views/scan.js](backend/static/views/scan.js#L40-L165),
  called from two pages with identical callback contract.
- Result-handling pipeline (`decoded text → apiGetItemByBarcode →
  onItemFound | handleUnknownBarcode`) is decoder-agnostic, so live
  mode plugs into it by skipping the `apiDecodeBarcode` step.
- Plain ES modules, no build step.

Gaps remaining (all in Phase 3):

- New DOM IDs to be added to the "frozen DOM contract" in
  [docs/interfaces.md](docs/interfaces.md) section 12, and the
  corresponding markup added to
  [backend/static/index.html](backend/static/index.html).
- Population of `liveEls` from the Transaction and Saved Items call
  sites in [backend/static/views/scan.js](backend/static/views/scan.js)
  and [backend/static/views/items.js](backend/static/views/items.js).
- Page-level `visibilitychange` and section-leave lifecycle hooks.
- Blocked-mode UI (Permissions-API pre-check + fallback messaging).
- Deletion of the Phase 1 spike files (see "Spike files left in
  place" below).

Gaps already closed:

- `Permissions-Policy: camera=(self)` header shipped in
  [backend/app/main.py](backend/app/main.py#L46) during Phase 1.
- `backend/static/vendor/` exists with the pinned ZXing UMD and its
  LICENSE; vendoring procedure documented in
  [docs/reference.md](docs/reference.md).
- `/barcodes/decode` auth gate lowered in Prerequisites #2.
- Session idle timeout raised in Prerequisites #1.

---

## Prerequisites (separate PRs, must land before Phase 3)

1. **Session idle timeout 60 s → 600 s.** Today
   `SESSION_IDLE_TIMEOUT = timedelta(seconds=60)` in
   [backend/app/services/auth.py](backend/app/services/auth.py#L33).
   Aiming a phone at a label can easily exceed 60 s of no network
   activity; live capture is unusable until this is raised. The
   comment above the constant says "the product spec fixes this at
   60 seconds," so [docs/spec.md](docs/spec.md) must move in lockstep.
   One-line PR.
2. **`/barcodes/decode` auth gate technician+.** Today the route in
   [backend/app/routers/barcodes.py](backend/app/routers/barcodes.py#L29)
   is gated at `ROLE_SUPERVISOR`. Lower it to "any authenticated user"
   (drop the `require_min_role` dependency, rely on the existing auth
   cookie). Same change for the live-mode item lookup is unnecessary —
   `apiGetItemByBarcode` is already all-roles. This is an intentional
   expansion of what Technicians can do.

These two land before Phase 3 ships to users; the Phase 1 spike does
not depend on either.

---

## Decisions locked

| #  | Decision                                       | Value |
|----|------------------------------------------------|-------|
| 1  | Pages getting live capture                     | Both Transaction and Saved Items |
| 2  | Upload still supported                         | Yes, kept alongside live capture |
| 3  | Server-side verify in live mode                | **No.** Live mode calls `apiGetItemByBarcode(text)` directly. Upload mode keeps `POST /barcodes/decode` unchanged. Rationale: ZXing (client) and pyzbar (server) are different decoders, so a "verify" step can fail on a correct client decode; the auth gate is also enforced again by `GET /items/{barcode}` and `POST /transactions/`, so nothing security-relevant is lost.<br>**Amended ([plan-scan-tuning.md](plan-scan-tuning.md)):** verify still skipped, but the upload decoder was widened from 5 formats to all zbar symbologies, with canonical names aligned to ZXing's. The two paths now share a format vocabulary; the residual gap is zbar's lack of 2D (DataMatrix) support, accepted. |
| 4  | Decoding cadence                               | **One accepted result per transaction; continuous decode otherwise.** Decoder runs every frame while in `scanning`, pauses on accept, resumes after the transaction closes. |
| 5  | Decoder library                                | `@zxing/browser` |
| 6  | Vendor vs CDN                                  | Vendor. File in `backend/static/vendor/`, version pinned by filename (e.g. `zxing-browser-0.1.5.min.js`), SHA-256 recorded in [docs/reference.md](docs/reference.md), manual update steps documented there. |
| 7  | Main thread vs Web Worker                      | Main thread v1, behind a `BarcodeDecoder` class for an easy later swap.<br>**Amended ([plan-scan-tuning.md](plan-scan-tuning.md)):** still main-thread and still behind `BarcodeDecoder`, but the decode model moved from ZXing's `decodeFromStream` to a manual `requestAnimationFrame` + `decodeFromCanvas` loop (required to crop — see #15). |
| 8  | Camera constraints                             | `facingMode: { ideal: "environment" }`, `width: { ideal: 1920 }`, `height: { ideal: 1080 }`, **no `max`** — higher resolution helps decode small/distant labels and decode time stays within budget on the phones we care about.<br>**Amended ([plan-scan-tuning.md](plan-scan-tuning.md)):** resolution dropped to **720p** (`width/height ideal 1280/720`). With the aim-box crop, the cropped region has ample pixels for a label that fills the box, and smaller frames decode faster. |
| 9  | `Permissions-Policy: camera=(self)` middleware | Yes. |
| 10 | CSP                                            | Out of scope — threat model does not justify it. |
| 11 | Role gating                                    | All authenticated roles (Technician through Owner) get **both** upload and live capture. See Prerequisites #2 for the upload-mode gate change. |
| 12 | Audit / logging                                | Only the confirmed scan (the one that triggers item lookup or transaction) is logged, same as today. |
| 13 | New DOM IDs                                    | `txn-scan-video`, `txn-scan-scan-btn`, `txn-scan-upload-btn`, `txn-scan-torch-btn`, `txn-scan-aimbox`; mirrored `items-scan-*`. |
| 14 | Bundling format additions in same PR           | No — separate work. |
| 15 | Live-feed visuals                              | Grayscale via `filter: grayscale(100%)` on `<video>`. Decoder still receives full-colour frames internally. Aim-box overlay: positioned `<div>` with thin high-contrast border, ~3:1 aspect ratio, guidance only — **no frame cropping in v1.**<br>**Amended ([plan-scan-tuning.md](plan-scan-tuning.md)):** the aim-box is now the **decode region** — the loop crops to it (80% width, 3:1, centred) before decoding. Faster decode and no background-label misreads. Crop constants must stay in sync with `.scan-aimbox` in `styles.css`. |
| 16 | Offline / PWA / installable                    | Out of scope. |
| 17 | Multiple barcodes in one frame                 | Discard the frame, wait for the next. |
| 18 | False-positive debounce                        | Accept decoded text X only when X appears in **≥5 of the last 10 frames.** Sliding window; reset on accept. Cheap, kills almost all single-frame misreads.<br>**Amended ([plan-scan-tuning.md](plan-scan-tuning.md)):** replaced by **3 consecutive identical decodes** (a differing decode resets the streak; misses don't). Faster to accept; safe because the crop (#15) removed the background noise the wider window guarded against. |
| 19 | Camera lifecycle                               | Camera tracks stopped on `visibilitychange→hidden`, on navigating away from the scan section, and on tapping a Cancel/Stop button. Restart **requires the user tapping the Scan button again** — iOS Safari rule. |
| 20 | iOS Safari support                             | In scope. `<video playsinline muted autoplay>`. Camera start is **only** from the Scan button click handler, never on section open. |
| 21 | Permission-denied handling                     | On scan-section entry, pre-check `navigator.permissions.query({name:'camera'})` (where supported). If state is `denied`, hide the Scan button, show "Camera blocked. Re-enable via the lock icon in the address bar," and surface Upload mode as the only option. If `getUserMedia` itself rejects with `NotAllowedError`, same message. |
| 22 | Torch button                                   | Yes, v1. After camera starts, check `track.getCapabilities().torch`; if true, show the Torch button. Toggle via `track.applyConstraints({ advanced: [{ torch: bool }] })`. Hidden on iOS and on Android devices that don't expose torch (most do; Chrome supports it). |
| 23 | Mode buttons                                   | Two buttons: **Scan** (starts live capture) and **Upload** (opens file picker). Neither is active until pressed; no persisted default. |
| 24 | Phase 1 spike exit criterion                   | Open-ended exploration on the actual labels and phones in use. No numeric pass/fail. |

---

## State machine

```
idle
  │
  │ on scan-section enter: query Permissions API
  │   └── state=denied ──▶ blocked
  │
  └─ user taps Scan button (user-gesture; iOS-safe)
         │
         ▼
   requesting ── getUserMedia rejects ──▶ blocked
         │                                  (Scan button hidden;
         │                                   Upload remains the only option;
         │                                   message: "Camera blocked. Re-enable
         │                                   via the lock icon.")
         ▼
   scanning ◀────────────────────────────────┐
     │                                       │
     ├── frame with ≥2 codes ──▶ drop frame, stay in scanning
     ├── frame with no code  ──▶ stay in scanning
     ├── frame with 1 code ──▶ push to debounce window (last 10)
     │       │
     │       └── any text X in window has count ≥5 ──▶ accepted
     │                                                  │
     └────────────────────────── debounce window not yet satisfied
                                                        │
                                                        ▼
                                                    accepted
                                                        │ (decoder paused;
                                                        │  window cleared;
                                                        │  call apiGetItemByBarcode
                                                        │  directly — no /barcodes/decode)
                                                        ▼
                                                    transacting
                                                    (transaction bar open;
                                                     camera preview visible,
                                                     decoder paused)
                                                        │
                            ┌───────────────────────────┤
                            │                           │
                Save / Cancel                  leave section / tab hidden /
                            │                  tap Stop
                            ▼                           │
                       scanning ─────────────┘          ▼
                                                       idle
                                                       (stop tracks, release camera)

blocked
  │ user fixes permission and reloads, or uses Upload mode
  └─ (no JS-driven recovery — browsers refuse to re-prompt from script)
```

Reasoning behind the pause-on-accept: workers hold phones near their
belts while filling forms. Decoding during `transacting` risks scanning
a toolbox by accident. From the user request: "I do not want the
camera scanning while a transaction bar is up."

Reasoning behind the 5-of-10 debounce: ZXing returns no confidence
score and will occasionally emit a checksum-valid UPC from a blurry
frame that doesn't match the label in front of the lens. Requiring
agreement across a sliding window catches the common single-frame
misread without noticeably increasing time-to-accept on a well-aimed
scan.

---

## Phasing

1. **Phase 0 — close assumptions (no code).** ✅ Done. Decisions
   locked above.
2. **Prerequisites (separate PRs).** ✅ Done. Session idle timeout
   bumped to 600 s in [backend/app/services/auth.py](backend/app/services/auth.py#L33);
   `/barcodes/decode` gate lowered to any authenticated user in
   [backend/app/routers/barcodes.py](backend/app/routers/barcodes.py#L29).
3. **Phase 1 — decoder spike.** ✅ Done. See "Phase 1 results" below.
   The `Permissions-Policy: camera=(self)` middleware originally
   scheduled for Phase 3 shipped here (in [backend/app/main.py](backend/app/main.py#L46))
   so the spike validated it as well.
4. **Phase 2 — refactor `mountScanner`.** ✅ Done. The reusable
   scanner in [backend/static/views/scan.js](backend/static/views/scan.js)
   now accepts optional `liveEls` handles and returns
   `{ reset, stopLive }` while preserving the existing upload-only
   callers unchanged. The ZXing wrapper shipped in
   [backend/static/scan/barcode-decoder.js](backend/static/scan/barcode-decoder.js)
   with a push-based API: `static async supports()`,
   `async start(videoEl, stream, onDecode)`, and `stop()`. The 5-of-10
   debounce shipped separately in
   [backend/static/scan/frame-debouncer.js](backend/static/scan/frame-debouncer.js).
   The vendored UMD is now loaded globally from
   [backend/static/index.html](backend/static/index.html#L383).
5. **Phase 3 — wire and ship.** Implemented across Transaction and
   Saved Items.
   - **PR1 (Transaction page).** ✅ Done. Added new real-page DOM
     (video, Scan/Upload/Torch toolbar, aim-box overlay) to
     `#txn-scan-section`. Passed `liveEls` from the Transaction
     auto-mount in [backend/static/views/scan.js](backend/static/views/scan.js)
     and exported the `txnScanner` handle. Added page-level
     `visibilitychange` + section-leave lifecycle hooks and a
     blocked-mode fallback (Scan hidden, blocked-mode message,
     Upload still usable) via a new `refreshPermissionState()`
     helper called from [backend/static/views/nav.js](backend/static/views/nav.js).
     `getUserMedia` constraints now include `width: { ideal: 1920 }`
     and `height: { ideal: 1080 }`. Phase 1 spike files
     (`scan-test.html`, `scan-test.js`) deleted.
   - **PR2 (Saved Items page).** Done. Mirrored the markup/CSS
     additions in `#items-scan-section`, passes `liveEls` from the
     Saved Items `mountScanner` call site, exports `itemsScanner`,
     and registers it in `SCANNERS_BY_PAGE` in `views/nav.js`.

---

## Phase 1 results

Spike at `/static/scan-test.html` validated on the actual fleet (all
iPhones, plus desktop Chrome for control) and several Android phones
for comparison. Answers to the seven Phase 1 questions:

1. **Single vendored UMD works.** `@zxing/browser` 0.2.0 UMD
   (`ZXingBrowser` global, 441 KB) loads from
   `/static/vendor/zxing-browser-0.2.0.umd.min.js` with no runtime
   sub-imports, no source-map 404s. Phase 2 uses the same vendoring.
2. **5-of-10 debounce holds.** No false accepts observed during
   testing on iOS Safari. Keeping the ratio as locked in decision #18.
3. **iOS grants `environment` reliably.** No `enumerateDevices`
   camera-switching UI needed in Phase 3 — stays out of scope.
4. **Decode latency within budget** on iPhones (well under the 33 ms
   frame budget). Resolution kept uncapped per decision #8.
5. **Torch capability** surfaces only on Android (as predicted). Moot
   for v1 since the fleet is iOS; the torch button stays in the Phase
   3 DOM contract behind the `caps.torch === true` gate so it appears
   automatically if/when Android is added.
6. **Multi-barcode detection per frame** — ZXing's
   `BrowserMultiFormatReader.decodeFromStream` returns one result per
   frame, not all results. Decision #17 ("discard frame with 2+
   codes") is therefore not directly achievable with this entry point;
   the practical effect is that ZXing picks one of the two codes
   non-deterministically. **Plan amendment:** decision #17 becomes
   "single-decode-per-frame; if two labels are physically in view, the
   user will get whichever ZXing locks onto first, and the 5-of-10
   debounce will still suppress flicker between them." Real-world
   labels are rarely twinned in our environment so this is acceptable.
7. **UPC-A returns as `UPC_A`** — no normalisation needed in
   [backend/app/services/barcodes.py](backend/app/services/barcodes.py).

### Android caveat (non-blocking)

Decoding on Android Chrome and Edge is unreliable. Investigated:

- Same resolution as iOS in the granted track settings (so not a
  pixel-count issue).
- `focusMode` capability is exposed and includes `continuous`, but
  both the initial `getUserMedia` constraint *and* a post-start
  `applyConstraints({ advanced: [{ focusMode: 'continuous' }] })`
  retry left `getSettings().focusMode === 'manual'` on the test
  device. The Android Chrome camera driver accepts the request and
  ignores it.
- Did not test resolution cap, tap-to-focus, or wide-angle-vs-main
  camera selection — entire workforce is on iOS, so deferred.

Not a ship blocker for v1. If Android joins the fleet later, escalate
in this order: cap resolution at 1280×720 (cheap, may force a focus
mode change), add tap-to-focus on the video element, enumerate rear
cameras and prefer the "main" one, periodic single-shot AF re-trigger
every few seconds.

### Spike files left in place

The following stay in the repo through Phase 2 and are **deleted in
the Phase 3 ship PR**:

- [backend/static/scan-test.html](backend/static/scan-test.html)
- [backend/static/scan-test.js](backend/static/scan-test.js)

The vendored library, its LICENSE, the
[backend/static/vendor/](backend/static/vendor) directory, and the
`Permissions-Policy` middleware are permanent.

---

## Out of scope, explicitly

- CSP / HSTS / other security hardening (deferred; not justified by
  current threat model).
- Server-side preprocessing improvements (grayscale, retry pyramid,
  rotation passes in `decode_image`) — live capture removes most of
  the failure cases that motivated these; revisit only if needed.
- ~~Additional 1D / 2D barcode formats — tracked separately.~~ **Done
  for the upload path** ([plan-scan-tuning.md](plan-scan-tuning.md)): the
  pyzbar decoder now reads all zbar symbologies. Live (ZXing) was already
  all-formats. 2D matrix codes (DataMatrix) remain unsupported on upload.
- Offline / PWA / installable-app behaviour.
- Multi-decode per frame (decision #17).
- Camera switching UI (`enumerateDevices`-driven swap). Rear-camera
  default via `facingMode` is sufficient for v1; revisit if tablets or
  laptops need it.
- ~~Aim-box → decode-region cropping. Overlay is guidance only in v1;
  crop only if false positives from outside the box become a problem.~~
  **Done** ([plan-scan-tuning.md](plan-scan-tuning.md)): the decode loop
  now crops to the aim-box.
- Wake Lock API. The session-timeout bump (Prerequisites #1) plus the
  fleet's OS-level 10-minute screen timeout cover the same failure
  mode.
- Frontend UX overhaul for the construction-worker audience —
  tracked in [docs/plan-ux-overhaul.md](docs/plan-ux-overhaul.md).

---

## Decision log

Captured chronologically as they were settled. Numbers in parentheses
refer to the decisions table above.

- Threat model: small known internal user base, no public exposure,
  no high-value data. CSP and similar speculative hardening are not
  justified. The codebase already follows CSP-friendly conventions
  (no inline JS, no inline styles, `textContent` over `innerHTML`)
  for consistency, not for CSP compliance.
- Vendor over CDN (6): keeps origin count at one, avoids permanent
  widening of any future `script-src`, removes a third-party network
  dependency. Modern browsers partition HTTP cache by site so the
  historical "shared CDN cache" benefit no longer exists.
- Main thread over Web Worker for v1 (7): ZXing decode of a 720p frame
  is ~15–25 ms on mid-range Android, well under the 33 ms frame
  budget. Worker move stays cheap behind the `BarcodeDecoder` class
  if profiling later shows UI jank.
- Server-side verify dropped in live mode (3): the original plan kept
  it for "server authority," but ZXing and pyzbar are different
  decoders, so verify can fail on a correct scan. The supervisor gate
  the verify call used to enforce is no longer needed (decision #11
  opens scanning to all roles), and the real authorisation gates on
  `POST /transactions/` and item lookup are still in place. Net:
  removes 100–500 ms of dead time per scan and one failure mode.
- Resolution uncapped (8): original plan capped at 1280×720 to control
  decode time. With ZXing decode well under frame budget and the user
  priority being "nothing in the way of the scanning," letting phones
  hand back 1080p improves small/distant label decode at negligible
  cost.
- Debounce 5-of-10 (18): ZXing has no confidence score. A sliding
  window is the standard mitigation against single-frame misreads of
  checksum-valid-but-wrong codes. Five of ten is the smallest window
  that empirically catches the common case without making a
  well-aimed scan feel slow.
- iOS Safari camera-start must be user-gesture (19, 20): autoplay /
  `getUserMedia` from a non-user-initiated handler is blocked on iOS.
  The two-button UI (23) already provides the gesture handler, so the
  state machine starts in `idle` even after the section opens and
  only transitions to `requesting` on Scan-button click.
- No JS recovery for blocked permissions (21): once a user taps
  "Block," browsers refuse to re-prompt from script. The only path
  back is the address-bar lock icon; we say so plainly.
- Session idle timeout (Prerequisites #1) lifted out of this plan:
  it's a one-line change with no UI surface and is needed by other
  flows too, not just live capture.
- Phase 2 amended the implementation shape of decision #7: the
  `BarcodeDecoder` boundary stayed, but the concrete API is
  push-based (`supports()`, `start(videoEl, stream, onDecode)`,
  `stop()`) rather than a pull-based `decodeFrame(...)` method.
  Reason: ZXing's `decodeFromStream` is callback-driven, and wrapping
  it as per-frame pull logic adds complexity for no gain.
