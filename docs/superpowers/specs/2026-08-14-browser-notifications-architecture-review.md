# Browser Notification Architecture Review

**Status: investigation only. Nothing here is implemented and nothing should be
until §26 is answered.**

Written 2026-08-14 against `main` at `f7904e4` (local in sync with
`origin/main`). Every claim about the repository below was established by
inspection at that commit; every claim about browser behavior is cited to a
primary source with a date.

This document does not live in `docs/`. That directory is the four consolidated
files from 2026-08-10 and `open-work.md` remains the only backlog. This is a
design reference in the same position as
`2026-08-12-websocket-realtime-layer-design.md`, and it deliberately mirrors that
document's structure because the two layers share a spine.

---

## 1. Executive Summary

**Web Push is appropriate for this application, and the hard part is not Web
Push.** The delivery mechanics are a solved, standardized problem that this
codebase can absorb with one small synchronous dependency and one new table. The
genuinely difficult and genuinely risky parts are the four things the prompt
correctly identified as prior: deciding what constitutes a notification event,
resolving recipients from relationships that actually exist, re-checking
authorization at delivery time rather than at decision time, and keeping a
browser subscription bound to the right human on a shared device.

Seven findings drive every recommendation that follows.

**1. The app already has a real-time delivery layer, and it is not a substitute
for push — it is the other half of the same feature.** `/ws` (`app/routers/
realtime.py`, shipped `f7904e4`) already authenticates a cookie-bearing socket,
maintains a per-user connection registry, hands events from request threads to a
supervised dispatch task over a bounded queue, and fans out by role. That layer
refreshes screens for people who are *looking at the app*. Push interrupts people
who are *not*. They should share one notification decision and diverge only at
the delivery step. Building push as a parallel, independently-routed system would
give the codebase two answers to "who should know about this?"

**2. The existing layer's `P2 — broadcast invalidation, not payloads` can and
should be preserved through push, and this is the single highest-value security
decision in the document.** A push message can carry an opaque notification id
rather than text; the service worker then fetches the display text from the API
with the session cookie and renders it. Content never touches the push service,
never sits in a payload that a stolen endpoint could reveal, and authorization is
re-verified by the existing REST layer *at the moment of display*. See §6.4. This
choice also rules out Apple's Declarative Web Push, which by design has no
service worker to do the fetch (§3.4).

**3. iOS is the binding constraint and it has not moved: Web Push on iPhone
requires the app to be added to the Home Screen.** It does not work in a normal
Safari tab. This was true at introduction in iOS 16.4 (2023-02-16) and remains
true through Safari 26 (2025). Two consequences the prompt did not anticipate:
iOS 26 removed all installability requirements, so a manifest is no longer
*required* to install — but installation is still a manual, unpromptable user
action Apple gives the site no API to trigger; and a Home Screen web app has its
own cookie jar, so **every iPhone user must log in a second time inside the
installed app**. That is a rollout and training cost, not a code cost, and it is
the most likely reason this project fails in practice.

**4. macOS Safari does not share that constraint.** Web Push works in ordinary
Safari tabs on macOS since Safari 16.1 (2022). "Safari" is not one platform here
and the compatibility matrix (§5) must be read per-OS, not per-browser.

**5. Delivery cannot happen inside a request handler.** Every route in this app
is a synchronous `def` running in a threadpool (72 HTTP operations, zero
`async def` handlers outside `/ws` — verified by inspection). Push delivery is N
outbound HTTPS calls to Google's and Apple's push services. Putting them in
`POST /work-orders/...` would violate `UX-7` (no new perceptible latency), an
invariant this codebase already holds itself to. The recommendation is a
**database-backed outbox drained by a second supervised task on the existing
lifespan hook** — not Redis, not Celery, not RQ. The lifespan hook already exists
for realtime dispatch, and the wake-on-enqueue-plus-bounded-queue pattern is
already written and tested in `services/realtime.py`. This adds one table and
zero infrastructure.

**6. Event-driven push works on the current Render free tier. Time-driven push
does not.** The free instance spins down when idle. An event-driven notification
is safe because the HTTP request that caused the event is itself proof the
process is awake. Anything phrased as *"...is overdue"*, *"...has been sitting in
Review for two days"*, or *"end-of-day summary"* requires a scheduler that
survives spin-down, which means a Render cron job or a paid always-on service.
Any notification type worded with a deadline is a hosting decision in disguise.

**7. Several routing dimensions named in the prompt do not exist in this
schema and must not be invented.** There is no reorder point or stock threshold
on `Item`, so "low inventory" has no trigger to fire from. There is no
department, no inventory-responsibility relation, no item ownership, and no
supervisor→subordinate *user* hierarchy beyond role rank. `Item.location` is a
free-text shelf string, not an ownership concept. What does exist is rich and
sufficient: work-order technician assignment, work-order supervisor routing,
tool custody, action initiator, role rank, and a ready-made pure authorization
predicate in `domain/work_orders.can_view_work_order`. §8 builds the routing
model out of those and labels the gaps explicitly.

**Recommendation:** proceed, natively (no FCM SDK, no OneSignal), in the phased
order in §24, with the Phase A proof-of-concept run on a real iPhone Home Screen
web app **before** any routing, preference, or notification-type code is written.
If the iPhone install step proves unacceptable to the crew, the correct outcome
is to stop and ship in-app notifications over the existing socket instead — which
would be a genuinely useful feature and requires no new delivery infrastructure
at all.

---

## 2. Existing Application Architecture

Established by inspection at `f7904e4`. Where this contradicts the prompt, the
repository is authoritative and the discrepancy is called out.

### 2.1 Stack, as built

| Layer | Reality |
|---|---|
| Frontend | No-build static SPA, plain ES modules, no bundler, no framework. `backend/static/`, ~33 non-vendor JS files. One vendored library (`@zxing/browser`) for camera scanning. |
| Backend | FastAPI 0.136.3 on Uvicorn 0.48.0, single process, **no `--workers`**. |
| Data | PostgreSQL via SQLAlchemy 2.0.50 + Alembic (32 revisions), Pydantic 2.13.4, psycopg 3. |
| Hosting | One Render Docker web service (`plan: free`) + one managed Postgres. Port 8124. |
| Transport | HTTP + one WebSocket route. `websockets==15.0.1` pinned explicitly because uvicorn is installed without `[standard]`. |

The prompt's stack description is accurate. It omits the WebSocket layer, which
is the single most important omission for this work.

### 2.2 Layer discipline

Strict and enforced by convention throughout: `routers → schemas/services →
domain/models → database`.

- `app/domain/*` — pure rules. No FastAPI, no SQLAlchemy, no I/O. Unit-testable
  standalone. `roles.py`, `work_orders.py`, `realtime.py`, `rate_limit.py`.
- `app/services/*` — DB queries, row locks, commits, state.
- `app/routers/*` — parse, authorize, delegate. Thin.
- `app/models.py` — the ORM schema. Routers and schemas never import it.

**A notification layer must respect this or it will be rejected on review.** The
concrete implication: routing rules and event vocabulary are *pure domain*
(`app/domain/notifications.py`), recipient resolution and outbox writes are
*services*, and the subscription endpoints are *routers*. Push-service HTTP calls
belong in a service, never in a domain module.

### 2.3 Users, authentication, authorization, sessions

- **`User`**: `id` (UUID), `username` (unique, login identity), `first_name` /
  `last_name` (nullable on legacy rows; drive all operational display),
  `password_hash` (scrypt), `role`, `created_at`, `archived_at` (soft delete).
- **Roles**: exactly four, strictly ranked — `owner(3) > admin(2) >
  supervisor(1) > technician(0)` (`app/domain/roles.py`). `role_at_least()` is
  the gate primitive. `can_manage()` requires strict outranking. Owner is created
  only by `backend/scripts/create_owner.py`.
- **Sessions** (`AuthSession`): server-side, opaque 256-bit token in an
  **HttpOnly, SameSite=Lax, Secure-in-production cookie named `session`**. The
  table stores **only the SHA-256 hash** of the token. Hard absolute
  `expires_at`, never NULL, no idle timeout. "Remember this device" changes only
  cookie persistence, not server lifetime.
- **Revocation is already thorough**: logout deletes the row; `services.users`
  deletes all of a user's sessions on archive, role change, and password reset.
  `get_active_session_user` rejects archived users.
- **Gates**: `Depends(get_current_user)` → 401; `require_min_role("admin")` →
  403. `auth_deps.py` is the only place that knows the cookie name.

**This is a strong foundation for push and it needs no changes.** Subscription
registration reuses `get_current_user` unmodified. The existing revocation paths
are exactly the hooks a subscription lifecycle needs (§10).

### 2.4 Domain entities relevant to notification routing

| Entity | Notification-relevant fields |
|---|---|
| `WorkOrder` | `number` (identity, CI-unique), `status`, `assigned_to_id` (legacy singular mirror), `supervisor_id`, `created_by_id`, `archived_at`, `completed_at`, `entry_mode`, `location` (raw text) |
| `WorkOrderTechnician` | **the real assignment relation** — `(work_order_id, technician_id)`, `assigned_by_id` |
| `WorkOrderLabor` | `technician_id`, `recorded_by_id`, `minutes` |
| `WorkOrderItem` | `created_by_id`, `mode`, `transaction_id` |
| `Transaction` | `user_id` (actor), `item_id`, `transaction_type` (stock/dispense/adjust), `work_order_id`, `voided_at`, `voided_by_id`, `affects_stock` |
| `UserRequest` | `request_type` (`inventory_recount` \| `missing_item_price` \| item request), `status`, `created_by_id`, `resolved_by_id`, `work_order_id`, `item_id` |
| `Tool` / `ToolTransaction` | `assigned_to_id` (**custody holder**), `performed_by_id` (**actor**) — deliberately distinct |
| `MassStage` | `community`, `building_name`, `status`, `created_by_id` |
| `Item` | `barcode`, `name`, `quantity`, `location`, `price`, `archived_at` |

**Work-order status workflow**: `created → assigned → in_progress → completed →
review`, with `on_hold` as a supervisor-controlled pause. Closed is
`archived_at`, not a status. Review requires Completed **plus a second person**
(Admin+ or the routed Supervisor, and the caller must not be assigned to the
work) — a two-person handoff already enforced server-side.

**Visibility scope** is a pure function, already written, already tested:

```python
# app/domain/work_orders.py
def can_view_work_order(role, *, created_by_id, assigned_to_id, user_id,
                        supervisor_id=None, assigned_to_ids=None) -> bool
```

Admin/Owner see all; a Supervisor sees unrouted work orders (the shared pickup
queue), work routed to them, and work where they are an assigned technician; a
Technician sees only work assigned to them. **This is the authorization check the
notification pipeline should call. Do not write a second one.**

### 2.5 What does NOT exist

Named here because §8 depends on not inventing them:

- **No stock threshold / reorder point / min-quantity column anywhere.** "Low
  inventory" has no trigger. The nearest real thing is the short-count path,
  which already raises a durable `UserRequest` when a dispense exceeds recorded
  on-hand.
- **No department, team, crew, or org-unit entity.**
- **No inventory-responsibility or item-ownership relation.** `Item.location` is
  a shelf string.
- **No supervisor→subordinate relation between users.** Role rank governs
  management authority; `WorkOrder.supervisor_id` is per-work-order routing, not
  a standing reporting line.
- **No explicit watch/subscribe-to-entity concept.**
- **No `notifications`, `preferences`, or `push_subscriptions` table.**
- **No service worker and no web app manifest.** Confirmed: nothing matching
  `sw.js`, `service-worker.js`, `manifest.json`, or any `.json` in
  `backend/static/`.
- **No background job table, scheduler, queue, Redis, or worker process.**
- **No email or SMS channel.** Push would be the app's first outbound
  communication of any kind.

### 2.6 The real-time layer (the most important existing precedent)

Shipped across five commits ending at `f7904e4`. Read
`docs/superpowers/specs/2026-08-12-websocket-realtime-layer-design.md` before
designing anything here.

**Its five principles**, which a notification layer either inherits or must
consciously and defensibly break:

- **P1 — the socket is never the system of record.** Every delivered fact is
  already durable in Postgres and reachable over REST.
- **P2 — broadcast invalidation, not payloads.** Events carry *what changed*, not
  *what it now is*. Recipients re-fetch through the existing API, which re-runs
  the server's own scoping. *This is what makes the socket structurally incapable
  of leaking anything REST would not already return.*
- **P3 — REST remains the only way state changes.** The socket never mutates.
- **P4 — degradation is invisible.** A dead socket means exactly today's app.
- **P5 — explicit over ambient.** One endpoint; all policy readable in one file
  because no middleware runs for a `websocket` scope.

**Its seven UX invariants**, `UX-1` through `UX-7`, most notably:

- `UX-2` — **No new UI. No nav entries, buttons, badges, toasts, banners,
  counters, or indicators.**
- `UX-4` — no permission changes; the socket reveals nothing REST would not.
- `UX-5` — no user-facing errors, ever. Failure is silent.
- `UX-6` — a live refresh never discards uncommitted input.
- `UX-7` — no new perceptible latency on any existing action.

**The tension, stated plainly.** A device notification is precisely the
narration `UX-2` forbids — *"Data freshens; it does not narrate."* This is not a
contradiction to paper over. `UX-2` was scoped to a specific promise: *adopting
real-time changes nothing about the app*. Notifications are a deliberate product
change with a deliberate user-visible surface, so they are a **new decision**,
not a violation of the old one. But the boundary must be written down, because
the failure mode is real: someone adds an in-app toast "because we have
notifications now" and silently breaks a shipped invariant. The recommended rule
is in §12.

**What the socket layer gives push for free, conceptually and in code:**

| Existing | Reusable for push |
|---|---|
| `Connection` registry keyed by **user**, cap 6/user | The insight that delivery targets are per-user, multi-device |
| `emit()` — non-blocking, bounded, total, never raises | The exact handoff shape the outbox drain needs |
| `_supervised_dispatch` / `DispatchSupervisor` | A written, tested bounded-restart supervisor for a second background task |
| `lifespan` in `routers/realtime.py` | **The startup/shutdown hook already exists.** It is the app's only one. |
| `_revalidation_loop` (60s re-resolve of session identity) | The precedent that long-lived authorization must be re-checked, not trusted |
| `audience_allows(event_type, role)` fail-closed map | The shape of an event→audience vocabulary |
| `static/realtime.js` `subscribe()` + backoff | A client event bus that a push-enabled UI can share |

**What it cannot do, which is why push is being considered at all:** the socket
only delivers to a browser tab that is open and connected. A technician whose
phone is in their pocket receives nothing. That gap is the entire justification
for this project and should be stated to stakeholders in exactly those terms.

### 2.7 Configuration, deployment, migrations

- **Env vars** (`render.yaml`): `DATABASE_URL` (from the managed DB, never in
  git), `COOKIE_SECURE=true`, `SQL_ECHO=false`, `LOG_LEVEL=INFO`. Also read in
  code: `LOGIN_THROTTLE_PER_IP`.
- **`COOKIE_SECURE` is the de-facto "this is production" flag** — it gates the
  cookie Secure attribute, HSTS, *and* whether FastAPI's `/docs`, `/redoc`, and
  `/openapi.json` exist at all. A new secret should follow the same discipline.
- **Migrations**: `entrypoint.sh` runs `alembic upgrade head` on every cold
  start. Its own comment notes this cannot race on one instance and must be
  revisited before a second.
- **Deploy gate**: `autoDeploy: false`; `.github/workflows/ci.yml` runs the
  backend suite, JS `node --check`, `compileall`, a single-Alembic-head check, a
  migration round-trip, and a **blocking `pip-audit`** — then curls the Render
  deploy hook. **A new dependency must survive `pip-audit` or main goes red and
  nothing deploys.** A dashboard Manual Deploy bypasses all of this (observed
  2026-08-10).
- **Static serving**: `NoCacheStaticFiles` stamps `Cache-Control: no-cache` on
  every asset and `/` re-reads and concatenates 13 HTML fragments per request.
  Both exist specifically to defeat a real blank-page stale-cache failure. **This
  is the single most important fact for §12.**
- **Security headers**: CSP `default-src 'self'` with narrow `img-src`/`media-src`
  additions, `object-src 'none'`, `frame-ancestors 'none'`, `nosniff`,
  `Referrer-Policy: same-origin`, `X-Frame-Options: DENY`, HSTS in production.
  Verified against the whole SPA — no inline script, no `on*` handlers, no
  `eval`.
- **Rate limiting**: in-process sliding window, 60 req/s/caller, keyed on a
  hash of `(session token, IP)`. Exempt paths skip the counter.
- **Logging**: structured, `request_id` per request via contextvar, `user_id`
  bound in `get_current_user`. Query strings deliberately never logged.

---

## 3. Current Safari Support

### 3.1 macOS Safari — works in ordinary tabs

Web Push shipped in **Safari 16.1 on macOS Ventura (2022)**, using standard Web
Push (RFC 8030 / 8291 / 8292) with VAPID. No installation required; a normal
tab can subscribe. Permission must be requested from a user gesture. Users
manage permission in Safari → Settings → Websites → Notifications, and macOS
Notification Center settings.

### 3.2 iOS / iPadOS Safari — Home Screen web apps only

From the WebKit announcement, **2023-02-16**, *"Web Push for Web Apps on iOS and
iPadOS"*:

> "Now with iOS and iPadOS 16.4, we are adding support for Web Push to Home
> Screen web apps."

> "A web app ... can request permission to receive push notifications as long as
> that request is in response to direct user interaction — such as tapping on a
> 'subscribe' button."

> "the user can manage those permissions per web app in Notifications Settings —
> just like any other app."

Apple explicitly stated **no Apple Developer Program membership is required**,
and that delivery uses APNs as the transport under standard Web Push semantics.

**This restriction has not been lifted.** Verified against WebKit's Safari 18.4
(2025-03-31) and Safari 26.0 posts: neither announces push in ordinary iOS Safari
tabs. Safari 26.0's release notes contain no Web Push section at all; the only
push-adjacent change is DevTools automatically inspecting and pausing service
workers, *"useful ... with Web Push events where the Service Worker has already
handled the incoming push."*

### 3.3 The iOS 26 installability change — real, and helpful, but not what it
sounds like

WebKit's Safari 26.0 notes state that on iOS 26 / iPadOS 26:

> "By default, every website added to the Home Screen opens as a web app. If the
> user prefers to add a bookmark for their browser, they can disable 'Open as
> Web App' when adding to Home Screen."

> "Simply put, there are now zero requirements for 'installability' in Safari."

**What this changes:** a manifest with `display: standalone` is no longer
*required* for a site to install as a web app on iOS 26+. On iOS 16.4–18.x it
was.

**What this does not change:** the user must still perform Share → Add to Home
Screen **by hand**. iOS gives the site no `beforeinstallprompt` equivalent, no
API to trigger it, and no way to detect that the user declined. Push still
requires the installed web app.

### 3.4 Declarative Web Push — available, and the wrong choice here

Safari 18.4 (2025-03-31, iOS/iPadOS 18.4, macOS Sequoia 15.4, visionOS 2.4)
introduced Declarative Web Push, which *"displays instantly without requiring a
Service Worker"* and avoids *"additional battery and CPU resources."* On iOS it
is likewise limited to Home Screen web apps.

**Reject it for this application.** Its entire benefit is that no service worker
runs — which means the notification text must travel *inside the push payload*.
That forfeits the fetch-on-display design in §6.4, which is the mechanism that
keeps `P2` intact and keeps operational text out of the push service. Standard
service-worker Web Push is supported on every target platform and gives strictly
more control. Declarative Push is a reasonable fit for a news site; it is the
wrong trade for an app whose notification text names people, buildings, and
units.

### 3.5 The EU question — settled, and the widely-repeated claim is wrong

Third-party sources still assert that iOS Web Push is unavailable in the EU.
That is stale. Apple announced removal of Home Screen web apps in the EU in the
iOS 17.4 beta, then **reversed it before release in March 2024**; Home Screen web
apps and their push capability continue to work in the EU, still built on WebKit.
Not operationally relevant to a US field crew, but it is the kind of claim that
gets pasted into a design doc and never re-checked.

### 3.6 The consequence nobody plans for: the second login

A Home Screen web app on iOS gets **its own storage and cookie jar**, separate
from Safari. The `session` cookie established by logging in through Safari does
not exist inside the installed app.

Every iPhone user will therefore: install to Home Screen → open the app → see the
login screen again → log in → *then* be able to enable notifications. Nothing in
the code prevents this and nothing can. It must be in the rollout instructions,
and it interacts with the 12-hour absolute session cap: an installed app left
untouched overnight requires a fresh login, and **a logged-out installed app
cannot receive push if the design ties subscription validity to an active session
(it should — see §10.2).**

---

## 4. Current Chrome Support

### 4.1 Android Chrome

Full, unremarkable support: service workers, Push API, Notifications API,
VAPID, background delivery while the browser is closed (Android keeps the push
channel alive at the OS level). Works in a normal tab; does not require
installation. An installed PWA also works and is treated as a separate install
surface.

### 4.2 Desktop Chrome (Windows / macOS / Linux)

Works in a normal tab. The operational caveat: **delivery requires Chrome to be
running**, including its background process. If Chrome is fully quit, messages
are held by the push service and delivered on next launch, subject to the `TTL`
header. For an ops tool where a notification loses value quickly, set a short
TTL rather than letting a two-day-old backlog arrive at once.

### 4.3 Requirements Chrome imposes that Safari does not

- **`userVisibleOnly: true` is mandatory.** MDN: Chrome and Edge *"will reject
  the Promise if `userVisibleOnly` is not set to `true`."* Silent push is not
  available. Every delivered push must result in a visible notification, or
  Chrome may show a generic "This site has been updated in the background"
  notification on your behalf and, on repetition, revoke the permission.
  **Design consequence:** the service worker's `push` handler must show a
  notification on *every* path, including the failure path where its
  authenticated fetch returns 401 or the network is down (§6.4).
- **`applicationServerKey`** is a base64url ECDSA P-256 public key; supplying it
  binds the subscription to that key and requires every message to carry a VAPID
  JWT signed by the matching private key.

### 4.4 VAPID means no Firebase project

Chrome's push endpoints are `https://fcm.googleapis.com/...`, which routinely
misleads people into provisioning Firebase. With VAPID, no Google Developer
project, no `gcm_sender_id`, and no server API key are needed; the endpoint URL
is used directly as a standard Web Push Protocol endpoint, the same way Firefox's
and Apple's are. **Chrome support does not imply an FCM dependency.**

### 4.5 Permission-prompt and permission-lifetime behavior

Three Chrome behaviors that shape the UX design and the failure model:

- **Quieter prompts** (Chrome 80+): users who habitually block, and sites with
  low acceptance rates, get a subdued bell icon instead of a modal. A site that
  prompts cold, at page load, earns this treatment.
- **Abusive-notification enforcement**: Chrome automatically revokes permission
  from sites Safe Browsing flags, and rate-limits high-volume low-engagement
  domains.
- **Automatic revocation for disengagement** (announced 2025-10-10): Chrome
  automatically removes notification permission from sites with *"very low user
  engagement and a high volume of notifications being sent."* Google notes
  *"less than 1% of all notifications receive any interaction."* Crucially:
  **installed web apps are excluded from this policy.**

For a daily-use work tool the engagement criterion should never bite, but two
design consequences follow anyway: keep volume genuinely low (which the routing
model in §8 does by construction), and treat *permission silently disappearing*
as a normal, expected state that the app must detect and offer to repair — not an
error (§11.5).

---

## 5. Browser Compatibility Matrix

| Platform | Install state | Push API | Notifications | Service worker | Notes |
|---|---|---|---|---|---|
| **iOS / iPadOS Safari** | Normal tab | ❌ **No** | ❌ | ✅ | Not supported in any iOS version to date. Must detect and instruct. |
| **iOS / iPadOS Safari** | Home Screen web app | ✅ Yes (16.4+) | ✅ | ✅ | Manual install only. Separate cookie jar → second login. Manifest required <iOS 26, optional ≥26. |
| **Android Chrome** | Normal tab | ✅ Yes | ✅ | ✅ | Background delivery via OS channel. Subject to auto-revocation policy. |
| **Android Chrome** | Installed PWA | ✅ Yes | ✅ | ✅ | Exempt from disengagement auto-revocation. |
| **Desktop Chrome** | Normal tab | ✅ Yes | ✅ | ✅ | Requires Chrome running/background process; TTL governs held messages. |
| **Desktop Chrome** | Installed PWA | ✅ Yes | ✅ | ✅ | Exempt from auto-revocation. |
| **macOS Safari** | Normal tab | ✅ Yes (16.1+) | ✅ | ✅ | **No installation required.** The key Safari asymmetry. |
| **macOS Safari** | Added to Dock | ✅ Yes | ✅ | ✅ | Same capability, separate permission/storage scope. |

**The four differences that matter most:**

1. **iOS Safari tab vs. iOS Home Screen app** — the difference between "no
   feature" and "full feature". This is the only hard capability gap in the
   matrix.
2. **iOS Safari vs. macOS Safari** — same vendor, same brand, opposite install
   requirements. Never reason about "Safari" as one target.
3. **Chrome vs. Safari on `userVisibleOnly`** — Chrome mandates a visible
   notification per push; the service worker must guarantee one on every code
   path.
4. **Chrome permission auto-revocation vs. Safari's** — Chrome may take
   permission away on its own; installed apps are exempt. Plan for silent
   permission loss on Chrome-in-a-tab.

Universal preconditions across all supported rows: **HTTPS** (satisfied by
Render), a **registered service worker**, **VAPID keys**, and permission granted
**from a user gesture**.

---

## 6. How Web Push Actually Works

### 6.1 The components, and who owns each

| Component | Owner | Role |
|---|---|---|
| Application frontend | Us | Explains value, captures the gesture, calls `subscribe()`, POSTs the result |
| Service worker | Us | Background script; receives `push`, displays notification, handles `notificationclick`, `pushsubscriptionchange` |
| Notifications API | Browser | `Notification.requestPermission()`, `registration.showNotification()` |
| Push API / `PushManager` | Browser | `registration.pushManager.subscribe({userVisibleOnly, applicationServerKey})` |
| `PushSubscription` | Browser | `{endpoint, keys:{p256dh, auth}}` — **treat as a credential** |
| Browser push service | Google / Apple / Mozilla | `fcm.googleapis.com` (Chrome), `web.push.apple.com` (Safari). Routes to the device. Never sees plaintext. |
| VAPID keypair | Us | ECDSA P-256. Public half → browser at subscribe. Private half → signs a JWT per send. Identifies the sender; does **not** encrypt. |
| Application backend | Us | Decides, routes, authorizes, encrypts, sends, records, cleans up |
| PostgreSQL | Us | Subscriptions, notification records, delivery state |

**Two independent key systems, routinely conflated:**

- **VAPID (RFC 8292)** — an ECDSA P-256 keypair *we* own. Authenticates *us* to
  the push service. One pair per environment, long-lived.
- **Payload encryption (RFC 8291)** — ECDH using `p256dh` + `auth` *from the
  subscription*. Per-subscription. The push service cannot read the payload.

A leaked VAPID private key does **not** by itself let an attacker read anything;
combined with leaked subscription rows it lets them forge notifications (§17).

### 6.2 The corrected network path

The prompt's straw-man is close. Three corrections:

```
  DOMAIN ACTION                      (POST /work-orders/{id}/technicians)
      ↓                              synchronous, in-request, committed
  DOMAIN EVENT recorded              same DB transaction as the change  ← [1]
      ↓
  NOTIFICATION RULE EVALUATION       pure domain: is this notifiable?
      ↓
  RECIPIENT RESOLUTION               DB: who, from real relations
      ↓
  AUTHORIZATION CHECK                can_view_work_order() per recipient
      ↓
  PREFERENCE CHECK                   opt-out lookup
      ↓
  NOTIFICATION RECORD                durable row, one per recipient
      ↓                              ══ HTTP request returns here ══     ← [2]
      ↓
  DELIVERY DRAIN                     background task on the lifespan
      ↓
  SUBSCRIPTION LOOKUP                all active subs for that user
      ↓
  ENCRYPT + SIGN                     RFC 8291 payload, RFC 8292 JWT
      ↓
  POST to push service               fcm.googleapis.com / web.push.apple.com
      ↓                              → 201 / 404 / 410 / 429 / 5xx        ← [3]
  DEVICE                             OS wakes the browser
      ↓
  SERVICE WORKER `push` event
      ↓
  SW fetches display text            GET /notifications/{id} w/ cookie    ← [4]
      ↓
  showNotification()                 MUST happen on every path
      ↓
  OS/BROWSER NOTIFICATION
      ↓
  notificationclick → clients.openWindow / focus + navigate
```

**[1]** The notification decision is made *inside the originating transaction*.
If the work-order write rolls back, no notification exists. Deciding afterward
from a separate read creates a window where a rolled-back change notifies people.

**[2]** The request returns after the durable record is written and **before any
network call to a push service**. This is what preserves `UX-7`.

**[3]** The response code is the whole cleanup story. **404/410 → delete the
subscription. 401/403 → this is a VAPID configuration failure; alert, and delete
nothing.** A naive "any 4xx deletes the row" wipes the entire table the first
time someone fat-fingers a key. This is the single most destructive plausible bug
in the system.

**[4]** The step the prompt's version omits, and the most important one — §6.4.

### 6.3 What travels on the wire

The push service sees: our VAPID JWT (public key + `aud`/`exp`/`sub`), the
endpoint, TTL/urgency headers, and an opaque encrypted blob (≤4096 bytes across
implementations). It cannot decrypt the payload. It *does* learn that our origin
sent a message to that device at that time — unavoidable metadata, and one more
argument for low volume.

### 6.4 The recommended payload design — an id, not a sentence

**Recommendation: the encrypted payload carries an opaque notification id and
nothing else. The service worker fetches the display text.**

```js
// sw.js — sketch only, not implementation
self.addEventListener("push", (event) => {
  event.waitUntil((async () => {
    let title = "Inventory App", body = "You have a new notification.";
    try {
      const { id } = event.data.json();
      const res = await fetch(`/notifications/${id}/display`, {
        credentials: "include", cache: "no-store",
      });
      if (res.ok) ({ title, body } = await res.json());
    } catch { /* fall through to the generic text */ }
    // Unconditional: Chrome's userVisibleOnly contract.
    await self.registration.showNotification(title, { body, tag: /* … */ });
  })());
});
```

**Why this is the right call for this codebase specifically:**

- **It preserves `P2` end-to-end.** The push message is an invalidation carrying
  an identifier, exactly like the WebSocket envelope's `{type, id, req}`. The
  architecture stays coherent across both channels.
- **Authorization is re-checked at display time**, by the existing REST layer,
  against the session that actually exists on that device *right now* — not
  against the authorization that held when the event was queued minutes or hours
  earlier. Reassignment, archival, role demotion, and logout all invalidate a
  queued notification for free.
- **A stolen or leaked subscription row reveals nothing.** Even an attacker who
  can decrypt the payload gets a UUID.
- **The server chooses the redaction**, in one place, on a route that is
  reviewable — rather than at each of N emit sites.

**The costs, honestly:**

- **One extra round-trip** before display. Milliseconds in practice.
- **It cannot work with Declarative Web Push** (§3.4). Accepted.
- **If the device has no valid session, the fetch 401s** and the user sees the
  generic text. Correct behavior: a logged-out device should not be shown work
  details. It also means the notification is nearly useless — which is the
  argument for deleting subscriptions on logout (§10.2), so it never arrives.
- **Offline devices get generic text.** Acceptable; the push arrived because the
  device came online, so the fetch usually succeeds.

**The alternative — text in the payload — is not unreasonable** and is simpler,
but it puts operational text ("Work order 44821, Building 7 Unit 3B assigned to
you") into a blob that is decryptable by anything holding the subscription keys,
and freezes the text at queue time. Given §7's lock-screen requirement, the
fetch design costs little and buys a lot.

---

## 7. Proposed Notification Domain Model

The separation the prompt asks about is real, and collapsing any of these into
its neighbor causes a specific, nameable failure.

### 7.1 The nine concepts, and why each is distinct

| Concept | Definition | What collapsing it costs |
|---|---|---|
| **Domain event** | Something that happened, in the app's own vocabulary. `WorkOrderTechnicianAssigned`. | Merge with *notification event* and the domain grows a notification dependency; every future rule change edits business code. |
| **Notification event** | A domain event that the rules say *may* warrant telling someone. | Merge with *delivery* and you get `event → send to everybody`, exactly what the prompt forbids. |
| **Notification rule** | Pure function: given the event, produce candidate recipients + a reason. | Merge with recipient and rules become unreadable joins. |
| **Notification recipient** | A resolved `user_id` **plus the reason they qualified**. | Drop the reason and you cannot authorize, explain, or debug. |
| **Authorization decision** | May this user know this fact *right now*? | **Never merge with rule.** A rule says who *should* care; authorization says who *may*. Different questions, different answers, different failure severity. |
| **Notification preference** | Does this user *want* to be interrupted by this type? | Merge with authorization and turning off a preference silently removes in-app access. §16 makes this explicit. |
| **Notification** | The durable per-recipient record. One event → N notifications. | Without it there is no "was this person told?" and no in-app fallback. |
| **Delivery** | One attempt to one subscription through one channel. | Merge with notification and retry state becomes per-person rather than per-device, so one dead phone re-notifies everything. |
| **Push subscription** | One browser profile's push credential. | Merge with device or user and every scenario in §9 breaks. |

### 7.2 The pipeline, and where each stage lives

```
Domain action (service, in transaction)
   └─ emits ──▶ Domain event  ─────────────── app/services/*  (existing code)
                    │
                    ▼
        ┌───────────────────────────┐
        │ Notification rule         │  app/domain/notifications.py   PURE
        │  event → [candidate,      │  no I/O, unit-testable
        │           reason]         │
        └───────────────────────────┘
                    │
                    ▼
        ┌───────────────────────────┐
        │ Recipient resolution      │  app/services/notifications.py
        │  reason → user_ids        │  DB reads only
        └───────────────────────────┘
                    │
                    ▼
        ┌───────────────────────────┐
        │ Authorization             │  domain/work_orders.can_view_work_order
        │  drop anyone not allowed  │  domain/roles.role_at_least
        └───────────────────────────┘   ← EXISTING CODE, do not duplicate
                    │
                    ▼
        ┌───────────────────────────┐
        │ Preference                │  services/notifications
        │  drop anyone opted out    │  (mandatory types skip this)
        └───────────────────────────┘
                    │
                    ▼
        ┌───────────────────────────┐
        │ Notification records      │  one row per surviving recipient
        │  written in the SAME txn  │  ← the outbox
        └───────────────────────────┘
                    │  ══ request returns ══
                    ▼
        ┌───────────────────────────┐
        │ Delivery drain            │  background task, lifespan-owned
        │  → subscriptions → push   │  re-checks auth before sending
        └───────────────────────────┘
```

**`InventoryChanged` does not mean `SendPushNotification`.** It means: evaluate
rules. Most of the time, for most recipients, the answer is *no notification*,
and that is a healthy system rather than a broken one.

### 7.3 Authorization is evaluated twice, deliberately

Once at decision time (to avoid writing a record for someone who may not know)
and again at delivery/display time (because minutes or hours have passed).
§6.4's fetch-on-display makes the second check nearly free — it is the existing
REST authorization, unmodified. **Never send information to a device merely
because a row exists in `push_subscriptions`.**

---

## 8. Notification Routing Model

### 8.1 Routing dimensions — audited against the schema

| Dimension | Exists? | Where |
|---|---|---|
| User (direct) | ✅ | `users.id` |
| Role | ✅ | `users.role`, `domain/roles.role_at_least` |
| Work-order technician assignment | ✅ | `work_order_technicians` (plural, authoritative) + `work_orders.assigned_to_id` (legacy mirror) |
| Work-order supervisor routing | ✅ | `work_orders.supervisor_id` |
| Work-order creator | ✅ | `work_orders.created_by_id` |
| Unrouted pickup queue | ✅ | `supervisor_id IS NULL` + `can_view_work_order` |
| Action initiator | ✅ | `transactions.user_id`, `tool_transactions.performed_by_id`, `work_order_labor.recorded_by_id`, `work_order_items.created_by_id` |
| Tool custody holder | ✅ | `tool_transactions.assigned_to_id` (distinct from actor) |
| Request creator / resolver | ✅ | `user_requests.created_by_id` / `resolved_by_id` |
| Mass-stage creator | ✅ | `mass_stages.created_by_id` |
| Community (derived) | ⚠️ Derived | Computed from `work_orders.location` text; a **filter**, not an ownership relation. Usable for scoping, not for "whose job is this". |
| Building / unit | ⚠️ Partial | `building_number` / `unit_number` populated only on some rows; raw `location` is deliberately unparsed. |
| Supervisor→subordinate (standing) | ❌ **No** | Only role rank and per-work-order routing. |
| Department / team | ❌ **No** | No entity. |
| Location responsibility | ❌ **No** | `items.location` is a shelf string. |
| Item ownership | ❌ **No** | No relation. |
| Inventory responsibility | ❌ **No** | No relation. |
| Explicit watch/subscribe | ❌ **No** | No entity. Cheapest future addition if needed. |
| Stock threshold / reorder point | ❌ **No** | **No column exists.** "Low inventory" has no trigger without new schema and a business decision about per-item thresholds. |

**Four of the prompt's suggested dimensions do not exist and must not be
invented: department, location responsibility, item ownership, and standing
supervisor/subordinate relationships.** A fifth, "low inventory", has no data to
fire from.

### 8.2 The recipient-reason vocabulary

Rules should emit `(user_id, reason)` pairs, never bare ids. Proposed reasons,
each backed by a real relation:

`ASSIGNED_TECHNICIAN` · `ROUTED_SUPERVISOR` · `WORK_ORDER_CREATOR` ·
`TOOL_CUSTODIAN` · `REQUEST_CREATOR` · `ADMIN_QUEUE` (role ≥ admin) ·
`PICKUP_QUEUE` (supervisors, unrouted work) · `ACTION_INITIATOR` (almost always
used to **exclude**, not include)

**The actor-exclusion question is a genuine open decision (§26).** The realtime
layer resolved it in the opposite direction on purpose — invalidations always
refresh, including the actor's own, because a user id cannot distinguish the tab
that made a write from the same person's other device. For *push*, the reasoning
inverts: notifying someone about a thing they just did is noise, and volume
directly determines whether Chrome revokes the permission. Recommendation:
**exclude the initiator by default, per-type overridable.** Note explicitly that
this differs from the socket's rule and why, or someone will "fix" the
inconsistency later.

### 8.3 Fail-closed vocabulary

Mirror `domain/realtime.audience_allows`: an event type with no registered rule
reaches **nobody**. Adding an event without adding a rule must be a silent no-op,
never a broadcast.

---

## 9. User / Device / Subscription Model

### 9.1 The shape

```
User  1 ────< n  PushSubscription
```

**One table. `Device` is not warranted.** A `Device` entity would only earn its
place if the app needed to address a physical device across browsers, or show
users a device list with stable identity. Neither is true, and browsers
deliberately make cross-browser device identity impossible. A subscription
already *is* the addressable unit: one browser profile on one device.

### 9.2 Fields, with a privacy verdict on each

| Field | Verdict | Reasoning |
|---|---|---|
| `id` UUID PK | ✅ Required | Consistent with every other table |
| `user_id` FK → users, `ON DELETE CASCADE` | ✅ Required | Deleting a user must not orphan a push target |
| `endpoint` TEXT **UNIQUE NOT NULL** | ✅ Required | The address. **UNIQUE is load-bearing** — §10.1 |
| `p256dh` TEXT | ✅ Required | RFC 8291 encryption |
| `auth` TEXT | ✅ Required | RFC 8291 encryption |
| `created_at` | ✅ Required | Age, debugging |
| `last_success_at` | ✅ Recommended | The only signal that a subscription is alive |
| `last_failure_at` + `failure_count` | ✅ Recommended | Bounded retry; distinguishes flaky from dead |
| `label` (user-typed, e.g. "work phone") | 🟡 Optional, later | Only if a manage-devices UI is built. **User-supplied beats sniffed.** |
| `user_agent` (raw) | ❌ **Do not store** | A high-entropy fingerprint. Not needed — the endpoint host already tells you Apple vs Google, which is the only distinction that affects behavior. |
| `browser` / `os` / `device_model` (parsed) | ❌ Not for MVP | Same objection, less data. Add only when a support workflow demonstrably needs it. |
| IP address | ❌ **Never** | Location tracking of employees. No delivery purpose whatsoever. |
| `disabled_at` (soft delete) | ❌ Prefer hard delete | A dead endpoint has no audit value and a retained row is a permanent leak target. Delete on 404/410 and on logout. Keep counts in logs, not rows. |

**Privacy stance, stated for the record:** this is an employee-monitoring-adjacent
surface. Storing per-device browser/OS/IP metadata about a work crew creates a
capability nobody asked for and a liability nobody wants. The delivery path needs
exactly four fields — `user_id`, `endpoint`, `p256dh`, `auth`. Everything else
must justify itself against a named operational need.

### 9.3 Every scenario in the prompt, resolved

| Scenario | Behavior |
|---|---|
| One user, one phone | One row. |
| One user, multiple devices | N rows, same `user_id`. Fan-out to all. Already the socket registry's model (`MAX_CONNECTIONS_PER_USER = 6`, *"phone-plus-desktop is legitimate"*). |
| One user, Safari + Chrome on one machine | Two rows — different browser profiles, different endpoints. Correct, not a duplicate. |
| **Multiple users, one shared computer** | **Handled by `UNIQUE(endpoint)` + reassign-on-register.** Registering an endpoint already owned by another user **transfers** it. The browser profile has one push channel; its owner is whoever is currently authenticated. Combined with delete-on-logout, this is airtight — §10.1. |
| User logs out | Server deletes the row (authoritative); client calls `subscription.unsubscribe()` (best-effort). Either alone fails safe. |
| User switches accounts | Logout deletes; the new user's opt-in creates a new row. If logout was skipped, reassign-on-register catches it. |
| Permission revoked in browser | Push service returns 404/410 → delete. Client detects `Notification.permission !== "granted"` on next load and offers re-enable. |
| Subscription invalidated / rotated | Browser fires `pushsubscriptionchange` in the SW → re-subscribe → POST the new one. **Safari's support for this event is unreliable**; the belt-and-braces fix is a cheap re-assert of the current subscription on app boot. |
| Device replaced | Old endpoint goes dead → 410 → deleted. New device subscribes fresh. Self-healing, no user action. |
| Browser data cleared | Subscription and SW destroyed. Server row goes stale → 410 → deleted. User must opt in again. |
| Device stolen | **Requires an explicit answer.** Archiving the user cascades the rows away (`ON DELETE CASCADE`) *if* the account is archived. A "sign out all devices" action does not exist today; `services.users` already deletes all sessions on password reset, which should also delete all subscriptions. §26. |

---

## 10. Authentication and Authorization Analysis

### 10.1 Wrong-account subscriptions on a shared device

**The scenario:** User A logs in on the shop computer, enables notifications, logs
out. User B logs in. Does B receive A's notifications?

**With a naive design, yes** — the browser's push channel persists across logins
and the row still says `user_id = A`. A's notifications would arrive on a machine
now operated by B. Because §6.4's payload is only an id, B would not see A's
*content* (the display fetch runs as B and would 403/404) — but B would see that
notifications exist, and the generic fallback text would appear. That is a
disclosure of activity metadata and a serious confusion hazard.

**Three mechanisms, layered, and the design is safe if any one holds:**

1. **`UNIQUE(endpoint)` with reassign-on-register.** `POST /push/subscriptions`
   upserts by endpoint and sets `user_id` to the *currently authenticated* user,
   replacing any prior owner. One browser profile has exactly one push channel;
   its rightful owner is whoever is authenticated in it now.
2. **Delete on logout.** `POST /auth/logout` already deletes the session row; it
   should also delete subscriptions matching the endpoint the client reports.
   The client calls `unsubscribe()` first and sends the endpoint it is
   abandoning.
3. **Re-authorize at display.** §6.4's fetch runs with B's cookie against the
   existing REST authorization, so A's content cannot render for B under any
   circumstance.

**Mechanism 3 is the safety net and must never be skipped**, because 1 and 2 both
depend on a network call that can fail. Together they mean the worst realistic
outcome on a shared device is a generic "You have a new notification" that
resolves to nothing when tapped.

### 10.2 Subscription theft

**Could a malicious user submit someone else's endpoint?** They would first have
to *obtain* it — it is never exposed by the API, never logged, and never sent to
the client except as the browser's own local object. Assume they did.

**The result is not what intuition suggests.** Registering a victim's endpoint
under the attacker's `user_id` causes the attacker's notifications to be pushed
**to the victim's device**. The attacker receives nothing — they do not hold the
private key that decrypts the payload, and it is not their device. So:

- **Not a disclosure vector.** It is a spam/annoyance vector aimed at the victim,
  and a self-denial-of-service for the attacker.
- **It denies the victim their own notifications** until they re-register, which
  happens automatically on their next app boot (the re-assert in §9.3), because
  reassign-on-register works in both directions.

**Required controls regardless:**
- Registration is authenticated (`Depends(get_current_user)`) — no anonymous
  endpoint submission, ever.
- Validate the endpoint's **origin against an allowlist of known push services**
  (`*.push.apple.com`, `fcm.googleapis.com`, `*.push.services.mozilla.com`).
  Without this, `POST /push/subscriptions` becomes a blind SSRF primitive: the
  attacker names any internal URL and the app dutifully POSTs to it from inside
  Render's network. **This is the most important input validation in the
  feature.**
- Rate-limit registration (the existing 60/s limiter covers it; a per-user
  ceiling on total subscriptions — say 10 — bounds table growth).
- Cap stored field lengths; reject non-HTTPS endpoints.

### 10.3 Unauthorized notification leakage — the lock screen

The prompt's example is exactly right: *"John's work order at Building X is
overdue"* on a lock screen discloses a named employee, a location, and a
performance judgement, to anyone holding the phone — including someone who has
stolen it, and including a bystander.

**Rules for notification content:**

| Never in a notification | Rationale |
|---|---|
| Employee names (first, last, full) | Names a person to a bystander |
| Building, unit, community, address | Physical location of work/assets |
| Work-order numbers | The operational identifier; enough to look up externally |
| Prices, totals, quantities, on-hand counts | Cost-sensitive; already redacted below Admin in the app |
| Item names / barcodes | Reveals what is being moved |
| Note text, request messages, descriptions | Free text — unbounded disclosure |
| Counts implying volume ("7 requests pending") | Operational intelligence |

**What is safe:** the app's name, and a category. `"Inventory App — A work order
was assigned to you."` `"Inventory App — A request needs review."` The specifics
live behind the tap, after the app has authenticated the user.

**§6.4 makes this enforceable rather than aspirational.** Redaction happens in
one server route (`GET /notifications/{id}/display`) that returns only
category-level text, and it is the only text any notification can display. There
is no emit site that can accidentally interpolate a building number.

If richer text is ever wanted, the correct mechanism is a per-user preference —
**opt-in, off by default**, phrased honestly as *"Show details on the lock
screen"* — not a global default.

---

### 10.4 Subscription lifetime is NOT session lifetime

**Stated requirement (project owner, 2026-08-14):** *"The user won't have to be
in the app to receive device notifications. If their log-in session is active,
it should still send notifications."*

**This corrects §10.2.** That section suggested tying subscription validity to
an active session. That is the wrong coupling, and the reason is a number
already in the schema: `AuthSession.expires_at` is a **hard 12-hour absolute cap
with no idle timeout**, and "remember this device" changes only cookie
persistence, not server lifetime. A technician who logged in at 7am yesterday is
logged out at 7pm yesterday. Coupling the two would mean notifications stop
overnight, every night, and resume only after someone opens the app — which is
precisely the behavior this feature exists to eliminate.

**The corrected rule:**

| Event | Deletes the subscription? |
|---|---|
| Explicit logout | ✅ **Yes** — the user said so |
| Session expiry (the 12-hour cap) | ❌ **No** |
| Browser closed / app backgrounded | ❌ No |
| Push service returns 404 / 410 | ✅ Yes |
| User archived, or password reset | ✅ Yes (mirrors existing session revocation) |
| Permission revoked in the browser | ✅ Yes, via the resulting 404/410 |

**What is checked at send time is that the *user* is active, never that a
session exists.** `users.archived_at IS NULL` plus the event's authorization
rule. A push subscription is a property of a browser profile that a user has
claimed, not a property of a login.

**Two consequences that must be designed for, not discovered:**

1. **Display text degrades after session expiry.** Under §6.4 the service worker
   fetches display text with the session cookie; with no live session that fetch
   401s and the generic fallback ("You have a new notification") is shown. That
   is the correct security outcome — a device with no session must not render
   work details — but with a 12-hour cap it is the *common* case each morning
   rather than an edge case. **This is a live decision, not a settled one**, and
   §26.2 carries it. The three options are: accept generic text and let the tap
   drive re-login; put a short, already-redacted category string in the payload
   so it survives without a session; or revisit the session cap itself, which is
   an auth change outside this feature's scope.
2. **Shared devices need a boot-time re-assert.** With subscriptions outliving
   sessions, User A's subscription can persist in a browser that User B later
   logs into. The fix is cheap and does double duty with
   `pushsubscriptionchange` robustness (§9.3): **on every app boot, if the
   browser holds a subscription, POST it again.** Reassign-on-register then
   binds it to whoever is actually logged in now. Display-time authorization
   remains the guarantee, so the worst pre-re-assert outcome is a generic
   notification that resolves to nothing.

---

## 11. Notification Permission UX

### 11.1 What not to do

Do not call `Notification.requestPermission()` on load. It earns Chrome's
quieter-prompt treatment, and a denial is close to permanent: browsers offer no
API to re-prompt, and the user must dig through site settings to undo it. **One
badly-timed prompt permanently costs that device.**

### 11.2 The flow

```
[Settings / profile area]
  "Get notified about work assigned to you"          ← plain-language value
  [ Enable notifications ]                            ← the user gesture

        ├── iOS Safari, not installed ────▶ Instruction card, no prompt:
        │                                   "Tap Share → Add to Home Screen,
        │                                    open the app from your Home
        │                                    Screen, sign in, and enable
        │                                    notifications there."
        │                                   (with the reason stated plainly)
        │
        ├── Push unsupported entirely ────▶ Honest message; hide the control
        │
        └── Supported ──▶ Notification.requestPermission()   [in the gesture]
                              ├── denied ──▶ "Notifications are blocked for
                              │               this site. To turn them on,
                              │               change it in browser settings."
                              │               Control stays visible, disabled.
                              ├── default (dismissed) ──▶ Silent. Control stays
                              │                            available. Never
                              │                            auto-retry.
                              └── granted ──▶ register SW
                                            ─▶ pushManager.subscribe({
                                                 userVisibleOnly: true,
                                                 applicationServerKey })
                                            ─▶ POST /push/subscriptions
                                            ─▶ confirm + offer a test push
```

### 11.3 Explain first, then prompt

The pre-prompt matters because the browser prompt is unrecoverable. A single
sentence naming the concrete benefit — *"so you find out when a work order is
assigned to you without checking the app"* — is enough. **Never show a fake
prompt styled to look like the browser's.**

### 11.4 Safari vs Chrome differences that reach the UX

- **iOS**: the whole flow is gated behind a manual Home Screen install the site
  cannot trigger or detect the refusal of. The app can detect the *result* —
  `window.navigator.standalone === true`, or
  `matchMedia("(display-mode: standalone)").matches` — and must branch on it.
- **macOS Safari**: no install step. Same flow as Chrome.
- **Chrome**: `userVisibleOnly: true` is mandatory. Permission may be revoked
  later by Chrome itself (§4.5), so the app must re-check on boot rather than
  assuming permission is permanent.
- **All**: `requestPermission()` must be inside the gesture's call stack. Any
  `await` before it may forfeit the gesture on some engines — do the permission
  request first, service worker registration after.

### 11.5 After denial, and permission drift

Denial is respected permanently: never re-prompt, never nag, never gate app
functionality on it. The control remains visible and disabled, with a truthful
explanation of where to change it. **On every app boot, compare
`Notification.permission` and `getSubscription()` against the server's state** —
this is how the app notices Chrome's auto-revocation, a cleared profile, or a
rotated subscription, and it is the cheapest reliability mechanism in the design.

### 11.6 The `UX-2` boundary — write it down

The socket layer promised no new UI, and that promise stands for the socket. This
feature deliberately adds exactly two surfaces and no more:

1. **One opt-in control** in the settings/profile area.
2. **The OS notification itself**, plus the navigation on click.

**Explicitly out of scope, and the reason to say so now:** no in-app toasts, no
badge counters, no notification bell, no banner, no connection indicator. If a
durable in-app notification list is wanted later, it is its own feature with its
own decision — not something that gets smuggled in as "part of notifications."

---

## 12. Service Worker Architecture

### 12.1 The app has none, and that is a load-bearing fact

`main.py`'s `NoCacheStaticFiles` stamps `Cache-Control: no-cache` on every asset,
and `/` re-reads and concatenates 13 HTML fragments on every request. Both exist
because of a real failure: *"a cached old `main.js` renders a completely blank
page (both screens stay hidden until the fresh JS runs)"* — a failure the docs
note is *"awkward"* to clear on a phone.

**A caching service worker would resurrect that bug in its worst form.** A
service worker can serve stale assets indefinitely, survives reloads, ignores
`Cache-Control`, and on a phone is genuinely hard for a non-technical user to
clear. Introducing one to an app that has explicitly engineered *against* stale
assets is the biggest self-inflicted risk in this entire proposal.

### 12.2 The mitigation: a service worker with no `fetch` handler

**Register no `fetch` event listener at all.** Not a pass-through handler — none.
A service worker with no `fetch` listener is not consulted for navigation or
asset requests; the browser goes straight to the network exactly as it does
today. The app's loading behavior stays byte-identical, and `NoCacheStaticFiles`
remains the only caching authority.

The worker handles exactly three events:

| Event | Purpose |
|---|---|
| `push` | Fetch display text (§6.4), `showNotification()` unconditionally |
| `notificationclick` | Focus an existing client and navigate it, or `clients.openWindow()` |
| `pushsubscriptionchange` | Re-subscribe and POST the replacement |

Plus `install` → `self.skipWaiting()` and `activate` → `self.clients.claim()`, so
a deployed update takes effect immediately rather than waiting for every tab to
close. That matters on Render, where every deploy ships a new file.

**This constraint should be enforced, not merely intended.** A CI grep asserting
that `sw.js` contains no `addEventListener("fetch"` is a two-line check that
prevents the exact regression this section exists to avoid. The repo already has
precedent for this style of guard (`tests/test_realtime_dependency.py` exists
solely to guard a pinned dependency that no other test can catch).

### 12.3 Scope — a concrete finding about `main.py`

A service worker's scope is capped by its own URL path. `app.mount("/static",
...)` means a worker at `/static/sw.js` would be scoped to `/static/` — unable to
control the app root, breaking `clients.matchAll()` and `openWindow` focus
behavior.

**Two options:**
1. **Serve `/sw.js` from a root route in `main.py`**, alongside `/` and
   `/healthz`, reading the file from `STATIC_DIR`. Explicit, matches the file's
   existing habit of serving assembled content from root, no header subtlety.
   **Recommended.**
2. Serve from `/static/sw.js` with a `Service-Worker-Allowed: /` header and
   `register("/static/sw.js", { scope: "/" })`. Works, but relies on a header
   that is easy to lose in a refactor.

**CSP check:** the existing `default-src 'self'` covers `worker-src` (via
`child-src` → `default-src` fallback) and `connect-src`, so a same-origin worker
and its same-origin fetches are permitted with **no CSP change**. Verify in the
browser console during Phase A rather than assuming — the realtime layer had the
analogous `connect-src` question and it was worth checking.

### 12.4 Versioning, updates, and the uninstall path

- The browser re-fetches `sw.js` on navigation (and at least every 24h) and
  installs a byte-different file as an update. `skipWaiting` + `clients.claim`
  make it immediate.
- Serve `sw.js` with `Cache-Control: no-cache`, consistent with everything else.
- **Build the uninstall path in Phase A, not later.** A route or documented
  console snippet that calls `registration.unregister()` is the emergency exit if
  a bad worker ships. Without it, a broken worker on a technician's phone is a
  field visit.

### 12.5 Risks, ranked

| Risk | Severity | Mitigation |
|---|---|---|
| Accidental caching reintroduces the blank-page bug | **High** | No `fetch` handler; CI grep; uninstall path |
| Bad worker persists after a fixed deploy | **High** | `skipWaiting` + `clients.claim`; `no-cache`; uninstall route |
| Wrong scope breaks click-to-focus | Medium | Serve from root (§12.3) |
| SW code is untestable in the Python suite | Medium | Accept; §25 manual matrix is the coverage. Keep the worker tiny enough to review by eye. |
| SW fetch runs with ambient cookies | Low | Same-origin only; the server authorizes it like any request |

---

## 13. PWA Requirements

**Separate two questions the prompt correctly warns against conflating.**

### 13.1 What push actually requires

| Requirement | Needed for push? |
|---|---|
| HTTPS | ✅ **Yes, universally.** Satisfied by Render. |
| Service worker | ✅ **Yes** (except Declarative Push, which we reject). |
| VAPID keys | ✅ **Yes.** |
| Permission from a user gesture | ✅ **Yes.** |
| `manifest.json` | ⚠️ **Conditional** — see below. |
| Icons | ⚠️ Practically yes; cosmetically required. |
| `display: standalone` | ⚠️ Conditional. |
| Home Screen installation | ⚠️ **iOS only — and there, absolutely.** |
| Offline caching | ❌ **No.** Never conflate. |

### 13.2 Per platform

| Platform | PWA status |
|---|---|
| **iOS Safari** | **Required.** Installation is mandatory for push. On iOS 16.4–18.x a manifest with `display: standalone`/`fullscreen` was required to install as a web app; on iOS 26+ *"there are now zero requirements for installability"*. Since the crew will not be uniformly on iOS 26, **ship a manifest** — it is the only way to cover both. |
| **Android Chrome** | **Optional.** Push works in a tab. Installing is a genuine benefit: exempt from Chrome's disengagement auto-revocation. |
| **Desktop Chrome** | **Optional.** Same reasoning. |
| **macOS Safari** | **Not required.** Push works in a tab. |

### 13.3 Minimum manifest

`name`, `short_name`, `start_url: "/"`, `display: "standalone"`,
`theme_color` / `background_color` (the red/black/white palette), and icons at
192×192 and 512×512 plus a 180×180 `apple-touch-icon` link. `backend/static/`
currently has `favicon.png` only.

**Cost:** one small JSON file, one `<link rel="manifest">` in `shell-head.html`,
three icons. It changes nothing about how the app behaves in a browser tab.

**Explicitly not adopted:** offline caching, background sync, periodic sync,
app shortcuts, share targets. None are needed and each would pull the service
worker into the request path that §12 keeps it out of.

---

## 14. FastAPI Backend Responsibilities

### 14.1 Endpoints (router layer — thin, per house rules)

| Endpoint | Auth | Purpose |
|---|---|---|
| `POST /push/subscriptions` | `get_current_user` | Upsert by endpoint; bind to caller. Validates endpoint host allowlist. |
| `DELETE /push/subscriptions` | `get_current_user` | Body carries the endpoint being abandoned. Idempotent. |
| `GET /push/vapid-public-key` | `get_current_user` | Serves the public key. Could be embedded in the shell instead; an endpoint keeps key rotation from requiring an HTML edit. |
| `GET /notifications/{id}/display` | `get_current_user` | **The redaction boundary.** Returns `{title, body, url}` only, only if the caller owns the notification and still passes authorization. |
| `POST /push/test` | `require_min_role("admin")` | Sends a test push to the caller's own devices. Phase A's proof and a permanent support tool. |
| `GET /notifications` | `get_current_user` | *Later.* Only if a durable in-app list is built. |

`POST /push/test` must send **only to the caller's own subscriptions**. An admin
endpoint that can push to arbitrary users is a spam weapon and has no
justification.

### 14.2 Layer assignment

| Responsibility | Layer | Module |
|---|---|---|
| Event vocabulary, rules, audience, redaction templates | **domain (pure)** | `app/domain/notifications.py` |
| Recipient resolution, preference lookup, outbox writes | **services** | `app/services/notifications.py` |
| Encryption, VAPID signing, HTTP to push services, response classification | **services** | `app/services/push_delivery.py` |
| Subscription CRUD | **services** | `app/services/push_subscriptions.py` |
| Drain loop + supervisor | **services** | `app/services/push_delivery.py` |
| Lifespan wiring | **routers** | extend the existing `lifespan` in `routers/realtime.py`, or lift it to a neutral module |
| Request/response shapes | **schemas** | `app/schemas/notifications.py` |

**The domain module must stay pure** — no `pywebpush` import, no SQLAlchemy. That
is what makes the routing rules unit-testable without a database, exactly as
`domain/realtime.py` and `domain/work_orders.py` are today.

### 14.3 VAPID key handling

- **Private key**: `VAPID_PRIVATE_KEY` env var. In `render.yaml`, declare it with
  `sync: false` so the value is set in the dashboard and **never enters git**.
  Loaded once at startup. Never logged, never in an error message, never returned
  by any route. **`/db-test` is the cautionary precedent** — an Admin-gated route
  that returns environment facts. Do not add a "push config" route in that shape.
- **Public key**: not a secret; it is handed to every browser by definition.
- **Rotation invalidates every subscription** (the key is bound at `subscribe()`).
  Rotation therefore means every user re-opts-in. Budget for that: it is the
  incident response for a leaked private key, and it should be rehearsed once in
  staging before it is ever needed in anger.

---

## 15. Database Architecture

### 15.1 Verdict per table

| Table | MVP? | Verdict |
|---|---|---|
| `push_subscriptions` | ✅ **Required** | The only table Phase A/B needs. |
| `notifications` | ✅ Required **once routing exists** (Phase C) | The durable per-recipient decision record **and the outbox**. |
| `notification_deliveries` | 🟡 Later (Phase F) | Per-subscription attempts. Warranted when per-device retry and diagnosis matter — not before. |
| `notification_preferences` | 🟡 Later (Phase E) | Sparse opt-out rows only. |
| `notification_rules` (data-driven) | ❌ **No** | Rules as database rows means business logic that CI cannot test, code review cannot see, and migrations cannot version. Rules belong in `domain/notifications.py`. |
| `devices` | ❌ **No** | §9.1. |

### 15.2 Sketches

```
push_subscriptions
  id                UUID PK
  user_id           UUID FK → users(id) ON DELETE CASCADE, indexed
  endpoint          TEXT NOT NULL UNIQUE          -- reassign-on-register
  p256dh            TEXT NOT NULL
  auth              TEXT NOT NULL
  created_at        TIMESTAMPTZ NOT NULL
  last_success_at   TIMESTAMPTZ NULL
  last_failure_at   TIMESTAMPTZ NULL
  failure_count     INTEGER NOT NULL DEFAULT 0

notifications                                     -- Phase C; also the outbox
  id                UUID PK
  event_type        TEXT NOT NULL                 -- domain vocabulary
  entity_type       TEXT NOT NULL                 -- 'work_order' | 'user_request' | …
  entity_id         UUID NULL
  recipient_id      UUID FK → users(id) ON DELETE CASCADE, indexed
  reason            TEXT NOT NULL                 -- §8.2 — why they qualified
  created_at        TIMESTAMPTZ NOT NULL
  delivery_state    TEXT NOT NULL DEFAULT 'pending'  -- pending|sent|failed|skipped
  delivered_at      TIMESTAMPTZ NULL
  read_at           TIMESTAMPTZ NULL              -- only if an in-app list exists
  request_id        TEXT NULL                     -- correlate to the originating request
  INDEX (delivery_state, created_at)              -- the drain's query
```

**No notification text is stored.** The row records *what happened to whom and
why*; the display text is rendered on demand by `GET /notifications/{id}/display`
from the live entity. This is `P1`/`P2` applied to storage: text stored at queue
time would go stale, would duplicate the entity, and would be a second place
sensitive strings live.

`request_id` is worth the column: it makes one HTTP write and its N notifications
and M deliveries a single greppable chain, which is exactly the reasoning behind
the WebSocket envelope's `req` field.

### 15.3 Migration notes

Alembic head is `fbc4e6a8d0f2` (32 revisions). CI enforces **exactly one head**
and a **round-trip** (`upgrade head` → `downgrade -1` → `upgrade head`), so every
migration needs a working `downgrade`. All tables are additive with no backfill —
low risk. `entrypoint.sh` runs `alembic upgrade head` on cold start, so they
apply on deploy without manual steps.

---

## 16. Notification Preferences

### 16.1 Authorization and preference are different questions

| | Authorization | Preference |
|---|---|---|
| Question | *May* this user know? | Does this user *want* to be interrupted? |
| Source | Role + relationship + `can_view_work_order` | The user's own choice |
| Owner | The system | The user |
| Failure mode | **Data disclosure** | Annoyance, or a missed update |
| Default | Deny | Per-type, defined in code |
| Overridable by user | ❌ Never | ✅ Always (except mandatory types) |
| Effect on in-app access | — | **None whatsoever** |

**The invariant, to be stated in the code and tested:** *turning off a
notification preference must not change what a user can see inside the
application.* A technician who disables assignment notifications still sees every
work order assigned to them, in the app, unchanged. Preference governs
**interruption**, never **access**. Conflating them produces a system where
muting notifications silently hides work — a genuinely dangerous outcome for an
ops tool.

The converse also holds: **authorization always wins.** A user who wants
notifications they are not authorized for gets nothing, silently.

### 16.2 The model

**Sparse opt-out rows against code-defined defaults.**

```
notification_preferences        -- absence means "use the type's default"
  user_id            UUID FK → users(id) ON DELETE CASCADE
  notification_type  TEXT
  enabled            BOOLEAN NOT NULL
  PRIMARY KEY (user_id, notification_type)
```

Defaults live in `domain/notifications.py` next to the type definition, so adding
a type does not require a backfill and a new user needs no rows.

**Rejected:** a full row per user per type (backfill on every new type, and a
migration every time defaults change); role-based preference defaults (roles
already determine *authorization*; making them also determine *preference*
recreates exactly the conflation §16.1 forbids).

### 16.3 Mandatory vs optional

Some notifications may reasonably be non-disableable — an inventory-recount
request that blocks billing, for instance. **Keep the mandatory set as small as
possible and mark it in the type definition, not by omitting the toggle from the
UI.** A toggle a user cannot change should be visible and explained, not absent.

**`delivery_method` should not be modelled yet.** Push is the only channel. A
`delivery_method` column with one legal value is speculative schema. Add it when
a second channel exists.

---

## 17. Security Threat Model

| # | Threat | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| T1 | **SSRF via attacker-supplied endpoint** — `POST /push/subscriptions` makes the server POST to an arbitrary URL from inside Render's network | **Medium** | **High** | **Allowlist endpoint hosts** (`*.push.apple.com`, `fcm.googleapis.com`, `*.push.services.mozilla.com`); require HTTPS; reject private/loopback hosts. **The most important control in the feature.** |
| T2 | **Mass subscription deletion from misread response codes** — a VAPID misconfiguration returns 401 on every send; a naive handler deletes every row | **Medium** | **High** | **Only 404/410 delete.** 401/403 → alert, delete nothing. 429/5xx → back off. Test this explicitly. |
| T3 | **Leaked VAPID private key** | Low | **High** | Env var with `sync: false`, never logged or returned; rotation runbook (accepting that rotation forces universal re-opt-in); alone it does not permit forging payloads without subscription keys |
| T4 | **`push_subscriptions` table leak** (backup, replica, injection) | Low | **Medium** | Endpoints + keys are credentials. With T3 also breached → full spoofing. Delete rows rather than soft-disabling; keep the table minimal (§9.2); the existing session table already sets the "store the minimum" precedent |
| T5 | **Sensitive content on a lock screen** | **High if unaddressed** | **Medium–High** | §10.3 content rules, enforced structurally by §6.4's single redaction route |
| T6 | **Wrong-account delivery on a shared device** | **Medium** | **High** | Three layered mechanisms (§10.1); display-time re-authorization is the guarantee |
| T7 | **Notification spoofing** by a third party | Low | Medium | Requires both VAPID private key *and* subscription keys. Browsers reject improperly signed/encrypted messages |
| T8 | **Notification spam / volume abuse** (bug or malice) | **Medium** | **Medium** | Per-user daily ceiling; deduplicate by `(recipient, event_type, entity_id)` within a window; volume alarm in logs. **Chrome revokes permission for high-volume/low-engagement sites (§4.5) — a runaway loop can permanently cost the whole crew the feature** |
| T9 | **CSRF on subscribe/unsubscribe** | Low | Medium | Cookie is `SameSite=Lax`; these are `POST`/`DELETE` (not top-level navigations) with JSON bodies; existing CSP `form-action 'self'`. Worth an explicit test |
| T10 | **XSS → attacker reads/creates subscriptions** | Low | **High** | Existing CSP `default-src 'self'` with no `unsafe-inline`; no `eval`; no inline handlers. XSS here also means SW compromise (T12), so the CSP is doing double duty |
| T11 | **Stale subscriptions accumulate** | **High** (certain) | Low | Delete on 404/410, on logout, on user archive (CASCADE); optional age sweep |
| T12 | **Service-worker compromise** | Low | **Critical** | A malicious SW at root scope persists across sessions and sees every request. Mitigated by CSP, same-origin-only registration, HTTPS, a tiny reviewable worker, and the uninstall path (§12.4) |
| T13 | **Logging subscription data** | **Medium** (easy mistake) | Medium | Log `subscription_id` and the endpoint **host**, never the full endpoint or keys. The codebase already has this discipline — query strings are deliberately never logged, and `services.rate_limit.caller_key` hashes its input |
| T14 | **Environment-variable exposure** | Low | High | `/openapi.json`, `/docs`, `/redoc` are already un-mounted in production. Do not add a config-echo route |
| T15 | **Enumeration via `GET /notifications/{id}/display`** | Low | Medium | UUID ids; ownership check; **return 404 for both "not found" and "not yours"** so the route cannot confirm existence |
| T16 | **Replay of a captured push message** | Low | Low | Payload is an opaque id; display re-authorizes; a replay shows the recipient something they were already entitled to see |
| T17 | **Archived/disabled user still receives push** | **Medium** | **Medium** | `ON DELETE CASCADE` covers deletion, but archival is a soft delete — the drain must re-check `archived_at IS NULL` before sending, and `services.users` archive should delete subscriptions the way it already deletes sessions |

---

## 18. Failure Modes and Recovery

| Failure | Response | Retry | Disable sub? | Log | Alert admin |
|---|---|---|---|---|---|
| Device offline | Push service queues per TTL | No | No | No | No |
| Push service 5xx / timeout | Bounded backoff, then give up | ✅ Yes | No | Warn | Only if sustained |
| Push service 429 | Honor `Retry-After` | ✅ Yes | No | Warn | Only if sustained |
| **404 / 410 Gone** | **Delete the row** | No | ✅ **Delete** | Info | No |
| **401 / 403** | **VAPID broken** — stop the drain | No | ❌ **Never** | **Error** | ✅ **Yes** |
| 413 payload too large | Bug — payload is a UUID | No | No | Error | ✅ Yes |
| Render instance restart mid-drain | Rows stay `pending`, resume after boot | Automatic | No | Info | No |
| Backend down | No events occur; nothing to deliver | — | No | — | No |
| Database unavailable | Existing `/healthz` 503 path handles it; notifications are simply not written | — | No | Error | Existing |
| Browser permission revoked | Endpoint 404/410s → delete; client detects on boot and offers re-enable | No | ✅ Delete | Info | No |
| User archived after queueing | Drain re-checks `archived_at`; skip and mark `skipped` | No | Delete their subs | Info | No |
| **Authorization changed before delivery** (technician unassigned) | **Drain re-checks; skip.** Display fetch is the second gate | No | No | Info | No |
| Duplicate domain events | Dedupe on `(recipient, event_type, entity_id)` within a window | — | No | Info | No |
| Duplicate push delivery (at-least-once) | SW uses a stable `tag` so a repeat **replaces** rather than stacks | — | No | No | No |
| Push accepted (201) but never displayed | **Undetectable server-side.** Accept it | No | No | — | No |
| SW `push` fires but fetch fails | Show generic text | No | No | No | No |
| Drain task crashes | **Reuse `DispatchSupervisor`** — bounded restarts, then a loud `ERROR` | ✅ Bounded | No | **Error** | ✅ Yes |

**The pattern worth restating:** `4xx` splits into two utterly different
meanings. `404`/`410` mean *this subscription is dead* — delete it. `401`/`403`
mean *we are configured wrong* — touch nothing and shout. Getting this backwards
destroys the table.

**The silent-death failure the codebase already anticipates:** if the drain task
dies, push stops for everyone while HTTP keeps serving perfectly and `/healthz`
stays green. `services/realtime.py` calls out this exact hazard for its dispatch
task and answers it with `DispatchSupervisor` and an unmistakable
`realtime.dispatch_gave_up` log line. **Reuse that pattern verbatim.**

---

## 19. Render Deployment Considerations

| Concern | Status | Action |
|---|---|---|
| **HTTPS** | ✅ Provided by Render; `COOKIE_SECURE=true`; HSTS set | None |
| **VAPID secret storage** | ⚠️ New | Add to `render.yaml` with `sync: false`; set the value in the dashboard. **Never a literal in git** |
| **Process lifecycle** | ⚠️ **Free tier spins down when idle** | Event-driven notifications are safe (the request proves the process is awake). **Time-driven notifications are not possible** without a cron job or paid tier |
| **Cold start** | ⚠️ ~30s, plus `alembic upgrade head` | The first push after idle is delayed by cold start. Acceptable; do not "fix" it with a keep-alive pinger, which defeats the free tier's purpose |
| **Background processes** | ✅ The lifespan hook already exists | Add the drain as a second supervised task. **No worker service needed** |
| **Deploy restarts** | ⚠️ Every deploy kills in-flight work | **This is the argument for the DB outbox over `BackgroundTasks`.** Pending rows survive; in-memory tasks do not |
| **Persistence** | ✅ Managed Postgres | Subscriptions and pending notifications survive restarts by construction |
| **Single instance** | ⚠️ `plan: free`, no `--workers` | **Push is immune to the N3 multi-instance hazard that the socket registry is not** — delivery is an outbound call from any process. But two instances would both drain the outbox: `SELECT … FOR UPDATE SKIP LOCKED` on the outbox query makes it safe *now*, cheaply, rather than after a duplicate-delivery incident |
| **SW cache invalidation** | ⚠️ New | Serve `sw.js` with `no-cache`; `skipWaiting` + `clients.claim`; keep the uninstall path |
| **CI gate** | ⚠️ **`pip-audit` is blocking** | `pywebpush` and its transitive `cryptography`/`http-ece` must be clean, or `main` goes red and nothing deploys. **Check before committing, not after** |
| **Migrations** | ✅ Automatic on cold start | New tables are additive; `downgrade` required by the CI round-trip |
| **Deploy = production** | ⚠️ Per project memory | Merging to `main` deploys. Ask before merging |
| **Staging environment** | ⚠️ **Required for this feature** | See §19.1. Cannot be skipped |

**The single most consequential Render fact:** the free tier's spin-down makes
any notification phrased with a deadline — *overdue*, *stale for N days*, *daily
digest* — impossible without new infrastructure. Filter that class out of the
candidate list in §22 up front, or one will be promised and then discovered
unbuildable. (Render *does* offer cron jobs on the free tier, so the door is not
closed — but it is a separate service with its own lifecycle, not a flag.)

### 19.1 A staging environment is a prerequisite, not a convenience

**iOS push cannot be tested locally.** Push requires HTTPS and an origin the
phone can actually reach. `localhost` is a secure context, so desktop Chrome
works against a dev server — but an iPhone cannot reach the dev machine's
localhost, and Phase A's kill criterion (Add to Home Screen → second login →
subscribe → receive) has nowhere to run without a deployed origin.

A tunnel (cloudflared, ngrok) satisfies HTTPS, but free tunnel hostnames rotate,
and **a changed origin destroys every push subscription, every service worker
registration, every notification permission grant, and every Home Screen
install.** The whole setup would be re-done each session. A stable staging
hostname is what makes iterative testing possible at all.

**Origin isolation is a structural safety control here, not just tidiness.**
Subscriptions, service workers, permission state, and Home Screen installs are
all scoped per-origin, which means a staging deployment gives the following for
free:

- **A broken service worker on staging cannot reach the production origin.**
  This is §12.5's highest-severity risk — a bad worker persisting on a
  technician's phone — neutralized by construction rather than by care.
- Separate VAPID keypairs per environment become the default rather than a
  discipline that has to be maintained (§14.3).
- The iOS install flow, including the second-login gotcha (§3.6), can be
  rehearsed on a real phone without touching the app the crew depends on.

**Cost and constraints, verified against Render's current terms:**

| Piece | Status |
|---|---|
| Second free web service | ✅ Available. No cap on service count; **750 instance-hours/month pooled per workspace**. Both services spin down after 15 min idle, so intermittent testing is comfortably within budget |
| HTTPS on `*.onrender.com` | ✅ Included, with managed TLS |
| Cron jobs | ✅ Available on free — relevant to the time-based question above |
| **Second free Postgres** | ❌ **One free database per workspace.** The binding constraint |
| Preview Environments | ❌ **Professional workspace or higher**, *and* each PR gets a new hostname — which is precisely wrong for push (see above). Not the right tool here regardless of plan |

**Two facts to verify before planning around them:** whether
`inventory-db-copy` is a free or paid instance, and if free, that its clock is
understood — Render reduced free Postgres lifetime from 90 days to **30 days
after creation**, with a 14-day grace period before deletion. A months-old
production database is almost certainly paid, but this is worth confirming
independently of this feature.

**Recommended staging shape:**

- **Database: an external free Postgres (Neon, Supabase), not Render.**
  `DATABASE_URL` is already just an environment variable, so this needs no code
  change, sidesteps the one-free-DB-per-workspace rule entirely, and has no
  30-day expiry. **Staging must never point at the production database** — a test
  run would write real `push_subscriptions` rows and then push to the crew's
  actual phones.
- **Create the service in the Render dashboard, not in `render.yaml`.** This
  file is the production contract and carries a documented hazard: a dashboard
  Blueprint sync rebuilds the configured branch and runs no tests (observed
  2026-08-10). Keeping staging out of the blueprint means a staging mistake can
  never rewrite the production service definition. The trade is config drift
  against isolation, and for a temporary environment isolation wins.
- **`autoDeploy: true`, tracking the feature branch. This needs no CI change.**
  The deploy job is gated on `github.ref == 'refs/heads/main'`, so staging
  pushes never reach it, while the workflow's `pull_request` trigger still runs
  the full suite on the PR. **The CI gate exists to protect production; staging
  does not need it.**
- **A different VAPID keypair.** Never share production's.
- `COOKIE_SECURE=true` — noting that it also un-mounts `/docs`, `/redoc`, and
  `/openapi.json` through `_doc_urls(production=COOKIE_SECURE)`. Push testing
  does not need those; if they are wanted in staging, the two meanings of that
  flag would have to be decoupled first, which is out of scope here.
- Bootstrap a login with `backend/scripts/create_owner.py` against the staging
  database.

**Three staging-specific hazards:**

1. **Two indistinguishable Home Screen icons.** Once staging and production are
   both installed, they look identical, and a test push will be checked against
   the wrong one. Give staging a distinct manifest `name`, `short_name`,
   `theme_color`, and a visibly different icon. Trivial now; genuinely confusing
   later.
2. **Spin-down masquerading as a bug.** A staging service idle for 15 minutes
   cannot drain its outbox; it wakes on the next request, so the first
   notification arrives late and looks like a delivery failure. Wake the service
   before testing delivery.
3. **`sync: false` on blueprint updates.** Render *ignores* `sync: false`
   environment variables when updating an existing Blueprint — which is the
   desired behavior for the production VAPID secret (a blueprint sync cannot
   clobber it), but means the value must be set in the dashboard and will not
   appear in git for either environment. Document where it lives.

---

## 20. Native Web Push vs Third-Party Services

| | **Native Web Push** | **FCM (SDK)** | **OneSignal** |
|---|---|---|---|
| Chrome support | ✅ Direct via VAPID | ✅ | ✅ |
| Safari macOS | ✅ | ⚠️ Wraps standard push anyway | ✅ |
| **Safari iOS** | ✅ (Home Screen) | ⚠️ Same iOS constraint | ⚠️ Same iOS constraint |
| Extra dependencies | **1 Python lib** | JS SDK + Firebase project | JS SDK + account |
| **CSP impact** | **None** — same-origin | ⚠️ Needs a CDN/script exception | ⚠️ Needs a CDN/script exception |
| Frontend complexity | Own SW, ~60 lines | Vendor SW | Vendor SW + hosted assets |
| Vendor lock-in | None | Medium | **High** |
| Cost | Free | Free tier | Free tier, then paid |
| **Privacy** | ✅ **Nothing leaves our infra but encrypted blobs** | ⚠️ Google sees subscriptions | ❌ **Vendor holds subscriptions + content** |
| Data ownership | ✅ Full | Partial | ❌ Theirs |
| Debugging | Full — our logs, our codes | Partial | Dashboard-mediated |
| Analytics/scheduling | Build it | Some | Extensive |
| Maintainability | Standards; no vendor migrations | Vendor SDK churn | Vendor SDK churn |

### 20.1 Recommendation: native, decisively

1. **Chrome does not require FCM.** With VAPID there is no Firebase project, no
   `gcm_sender_id`, no server key. The `fcm.googleapis.com` endpoint is used as a
   plain Web Push Protocol endpoint. The most common reason people reach for
   Firebase here is a misunderstanding.
2. **Safari requires standard Web Push regardless**, so a third party adds a
   layer without removing a requirement — and cannot remove the iOS install
   constraint, which is the only genuinely hard problem.
3. **CSP is the decisive technical objection.** This app runs
   `default-src 'self'` with **no** `unsafe-inline` and **no** external origins —
   verified against the entire SPA. Both third-party options ship JS from a CDN.
   Adopting one means either punching a hole in a CSP that was carefully verified
   line by line, or vendoring a large SDK into a repo whose only vendored file is
   a barcode decoder. **Neither is worth it for a feature whose native form is
   one Python library.**
4. **Privacy and data ownership.** Subscription endpoints and notification
   content are operational data about a small crew's work. OneSignal would hold
   both. There is no compensating benefit at this scale.
5. **The app's stated philosophy.** A deliberately simple stack, no bundler, no
   build step, dependencies individually justified with comments in
   `requirements.txt`. `pywebpush` fits that; a vendor SDK does not.

### 20.2 When to revisit

If the project later needs native iOS/Android apps sharing one notification
backend; or delivery analytics, scheduling, and A/B testing nobody wants to
build; or it outgrows a single instance and wants delivery infrastructure off the
critical path. **None are true today.**

### 20.3 Python library evaluation

| | **pywebpush** | **py-vapid** | Hand-rolled |
|---|---|---|---|
| Project | `web-push-libs/pywebpush` | `web-push-libs/vapid` | — |
| Purpose | Full Web Push: RFC 8291 encryption + VAPID + send | VAPID JWT only | — |
| Latest | **2.4.0, 2026-08-06** | Companion, same org | — |
| Maintenance | Active; PyPI **"Critical Project"**; *"maintained by a single person"*, PRs/issues accepted | Same org | — |
| Standards | RFC 8030 / 8291 / 8292 | RFC 8292 | — |
| VAPID | ✅ Full, auto-fills `aud`/`exp` | ✅ | — |
| Python | ≥3.10 (app runs 3.12) | ≥3.10 | — |
| Dependencies | `requests`, `cryptography`, `http-ece`, `py-vapid` | `cryptography` | `cryptography` |
| Sync/async | **Synchronous (`requests`)** | n/a | — |
| FastAPI fit | ✅ **Excellent** — the whole app is sync-in-a-threadpool | ✅ | — |
| Maturity | The de-facto Python implementation | Mature | — |
| Security notes | Must pass the blocking `pip-audit`; `cryptography` is well-maintained; bus-factor 1 is a real risk on a Critical Project | Same | ❌ **Do not.** RFC 8291 ECDH + HKDF + AES-GCM is exactly the code you must not write yourself |

**Recommendation: `pywebpush`.** Being synchronous is a *feature* here — the app
has zero `async def` handlers and the drain will run in a threadpool exactly like
every other blocking call (the same reasoning `routers/realtime.py` documents for
`run_in_threadpool(_resolve_identity, …)`). Pin the version, add a comment
explaining why, per the existing `requirements.txt` convention.

**The bus-factor-1 risk is real and should be recorded**, not dismissed. Mitigation:
pin exactly; the surface actually used is small (`webpush()` plus response
inspection); the underlying protocol is a stable RFC, so a fork or replacement
would be mechanical rather than a redesign.

**Frontend: add nothing.** The Push API, `PushManager`, and `Notification` are
browser built-ins. The only helper needed is a ~10-line base64url→`Uint8Array`
converter for the VAPID key. No library.

---

## 21. Recommended Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│ 1. DOMAIN ACTION           existing service, existing transaction    │
│    e.g. services/work_orders.assign_technicians()                    │
│    ── unchanged business logic; unchanged validation and gates ──    │
└──────────────────────────────────────────────────────────────────────┘
                                   ↓  same transaction
┌──────────────────────────────────────────────────────────────────────┐
│ 2. DOMAIN EVENT            {type, entity_type, entity_id, actor_id}  │
│    A fact about what happened. Carries NO recipients and NO text.    │
└──────────────────────────────────────────────────────────────────────┘
                                   ↓
┌──────────────────────────────────────────────────────────────────────┐
│ 3. NOTIFICATION RULE       app/domain/notifications.py — PURE        │
│    event → [(recipient_selector, reason)] · unknown type → []        │
│    Fail-closed, exactly like domain/realtime.audience_allows         │
└──────────────────────────────────────────────────────────────────────┘
                                   ↓
┌──────────────────────────────────────────────────────────────────────┐
│ 4. RECIPIENT RESOLUTION    services — selectors → concrete user_ids  │
│    work_order_technicians · supervisor_id · role queries             │
│    Actor excluded by default (§8.2)                                  │
└──────────────────────────────────────────────────────────────────────┘
                                   ↓
┌──────────────────────────────────────────────────────────────────────┐
│ 5. AUTHORIZATION           domain/work_orders.can_view_work_order    │
│    domain/roles.role_at_least · users.archived_at IS NULL            │
│    ══ EXISTING CODE. Do not write a second predicate. ══             │
└──────────────────────────────────────────────────────────────────────┘
                                   ↓
┌──────────────────────────────────────────────────────────────────────┐
│ 6. PREFERENCE              opt-out lookup vs code-defined defaults   │
│    Never affects in-app access (§16.1). Mandatory types skip this.   │
└──────────────────────────────────────────────────────────────────────┘
                                   ↓
┌──────────────────────────────────────────────────────────────────────┐
│ 7. NOTIFICATION RECORDS    one row per recipient, state='pending'    │
│    WRITTEN IN THE SAME TRANSACTION AS STEP 1 — rollback ⇒ no notify  │
└──────────────────────────────────────────────────────────────────────┘
        ↓                                                              
   ══ COMMIT · HTTP REQUEST RETURNS HERE · UX-7 PRESERVED ══           
        ↓                              ↘                               
┌────────────────────────────┐    ┌────────────────────────────────────┐
│ 8a. WEBSOCKET (existing)   │    │ 8b. PUSH DRAIN (new)               │
│  emit() → dispatch → tabs  │    │  supervised lifespan task          │
│  Refreshes OPEN screens    │    │  wake-on-enqueue + slow safety poll│
│  Invalidation only         │    │  SELECT … FOR UPDATE SKIP LOCKED   │
└────────────────────────────┘    └────────────────────────────────────┘
                                        ↓
┌──────────────────────────────────────────────────────────────────────┐
│ 9. RE-CHECK, THEN LOOK UP SUBSCRIPTIONS                              │
│    Recipient still active? Still authorized? (time has passed)       │
│    → all push_subscriptions for that user (fan-out to every device)  │
└──────────────────────────────────────────────────────────────────────┘
                                   ↓
┌──────────────────────────────────────────────────────────────────────┐
│ 10. ENCRYPT + SIGN + SEND   pywebpush · payload = {"id": <uuid>}     │
│     RFC 8291 body · RFC 8292 JWT · short TTL                         │
│     201 → last_success_at   404/410 → DELETE   401/403 → ALERT ONLY  │
└──────────────────────────────────────────────────────────────────────┘
                                   ↓
       ┌───────────────────────────────────────────────┐
       │ BROWSER PUSH SERVICE (Google / Apple)         │
       │ sees: our VAPID identity + an encrypted blob  │
       └───────────────────────────────────────────────┘
                                   ↓
┌──────────────────────────────────────────────────────────────────────┐
│ 11. SERVICE WORKER `push`   NO fetch handler — never in the nav path │
│     GET /notifications/{id}/display  (session cookie, same-origin)   │
│     ↳ server re-authorizes AND redacts — the single content boundary │
│     showNotification() unconditionally (Chrome userVisibleOnly)      │
└──────────────────────────────────────────────────────────────────────┘
                                   ↓
┌──────────────────────────────────────────────────────────────────────┐
│ 12. DEVICE NOTIFICATION     app name + category only. No names,      │
│     no buildings, no numbers, no prices. (§10.3)                     │
└──────────────────────────────────────────────────────────────────────┘
                                   ↓
┌──────────────────────────────────────────────────────────────────────┐
│ 13. notificationclick       focus an existing client and navigate,   │
│     else clients.openWindow() · auth gate applies as normal          │
└──────────────────────────────────────────────────────────────────────┘
```

### 21.1 Changes from the prompt's proposed flow

1. **Steps 1–7 are one transaction.** The prompt implied the routing decision
   follows the request. Deciding after commit lets a rolled-back change notify.
2. **A fork at step 8.** One decision, two channels. The socket and push are
   siblings, not alternatives, and they must not route independently.
3. **Authorization appears twice** (5 and 9) plus a third time at display (11).
   Not redundancy — hours can pass between decision and display.
4. **The service worker fetches rather than renders a payload** (§6.4). The
   single highest-value security decision here.
5. **The push service is explicitly marked as seeing nothing but metadata.**
6. **Subscription lookup happens at delivery time, not decision time.** Devices
   come and go between the two.

---

## 22. Notification Routing Matrix

**Every row is a CANDIDATE, not a requirement.** Each is backed by a relation
that exists in the schema today. `Push?` and `In-App?` are deliberately
unanswered — they are the business decision this report exists to inform.

| Event | Trigger (repo) | Candidate recipient | Why | Authorization rule | Preference | Push? | In-App? |
|---|---|---|---|---|---|---|---|
| **Work order assigned** | `WorkOrderTechnician` row created (`POST /work-orders/{id}/technicians`) | Each newly assigned technician (**exclude the assigner**) | New work they must know about | `can_view_work_order` (they are now an assignee) | Optional; default **on** | TBD | TBD |
| **Work order unassigned** | `WorkOrderTechnician` row deleted | Removed technician | Stop expecting work | Must have *been* assigned — a deliberate exception; check at decision time | Optional; default **off** | TBD | TBD |
| **Work order routed to supervisor** | `supervisor_id` set (manual or import) | That supervisor | Work is now theirs to oversee | `can_view_work_order` | Optional; default **on** | TBD | TBD |
| **Work order sent to Review** | status → `review` | Admin/Owner | Review queue needs action; **already the existing socket event's audience** | `role_at_least("admin")` | Optional; default **on** | TBD | TBD |
| **Work order placed On-Hold** | status → `on_hold` | Assigned technicians + routed supervisor | Work is paused | `can_view_work_order` | Optional; default **off** | TBD | TBD |
| **Inventory recount request raised** | `UserRequest` `inventory_recount` (short-count dispense) | Admin/Owner | Blocks billing accuracy; **strongest MVP candidate** | `role_at_least("admin")` | **Possibly mandatory** | TBD | TBD |
| **Missing item price request raised** | `UserRequest` `missing_item_price` | Admin/Owner | Blocks billing | `role_at_least("admin")` | Optional; default **on** | TBD | TBD |
| **Item request raised** | `UserRequest` item request | Admin/Owner | Catalogue gap blocking a technician | `role_at_least("admin")` | Optional; default **on** | TBD | TBD |
| **User request resolved** | `resolved_at` set | The request's `created_by_id` | Their blocker is cleared | Creator only | Optional; default **on** | TBD | TBD |
| **Tool checked out to you** | `ToolTransaction` `checkout` where `assigned_to_id != performed_by_id` | The custody holder | They are now accountable for a tool they did not check out themselves | Assignee only | Optional; default **on** | TBD | TBD |
| **Unassigned work order available** | Import creates a row with `supervisor_id IS NULL` | All supervisors | The shared pickup queue | `can_view_work_order` (supervisors see unrouted) | Optional; default **off** — **highest spam risk: one import can create many** | TBD | TBD |
| **Transaction voided** | `voided_at` set | Original `Transaction.user_id` | Their record was reversed | Actor only | Optional; default **off** | TBD | TBD |
| ~~**Low inventory**~~ | ❌ **NO TRIGGER EXISTS** | — | — | — | — | **Blocked** | — |
| ~~**Item dispensed**~~ | `Transaction` `dispense` | ⚠️ **No natural recipient** | Routine, high-volume, expected. Notifying on it is the `event → notify everybody` anti-pattern the prompt forbids | — | — | **Not recommended** | — |
| ~~**Overdue / stale / digest**~~ | ❌ **No scheduler** | — | Requires a Render cron job or paid tier (§19) | — | — | **Blocked** | — |

**Three findings worth reading twice:**

- **The prompt's own three examples do not survive contact with the schema.**
  "Work order assigned" is excellent and real. "Low inventory" has no threshold
  column to fire from. "Item dispensed" is the highest-volume routine event in
  the app with no one who needs interrupting.
- **The best MVP candidate is the `UserRequest` family**, because those rows
  already exist precisely to say *"a human must act on this"* — the routing
  question is already answered by the data model. Nothing else in the schema is
  that unambiguous.
- **"Unassigned work order available" is the volume hazard.** One CSV import can
  create dozens of rows. Either default it off, or aggregate ("N new work orders
  available") — and aggregation needs the scheduler §19 says does not exist. Flag
  it now rather than discovering it after Chrome revokes permission for the whole
  crew (§4.5).

---

## 23. Minimum Viable Implementation

### 23.1 What the MVP must prove

Not "a notification appeared." The MVP exists to falsify the four assumptions
that would each invalidate the whole design if wrong:

1. **iPhone Home Screen web app push actually works** for this app, on this
   crew's phones, with this CSP and this cookie setup — **including the second
   login (§3.6), which is the most likely rollout blocker.**
2. **A subscription stays bound to the right user** through logout, login as
   someone else, and a second device.
3. **The service worker does not disturb the app's loading behavior.** No blank
   pages, no stale assets, on any platform.
4. **The delivery path survives a Render deploy and a spin-down**, because that
   is what separates the DB outbox from a `BackgroundTask` that merely appears to
   work in testing.

### 23.2 The MVP, and how it differs from the prompt's sketch

The prompt's sketch is close. **Four changes, each for a stated reason:**

| Prompt's step | Change | Why |
|---|---|---|
| "Backend stores subscription" | **Also: delete on logout, reassign on re-register, allowlist the endpoint host** | Security-critical and cheap now; retrofitting into a live subscription table is painful and leaves a window where the wrong person receives push |
| "FastAPI sends the notification" | **Send through the real outbox + drain, not a synchronous shortcut** | A synchronous test send proves the encryption works and nothing about the architecture. The async path is what needs the confidence |
| "Administrator triggers a test notification" | **Admin triggers it to their own devices only** | An arbitrary-recipient admin push is a spam weapon with no MVP justification |
| — | **Add: verify on a real iPhone Home Screen web app before anything else** | It is the only step that can kill the project. Do it first, not last |

### 23.3 The MVP

```
0. Staging environment (§19.1): Render web service on the feature branch,
   external free Postgres, its own VAPID keypair, bootstrap owner account.
   ── EVERY STEP BELOW RUNS AGAINST STAGING, NOT PRODUCTION ──
1. Manifest + icons, distinct from production's. Verify Add to Home Screen
   on a real iPhone. Confirm the second login (§3.6).
   ── STOP HERE IF THIS FAILS ──
2. Generate VAPID keys (one pair per environment). Private → env var,
   sync: false. Public → endpoint.
3. Migration: push_subscriptions.
4. sw.js at root scope, NO fetch handler. push + notificationclick +
   pushsubscriptionchange. Uninstall path documented.
5. Opt-in UI: one control, in settings. Explain → gesture → permission →
   subscribe → POST. iOS-not-installed branch shows instructions, no prompt.
6. POST/DELETE /push/subscriptions. Authenticated. Endpoint-host allowlist.
   Reassign-on-register. Logout deletes.
7. Migration: notifications (as the outbox). One hardcoded event type.
8. Drain task on the existing lifespan, with DispatchSupervisor. Wake-on-
   enqueue + slow safety poll. FOR UPDATE SKIP LOCKED.
9. GET /notifications/{id}/display — the redaction boundary. 404 for
   both "missing" and "not yours".
10. POST /push/test (Admin, self only) → writes an outbox row → drain
    delivers → SW fetches → notification appears → click focuses the app.
11. Run the full §25 device matrix against staging.
```

**Explicitly NOT in the MVP:** notification types, routing rules, recipient
resolution, preferences, `notification_deliveries`, retry/backoff beyond the
simplest form, in-app notification list, aggregation, any real business event.

**Completion criterion:** an Admin on each of the six §25 platform rows can
trigger a test push to their own devices, receive it, tap it, land in the app —
and after logging out, receive nothing. **No business event is wired to
notifications yet.** That is the point: the infrastructure is proven independent
of the routing decisions, which is precisely the separation the prompt asked for.

---

## 24. Implementation Roadmap

### Phase A0 — Staging environment

**Objective:** a stable HTTPS origin, isolated from production, that an iPhone
can reach. **Nothing in Phase A can be tested without it** (§19.1).
**Components:** no repository changes — a Render web service created in the
dashboard, tracking the feature branch with `autoDeploy: true`; an external free
Postgres; `backend/scripts/create_owner.py` run against it.
**DB:** a separate staging database. **Never production's.**
**Security:** its own VAPID keypair; `COOKIE_SECURE=true`; confirm the staging
`DATABASE_URL` cannot resolve to the production instance.
**Tests:** `/healthz` green against the staging database; `/db-test` (Admin)
reports the staging database name, not production's — this route exists exactly
to answer "which database am I pointed at" and this is its moment.
**Done when:** you can log in to the staging URL from a phone on cellular data.
**Note:** no CI change is required. The deploy job is gated on `main`, so
staging pushes never reach it, while the `pull_request` trigger still runs the
full suite.

### Phase A — Push proof of concept

**Objective:** prove device notifications reach every target platform.
**Components:** `static/manifest.json` (distinct name/icon from production),
icons, `static/sw.js`, root `/sw.js` route in `main.py`, `shell-head.html`
(manifest + apple-touch-icon links).
**DB:** none. **Security:** VAPID key generation and storage discipline; verify
CSP permits the worker; uninstall path exists before anything ships.
**Tests:** manual device matrix; CI grep asserting `sw.js` has no `fetch`
listener; `node --check` (already in CI).
**Done when:** a hardcoded push, sent by hand **against staging**, displays on an
iPhone Home Screen web app, Android Chrome, desktop Chrome, and macOS Safari.
**Kill criterion:** if the iPhone install + second-login flow is unacceptable to
the crew, **stop and reconsider** — in-app notifications over the existing socket
become the right answer.

### Phase B — Subscription infrastructure

**Objective:** bind subscriptions to authenticated users, safely, for their whole
lifecycle. **Components:** `routers/push.py`, `services/push_subscriptions.py`,
`schemas/push.py`, `views/notifications.js`, `views/auth.js` (logout hook),
`services/users.py` (archive + password-reset cleanup).
**DB:** `push_subscriptions`.
**Security:** the whole of §10 — endpoint-host allowlist (SSRF), reassign-on-
register, delete-on-logout, per-user subscription cap, no endpoint or keys in
logs.
**Tests:** register/delete; register-while-owned-by-another-user reassigns;
logout deletes; archive cascades; unauthenticated registration 401s; a
non-push-service endpoint is rejected; two devices coexist; duplicate register is
idempotent.
**Done when:** every §9.3 scenario has a passing test.

### Phase C — Notification domain and outbox

**Objective:** durable, routed notification records with asynchronous delivery.
**Components:** `domain/notifications.py` (pure), `services/notifications.py`,
`services/push_delivery.py`, lifespan wiring.
**DB:** `notifications`.
**Security:** display-route redaction and ownership; re-check authorization in
the drain; correct 4xx handling (§18).
**Tests:** rules are pure and unit-tested with no DB; unknown event type notifies
nobody; a rolled-back transaction writes no notification; the drain skips an
archived user; 410 deletes and 401 does not; supervisor restart is bounded.
**Done when:** one real event type flows end-to-end and survives a deploy
restart mid-drain.

### Phase D — Routing

**Objective:** correct recipients for each event type.
**Components:** `domain/notifications.py` rules; resolution queries; call sites in
existing services.
**DB:** none. **Security:** every rule's authorization check exercised by a test
that asserts an *unauthorized* user gets nothing.
**Tests:** one per matrix row, both directions (right people notified, wrong
people not); actor exclusion; deduplication.
**Done when:** §22's chosen rows are implemented with negative tests.

### Phase E — Preferences

**Objective:** per-user control that never affects access.
**Components:** preferences service, settings UI.
**DB:** `notification_preferences`.
**Security:** **the §16.1 invariant, as an explicit test** — disabling a
preference must not change any API response.
**Done when:** toggles work, defaults apply without rows, and mandatory types
cannot be disabled.

### Phase F — Reliability

**Objective:** retries, cleanup, and per-device delivery visibility.
**DB:** `notification_deliveries`.
**Tests:** backoff bounded; permanent failures give up and are logged; sweep
removes long-dead subscriptions.
**Done when:** a device offline for a day, then online, behaves correctly.

### Phase G — Production hardening

**Objective:** safe under abuse and observable under failure.
**Scope:** per-user volume ceilings; a volume alarm; the `dispatch_gave_up`-style
loud line for the drain; a documented VAPID rotation runbook, rehearsed once in
staging; §17 threat-by-threat review.
**Done when:** every §17 mitigation has a test or a written operational
procedure.

**Sequencing note:** A0→A→B→C is fixed, and **A0 is not optional** — Phase A's
kill criterion cannot be evaluated without it. **D must not start before C**, because
routing rules written without a working delivery path get debugged through two
unproven layers at once. E and F may swap. G is continuous, not final.

---

## 25. Testing Matrix

### 25.1 Platform matrix (expected results from §3–§5)

| Device | Browser | Install state | Permission | Expected result |
|---|---|---|---|---|
| iPhone | Safari | Normal tab | n/a | ❌ **No push.** App must detect and show install instructions. The opt-in control must **not** call `requestPermission()` |
| iPhone | Safari | Home Screen app | Allowed | ✅ Delivered. Requires a **separate login** inside the installed app first |
| iPhone | Safari | Home Screen app | Denied | ❌ None. Control disabled with a truthful message. Never re-prompt |
| iPad | Safari | Home Screen app | Allowed | ✅ Same as iPhone |
| Android | Chrome | Browser tab | Allowed | ✅ Delivered, including with the browser closed |
| Android | Chrome | Installed PWA | Allowed | ✅ Delivered; exempt from disengagement auto-revocation |
| Windows | Chrome | Browser tab | Allowed | ✅ Delivered while Chrome runs (incl. background). Held per TTL if quit |
| Windows | Chrome | Installed PWA | Allowed | ✅ Delivered; exempt from auto-revocation |
| macOS | Safari | Browser tab | Allowed | ✅ **Delivered — no install required.** The key Safari asymmetry |
| macOS | Safari | Added to Dock | Allowed | ✅ Delivered; separate permission scope from the tab |
| macOS | Chrome | Browser tab | Allowed | ✅ Delivered |
| Any | Any | Any | Default (dismissed) | ❌ None. Control remains available. No auto-retry |

### 25.2 Lifecycle and security tests

| Test | Expected |
|---|---|
| Login → enable → subscription row exists, bound to that user | ✅ |
| **Logout → row deleted AND browser unsubscribed** | ✅ Both |
| **Logout with the network down → row still deleted server-side** | ✅ Server is authoritative |
| **User A enables → logs out → User B logs in and enables → endpoint reassigns to B** | ✅ B owns it; A has none |
| **User A enables → logs out (unsubscribe fails) → B logs in → A's push arrives** | ✅ Generic text only; display fetch 404s under B's session |
| Two devices, same user → both receive | ✅ |
| Safari + Chrome on one machine → two rows, both receive | ✅ |
| Delete one device's subscription → other still receives | ✅ |
| Permission revoked in browser settings → next send 410s → row deleted | ✅ |
| Browser data cleared → next send 410s → row deleted | ✅ |
| **Invalid/foreign endpoint submitted (`http://169.254.169.254/…`) → rejected** | ✅ **SSRF guard** |
| Duplicate register of the same endpoint → idempotent, one row | ✅ |
| **Disabled (archived) user → no delivery, even with a live row** | ✅ |
| **Unauthorized event → not delivered even if a rule matched** | ✅ |
| Preference off → no push, **and no change to any API response** | ✅ §16.1 |
| Preference on → push delivered | ✅ |
| **Recipient unassigned between queue and drain → skipped** | ✅ |
| **Push service returns 401 → NO subscriptions deleted, alert raised** | ✅ **The destructive-bug test** |
| Push service returns 410 → that subscription deleted, others untouched | ✅ |
| Notification content contains no name/building/number/price | ✅ Assert against the display route |
| `GET /notifications/{id}/display` for someone else's id → **404, not 403** | ✅ No enumeration |
| Deploy restart mid-drain → pending rows delivered after boot | ✅ |
| Drain task killed → supervisor restarts it, bounded, then logs loudly | ✅ |
| **App loads normally with the SW registered** — no blank page, no stale assets, all platforms | ✅ §12 |

**Automatable in the existing pytest suite:** all of §25.2's server-side rows,
with the push service mocked. **Not automatable:** everything in §25.1 and the
service worker's behavior — there is no frontend test harness, and per the
project owner's standing direction, in-browser click-through testing is done
manually. §25.1 is therefore a **manual checklist that must be run and recorded**,
not aspirational documentation.

---

## 26. Open Questions

### 26.1 Direct answers to the prompt's questions

| # | Question | Answer |
|---|---|---|
| 1 | Can Safari and Chrome both support this? | **Yes** — with one hard condition: on iPhone/iPad the app must be added to the Home Screen. |
| 2 | Exact Safari/iOS limitations? | No push in an iOS Safari tab, ever. Home Screen install is manual and untriggerable. Installed app has a **separate cookie jar → second login**. Permission needs a user gesture. Declarative Push exists but is rejected (§3.4). macOS Safari has none of these limits. |
| 3 | Does the app need to become a PWA? | **Partially.** A manifest + icons: **yes**, to cover iOS <26. Home Screen installation: **required on iOS, optional elsewhere** (worthwhile on Chrome for auto-revocation exemption). Offline capability: **no, and explicitly avoid it.** |
| 4 | Do we need a service worker? | **Yes** — and it must have **no `fetch` handler** (§12). |
| 5 | Do we need a manifest? | **Yes**, practically — required on iOS <26, harmless and useful everywhere else. |
| 6 | Do we need VAPID keys? | **Yes.** One ECDSA P-256 pair per environment. |
| 7 | Where stored? | Private → Render env var, `sync: false` in `render.yaml`, never in git, never logged, never returned. Public → served to the client. |
| 8 | How does a subscription bind to a user? | The browser creates it; the client POSTs it to an **authenticated** endpoint; the server binds it to the caller with `UNIQUE(endpoint)` and reassign-on-register. |
| 9 | What happens on logout? | Client `unsubscribe()`s and sends the endpoint; server deletes the row. Server-side deletion is authoritative. |
| 10 | Multiple devices per user? | N rows per user; fan out to all. Already the socket registry's model. |
| 11 | Preventing wrong-user delivery? | Three layers: `UNIQUE(endpoint)` + reassign; delete-on-logout; **display-time re-authorization** (§6.4) as the guarantee. |
| 12 | Store notification events in Postgres? | **Yes**, from Phase C. It is the outbox, the audit trail, and the in-app fallback. |
| 13 | Store delivery attempts? | **Not for MVP.** Phase F, when per-device retry matters. |
| 14 | Sync or async delivery? | **Asynchronous, always.** Sync would violate `UX-7`. |
| 15 | Do we need a queue immediately? | **A queue, yes — infrastructure, no.** A `notifications` table with a `pending` state drained by a lifespan task. No Redis, no Celery, no RQ. |
| 16 | MVP tables? | `push_subscriptions` alone for Phase A/B; `notifications` from Phase C. |
| 17 | What events could produce notifications? | §22 — twelve candidates backed by real relations, plus three explicitly blocked. |
| 18 | How to model types? | String constants in a **pure domain module** with a fail-closed rule map, mirroring `domain/realtime.audience_allows`. **Never database rows.** |
| 19 | How should preferences work? | Sparse opt-out rows vs code-defined defaults. **Preference governs interruption, never access** (§16.1). |
| 20 | Smallest safe implementation? | §23.3 — ten steps, ending at an admin self-test push on all six platforms, with **no business event wired up**. |

### 26.2 Questions only you can answer

1. **Will the crew accept installing the app to their iPhone Home Screen and
   logging in a second time?** This is the project's kill criterion and should be
   tested with one real technician before Phase B. Everything else is
   recoverable; this is not.
2. **Which of §22's candidates are actually wanted?** The infrastructure is
   type-agnostic; the volume and the value are entirely determined by this list.
   Fewer is better — Chrome's auto-revocation makes over-notification
   self-defeating.
3. **Do you want a durable in-app notification list, or only OS notifications?**
   It changes whether `notifications.read_at` is meaningful and whether the app
   gains a new UI surface (§11.6). It is also the correct fallback if question 1
   fails.
4. **Should the acting user be excluded from their own notifications?** Recommended
   yes, per-type overridable — and note it **differs from the socket layer's rule
   on purpose** (§8.2).
5. **Are any notification types mandatory?** Recommend keeping the set empty or
   near-empty (§16.3).
6. **Is any time-based notification wanted?** If yes, that is a **hosting
   decision** — Render cron or a paid always-on service (§19).
7. **Should a password reset / "sign out everywhere" also drop push
   subscriptions?** Recommended yes, mirroring the existing session-revocation
   behavior in `services.users` (§9.3, T17).
8. **Who is alerted when the drain gives up or VAPID breaks?** There is no
   alerting channel today — only log lines. A loud log nobody reads is not an
   alert (§18).

---

## 27. Final Recommendation

**Proceed with native Web Push, built as the second delivery channel of a single
notification decision, in the phase order of §24 — and gate the whole project on
a Phase A iPhone test with a real user before writing any routing code.**

**Why Web Push is right for this application:**

- The requirement — reach a technician whose phone is in their pocket — cannot be
  met by the existing socket layer, and no amount of work on that layer will
  change it.
- The codebase is unusually well-prepared: session auth that needs no changes, a
  pure authorization predicate ready to reuse, a lifespan hook that already
  exists, a supervised-background-task pattern already written and tested, and a
  documented architectural philosophy (`P1`/`P2`) that maps onto Web Push
  cleanly.
- Native standards need one small synchronous Python dependency and no
  infrastructure. A third-party service would force a hole in a carefully
  verified CSP and hand a small crew's operational data to a vendor, in exchange
  for nothing that solves the actual hard problem (iOS installation).

**Where the risk actually is, ranked:**

1. **The iPhone Home Screen install + second login.** A human/rollout problem, not
   a technical one, and the most likely cause of failure. Test it first.
2. **The service worker reintroducing the stale-cache blank page.** Mitigated
   structurally by having no `fetch` handler and a CI check that keeps it that
   way.
3. **Wrong-user delivery on a shared device.** Mitigated by three layers, of which
   display-time re-authorization is the one that cannot fail.
4. **Notification content on a lock screen.** Mitigated structurally by carrying
   an id, not a sentence, and redacting in one reviewable route.
5. **Volume.** Over-notifying costs the whole crew the feature via Chrome's
   auto-revocation. Fewer types, actor excluded, no aggregate-import events.

**Where this design deliberately says no:**

- No Redis, Celery, RQ, or worker service. A table and a supervised task.
- No FCM SDK, no OneSignal, no vendored JS.
- No offline caching, background sync, or any PWA capability beyond installation.
- No `notification_rules` table. Rules are code.
- No device metadata, user agents, or IP addresses.
- No notification text in the payload or in the database.
- No in-app toasts, badges, or bells (§11.6) — that is a separate decision.
- No time-based notifications until the hosting question is answered.

**If the iPhone constraint proves unacceptable**, the honest fallback is a durable
in-app notification list delivered over the existing WebSocket: no service
worker, no manifest, no VAPID, no push services, no new failure modes — and
genuinely useful. It would not reach a pocketed phone, which is the whole point,
so it is a lesser feature. But it is a real one, and it is strictly better than a
push implementation the crew will not install.

**Nothing in this document should be implemented until §26.2 is answered.**

---

### Sources

Repository: inspection at `f7904e4`, 2026-08-14. Referenced files:
`backend/app/main.py`, `models.py`, `auth_deps.py`, `domain/roles.py`,
`domain/realtime.py`, `domain/work_orders.py`, `services/realtime.py`,
`routers/realtime.py`, `routers/auth.py`, `static/realtime.js`, `static/main.js`,
`static/views/auth.js`, `requirements.txt`, `entrypoint.sh`, `render.yaml`,
`.github/workflows/ci.yml`, `docs/project-summary.md`, `docs/open-work.md`,
`docs/superpowers/specs/2026-08-12-websocket-realtime-layer-design.md`.

Browser and platform documentation:

- [Web Push for Web Apps on iOS and iPadOS — WebKit, 2023-02-16](https://webkit.org/blog/13878/web-push-for-web-apps-on-ios-and-ipados/)
- [WebKit in Safari 18.4 — WebKit, 2025-03-31](https://webkit.org/blog/16574/webkit-in-safari-18-4/)
- [WebKit Features in Safari 26.0 — WebKit](https://webkit.org/blog/17333/webkit-features-in-safari-26-0/)
- [Push API — MDN](https://developer.mozilla.org/en-US/docs/Web/API/Push_API)
- [PushManager.subscribe() — MDN](https://developer.mozilla.org/en-US/docs/Web/API/PushManager/subscribe)
- [Notification.requestPermission() — MDN](https://developer.mozilla.org/en-US/docs/Web/API/Notification/requestPermission_static)
- [Reducing notification overload — Chromium/Google blog, 2025-10-10](https://blog.google/chromium/automatic-notification-permission/)
- [Web Push Interoperability Wins — Chrome for Developers](https://developer.chrome.com/blog/web-push-interop-wins)
- [Increasing web push notification value with rate limits — Chrome for Developers](https://developer.chrome.com/blog/web-push-rate-limits)
- [RFC 8292 — VAPID for Web Push](https://datatracker.ietf.org/doc/html/rfc8292)
- [pywebpush — PyPI (2.4.0, 2026-08-06)](https://pypi.org/project/pywebpush/)
- [Apple reverses decision on EU Home Screen web apps — TechCrunch, 2024-03-01](https://techcrunch.com/2024/03/01/apple-reverses-decision-about-blocking-web-apps-on-iphones-in-the-eu/)
