# NetFacilities Live Session — Design Spec

Status: **designed 2026-08-28, not yet implemented.** Tracks `IMP-039` in
`docs/open-work.md`. Implementation plan:
`docs/superpowers/plans/2026-08-28-netfacilities-live-session.md`.

Turns the one-shot "sign in, save state, close the browser" ceremony into a
**live session**: the dedicated NetFacilities window stays open after login,
the CSV the operator exports from it lands in their Downloads folder under its
real name, and enrichment runs through that same signed-in window instead of a
second headless browser. The operator's workflow becomes exactly:

> Click **Log in to NetFacilities** → log in (credentials, CAPTCHA, MFA) →
> export the work-order CSV in that window → click **Import downloaded CSV**
> (or pick it with **Import from CSV…**) → Task/Symptom and Priority fill in.

---

## 1. Why this exists

Three things about the current flow are wrong for the operator, and all three
are consequences of one design choice: the login was modelled as a *stored
credential* rather than as a *step in a job*.

1. **The operator logs in twice.** `POST /auth/confirm` verifies the page,
   saves `playwright-storage-state.json`, and **closes the dedicated browser**
   (`services/netfacilities_auth.py:163`). The operator then needs the CSV,
   which lives behind the same login — so they sign in again in their normal
   browser, CAPTCHA and MFA included. The saved state exists precisely so the
   app can act *without* the operator, but the operator has to be present
   anyway to get the CSV.
2. **Downloads in the dedicated browser are silently cancelled.** The headed
   persistent context launches with `accept_downloads=False`
   (`integrations/netfacilities/client.py:141-146`). Playwright never writes a
   cancelled download anywhere, so an operator who exports the CSV from the
   dedicated window gets nothing and no error. This is why the "download it in
   the app's own browser" workflow does not work today even if the window were
   left open.
3. **Expiry is a surprise.** The saved state is bearer-equivalent and has no
   expiry clock. The first sign it has lapsed is an enrichment job ending
   `authentication_required`. Because every enrichment run in the new model
   begins with a fresh login, "expired between runs" stops being a state the
   app can be in.

The vendor-side facts do not change: the credential entry, CAPTCHA, and MFA
still need a human in a headed browser on a Windows host, and the app still
never receives a credential field. What changes is that the human is already
there for the CSV, so the login stops costing anything extra.

**This spec is local-Windows only.** The headed window only exists where
`interactive_authentication_available` is true (`config.py:110-124`), which is
`sys.platform == "win32"`. Render keeps the operator-provisioned secret-file
path untouched (§10 sketches the follow-up that would bring the same model to
Render).

---

## 2. Decisions locked

Settled with the owner on 2026-08-28. Changing any of these reopens the design.

| # | Decision | Choice |
|---|---|---|
| D1 | Browser lifetime | **The window stays open after login.** `confirm()` verifies, saves state, and returns with the session in a new `signed_in` state. Nothing closes the window except: the operator clicking **Close NetFacilities**, the operator closing the window themselves, the session idle timeout, or application shutdown. |
| D2 | Sign-in detection | **Automatic, with the manual button kept as a fallback.** A coordinator task polls once a second with a *local* check (any page on the allowlisted host and off the login path — `verify_authentication_page`, no network). When that passes it calls `confirm()`, which performs the *server-verified* probe (`GET /myhome`, the existing priming request) before saving state. A failed probe waits 5 s before the next try. **I finished signing in** still calls the same `confirm()`. |
| D3 | Downloads | **Accepted and saved under the suggested filename.** The headed context launches with `accept_downloads=True`; a `download` handler is attached to every page (existing and later-opened). Files go to `config.download_dir` — `%USERPROFILE%\Downloads` when it exists, else `<profile_dir>\downloads`, overridable with `NETFACILITIES_DOWNLOAD_DIR`. A name collision appends ` (1)`, ` (2)`, … **The app never initiates a download**; it saves the one the operator triggers. Only a `.csv` download is recorded as "the captured CSV"; other downloads are saved and otherwise ignored. |
| D4 | Enrichment transport | **Enrichment borrows the live window.** `POST /work-orders/enrich` asks the session coordinator for the live client first; if one exists the job reads through the persistent context's `request` API — the pure-HTTP path priming already uses (`client.py:311-352`) and the headed path already reads through (`client.py:354-380`). No second browser, no storage-state file read, no separate profile lease. The saved-state headless path stays as the fallback when no window is open, and remains the only path on Render. |
| D5 | Import in one click | **New `POST /integrations/netfacilities/downloads/import`** imports the most recently captured CSV through *exactly* the pipeline `POST /work-orders/import` uses (extracted into one shared function). **Import from CSV…** stays. The app still creates work orders only from a CSV a human exported. |
| D6 | Storage state | **Still written at confirm.** It keeps the headless fallback working, and it is how the Render secret file gets generated. |
| D7 | Secret-safety | Unchanged. Responses and logs carry **filenames only** for downloads — never a directory, path, cookie, HTML, header, or source value. The captured file's path lives in coordinator memory and is read by one server-side route. |
| D8 | Concurrency | One profile lease, as today. The live session holds the `authentication` lease from `start` to close. A borrowed job does **not** acquire a lease; while it runs, `cancel` is refused with 409 and the idle timeout waits. Shutdown cancels the job *before* closing the window (lifespan order swapped). |
| D9 | Page feedback | While the session is `authenticating` or `signed_in`, the Integrations card polls `GET /session` every 3 s (skipped while the tab is hidden or a job poll is running) so auto-confirm, a saved CSV, and a closed window all show up without a click. |
| D10 | Testing | Backend: offline unit tests with fakes, same style as the existing five `test_netfacilities_*.py` files. Frontend: `node --check` plus the owner's manual click-through (§11). No live NetFacilities request in any test. |

---

## 3. Hard constraints found in the code

Each of these was verified in the tree at `2858221` and each kills an obvious
shortcut.

### 3.1 `accept_downloads=False` cancels the download outright

Playwright does not save downloads to the OS Downloads folder. It either
cancels them (`accept_downloads=False`) or stores them under a GUID in a
temporary directory that is deleted with the context. Getting a file the
operator can find therefore *requires* a `download` event handler calling
`download.save_as(...)` with the suggested filename. There is no
configuration-only fix.

### 3.2 The headed context already reads through pure HTTP

With `use_saved_state=False` (the headed path), `_read_work_order_document`
routes to `_request_work_order_document`, which is a `context.request.get`
— an `APIRequestContext` call sharing the persistent context's cookies. It
executes no JavaScript and loads no subresources; it is strictly *more*
isolated than the saved-state navigation path with route blocking. Priming
(`_ensure_session_primed`) already uses the same API in production. Borrowing
the live client for enrichment is therefore reuse, not a new transport.

### 3.3 The auth coordinator and the job coordinator share one gate

`NetFacilitiesOperationGate` issues one lease. Today `confirm` releases the
authentication lease when it closes the browser, and the job takes its own
`enrichment` lease. With the window staying open, the authentication lease is
held for the whole session, so a job that borrows the window must **not** try
to acquire a lease — it would deadlock against its own session.

### 3.4 Only a `confirm` that succeeds against the server counts

`verify_authentication_page` is a URL check. Right after `goto(BASE_URL)` the
URL can be the site root for an instant before a client-side redirect to the
login page, so a local check alone could report "signed in" while the operator
has not typed anything. The auto-confirm loop uses the local check only as a
cheap gate; `confirm()` must always do the `GET /myhome` probe before it
declares `signed_in`, and a probe that fails (`AuthenticationRequired` or an
unexpected status) must leave the session *pending*, not failed.

### 3.5 Windows event loop

Unchanged constraint: local Uvicorn must run as one process without
`--reload`; `_require_subprocess_capable_event_loop` rejects
`SelectorEventLoop` before Playwright starts.

### 3.6 `POST /work-orders/import` is not just a service call

`routers/work_orders.py:596-656` wraps `wo_service.import_work_orders` with two
realtime invalidations and the batched supervisor push. A second import route
that calls only the service would silently drop those. The route body is
extracted into one function both routes call (D5).

### 3.7 Files stay under 500 lines

`services/netfacilities_auth.py` is 300 lines and grows. The borrowed-client
context manager goes into a new 40-line module rather than into the
coordinator.

---

## 4. The workflow, as the operator sees it

Integrations page, NetFacilities card, TechFM OA or above, local Windows host.

1. Card shows **Log in to NetFacilities**. Click it. A dedicated Chrome window
   opens on the NetFacilities sign-in page. Card says: *Log in to NetFacilities
   in the window that opened. This page will notice when you're in.* Buttons:
   **I finished signing in** (fallback), **Close NetFacilities**.
2. Operator logs in. Within ~1–6 s the card flips to *NetFacilities is open and
   logged in. Export the work-order CSV in that window; it is saved to your
   Downloads folder and can be imported from here.* Buttons: **Close
   NetFacilities**, **Import from CSV…**, **Import Tasks and Priority**.
3. Operator exports the CSV in the NetFacilities window. The file lands in
   Downloads as, e.g., `WorkOrders.csv`. Within ~3 s the card says *Saved
   WorkOrders.csv to your Downloads folder. Click Import downloaded CSV to
   import it and fill in Task/Symptom and Priority.* A new **Import downloaded
   CSV** button appears.
4. Operator clicks **Import downloaded CSV**. The import summary appears
   (*N new work orders · M with a supervisor name match.*), the list reloads,
   and enrichment starts automatically through the open window: *Seeking
   Task/Symptom and Priority in NetFacilities… Currently requesting work
   order 12345678.*
5. Enrichment finishes: *NetFacilities enrichment completed: checked 290 of
   290 candidates · …* followed by the signed-in guidance. The operator clicks
   **Close NetFacilities** (or just closes the window). Card returns to **Log
   in to NetFacilities** / **Log in again**.

Every step that touches the vendor is still triggered by the human: opening
the window, logging in, clicking Export. The app only saves what the operator
exported and reads work orders that already exist locally.

---

## 5. State machine

### 5.1 Session (authentication coordinator)

```
starting ──► awaiting_confirmation ──► confirming ──► signed_in ──► closed
                    │                       │                         ▲
                    │ (probe fails: back    │                         │
                    │  to awaiting)         │                 cancel / window
                    ▼                       ▼                 closed / shutdown
   cancelled  timed_out  failed        failed              timed_out (idle)
```

- `starting`, `awaiting_confirmation`, `confirming` are **pending** (unchanged
  set; `_active_locked()` keeps meaning "pending").
- `signed_in` is new and **not terminal**: the lease is held, the client is
  live, `signed_in_at` is set, `finished_at` is `None`.
- `closed` is new and terminal: an intentional close (cancel route, operator
  closed the window, shutdown) of a signed-in session. `failure` is `None`.
- `timed_out` now covers both the pending timeout (`auth_timeout_seconds`,
  default 900) and the idle session timeout (`session_timeout_seconds`, new,
  default 7200). The idle timer starts at `signed_in`; if a job is borrowing
  the window when it fires, it re-checks every 60 s instead of closing.
- `authenticated` **is removed**. Nothing produced it except the old
  `confirm`, and the frontend never read it.
- `start()` while pending **or** signed in returns the current snapshot with
  `created=False` — the window is already open.
- `cancel()` ends whichever is active: pending → `cancelled`, signed in →
  `closed`. Raises `NetFacilitiesOperationInProgress` while a job is borrowing
  the window.

### 5.2 Snapshot fields (all secret-free)

```python
@dataclass(frozen=True, slots=True)
class NetFacilitiesAuthenticationSnapshot:
    attempt_id: UUID
    state: AuthenticationState
    started_at: datetime
    finished_at: datetime | None = None
    failure: AuthenticationFailure | None = None
    signed_in_at: datetime | None = None          # new
    last_download_filename: str | None = None     # new — name only, never a path
    last_download_at: datetime | None = None      # new
```

Transitions within one attempt use `dataclasses.replace`, so the download
fields survive every later state, including `closed`. `start()` resets them
with a fresh attempt.

### 5.3 Job (job coordinator)

Unchanged states. One new field: `source: "live_session" | "saved_state"`.
`start(config, *, live_client_context=None)`:

- with a live context: skip the `has_saved_authentication` check, skip the
  gate, run `enrich_work_orders` against the borrowed client;
- without: exactly today's behaviour.

---

## 6. API changes

All under `/integrations/netfacilities`, all TechFM OA+.

| Method | Path | Change |
|---|---|---|
| GET | `/session` | `state` gains `signed_in`. Precedence: `unavailable` → `running` → `authenticating` → **`signed_in`** → `not_authenticated` → `expired` → `ready`. One exception inside `signed_in`: if the latest job is `authentication_required`, has `source == "live_session"`, and finished after `signed_in_at`, report **`expired`** with message *Your NetFacilities window is no longer logged in. Close it and log in again.* `latest_authentication` carries the three new snapshot fields. |
| POST | `/auth/start` | Unchanged contract. While signed in, returns the live attempt (202, `created` is not exposed). |
| POST | `/auth/confirm` | Unchanged contract; success now returns `state: "signed_in"`. A probe that says "not signed in" or returns an unexpected status is the existing 409 *Finish signing in, then confirm again.* |
| POST | `/auth/cancel` | Now also closes a signed-in window (`state: "closed"`). **409** *Enrichment is still using the NetFacilities window; wait for it to finish.* while a job borrows it. |
| POST | `/work-orders/enrich` | Prefers the live window. Response gains `source`. The 409 for "no way to authenticate" is unchanged. |
| GET | `/work-orders/enrich/{job_id}` | Response gains `source`. |
| POST | `/downloads/import` | **New.** Imports the most recently captured CSV. Response: `WorkOrderImportResult` (same as `/work-orders/import`). **409** *No CSV has been exported through the NetFacilities window yet. Export it there, or use Import from CSV….* when nothing was captured; **409** *The exported CSV is no longer where it was saved. Export it again, or use Import from CSV….* when the file is gone; **413** over `MAX_CSV_UPLOAD_BYTES`; `DomainError` mapping identical to the upload route. Sync `def`, like the upload route, because the import is one long transaction. |

Schema literals: `NetFacilitiesAuthenticationAttempt.state` = `starting |
awaiting_confirmation | confirming | signed_in | closed | failed | cancelled |
timed_out`; `NetFacilitiesCapability.state` adds `signed_in`;
`NetFacilitiesEnrichmentJob.source` = `live_session | saved_state | null`.

---

## 7. Configuration

Two additions, both read only on the Windows branch of
`load_netfacilities_config`; both `None`/default when disabled or on Linux.

| Variable | Default | Rule |
|---|---|---|
| `NETFACILITIES_SESSION_TIMEOUT_SECONDS` | `7200` | Positive whole number (`_positive_seconds`). Idle limit for a signed-in window. |
| `NETFACILITIES_DOWNLOAD_DIR` | `%USERPROFILE%\Downloads` if it is a directory, else `<NETFACILITIES_PROFILE_DIR>\downloads` | When set: absolute, outside the repository, and not an existing non-directory — the same three checks `_profile_dir` makes. |

`NetFacilitiesConfig` gains `session_timeout_seconds: int` and
`download_dir: Path | None = None`. No change to `render.yaml` or the
Dockerfile.

---

## 8. Client changes (`integrations/netfacilities/client.py`)

- Headed launch passes `accept_downloads=True`. The saved-state launch keeps
  `accept_downloads=False`.
- `capture_downloads(destination: Path, on_saved)` attaches a `download`
  handler to every current page and, via `context.on("page")`, to every later
  one. The handler schedules `_save_download`, which makes the directory,
  picks a unique target (`_unique_download_path`), calls
  `download.save_as(target)`, and awaits `on_saved(target)`. Save failures are
  logged with the exception class only and never raised into Playwright.
- `on_context_closed(callback)` registers `context.on("close")`; the client
  records that the context is gone so `__aexit__` skips the second `close()`.
- `prime_session()` = reset the primed flag and run `_ensure_session_primed`.
  This is the server-verified probe `confirm()` uses; it also leaves the
  session primed for the enrichment that follows.
- `wait_for_downloads()` awaits any in-flight saves; `__aexit__` calls it
  (bounded by the request timeout) before closing.
- `NetFacilitiesAuthenticationClientProtocol` (in `contracts.py`) now also
  extends `NetFacilitiesClientProtocol` and declares `prime_session`,
  `capture_downloads`, `on_context_closed`. Test fakes implement all of them.

---

## 9. Frontend (`views/workOrders.js`, `pages/integrations.html`, `api.js`, `tips.js`)

- Buttons: *Sign in to NetFacilities* → **Log in to NetFacilities** (and
  *Sign in again* → **Log in again**); *Cancel sign-in* → **Close
  NetFacilities**; new **Import downloaded CSV** (`id`
  `wo-netfacilities-import-download-btn`, hidden unless `signed_in` with a
  captured filename). **I finished signing in** unchanged.
- Visibility matrix (`updateNetFacilitiesControls`):

  | state | Log in | I finished | Close | Import downloaded CSV | Import Tasks and Priority |
  |---|---|---|---|---|---|
  | unavailable | hidden | hidden | hidden | hidden | hidden |
  | not_authenticated / expired (no window) | shown | hidden | hidden | hidden | disabled |
  | expired (window open, live job lost auth) | hidden | hidden | shown | hidden | disabled |
  | authenticating | hidden | shown (enabled only in `awaiting_confirmation`) | shown | hidden | disabled |
  | signed_in | hidden | hidden | shown | shown iff captured filename | enabled |
  | ready (saved state, no window) | shown ("Log in again") | hidden | hidden | hidden | enabled |
  | running | hidden | hidden | shown, disabled | hidden | disabled |

- Status line: the `signed_in` branch composes (a) the latest job's result
  line, only if that job finished after `signed_in_at`, and (b) the
  signed-in guidance, which names the captured file when there is one.
- Polling (D9): `ensureNetFacilitiesSessionPolling()` runs while
  `capability.state ∈ {authenticating, signed_in}`.
- After any successful import (upload or captured), enrichment starts when
  `capability.state` is `ready` **or** `signed_in`.
- `tips.js` `integrations.netfacilities` copy describes the new flow.

---

## 10. Out of scope (deliberately)

- **Render.** The hosted service cannot open a window on the operator's desk.
  The follow-up that brings this model to Render is an *ephemeral in-memory
  state handoff*: the local `auth` CLI posts the storage state to a TechFM OA+
  endpoint that holds it for one job and never writes it to disk. Not in this
  spec; it needs its own threat-model pass.
- **Auto-import on download.** Tempting once the bytes are in hand, but a
  download is not always the work-order export, and "a human clicked Import"
  is the boundary that keeps CSV import the sole, deliberate create path.
  **Import downloaded CSV** is one click and keeps that boundary.
- **Scheduled / unattended enrichment.** Requires a login without a human,
  which requires the vendor to offer a token or MFA-exempt account.
- **A notification when enrichment finishes** (open-work item 5 in the
  notification list). Unrelated to this change; the card polls.

---

## 11. Manual acceptance (owner, local Windows host)

Run Uvicorn as one process without `--reload`, `NETFACILITIES_ENABLED=true`,
`NETFACILITIES_PROFILE_DIR` set. Do not start the server on the implementer's
behalf — per the owner's standing preference, the implementer hands over this
list.

1. Integrations → **Log in to NetFacilities**. Chrome opens on the sign-in
   page; card shows the *window that opened* message and **Close
   NetFacilities**.
2. Log in. Without clicking anything, the card flips to the signed-in message
   within ~6 s. The window is still open. `playwright-storage-state.json` in
   the profile directory has a fresh modification time.
3. In the NetFacilities window, export the work-order CSV. Within ~3 s the
   card names the file and shows **Import downloaded CSV**. The file is in
   `%USERPROFILE%\Downloads` under that name. Export it again: a second file
   ` (1).csv` appears and the card names the new one.
4. Click **Import downloaded CSV**. Import summary appears, list reloads,
   enrichment starts and reports *Currently requesting work order …*. The
   NetFacilities window stays open throughout. Completion shows counts with
   `Priority updated` > 0 on at least one blank-priority row (this doubles as
   the pending acceptance of the `/myhome` priming fix).
5. While enrichment runs, click **Close NetFacilities** → 409 message; the
   window stays open. After completion, **Close NetFacilities** closes it and
   the card returns to **Log in again**.
6. Log in again, then close the Chrome window by hand. Within ~3 s the card
   returns to **Log in to NetFacilities** with no error.
7. **Import from CSV…** with a file picked from Downloads still works and
   still triggers enrichment.
8. With no window open and saved state present, **Import Tasks and Priority**
   still runs the headless fallback (job `source: saved_state`).

---

## 12. Backlog entry

`docs/open-work.md` gains `### IMP-039 — NetFacilities live session — IN
PROGRESS` with the summary in §0 of this file and a link here. The plan's last
task updates `current-state.md`, `endpoint-map.md`, and `project-summary.md`
so the route count, states, and env vars stay reconciled.
