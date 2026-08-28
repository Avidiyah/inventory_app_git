# NetFacilities Cloud Auth (Per-User) — Design Spec

Status: **designed 2026-08-28, not yet implemented.** Follows
`docs/superpowers/specs/2026-08-28-netfacilities-live-session-design.md`
(IMP-039), which this spec builds on rather than replaces. No implementation
plan exists yet.

Lets **any** authorized user (TechFM OA+/Admin), on **any** device, from the
**deployed Render app**, interactively log into NetFacilities — credentials,
CAPTCHA, MFA — through a cloud browser, so the backend can read work-order
pages on their behalf for Task/Symptom + Priority enrichment. Today that
capability exists only for whoever is physically at a Windows machine with
this repo checked out (IMP-039's live session) or via the single shared
Render secret file someone refreshes from that Windows machine. This spec
does not touch either of those paths; it adds a third.

---

## 0. Why this exists

The owner's actual requirement, stated directly: *"I want a User not on my
machine to be able to do the enrichment by clicking a button to open
NetFacilities, downloading and uploading the CSV, leaving the window open and
logged in, and then clicking Import Tasks and Priority."* — i.e. the exact
UX IMP-039 built, but usable by someone who isn't at the owner's Windows
desktop and isn't limited to whichever machine holds the Playwright profile.

Render's web service is headless Linux with no display. Playwright can only
drive a browser a human can see and click into if that browser is running
somewhere with a screen — which Render's container is not, and a random
user's phone or Mac cannot provide either. A cloud browser platform
(Browserbase or Steel) solves exactly this: it runs the real browser in
their infrastructure and exposes a **live-view URL** — an embeddable page
where a human watches and directly controls that browser through their own
existing browser tab. The backend, on the same session, connects over CDP
(`chromium.connect_over_cdp`) exactly the way `NetFacilitiesClient` already
connects to a locally-launched context — the vendor is a transport swap, not
a rewrite of the read/parse/enrichment logic.

## 1. Research findings this design relies on

Verified against vendor docs 2026-08-28 (see citations at the end). Written
here because the design below depends on these specifics, not general
cloud-browser marketing claims.

| Question | Browserbase | Steel |
|---|---|---|
| Live-view / human-in-the-loop login | **Session Live View.** `bb.sessions.debug(session.id)` returns `debuggerFullscreenUrl` / `debuggerUrl`. Full interactive control (click, type, scroll); no special session flag needed. | `sessionViewerUrl` returned directly on `sessions.create()`. Interactive solving works on any plan; `solveCaptcha: true` is a separate paid *auto*-solve feature this design does not need — a human is already present. |
| Download capture | **Not automatic.** Must call CDP `Browser.setDownloadBehavior` (`behavior: "allow"`, `downloadPath`, `eventsEnabled: true`) after connecting. Retrieve via `GET /v1/downloads?sessionId=...`. | Same CDP call required. Retrieve via SDK `sessions.files.download(sessionId, path)` or `downloadArchive(sessionId)`; raw `GET /v1/sessions/{id}/files/{path}`. |
| Cookies reusable outside the platform, session closed | **Contexts API** persists cookies/storage across their sessions ("weeks or months") — but that's *their* persistence mechanism, not confirmation that a raw exported `storage_state()` works replayed independently. | **Profiles API** (`persistProfile: true`, reopen via `profileId`) — same caveat. |
| Free tier | 1 browser-hour, 3 concurrent, 15 min/session cap. | $30 one-time credit (Launch), 15 min/session cap, 10 concurrent. |

**The one open question neither vendor's docs settle:** whether a plain
Playwright `storage_state()` snapshot, captured during a session and then
replayed into a *fresh* session later with **no further involvement from
that vendor's persistence feature**, just works — the way this repo's
existing Render deployment already proves NetFacilities' own cookies behave
today with zero cloud-browser vendor in the picture at all. Neither vendor's
docs claim a restriction that would break this (no mention of session-scoped
proxies, IP-binding, or fingerprint-locking the cookies), but it is inferred,
not confirmed. §3 D5 covers how the plan verifies this before building
anything else on top of it, and §3 D6 is the fallback if it turns out false.

## 2. What this does *not* replace

- **IMP-039's local Windows live session is untouched.** It stays the
  zero-cost, zero-third-party-dependency path for whoever is at that
  machine. `services/netfacilities_auth.py` is not modified by this spec.
- **The single shared Render secret file stays as the fallback of last
  resort** (e.g. this feature is disabled, over budget, or the vendor is
  down) — `has_saved_authentication` / `use_saved_state` keep working
  exactly as today.
- This is a **third, additive** path: per-user cloud sessions, available
  only when `NETFACILITIES_CLOUD_AUTH_ENABLED=true` and a vendor API key is
  configured.

## 3. Decisions locked

| # | Decision | Choice |
|---|---|---|
| D1 | Vendor | **Steel.** Comparable feature set to Browserbase (§1), open-source core with a self-host escape hatch if usage costs become a problem, and `sessionViewerUrl` ships directly on session creation (one fewer round-trip than Browserbase's separate `.debug()` call). Wrapped behind a small internal protocol (`CloudBrowserProvider`, mirroring the existing `NetFacilitiesAuthenticationClientProtocol` pattern) so swapping to Browserbase later touches one adapter module, not the feature. |
| D2 | Session model | **Per-user.** Each authorized user has their own captured session, stored server-side keyed by `user_id`. No sharing, no "use whoever's session is live" fallback — using another person's captured NetFacilities cookies without their knowledge is exactly the kind of silent cross-user auth reuse this design avoids. |
| D3 | Login ceremony | User (any device) clicks **Log in to NetFacilities** on the deployed app. Backend creates a Steel session, returns `sessionViewerUrl`. Frontend opens it in a new tab (not an iframe — avoids X-Frame-Options / CSP friction with a third-party origin rendering interactive login for a vendor site). User completes credentials/CAPTCHA/MFA live, same as they would on the vendor's own site. Backend polls the same way IMP-039's `_auto_confirm` does — a local URL check, then the server-verified `GET /myhome` probe — reusing that logic against a CDP-connected client instead of a locally-launched one. |
| D4 | Download capture | Cloud sessions do not accept downloads by default the way a locally-launched persistent context does with `accept_downloads=True`. Immediately after `connect_over_cdp`, issue CDP `Browser.setDownloadBehavior` (`allow`, `eventsEnabled: true`). When the operator exports the CSV in the live-view tab, poll Steel's Files API for a new `.csv`, fetch it, and feed it through the existing `run_csv_import` — unchanged from IMP-039. |
| D5 | Session lifetime | **Short-lived, reconnect-per-job — not kept running.** After capturing `storage_state()`, the Steel session is allowed to end (or is explicitly closed) rather than billed continuously; this stays within the 15-minute/session cap and keeps cost near-zero for infrequent use. Enrichment opens a **fresh** short-lived Steel session on demand, replays the saved `storage_state()` into it via Playwright's `new_context(storage_state=...)`, runs the same read-only requests `NetFacilitiesClient` already makes, then closes it. **This is exactly the open question from §1 being exercised in production** — see D6 for what happens if it doesn't work. |
| D6 | Fallback if raw replay fails | If reconnect-with-replayed-`storage_state()` turns out to need Steel's own persistence (contrary to what the docs suggest), fall back to Steel's **Profiles API**: `persistProfile: true` at first login, store the returned `profileId` instead of (or alongside) the raw `storage_state()`, reopen sessions with `profileId` for enrichment. The data model (D8) stores both fields from day one so this fallback needs no migration — just a code path change. |
| D7 | Per-user expiry | `GET /session` (or a new `GET /session/mine`) reports state for the **calling user's own** cloud session, not one shared banner. A user whose session lapsed sees their own "log in again"; it says nothing about anyone else's. |
| D8 | Data model | New table `netfacilities_cloud_sessions`: `id`, `user_id` (FK, unique), `storage_state` (JSON), `steel_profile_id` (nullable, for D6), `signed_in_at`, `last_download_filename`, `last_download_at`, `expires_at` (nullable — set only once an enrichment attempt actually reports `authentication_required`, mirroring how expiry is detected today rather than guessed from a TTL). |
| D9 | Secret-safety | `storage_state` is a bearer-equivalent credential, same class as `playwright-storage-state.json` today — but this is the first time such credentials live in the primary Postgres database rather than one trusted local file or one Render secret file. That is a materially larger blast radius (every enrolled user's session, in the same DB as everything else, reachable by any code path with DB access) and needs its own hardening pass: encrypt `storage_state` at rest (e.g. via `pgcrypto` or an app-level envelope with a key from Render's secret store, not the DB itself), never return it or `steel_profile_id` in any API response, and never log it. This is the single biggest security delta from IMP-039 and deserves explicit sign-off before implementation, not an inherited assumption. |
| D10 | Enrichment routing | `POST /work-orders/enrich` uses the **calling user's own** cloud session if present and valid. If absent or expired, the response is the existing `authentication_required` shape (no automatic fallback to the shared secret file or another user's session — silently switching auth identity mid-request is a correctness and audit problem, not a convenience). `NetFacilitiesJobSnapshot.source` gains a third value, `cloud_session`, alongside today's `live_session` and `saved_state`. |
| D11 | Testing | Same offline-fakes style as IMP-039: a fake `CloudBrowserProvider` in tests, no live Steel API call in any automated test. The one thing that **cannot** be tested offline — whether D5's raw-replay assumption actually holds — is a manual spike task at the start of the eventual implementation plan, done once, by a human, against the real vendor and real NetFacilities, before any other task is built on top of it. |

## 4. Hard constraints

- Steel's 15-minute session cap bounds both the login ceremony (must be
  completed within one session) and each reconnect-per-job enrichment run.
  A batch large enough to exceed 15 minutes needs either a session refresh
  mid-job or a smaller batch size — flagged for the implementation plan to
  size against real batch counts (current local enrichment already runs
  hundreds of work orders per pass; this needs verifying against Steel's
  cap, possibly via periodic session renewal within one job).
- `NETFACILITIES_CLOUD_AUTH_ENABLED` (or similar) must default `false` —
  this feature requires a paid third-party account and should never turn on
  by a config drift the way the existing capability flags do.
- The vendor API key is itself a secret with production blast radius
  (anyone holding it can spin up billed sessions) — provisioned the same
  way as other Render secrets, never in `render.yaml` in plaintext.

## 5. Open questions for the implementation plan to resolve first

1. **The D5/D6 spike** — confirmed working, or does it need the Profiles
   fallback from day one? This gates almost everything else.
2. Batch size vs. the 15-minute session cap (§4).
3. Encryption-at-rest mechanism for D9 — `pgcrypto` vs. app-level envelope —
   is an infra decision this spec intentionally leaves to whoever writes
   the plan, informed by however secrets are already handled elsewhere in
   this deployment (`VAPID_PRIVATE_KEY` handling is the closest existing
   precedent to check first).

---

**Citations** (fetched 2026-08-28): [Browserbase Session Live View](https://docs.browserbase.com/features/session-live-view) · [Browserbase Downloads](https://docs.browserbase.com/platform/browser/files/downloads) · [Browserbase Contexts](https://docs.browserbase.com/platform/browser/core-features/contexts) · [Browserbase Pricing](https://www.browserbase.com/pricing) · [Steel Sessions API Quickstart](https://docs.steel.dev/overview/sessions-api/quickstart) · [Steel Files API](https://docs.steel.dev/overview/files-api/overview) · [Steel Profiles API](https://docs.steel.dev/overview/profiles-api/overview) · [Steel Pricing/Limits](https://docs.steel.dev/overview/pricinglimits)
