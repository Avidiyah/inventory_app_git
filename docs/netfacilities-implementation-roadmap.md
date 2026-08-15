# NetFacilities Work-Order Enrichment Implementation Roadmap

Last updated: 2026-08-15

Status: Milestones 0 through 5 and the local in-app authentication slice are
implemented for the Windows, single-operator first release. The operator supplies a
CSV already downloaded on the computer. The owner-reported Milestone 6 live happy path
passed on 2026-08-15 after restarting Uvicorn without reload: Task/Symptom and Priority
both imported correctly. The remaining resilience scenarios below are not yet recorded
as accepted.

## Outcome

Extend the existing Admin+ Work Orders CSV import experience with a separate,
authenticated NetFacilities enrichment pass. CSV import remains the only path that
creates work orders. Enrichment reads existing work orders serially and may apply only:

| NetFacilities source | Local destination | Write rule |
| --- | --- | --- |
| `description` | `WorkOrder.description`, displayed as **Symptom / task** | Replace only the exact canonical fallback generated for the same work-order number. |
| `priority` | New nullable `WorkOrder.priority`, displayed as **Priority** | Fill only while the local value is null or blank. |

No other NetFacilities field may be persisted or applied. In particular, enrichment
must never change the application's lifecycle `WorkOrder.status`, create a work order,
restore or modify an archived work order, or request a URL supplied by a user or stored
description.

## Locked operating decisions

- The first release runs FastAPI and the headed Playwright authentication browser on
  the same Admin-controlled Windows machine.
- Run the local browser-enabled Uvicorn process without `--reload` and with one worker.
  On Windows, Uvicorn's reload/multi-worker mode uses `SelectorEventLoop`, which cannot
  start Playwright's driver subprocess; the client fails closed as `unavailable` if
  that incompatible loop is detected.
- CSV downloading is outside this integration. The operator obtains the CSV beforehand
  and selects it through the existing Work Orders file chooser. Do not add browser
  download automation or `NETFACILITIES_DOWNLOAD_DIR` for this release.
- The Admin+ Work Orders UI starts, confirms, or cancels a manual headed-browser login.
  Credentials, CAPTCHA, SSO, and MFA remain entirely inside NetFacilities/Chrome; the
  application receives no credential fields. The CLI `auth` command remains an
  operational fallback, not the primary app flow.
- Exactly one designated person will attempt imports. This is an operating constraint,
  not a new application identity or permission rule.
- Do not build per-user browser profiles, user-to-NetFacilities-session mapping,
  remote login handoff, or multi-user scheduling.
- Keep every integration route independently gated at Admin+ on the server. Frontend
  hiding is presentation only.
- Keep one browser/session owner and basic admission control so an accidental repeated
  click cannot overlap authentication or enrichment.
- Keep the current Render deployment free of a production browser runtime. The normal
  CSV import must continue to work when the NetFacilities local capability is disabled.
- Keep Playwright storage state and the persistent profile outside the repository.
  Treat both as bearer-equivalent secrets and never inspect, log, return, or copy their
  contents.
- Default tests use fakes and sanitized fixtures only. Live lookups remain explicit,
  operator-run smoke tests.

## Target architecture

```text
Work Orders Admin UI
  -> POST /integrations/netfacilities/auth/start
       -> dedicated headed browser on the same Windows host
       -> operator completes credentials/CAPTCHA/MFA directly in NetFacilities
  -> POST /integrations/netfacilities/auth/confirm (or /auth/cancel)
       -> allowlisted non-login page check + protected storage-state save
  -> existing POST /work-orders/import
       -> existing CSV import service (only creator)
  -> POST /integrations/netfacilities/work-orders/enrich
       -> one serialized process-local job coordinator
            -> enrichment service
                 -> NetFacilitiesClient.get_work_order(number)
                 -> short compare-and-set database update
```

Authentication and enrichment share one process-local protected-profile gate, so they
cannot overlap. The existing `scripts.netfacilities_poc auth` remains available as a
fallback against the same external profile.

The vendor client remains isolated under `app/integrations/netfacilities`. Candidate
selection and local update rules live in `app/services/netfacilities.py`. HTTP and role
concerns live in a dedicated router. Browser and job state are process-local; database
rows hold only the approved `priority` and `description` values.

Because Playwright and Beautiful Soup are currently local development dependencies,
the application composition path must not import the concrete browser/parser runtime
when NetFacilities is disabled. A small interface plus lazy local factory should let
Render start and retain CSV import without installing or launching Chromium.

## Milestone 0 - Baseline and local capability boundary

### Status

**Complete on 2026-08-14.** The dependency-free configuration and client contracts
are implemented in `app/integrations/netfacilities`, with a lazy concrete-client
factory and no FastAPI composition import. Configuration defaults disabled and uses
`NETFACILITIES_ENABLED`, `NETFACILITIES_PROFILE_DIR`,
`NETFACILITIES_BROWSER_CHANNEL`, and bounded request/authentication/batch timeout
settings. Enabled configuration is limited to Windows and rejects unsafe repository
paths, invalid channels, nonpositive timeouts, and missing local-only dependencies as
secret-safe `unavailable` failures.

The package initializer no longer eagerly imports the Beautiful Soup parser, so the
configuration/contracts/factory boundary and `app.main` import without Playwright or
Beautiful Soup. The existing Stage 1 safety behavior remains unchanged. Verification:
41 focused NetFacilities/configuration tests and 91 CSV-import/route-role regression
tests passed. No live request or browser launch was performed.

The headed Chrome CSV-download check failed because the Playwright context deliberately
uses `accept_downloads=False`. The owner then removed downloading from the integration
contract: the operator supplies an existing local CSV. The `--no-sandbox` browser
warning was not the download cause, no download handler was added, and
`NETFACILITIES_DOWNLOAD_DIR` is not part of the first release.

### Work

- Preserve and baseline the uncommitted Stage 1 client, parser, CLI, fixtures, tests,
  and documentation before application wiring.
- Add explicit local configuration, with names finalized during implementation:
  - feature enabled/disabled;
  - absolute dedicated profile directory outside the repository;
  - installed browser channel, defaulting to Chrome;
  - bounded authentication, request, and whole-batch timeouts.
- Fail closed as `unavailable` when the feature is disabled, the host is unsuitable,
  dependencies are absent, or protected paths are unsafe.
- Define a narrow client protocol used by the service so unit tests and disabled
  deployments never import or start Playwright.
- Preserve the Stage 1 URL allowlist, numeric work-order validation, response-size cap,
  login detection, returned-number check, and secret-safe errors.

### Resolved authentication/download gate

The headed-browser check did not produce a usable CSV. This no longer blocks the
release: downloading is explicitly out of scope, `accept_downloads=False` remains a
defense-in-depth setting, and the existing application file chooser accepts the CSV the
operator already has.

### Exit checks

- Existing Stage 1 focused tests pass unchanged or with deliberately updated CLI tests.
- A disabled NetFacilities capability does not affect FastAPI startup or ordinary CSV
  import.
- No browser starts at application startup.
- No secret path or browser-state content appears in responses or logs.

## Milestone 1 - Priority persistence and read-only display

### Status

**Complete on 2026-08-14.** Alembic revision `0c1d2e3f4a5b` adds nullable
`work_orders.priority` with no default, backfill, index, or constraint and a downgrade
that drops only the column. The ORM, card/detail responses, and existing response
builder expose nullable priority. The Work Orders detail block always shows a read-only
**Priority** row and uses `Not imported` while blank.

Priority remains absent from the generic update schema and editor, required CSV
headers, CSV import/export contracts, filters, sorting, and billing. A priority-only
generic update fails validation; an update containing another valid field ignores
priority. Re-import leaves both null and existing priority values unchanged.

Verification: 136 focused priority/response/import/export/role-gate tests passed;
`node --check static/views/workOrders.js` passed; the working database upgraded to the
new head; and the full migration chain plus priority downgrade/upgrade passed in a
uniquely named disposable PostgreSQL schema that was removed afterward. `alembic check`
still reports the repository's pre-existing index and transaction-FK metadata drift
already tracked in `docs/open-work.md`; it proposed no priority operation.

### Files

- New Alembic revision based on current head `fbc4e6a8d0f2`.
- `backend/app/models.py`
- `backend/app/schemas/work_orders.py`
- `backend/app/routers/work_orders.py`
- `backend/static/views/workOrders.js`
- Focused work-order response and migration tests.

### Work

- Add `work_orders.priority TEXT NULL` with no backfill and a reversible downgrade.
- Add `WorkOrder.priority` to the ORM model.
- Add nullable `priority` to `WorkOrderCard`; `WorkOrderDetail` inherits it.
- Populate it in the existing `_card()` response builder.
- Show a **Priority** row on every work-order card, using `Not imported` when blank.
- Keep priority out of `WorkOrderUpdate`, the generic edit form, required import
  headers, filters, sorting, billing, and the client billing export.
- Do not broaden CSV creation/update behavior in this milestone.

### Tests

- Card and detail responses contain null or populated priority correctly.
- Existing work orders remain valid after migration without a backfill.
- Priority is visible but cannot be written through the generic PATCH route.
- Existing CSV import/export tests remain green.

### Exit criterion

Priority is safely deployable and visible before any NetFacilities route or browser
lifecycle is introduced.

## Milestone 2 - Enrichment service and compare-and-set rules

### Status

**Complete on 2026-08-14.** A dependency-free async enrichment service now accepts a
session factory, the narrow async client protocol, and a bounded whole-batch timeout.
Numeric validation was moved into a dependency-free module shared by the CLI, parser,
client, and service; importing the service still does not import Playwright or Beautiful
Soup.

The service snapshots deterministic live candidates, releases the database session
before each serial source read, then opens a fresh short session and row lock to
compare-and-set only description and priority. It rechecks archive state and exact
number identity, preserves concurrent/manual values, never creates or restores rows,
and never reads or applies source status or other parsed fields. Authentication loss
stops the batch; not-found, forbidden, malformed responses, database apply failures,
and other known isolated integration errors are counted without exposing source data.
Whole-batch timeout cancels the current read and reports untouched remaining rows.

The secret-safe internal summary contains candidates, requests attempted, fetched,
description/priority update counts, unchanged, invalid number, not found, permission
denied, authentication required, other failures, remaining, and timed-out state. No
route, browser/session manager, background job, or live call was added.

Verification: all 10 focused database-backed/offline service tests passed, followed by
187 combined NetFacilities and work-order priority/response/import/export/role-gate
tests. Session-close coverage passed all 861 tests in the current tree: 857 in the
release-wide run plus four concurrently added VAPID tests in their own run after their
generator file became available. The only warnings were the two existing WebSockets
deprecations. Python compilation, dependency integrity, Work Orders JavaScript syntax,
Alembic head/current, and `git diff --check` also passed.

### Files

- `backend/app/services/netfacilities.py` (new)
- Optional narrow source projection/protocol under
  `backend/app/integrations/netfacilities/`
- `backend/tests/test_netfacilities_service.py` (new)

### Work

- Select only existing, non-archived work orders for which either:
  - description is the exact canonical fallback for that row's number; or
  - priority is null or blank.
- A broad SQL prefilter may narrow candidates, but application code must call
  `is_work_order_task_fallback` for the exact description decision.
- Snapshot local ID, number, description, and priority, then close/release the database
  transaction before making the external request.
- Validate the local work-order number before calling the client. Invalid/non-numeric
  values become failures without any outbound request.
- Fetch candidates serially through a fakeable `get_work_order(number)` interface.
- Retain only the parsed source description and priority for application use. Ignore
  source status, location, dates, task type, work-order type, and all secondary data.
- Re-read and briefly lock the local row before applying changes:
  - replace description only if it is still the exact fallback for that number;
  - fill priority only if it is still null or blank;
  - otherwise preserve the concurrent/manual value.
- Commit the short local update independently of the external read, then continue.
- Make retries idempotent.
- Return a secret-safe summary containing at least candidates, fetched, descriptions
  updated, priorities updated, already complete/unchanged, not found, permission denied,
  authentication required, and other failures.
- Stop further requests after authentication loss. Continue after per-record not-found,
  forbidden, or other isolated failures.

### Tests

- Candidate union includes fallback-description and missing-priority rows.
- Archived and already-complete rows are excluded.
- Enrichment never creates or restores a work order.
- Description and priority follow their independent conditional-write rules.
- Nonblank/manual values survive retries and simulated concurrent edits.
- Only description and priority are read from the source projection.
- Mixed outcomes produce exact counts while preserving successful updates.
- Authentication loss stops the remaining batch.
- No live HTTP or browser call occurs.

### Exit criterion

The complete data-mutation contract is proven with a fake client before any route can
invoke it.

## Milestone 3 - Authentication and owned browser/job lifecycle

### Status

**Completed on 2026-08-14 and extended on 2026-08-15 with the owner-approved in-app
sign-in decision.** The Work Orders page now starts the dedicated headed browser and
lets the operator complete CAPTCHA/MFA/SSO directly in NetFacilities. A separate
confirmation action verifies an allowlisted non-login page, persists storage state in
the configured external profile, and closes the browser. Cancel, configured timeout,
and application shutdown also close it. The CLI `auth` command remains usable as a
fallback.

`NetFacilitiesConfig.storage_state_path` and `has_saved_authentication` let the app test
only for the saved-state file without exposing its path. The authentication coordinator
and enrichment coordinator share one opaque profile lease; neither browser operation
can overlap the other. Disabled startup remains lazy and browser-free.

`app/lifespan.py` composes authentication-browser and enrichment-job shutdown with the
existing realtime dispatcher. Active operations exit the concrete client's async
context and close their browser/context/Playwright runtime. Realtime
`start_dispatch()` / `stop_dispatch()` behavior is preserved.

### Exit checks

- In-app and CLI auth remain usable; credentials never pass through Inventory App.
- Missing saved state fails before client/browser creation.
- Authentication loss becomes the recoverable `authentication_required` job state.
- Job cancellation closes the owned client context.
- Disabled application startup remains independent of Playwright and Beautiful Soup.

## Milestone 4 - Admin-only enrichment API and serialized job

### Status

**Complete on 2026-08-14.** Implemented files:

- `backend/app/services/netfacilities_jobs.py`
- `backend/app/schemas/netfacilities.py`
- `backend/app/routers/netfacilities.py`
- `backend/app/lifespan.py`
- `backend/app/main.py`
- `backend/tests/test_netfacilities_jobs.py`
- `backend/tests/test_netfacilities_routes.py`

### API shape

```text
GET  /integrations/netfacilities/session
POST /integrations/netfacilities/auth/start
POST /integrations/netfacilities/auth/confirm
POST /integrations/netfacilities/auth/cancel
POST /integrations/netfacilities/work-orders/enrich
GET  /integrations/netfacilities/work-orders/enrich/{job_id}
```

Every route independently declares Admin+ and documents 403. The session endpoint
reports only `unavailable`, `not_authenticated`, `authenticating`, `ready`, `running`,
or `expired`, plus source-value-free authentication/job snapshots. The three auth
routes expose only attempt IDs, states, timestamps, and safe failure classes.

The coordinator admits one process-local job, returns the active job on duplicate
starts, creates a lazy headless saved-state client only inside the job, and invokes the
Milestone 2 service with fresh `SessionLocal` sessions. Poll responses contain only
state, timestamps, safe failure classes, and aggregate counts. Authentication loss
stops the batch; timeout and partial results remain visible; retries remain idempotent.
The unchanged `POST /work-orders/import` remains the sole creator.

### Verification

- Missing state is rejected before client creation.
- Client lifetime, success counts, duplicate admission, auth loss, and shutdown are
  covered with offline fakes.
- Route behavior covers disabled/ready state, secret-safe aggregates, 409 recovery, and
  unknown job 404.
- All six routes are pinned as Admin+ in `test_route_role_gates.py`.

## Milestone 5 - Existing-file Work Orders UI

### Status

**Implemented on 2026-08-14; live operator acceptance remains in Milestone 6.**

### State flow

```text
operator opens Work Orders and clicks Sign in to NetFacilities
  -> app opens the dedicated headed browser on the same computer
  -> operator completes login there and clicks I finished signing in
  -> Import from CSV opens the existing local .csv chooser
  -> existing POST /work-orders/import succeeds
  -> app starts the serialized NetFacilities enrichment job
  -> app polls aggregate progress/result
  -> cards reload with Task/Symptom and Priority
  -> Import Tasks and Priority remains available for retry recovery
```

The Admin+ import panel now derives capability and active-job state from the backend.
It never asks the application to download a CSV. After a successful existing CSV import,
it starts enrichment automatically only when authentication is ready. Missing or
expired authentication leaves the CSV import committed and presents **Sign in to
NetFacilities**; the retry button enriches existing rows without another CSV upload.
Repeated sign-in starts return the active attempt, while confirm/cancel controls recover
the process-local browser state after page re-entry.

Polling displays only counts, disables duplicate enrichment actions, recovers a running
job after page re-entry, and reloads cards on completion/timeout. When the feature is
disabled or unavailable (including Render), the retry control stays hidden and ordinary
CSV import continues unchanged.

### Remaining manual checks

- Run the in-app sign-in -> existing CSV -> automatic enrichment flow.
- Confirm file chooser cancellation and failed CSV upload remain recoverable.
- Confirm early confirmation, cancellation, timeout, expired auth, sign-in again, and
  retry.
- Confirm duplicate-click resistance, partial counts, and page re-entry recovery.
- Confirm fallback Task/Symptom and blank Priority update while manual values, status,
  archived rows, and all other fields remain unchanged.

## Milestone 6 - Local acceptance, hardening, and documentation

### Automated checkpoint (2026-08-14)

- 218 focused NetFacilities, Work Orders, and role-gate tests passed.
- The unexcluded current-tree suite passed: 912 tests, with two known WebSockets
  deprecation warnings. This includes 37 concurrent push-domain tests that appeared
  after an earlier temporary collection failure.
- Python compileall, JavaScript syntax checks for `api.js` / `workOrders.js`, and
  `git diff --check` passed.
- No live request/browser/profile inspection occurred. The local operator acceptance
  below remains the release gate.

### In-app authentication checkpoint (2026-08-15)

- Added one shared profile gate, a process-local headed authentication coordinator,
  Admin+ start/confirm/cancel routes, safe authentication state in `GET /session`, and
  Work Orders sign-in/confirm/cancel controls.
- Early confirmation keeps the browser open; cancel, timeout, or shutdown closes it.
  Authentication and enrichment cannot overlap.
- 102 focused authentication/client/job/route/role-gate tests passed. The final full
  current tree passed 928 tests with the same two known WebSockets deprecation warnings.
- Python compilation, `pip check`, and JavaScript syntax checks passed. No live
  NetFacilities request, login, protected-state read, or enrichment occurred.

### Windows event-loop hardening (2026-08-15)

- The first manual sign-in request reached Playwright under Uvicorn's Windows selector
  loop and failed while spawning the driver with `NotImplementedError`.
- Uvicorn selects that loop for `--reload` or multiple-worker mode. The supported local
  launch is one worker without `--reload`, which selects the subprocess-capable Windows
  proactor loop.
- The client now detects the incompatible selector loop before Playwright startup and
  reports the existing secret-safe `unavailable` failure, producing HTTP 503 rather
  than an unhandled 500 traceback. The corrected-restart result is recorded below.
- The selector-loop regression plus authentication and route tests passed 27/27. The
  final current-tree suite passed 929 tests with the same two known WebSockets
  deprecation warnings; compileall, dependency integrity, JavaScript syntax, and diff
  checks also passed.

### Owner-reported live happy-path checkpoint (2026-08-15)

- The owner restarted the local Uvicorn process without `--reload` and reported that
  the live feature ran successfully.
- Task/Symptom imported correctly and Priority imported correctly. No source values,
  work-order identifiers, profile paths, or authentication material were recorded.
- This accepts the live happy path. Idempotent retry, concurrent/manual-value
  preservation, archived/status-field preservation, expired-auth recovery, cancellation,
  timeout, and page re-entry remain explicit follow-up acceptance scenarios unless the
  owner reports them separately.

### Local acceptance runtime prepared (2026-08-14)

- The ignored local `.env` now enables NetFacilities with the existing protected
  external profile, Chrome channel, and bounded request/auth/batch timeouts.
- Configuration validation confirmed the profile directory and saved authentication
  file exist without reading or printing their paths or contents.
- The configured database connection is reachable.
- Uvicorn is running locally on `127.0.0.1:8124`; `/healthz` and the application shell
  return 200, while an unauthenticated NetFacilities status request correctly returns
  401.
- The operator-run CSV/enrichment checks below are now in progress; no acceptance result
  is claimed yet.

### Verification

Run, at minimum:

```text
focused NetFacilities parser/client/session/service/route tests
focused work-order import/response/role-gate tests
full pytest suite
compileall for app and scripts
pip check
Alembic upgrade and downgrade/upgrade check against a disposable database
git diff --check
```

Then perform an opt-in local live acceptance with permitted data:

1. Start the local app with the protected external profile configuration, one worker,
   and no `--reload` (for example, from `backend/`: `python -m uvicorn app.main:app
   --host 127.0.0.1 --port 8124`).
2. In Work Orders click **Sign in to NetFacilities**, complete the manual login in the
   opened browser, return to the app, and click **I finished signing in**.
3. In Work Orders, choose a permitted CSV that is already present on the computer.
4. Let the successful CSV import start enrichment against a deliberately small
   candidate set.
5. Confirm only fallback descriptions and blank priorities changed.
6. Confirm application status, other local fields, archived rows, and manual values did
   not change.
7. Retry and confirm zero destructive/duplicate effects.
8. Expire or clear the session and confirm the batch stops with reauthentication needed.
9. Record only pass/fail, counts, duration, and secret-safe error classes.

### Documentation

- Update `docs/current-state.md` to describe what actually shipped.
- Extend `docs/netfacilities-stage1-poc.md` with app configuration, the separate CLI
  authentication command, existing-file selection, recovery, and shutdown.
- Update the investigation/roadmap status and record final verification results.
- Synchronize the resulting repository documentation into Obsidian project memory.

### Release gate

The first release is accepted only when all feature acceptance criteria in `handoff.md`
pass locally and the default test suite performs no live NetFacilities request.

## Recommended delivery slices

1. **Priority contract:** migration, model/schema/router plumbing, card display, tests.
2. **Enrichment core:** candidate selection, fake client, compare-and-set writes, counts.
3. **Local session:** configuration, in-app/CLI saved state, optional dependency
   boundary, shared profile gate, and app lifespan composition.
4. **Integration API:** Admin routes, serialized background job, polling and errors.
5. **Guided UI:** existing-file import/enrichment state machine and card refresh.
6. **Acceptance:** full regression suite, opt-in live test, runbook, current-state update.

Each slice should be independently reviewable and leave ordinary CSV import working.

## Explicitly deferred

- Render-hosted Chromium or a remote headed-browser interface.
- Browser-managed CSV downloading and `NETFACILITIES_DOWNLOAD_DIR`.
- Credential, CAPTCHA, SSO, or MFA collection/automation inside Inventory App.
- Uploading or transferring local Playwright storage state to Render.
- Local companion/agent or browser extension architecture.
- Multiple NetFacilities users or multiple protected profiles.
- Concurrent enrichment batches or large-scale parallel source reads.
- Scheduled/background unattended imports.
- Priority editing, filtering, sorting, billing, or required CSV/export columns.
- NetFacilities status, location, dates, assignees, labor, materials, notes,
  attachments, audit data, or secondary endpoint imports.

If remote production enrichment is requested later, treat it as a separate architecture
decision. A normal browser tab on an Admin's computer cannot authenticate Playwright on
Render.
