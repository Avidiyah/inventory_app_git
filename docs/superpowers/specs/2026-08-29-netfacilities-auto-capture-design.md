# NetFacilities Auto-Capture → Import → Enrich — Design Spec

Status: **designed 2026-08-29, not yet implemented.** Builds on
`docs/superpowers/specs/2026-08-28-netfacilities-cloud-auth-design.md`
(the per-user Steel cloud-auth path, now shipped) and repairs it. No
implementation plan exists yet.

Turns the cloud-browser CSV export into one unattended chain: the user
clicks *Download CSV* in the Steel live view, and the app captures the
file, imports it, closes the cloud session, and starts Task/Symptom +
Priority enrichment — with no further clicks. It also fixes three
defects in the shipped capture path, without which none of the above can
work.

---

## 0. Why this exists

Stated requirement: *"When I import the csv, the user downloading that
should immediately begin the import, then task/priority enrichment
begins, all automatic, any user with NetFacilities credentials can use
it."*

Today the chain is broken at its first link. The user exports a CSV in
the cloud browser, sees Chrome's download icon appear, and nothing ever
reaches the app. The file is not lost — it lands in Steel's session
storage and is listed correctly — but every attempt to retrieve it
fails, silently, and the failure kills the poll loop that would have
retried.

## 1. Root cause — the three defects

Diagnosed 2026-08-29 from production logs, a live inspection of the
deployed app at `inventory-app-gb1c.onrender.com`, the `steel-sdk==0.19.0`
wheel, and Steel's Files API documentation.

### D-A. The download call is malformed (the 400)

Production log, user `c3839464-…`:

```
BadRequestError('Error code: 400 - {'error': 'Bad Request', 'message':
"A file path is required. Provide a relative path with no leading '/',
'..', or '~', e.g. 'downloads/report.pdf'."}')
```

Two independent mistakes produce it:

1. **`DOWNLOAD_PATH = "/downloads"`** (`cloud_steel.py:28`) is not
   Steel's directory. The documented download target is **`/files`**.
2. **The listed path is passed to `download()` verbatim**
   (`cloud_steel.py:127`). Steel's docs are explicit that listing
   returns paths carrying a `/files/` prefix and that you *"strip that
   prefix before interpolating the value into the URL."* We strip
   nothing, so a leading `/` reaches the server.

Note on relative weight: the export *was* listed by `files.list()` — the
400 comes from `download()`, which only runs after a `.csv` entry is
found — so Steel evidently indexes `/downloads` too. **Stripping the
leading slash is therefore the load-bearing fix; moving to `/files` is
alignment with the documented contract, not strictly required.** Both are
in scope: relying on an undocumented directory is how this class of bug
recurs.

The SDK is not at fault and our call shapes are correct. Verified in the
wheel: `sessions.files.list(session_id)` is positional and
`download(path, *, session_id=...)` matches ours. `download()` builds
`path_template("/v1/sessions/{session_id}/files/{path}", …)`, and
`_quote_path_segment_part` percent-encodes `/` inside the interpolated
value — its own comment reads *"unlike the default `safe` for quote(),
`/` is unsafe and must be quoted."* So the leading slash survives
encoding and arrives as the server sees it. Steel's docs confirm nested
relative paths with interior slashes are accepted, so encoding of
interior separators is not a problem — only the leading one.

### D-B. The failure kills the capture loop permanently

`_poll_for_csv` (`netfacilities_cloud_auth.py:180-209`) calls
`poll_downloaded_csv` with no guard, and `_poll_until_signed_in` catches
only `CancelledError`. The `BadRequestError` therefore unwinds the whole
poll task on the first CSV it ever sees. This is the
`Task exception was never retrieved` line in the logs; the
`ImportError: sys.meta_path is None` above it is the logging module
dying during interpreter teardown, not a second fault.

Consequence: the ceremony stays parked in `signed_in`, the UI keeps
saying *"Export the work-order CSV in that window"*, and nothing polls
again for the life of the process. Retrying the export cannot help.

Compounding it, `_seen_files.add(path)` runs *before* the download
(`cloud_steel.py:126`), so even a transient failure blacklists that file
for the rest of the ceremony.

### D-C. Ceremony state never reconciles with the vendor

Observed live on 2026-08-29 at 19:09 UTC. `GET /cloud/session` reported:

```json
{"state": "signed_in", "signed_in_at": "2026-08-29T18:50:43Z",
 "finished_at": null, "last_download_filename": null,
 "live_view_url": "https://api.steel.dev/v1/sessions/66f9a985-…/player"}
```

Opening that `live_view_url` showed **"Browser Disconnected."** Steel had
reaped the session; the app never noticed, 18 minutes on. The user is
told they are signed in and sent to a dead player.

The cause is structural: once `poll_signed_in` succeeds,
`_poll_until_signed_in` returns into `_poll_for_csv`, which has no
deadline at all. Nothing but an explicit Cancel or a process restart ever
ends a signed-in ceremony — so the session is also billed until Steel's
own cap reaps it.

## 2. Decisions locked

| # | Decision | Choice |
|---|---|---|
| E1 | Role gate | **Unchanged — TechFM OA+.** The flow is already per-user: each OA signs in with their own NetFacilities credentials from any device, which satisfies "any user with NetFacilities credentials." Lowering the gate would let technicians create and update work orders org-wide through the import, which is a separate decision and not part of this spec. |
| E2 | Capture trigger | **Playwright `download` listener as the trigger, Steel Files API for the bytes.** The listener removes polling latency; the Files API is the vendor's own documented retrieval path and the one we can prove works once D-A is fixed. |
| E3 | Capture fallback | **A safety-net poll stays**, at a slower interval than today. If the listener never fires over `connect_over_cdp` (unverified — see §3), capture still works, a few seconds later. |
| E4 | Import trigger | **Automatic and unconditional** on capture. No confirmation step. |
| E5 | Enrichment on collision | **Queued.** `jobs.start()` returns `(snapshot, created=False)` while a batch runs; the chain retries until `created` is true, under a cap. Nothing is dropped. |
| E6 | Session lifetime | **Closed after a *successful* import.** One export per sign-in on the happy path. A failed import (wrong or malformed CSV) **keeps the session open** so the user can immediately download the right file without repeating the sign-in ceremony. `storage_state` is already persisted, so enrichment is unaffected either way. |
| E7 | Signed-in ceremonies get a deadline | **10 minutes** with no successful capture, then close and expire. Sits under Steel's own 15-minute session cap. E6 covers the success path; this covers abandonment and the failed-import case, so a kept-open session cannot leak. Fixes the billing leak in D-C. |
| E8 | Manual import button | **Kept**, hidden unless a capture is sitting unconsumed, and it **runs the same chain** — import *and* enrichment. Whether capture was automatic or the user clicked the fallback, behavior is identical. |
| E9 | Enrichment scope | **Global sweep, unchanged.** `_load_candidates` already selects every work order with a blank description or priority org-wide, so imported rows are covered and the existing backlog is cleaned up as a side effect. No candidate-filter plumbing. |
| E10 | Completion reporting | **Web push on completion *and* on failure**, via the existing VAPID setup. An unattended chain must reach the user whether or not the tab is still open. The in-page status line stays as the live narration. Both carry the reconcile sweep's counts — see §2a. |
| E11 | Calling `run_csv_import` | The chain **opens its own `Session` and constructs its own `BackgroundTasks()`**, then awaits it. No refactor of `run_csv_import`, which two live routes already depend on. |
| E12 | Timings | Ceremony deadline **10 min**; safety-net poll **5 s** (slower than today's 3 s, since the listener is primary); enrichment collision retry cap **2 min**. |

## 2a. Amendment (2026-08-30): the import now reconciles

`2026-08-30-netfacilities-reconcile-design.md` adds two things to
`import_work_orders`, which this chain reaches through `run_csv_import`
(E11) and therefore inherits with no plumbing: live work orders absent
from the CSV are auto-closed, and sweep-closed ones listed again are
reopened. `WorkOrderImportResult` gains `auto_closed` and `reopened`.

An unattended import has nobody watching the summary line, so this spec
absorbs the reporting duty (reconcile decision 9):

- **Snapshot.** `import_result` on the ceremony snapshot is the whole
  `WorkOrderImportResult`, so the frontend narration (§4.5) renders the
  "imported" step with `workOrders.js::importSummary` — the same text a
  clicked import shows, including `14 closed (not in NetFacilities)` and
  `1 reopened (back in NetFacilities)` clauses when non-zero.
- **Push (E10, §4.6).** The success body names the closes and reopens when
  non-zero: *imported 3 work orders · 14 closed (not in NetFacilities) · 1
  reopened; enrichment started.* The `docs/notification-events.md` row for
  this push carries that shape.
- **Nothing else changes.** The sweep's own safety valve is the
  Integrations-page *Undo auto-close* button, which reads pending state on
  page entry and so needs no hook here.

## 3. The one thing still unverified

**Whether `page.on("download")` fires at all** for a download initiated by
a human clicking in the Steel live view, on a browser we reached via
`connect_over_cdp` and whose download behavior we set ourselves through
raw CDP.

It could not be settled from the browser — the event fires inside our
server's Playwright connection, not in any Chrome we can drive from here
— and settling it requires deploying instrumented code. Two facts argue
for caution: Playwright's `download.path()` is documented to throw when
the browser is connected remotely, and Steel's own documented capture
pattern is CDP + Files API, not a Playwright listener.

**This is why E3 exists.** The design does not depend on the answer. If
the listener fires, capture is instant; if it never fires, the safety-net
poll catches the file and we delete the listener in a follow-up. The
implementation must log which path won, so the question gets answered by
production rather than by argument.

This is deliberate: the defect in D-A shipped because a vendor API shape
went to production untested. Betting the capture path on a second
unverified vendor behavior would repeat that mistake.

## 3a. Delivery in two phases

**Phase 1 — unblock capture.** D-A and D-B plus their tests: path
normalization, the guarded loop, retryable `_seen_files`, and the
`files` resource the existing fake lacks. A handful of lines. Exports
stop vanishing, and the manual Import button starts working again.

**Phase 2 — the chain.** Listener, automatic import, session lifetime,
enrichment queueing, expiry, push, frontend narration.

The split is deliberate: Phase 2 gets built on a capture path already
proven in production, so a chain bug and a capture bug can never be
confused for one another. It also gives §3's open question a known-good
baseline to be answered against.

## 4. Design

### 4.1 Capture (`cloud_steel.py`)

- `DOWNLOAD_PATH` becomes `/files`.
- A `_relative(path)` helper strips a leading `/files/` prefix, then any
  remaining leading `/`, before the path reaches `download()`.
- `poll_downloaded_csv` skips zero-byte entries and `.crdownload`
  entries, so a poll cannot capture a half-written export.
- `_seen_files.add(path)` moves to *after* a successful read, so a
  transient failure is retryable.
- `open_login_session` attaches `context.on("page", …)` and
  `page.on("download", …)`, recording completed downloads on the session
  object. The listener records the *event*; the bytes are still fetched
  through the Files API.
- `Browser.setDownloadBehavior` moves to a browser-level CDP session
  (`browser.new_browser_cdp_session()`), and its failure is no longer
  swallowed — it propagates as `NetFacilitiesUnavailable`, because a
  ceremony that cannot capture downloads is not a working ceremony.

### 4.2 The chain (`netfacilities_cloud_auth.py`)

`_poll_for_csv` becomes `_capture_and_dispatch`, driven by the listener
with the poll as backstop, and every provider call is wrapped so a vendor
error logs and continues instead of killing the loop (D-B).

On capture:

1. Record `last_download_filename` / `last_download_at` on the snapshot.
2. **Import.** The chain has no request scope, so it opens its own
   `Session` from `self._session_factory` and constructs its own
   `BackgroundTasks()`, then awaits it after `run_csv_import` returns so
   the supervisor notifications still fire (E11). Import runs in a worker
   thread — `import_work_orders` is synchronous and must not block the
   event loop.
3. **Close the session — only if the import succeeded** (E6):
   `close_login_session`, snapshot moves to `closed`. On failure the
   session stays open and the ceremony keeps its E7 deadline, so the user
   can re-export immediately and a kept-open session still cannot leak.
4. **Enrich.** Resolve the user's cloud enrichment context and call
   `jobs.start()`, retrying while `created is False` under the E12 cap.
5. **Notify** (E10).

Import result (the full `WorkOrderImportResult`, so the reconcile counts
ride along — §2a) and enrichment job id are recorded on the snapshot so
the UI can report both without inventing a second polling channel.

Ordering note: on the success path the session closes *before*
enrichment starts, and enrichment opens its own short-lived replay
session from the persisted `storage_state`. The two never overlap, so a
user's ceremony and their enrichment job cannot contend for the same
Steel session. On the failure path no enrichment starts at all, so the
still-open ceremony has nothing to contend with either.

This whole sequence is a single function shared by the automatic trigger
and the manual button (E8), so the two routes cannot drift.

### 4.3 Shared helper (`_resolve_cloud_enrichment_context`)

Currently a private function in `routers/netfacilities.py:139`. Both the
router and the chain now need it, so it moves to the service layer. This
is a move, not a rewrite — the router keeps calling it.

### 4.4 Ceremony expiry (D-C, E7)

A signed-in ceremony gets a deadline. On expiry: close the Steel session,
move the snapshot to `timed_out`. `GET /cloud/session` never again
advertises a `live_view_url` for a session we have released.

Out of scope, and named as a known gap: detecting that Steel reaped a
session early, before our deadline. The deadline bounds the damage; live
vendor-side health checking is a follow-up.

### 4.5 Frontend (`views/workOrders.js`)

The status line narrates the chain: captured → importing → imported (with
counts) → enriching → done. The existing `NETFACILITIES_SESSION_POLL_MS`
loop already polls `/cloud/session`; it carries the new fields. The
manual Import button (E8) appears only when a capture was not
automatically consumed, and triggers the same chain as the automatic
path — including enrichment.

### 4.6 Completion notification (E10)

The chain sends a web push on both outcomes, through the existing VAPID
setup, addressed to the ceremony's own user:

- **Success** — imported *n* work orders, plus *m closed (not in
  NetFacilities)* and *k reopened* when those counts are non-zero (§2a);
  enrichment started (or queued).
- **Failure** — which stage failed (capture, import, enrichment) and what
  the user can do: re-export while still signed in (import failure, E6),
  or click Enrich later (collision cap reached, E5).

This is the only channel that reaches a user who closed the tab, which
an unattended chain makes the normal case rather than the exception.
Notification content is defined in `docs/notification-events.md`, the
repo's single trigger table — this adds rows there rather than starting
a new vocabulary.

## 5. Error handling

| Failure | Behavior |
|---|---|
| Files API error on retrieval | Log, continue polling. Never kills the loop (D-B). |
| Import raises `DomainError` (malformed CSV) | **Session stays open** (E6) so the user can re-export without signing in again; the E7 deadline still bounds it. Capture retained, snapshot records the error, manual button offered (E8), failure push sent (E10). No enrichment. |
| Enrichment still busy after the retry cap | Import stands. Snapshot says enrichment was not started; UI offers the Enrich button; push says so (E10). |
| `setDownloadBehavior` fails | Ceremony fails at `open_login_session` with `NetFacilitiesUnavailable`. No silent half-working session. |
| Steel session dies mid-ceremony | Bounded by the E7 deadline. |

## 6. Testing

Offline, no live vendor, matching this suite's `asyncio.run()` convention:

- **`_relative()` path normalization** — `/files/x.csv`, `files/x.csv`,
  `/downloads/x.csv`, `x.csv`. This is the regression test for D-A and
  the one that would have caught the shipped bug.
- **`poll_downloaded_csv` against a fake `files` resource that returns
  absolute paths the way the real API does.** `FakeSteelClient` currently
  has no `files` resource at all, which is why D-A shipped — the existing
  fake cannot fail this way.
- Skips zero-byte and `.crdownload` entries.
- A failed download does not blacklist the file; the next poll retries.
- **A provider error does not kill the capture loop** (D-B).
- **The full chain**: capture → import called once with the right bytes →
  session closed → `jobs.start` called.
- **Collision**: `jobs.start` returning `created=False` retries and
  eventually starts (E5).
- **Import failure**: session stays **open** (E6), capture retained, no
  enrichment, failure push sent.
- **The manual button runs the same chain** — import *and* enrichment
  (E8), asserted against the same shared function the automatic trigger
  uses.
- **Push fires on both outcomes** (E10), with the failing stage named.
- **Expiry**: a signed-in ceremony past its deadline closes and reports
  `timed_out` (E7).

`FakeContext` also gains the `new_page` / `new_cdp_session` surface it
lacks today — its absence means the current tests exercise the
`except Exception` branch of the download-behavior setup rather than the
real path, which hid D-A's neighborhood from view entirely.

## 7. Out of scope

- Lowering the role gate below TechFM OA (E1).
- Vendor-side session health checks (§4.4).
- Any change to enrichment candidate selection. `_load_candidates`
  already selects every work order with a blank description or priority
  org-wide, so newly imported rows are picked up with no scoping work.
- Browserbase or any second vendor. The `CloudBrowserProvider` boundary
  is unchanged by this spec.

## 8. Sources

- Steel Files API — https://docs.steel.dev/overview/files-api/overview
  (documented download path `/files`; listing returns a `/files/` prefix
  that must be stripped; relative nested paths accepted).
- `steel-sdk==0.19.0` wheel, `steel/resources/sessions/files.py` and
  `steel/_utils/_path.py` (call signatures; segment-quoting of `/`).
- Production logs and live inspection of
  `inventory-app-gb1c.onrender.com`, 2026-08-29.
