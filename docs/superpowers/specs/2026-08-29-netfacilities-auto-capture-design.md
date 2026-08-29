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
| E6 | Session lifetime | **Closed immediately after the first successful capture.** One export per sign-in. `storage_state` is already persisted, so enrichment is unaffected. |
| E7 | Signed-in ceremonies get a deadline | A signed-in ceremony that never produces a CSV now expires (E6 covers the success path; this covers abandonment). Fixes the billing leak in D-C. |
| E8 | Manual import button | **Kept**, hidden unless a capture is sitting unconsumed. It is the fallback when the chain fails, and removing it would leave no recovery path. |

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
   the supervisor notifications still fire. Import runs in a worker
   thread — `import_work_orders` is synchronous and must not block the
   event loop.
3. **Close the session** (E6): `close_login_session`, snapshot moves to
   `closed`.
4. **Enrich.** Resolve the user's cloud enrichment context and call
   `jobs.start()`, retrying while `created is False` under a cap (E5).

Import result and enrichment job id are recorded on the snapshot so the
UI can report both without inventing a second polling channel.

Ordering note: the session closes *before* enrichment starts, and
enrichment opens its own short-lived replay session from the persisted
`storage_state`. The two never overlap, so a user's ceremony and their
enrichment job cannot contend for the same Steel session.

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
automatically consumed.

## 5. Error handling

| Failure | Behavior |
|---|---|
| Files API error on retrieval | Log, continue polling. Never kills the loop (D-B). |
| Import raises `DomainError` (malformed CSV) | Capture retained, snapshot records the error, manual button offered (E8). Session still closes. No enrichment. |
| Enrichment still busy after the retry cap | Import stands. Snapshot says enrichment was not started; UI offers the Enrich button. |
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
- **Import failure**: session still closes, capture retained, no
  enrichment.
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
