# NetFacilities Work-Order Import and Enrichment Handoff

Last updated: 2026-08-15

Status: The local Windows happy path remains accepted. Render capability enablement is
owner-confirmed after commit `0679c52`. A hosted retry fetched all 290 candidates but
updated no Priority values and reported every candidate unchanged. A one-line,
secret-safe production diagnostic now classifies the exact response used by enrichment;
the next step is to run it for one authorized work order in Render Shell and use the
decision tree below.

## Next-session brief: hosted Priority investigation

### Confirmed observations and boundaries

- On 2026-08-15 the owner confirmed that NetFacilities is enabled on Render after
  `0679c52` reached `main`. The prior `disabled` and false `unavailable` configuration
  states are resolved.
- The completed hosted retry reported 290 candidates, requests attempted, and fetched;
  zero description and Priority updates; 290 unchanged; zero invalid, not-found,
  permission, authentication, other-failure, and remaining counts; and no timeout.
- The owner clarified that Task/Symptom is always empty in the CSV and is genuinely
  supplied by enrichment. Earlier enrichment had already populated descriptions, so a
  later Priority retry can correctly show zero description updates.
- The expected minimal Priority markup is already represented by the sanitized fixture.
  Preliminary non-production request/headless inspection saw no supported Priority body
  markup and found the token only in inline script. Because that check may not represent
  Render's current saved state, verify the actual deployed response with the safe CLI
  before changing selectors or adding a secondary request.
- The Admin-visible job status now shows the work-order number currently being requested
  while the serialized enrichment job is running. It retains the generic seeking message
  before the first request and clears the number for every terminal outcome.
- Keep the existing Admin+ route gates, one-job serialization, one-second frontend
  polling, compare-and-set writes, and prohibition on returning/logging cookies, storage
  paths, HTML, headers, descriptions, or Priority values. A work-order number may be
  exposed only as the current Admin-visible progress identifier; do not retain a
  completed-number history.
- Never request or inspect the saved storage-state contents. The state pasted in the
  prior session had already expired; replacement state remains bearer-equivalent.

### Continue with these questions and checks

1. In Render Shell, run
   `python -m scripts.netfacilities_diagnostic WORK_ORDER_NUMBER` for one authorized
   work order and retain only its safe JSON result.
2. If `priority_populated` is false and the expected ID/label/body counts are zero,
   investigate why the authenticated request document differs from the visible UI. Do
   not guess a secondary endpoint: capture only sanitized request metadata if the live
   browser proves that a separate Priority request exists.
3. If `priority_populated` is true, trace the already-tested projection into the
   compare-and-set write path with a single blank database row.
4. Re-read the applicable Obsidian repo context and inspect the current tree/status
   before planning edits; the worktree may contain owner changes.

### Current code trace and remaining change points

| Concern | Current code | Current status / next action |
| --- | --- | --- |
| Current requested number | `backend/app/services/netfacilities.py`, `enrich_work_orders()` candidate loop | Implemented: an optional async observer receives each validated number immediately before its serialized `get_work_order()` request. |
| Process-local job state | `backend/app/services/netfacilities_jobs.py`, `NetFacilitiesJobSnapshot` and `_run()` | Implemented: the immutable running snapshot publishes `current_work_order_number` through the coordinator lock; duplicate starts/polling see the same snapshot, and terminal snapshots clear it. |
| Admin API contract | `backend/app/schemas/netfacilities.py` and `backend/app/routers/netfacilities.py::_job_response` | Implemented: the response explicitly maps nullable `current_work_order_number`. No source description, Priority, URL, HTML, storage data, header, or cookie was added. |
| Work Orders status UI | `backend/static/views/workOrders.js`, especially `renderNetFacilitiesJob()` and `pollNetFacilitiesJob()` | Implemented through the existing one-second polling path: running jobs display the current number when present and retain the generic fallback before the first callback. |
| Priority extraction | `backend/app/integrations/netfacilities/parser.py`, selecting `#priority-level` or `general.get("Priority Level")` | A missing selector/label returns `None`, which is legal and silently prevents a Priority write. `inspect_priority_markup()` now reports counts/booleans that distinguish body markup from script-only references without returning values or HTML. |
| One-response diagnostic | `backend/scripts/netfacilities_diagnostic.py` and `NetFacilitiesClient.get_work_order_with_diagnostics()` | Performs the same single allowlisted production GET, reports only safe structure/error types, and never prints the requested identifier or source/authentication data. Run it from Render Shell before changing retrieval behavior. |
| Candidate and write rules | `backend/app/services/netfacilities.py::_load_candidates`, `_source_values`, and `_apply_candidate` | Blank-priority rows are selected; source `None` is accepted; writes occur only when local Priority is blank and source Priority is non-null. Preserve these safety rules while testing whether the value is lost before `_apply_candidate`. |
| Regression coverage | sanitized fixture plus `test_netfacilities_parser.py`, `test_netfacilities_client.py`, and `test_netfacilities_diagnostic.py` | Covers expected body markup, script-only references, exactly one allowlisted diagnostic request, safe output, and redacted failures. Focused suite: 31 passed. |

### Priority investigation decision tree

- `candidates == 0`: inspect import persistence and `_load_candidates`; confirm new rows
  actually have null/blank Priority and are not archived.
- `requests_attempted == 0` with candidates present: inspect number validation and the
  loop's early-exit conditions.
- `fetched == 0`: investigate authentication, permission, not-found, timeout, and safe
  failure counts before touching parsing or persistence.
- `fetched > 0`, `other_failures == 0`, and `priorities_updated == 0`: inspect the live
  Priority DOM first. This most strongly fits the parser returning `None` while allowing
  description enrichment to continue.
- `other_failures > 0`: determine whether parsing/projection validation or database
  application failed using safe outcome classes and focused tests; do not add live
  values to logs.
- If a sanitized parser test returns a nonblank Priority but persistence still stays
  blank, trace `_source_values()` into `_apply_candidate()` with a fake projection and
  a real PostgreSQL row before changing compare-and-set rules.

### Progress verification and remaining acceptance

- Completed automated coverage proves that the observer receives validated numbers
  immediately before deterministic serial requests; running/duplicate/polled job
  snapshots expose the same current number; terminal snapshots clear it; and the route
  returns it only as approved nullable progress metadata. The focused suite passed
  **27 tests with 5 skipped**.
- `node --check backend/static/views/workOrders.js` and `git diff --check` passed. A
  manual running-job check that visibly advances through a small authorized sequence and
  clears the number at completion is still unreported.
- The safe diagnostic test set passed 31 focused parser/client/CLI tests. The production
  Render result is still required; automated tests intentionally make no live request.
- Existing service/database coverage continues to prove that a blank-priority candidate
  receives a nonblank source value while existing/manual Priority, archived rows, and
  concurrent edits remain unchanged.
- Hosted acceptance is complete only when a fresh small pass reports nonzero
  `priorities_updated` for eligible blank rows and the cards show those committed values.
  Record only counts, duration, safe outcomes, and pass/fail.

## Corrected operating decision

The headed Playwright browser could not download the CSV because its context is
deliberately configured with `accept_downloads=False`. The visible Chromium
`--no-sandbox` warning was not the cause.

The owner removed downloading from the integration scope. Assume the authorized
operator already has a permitted NetFacilities CSV on the computer. The supported flow
is now:

```text
click Sign in to NetFacilities in Work Orders
  -> complete credentials/CAPTCHA/MFA directly in dedicated Chrome
  -> return to Inventory App and click I finished signing in
  -> choose the existing local CSV in Work Orders
  -> ordinary CSV import creates/updates work orders
  -> one saved-session NetFacilities job seeks Task/Symptom and Priority
  -> cards reload with committed values
```

Do not add browser download handling or `NETFACILITIES_DOWNLOAD_DIR`. The in-app auth
routes control only the local headed-browser lifecycle; they must never accept password,
CAPTCHA, SSO, or MFA fields.

## What is implemented

### Foundation and persistence

- `backend/app/integrations/netfacilities/` contains strict disabled-by-default
  configuration, dependency-free protocols, validation, lazy client construction, the
  allowlisted Playwright reader, and the sanitized HTML parser.
- Windows interactive mode requires an absolute external
  `NETFACILITIES_PROFILE_DIR`. Linux/Render request-only mode requires an absolute
  `NETFACILITIES_STORAGE_STATE_PATH` pointing at an operator-provisioned secret file.
  Browser channel and positive request/auth/batch timeouts are validated. Protected
  paths never enter responses or logs.
- Alembic `0c1d2e3f4a5b` adds nullable `work_orders.priority`. Model/card/detail response
  plumbing is complete; Work Orders displays read-only Priority or `Not imported`.
- Priority remains absent from generic PATCH, CSV import/export, filters, sorting, and
  billing.

### Enrichment service

`backend/app/services/netfacilities.py` selects only existing, live rows needing either
an exact canonical fallback Task/Symptom or a blank Priority. Reads are serial and use
validated numeric work-order numbers. No database transaction is held across a source
request.

Each result is applied under a fresh short row lock and rechecked:

- description changes only while it is still the exact fallback for the same number;
- priority changes only while null/blank;
- archived, deleted, renumbered, or concurrently edited rows are preserved;
- retries are idempotent;
- no work order is ever created or restored;
- status and every other source/local field are ignored.

### In-app authentication and application job

`backend/app/services/netfacilities_auth.py` owns one process-local authentication
attempt. Start opens the dedicated headed browser; confirm verifies an allowlisted
non-login page, saves `playwright-storage-state.json` inside the protected profile, and
closes the browser. Early confirmation leaves the browser open. Cancel, configured
timeout, and application shutdown close it without persisting a new state. The existing
CLI `auth` command remains an operational fallback.

`backend/app/services/netfacilities_operations.py` issues one opaque protected-profile
lease shared by authentication and enrichment, so they cannot overlap.

`backend/app/services/netfacilities_jobs.py` owns one process-local job. It:

- refuses missing saved auth state before creating a browser client;
- lazily creates one headless saved-state client;
- returns the active job on duplicate starts;
- reports the current requested work-order number while running, plus aggregate counts
  and safe failure classes, and clears the number at every terminal outcome;
- maps auth loss to `authentication_required` and stops remaining reads;
- cancels and closes the owned client during application shutdown.

`backend/app/lifespan.py` closes pending authentication and enrichment lifecycles before
the existing realtime dispatcher shutdown; it does not replace `start_dispatch()` /
`stop_dispatch()`.

### Admin API

Every endpoint independently requires Admin+ and documents 403:

```text
GET  /integrations/netfacilities/session
POST /integrations/netfacilities/auth/start
POST /integrations/netfacilities/auth/confirm
POST /integrations/netfacilities/auth/cancel
POST /integrations/netfacilities/work-orders/enrich
GET  /integrations/netfacilities/work-orders/enrich/{job_id}
```

Capability state is limited to `unavailable`, `not_authenticated`, `authenticating`,
`ready`, `running`, and `expired`. Authentication and job payloads contain only
operation IDs, states, timestamps, the nullable current requested work-order number,
safe failure classes, and aggregate counts. The existing `POST /work-orders/import`
remains the only creator.

### Work Orders UI

The existing Admin+ `.csv` chooser is reused. On a successful import, the UI starts the
enrichment job automatically only when authentication is ready, polls it, displays
the current requested work-order number when available, displays counts, and reloads
cards. If auth is absent or expired, the CSV import stays committed; after in-app sign-in,
**Import Tasks and Priority** retries enrichment without another upload. Sign-in,
confirmation, and cancellation controls recover the process-local auth attempt after
page re-entry.

When the capability is disabled/unavailable, the retry control stays hidden and normal
CSV import continues. Technician/Supervisor hiding is presentation only; server gates
remain authoritative.

## Operator configuration and flow

Configure the app with one protected external path:

```text
NETFACILITIES_ENABLED=true
NETFACILITIES_PROFILE_DIR=C:\Users\YOUR-NAME\AppData\Local\InventoryApp\netfacilities-profile
NETFACILITIES_BROWSER_CHANNEL=chrome
```

From `backend/`, start the local browser-enabled server as one process without
auto-reload:

```powershell
.\venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8124
```

Do not add `--reload` or use multiple workers. On Windows those Uvicorn modes select
`SelectorEventLoop`, which cannot start Playwright's driver subprocess. The client now
rejects that runtime as unavailable before browser startup, so a mislaunch returns 503
instead of an unhandled 500 traceback.

Then:

1. Open the local Inventory app as Admin/Owner and navigate to Work Orders.
2. Click **Sign in to NetFacilities** and complete login directly in the dedicated
   browser.
3. Return to Inventory App and click **I finished signing in**.
4. Click **Import from CSV…** and choose the CSV already on the computer.
5. Observe CSV import success, then NetFacilities polling/counts.
6. Confirm cards refresh with only eligible Task/Symptom and Priority changes.
7. If the session expires, sign in again and click **Import Tasks and Priority**.

Never use the normal everyday browser profile, copy storage state into the repository,
inspect/log protected contents, or paste live source values into issues or notes.

For Render, upload the locally generated `playwright-storage-state.json` as the service
secret file `netfacilities-storage-state.json`. `backend/Dockerfile` and `render.yaml`
both enable the capability and point `NETFACILITIES_STORAGE_STATE_PATH` at
`/etc/secrets/netfacilities-storage-state.json`. The image defaults matter because a
deploy hook rebuild does not synchronize Blueprint environment changes into an existing
service. Hosted mode uses a browserless
Playwright `APIRequestContext` and intentionally makes interactive sign-in unavailable;
it does not install or launch Chromium. The state file is bearer-equivalent and must be
protected like a password. Refreshing an expired hosted session means repeating local
sign-in, replacing that secret file, and redeploying. The detailed procedure is in
`docs/netfacilities-stage1-poc.md`.

## Verification completed

- 45 focused hosted client/config/job/route tests passed.
- 182 NetFacilities/import/priority/role-gate regression tests passed for the hosted
  extension.
- The final full current-tree suite passed: 934 tests with two known WebSockets
  deprecation warnings.
- A real Playwright standalone `APIRequestContext` started and disposed successfully
  without launching a browser.
- `python -m pip check`, `node --check backend/static/views/workOrders.js`, and
  `git diff --check` passed.
- Automated verification made no live NetFacilities request and did not inspect the
  protected profile or storage-state contents.

## Live acceptance result and remaining checks

The owner restarted Uvicorn without `--reload` on 2026-08-15 and reported that the
feature ran successfully: Task/Symptom imported correctly and Priority imported
correctly. No source values, identifiers, profile paths, or authentication material
were recorded.

The local live happy path is accepted. Render capability enablement is also accepted,
but hosted Priority enrichment is not. The later completed retry fetched all 290
candidates with no categorized failure or timeout, changed no Priority, and classified
every candidate as unchanged. The owner clarified that Task/Symptom is always absent
from the CSV and had been populated by earlier enrichment. In-flight requested-number
progress and the one-response safe Render diagnostic have since been implemented; no
Priority selector or retrieval path was guessed. Run that diagnostic and follow the
brief above before claiming hosted acceptance. The following hardening checks also
remain unreported and should still record only pass/fail, counts, duration, and safe
outcome classes:

1. Confirm lifecycle status, other local fields, archived rows, and manual/CSV values do
   not change.
2. Retry **Import Tasks and Priority** and confirm idempotent zero destructive effects.
3. Confirm early confirmation stays recoverable; cancel closes Chrome; then expire/clear
   the session, confirm the batch stops, sign in again, and retry.
4. Reload/leave/re-enter Work Orders during a small job and confirm state recovery.
