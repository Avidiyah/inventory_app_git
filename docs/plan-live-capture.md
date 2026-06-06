# Plan: Live Camera Barcode Capture

Status: **Phase 0 signed off.** All assumptions closed. Ready to
proceed with the prerequisite work and Phase 1 spike.

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

Gaps to close as part of the work:

- New DOM IDs to be added to the "frozen DOM contract" in
  [docs/interfaces.md](docs/interfaces.md) section 12.
- `Permissions-Policy: camera=(self)` header (currently absent;
  future-proofs against iframe embedding).
- New `backend/static/vendor/` directory for vendored third-party JS.
- Auth gate on `/barcodes/decode` lowered from supervisor to any
  authenticated user (decision #2).
- Session idle timeout raised from 60 s to 600 s (see Prerequisites).

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
| 3  | Server-side verify in live mode                | **No.** Live mode calls `apiGetItemByBarcode(text)` directly. Upload mode keeps `POST /barcodes/decode` unchanged. Rationale: ZXing (client) and pyzbar (server) are different decoders, so a "verify" step can fail on a correct client decode; the auth gate is also enforced again by `/items/by-barcode/{text}` and `POST /transactions/`, so nothing security-relevant is lost. |
| 4  | Decoding cadence                               | **One accepted result per transaction; continuous decode otherwise.** Decoder runs every frame while in `scanning`, pauses on accept, resumes after the transaction closes. |
| 5  | Decoder library                                | `@zxing/browser` |
| 6  | Vendor vs CDN                                  | Vendor. File in `backend/static/vendor/`, version pinned by filename (e.g. `zxing-browser-0.1.5.min.js`), SHA-256 recorded in [docs/reference.md](docs/reference.md), manual update steps documented there. |
| 7  | Main thread vs Web Worker                      | Main thread v1, behind a `BarcodeDecoder` class for an easy later swap. |
| 8  | Camera constraints                             | `facingMode: { ideal: "environment" }`, `width: { ideal: 1920 }`, `height: { ideal: 1080 }`, **no `max`** — higher resolution helps decode small/distant labels and decode time stays within budget on the phones we care about. |
| 9  | `Permissions-Policy: camera=(self)` middleware | Yes. |
| 10 | CSP                                            | Out of scope — threat model does not justify it. |
| 11 | Role gating                                    | All authenticated roles (Technician through Owner) get **both** upload and live capture. See Prerequisites #2 for the upload-mode gate change. |
| 12 | Audit / logging                                | Only the confirmed scan (the one that triggers item lookup or transaction) is logged, same as today. |
| 13 | New DOM IDs                                    | `txn-scan-video`, `txn-scan-scan-btn`, `txn-scan-upload-btn`, `txn-scan-torch-btn`, `txn-scan-aimbox`; mirrored `items-scan-*`. |
| 14 | Bundling format additions in same PR           | No — separate work. |
| 15 | Live-feed visuals                              | Grayscale via `filter: grayscale(100%)` on `<video>`. Decoder still receives full-colour frames internally. Aim-box overlay: positioned `<div>` with thin high-contrast border, ~3:1 aspect ratio, guidance only — **no frame cropping in v1.** |
| 16 | Offline / PWA / installable                    | Out of scope. |
| 17 | Multiple barcodes in one frame                 | Discard the frame, wait for the next. |
| 18 | False-positive debounce                        | Accept decoded text X only when X appears in **≥5 of the last 10 frames.** Sliding window; reset on accept. Cheap, kills almost all single-frame misreads. |
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
2. **Prerequisites (separate PRs).** Bump session idle timeout to
   600 s; lower `/barcodes/decode` gate to any authenticated user. See
   Prerequisites section above.
3. **Phase 1 — decoder spike.** Vendor `@zxing/browser` to
   `backend/static/vendor/` with pinned-version filename and SHA-256
   in [docs/reference.md](docs/reference.md). Build a throwaway
   `/static/scan-test.html` that does nothing but camera-on,
   decode-loop, show decoded text plus the running debounce window.
   No auth, no router integration, no item lookup. Goal: prove the
   library works on the actual labels and phones the workers use,
   and shake out iOS Safari quirks. Open-ended exit criterion.
4. **Phase 2 — refactor `mountScanner`.** Extend
   [backend/static/views/scan.js](backend/static/views/scan.js#L40) to
   accept a mode (`upload` | `live`) without changing its callback
   contract. Add the `BarcodeDecoder` class (wraps ZXing, single
   `decodeFrame(videoEl): Promise<Result | null>` method). Existing
   callers at [backend/static/views/scan.js](backend/static/views/scan.js#L186-L199)
   and [backend/static/views/items.js](backend/static/views/items.js#L250-L269)
   keep working unchanged.
5. **Phase 3 — wire and ship.** Add the new DOM (video element, Scan /
   Upload / Torch buttons, aim-box overlay, permission-state
   messaging), the `Permissions-Policy: camera=(self)` middleware, the
   `visibilitychange` and section-leave lifecycle hooks, and the
   blocked-mode fallback. Both Prerequisites must already be merged.
   Ship to Transaction page first for a week, then Saved Items.

---

## Out of scope, explicitly

- CSP / HSTS / other security hardening (deferred; not justified by
  current threat model).
- Server-side preprocessing improvements (grayscale, retry pyramid,
  rotation passes in `decode_image`) — live capture removes most of
  the failure cases that motivated these; revisit only if needed.
- Additional 1D / 2D barcode formats — tracked separately.
- Offline / PWA / installable-app behaviour.
- Multi-decode per frame (decision #17).
- Camera switching UI (`enumerateDevices`-driven swap). Rear-camera
  default via `facingMode` is sufficient for v1; revisit if tablets or
  laptops need it.
- Aim-box → decode-region cropping. Overlay is guidance only in v1;
  crop only if false positives from outside the box become a problem.
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
