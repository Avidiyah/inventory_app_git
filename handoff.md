# NetFacilities Work-Order Import and Enrichment Handoff

Last updated: 2026-08-15

Status: Milestones 0 through 5 plus Admin+ in-app manual authentication are implemented
for the local Windows, single-operator release. The owner-reported live happy path
passed on 2026-08-15 after restarting Uvicorn without reload: Task/Symptom and Priority
both imported correctly. Remaining resilience scenarios are listed below.

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
- reports only aggregate counts and safe failure classes;
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
operation IDs, states, timestamps, safe failure classes, and aggregate counts. The
existing `POST /work-orders/import` remains the only creator.

### Work Orders UI

The existing Admin+ `.csv` chooser is reused. On a successful import, the UI starts the
enrichment job automatically only when authentication is ready, polls it, displays
counts, and reloads cards. If auth is absent or expired, the CSV import stays committed;
after in-app sign-in, **Import Tasks and Priority** retries enrichment without another
upload. Sign-in, confirmation, and cancellation controls recover the process-local auth
attempt after page re-entry.

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
secret file `netfacilities-storage-state.json`. `render.yaml` enables the capability and
points `NETFACILITIES_STORAGE_STATE_PATH` at
`/etc/secrets/netfacilities-storage-state.json`. Hosted mode uses a browserless
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

The local live happy path is accepted. The first hosted live request on Render is still
pending operator acceptance. The following hardening checks remain unreported and
should still record only pass/fail, counts, duration, and safe outcome classes:

1. Confirm lifecycle status, other local fields, archived rows, and manual/CSV values do
   not change.
2. Retry **Import Tasks and Priority** and confirm idempotent zero destructive effects.
3. Confirm early confirmation stays recoverable; cancel closes Chrome; then expire/clear
   the session, confirm the batch stops, sign in again, and retry.
4. Reload/leave/re-enter Work Orders during a small job and confirm state recovery.
