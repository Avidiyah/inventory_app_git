# NetFacilities Stage 1 Authentication and Enrichment Runbook

Status: local CLI lookup/authentication and the Admin+ in-app manual sign-in flow are
implemented; the local happy path is owner-accepted, and Render can consume the same
protected saved state through a browserless request client. The first hosted live
request is still pending operator acceptance.

## Scope

The command-line boundary:

- owns a dedicated Chrome/Playwright profile;
- requires the authorized user to complete NetFacilities login manually;
- sends only `GET /tools/viewworkorders/{work_order_number}` for lookup;
- validates status, host, path, content type, response size, and returned identifier;
- parses the confirmed server-rendered HTML into a small JSON projection;
- does not call labor, material, attachment, audit, discussion, or mutation routes;
- does not itself write to PostgreSQL or the Inventory application.

The application consumes the saved authentication state to enrich only eligible
existing work orders. On Render it uses Playwright's standalone `APIRequestContext`,
not a browser. The CLI still performs no database mutation.

The browser profile and its `playwright-storage-state.json` file contain
bearer-equivalent session state. Keep them outside the repository, outside synced
folders, and accessible only to the authorized Windows user. Never attach either to an
issue, copy either into documentation, or commit either. The one approved transfer is
the storage-state file into the Inventory service's protected Render secret-file slot;
the persistent browser profile itself never leaves the local host.

## Install local development dependencies

From `backend/` using the project virtual environment:

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

The default browser channel is the locally installed Google Chrome. It uses a new,
dedicated profile and does not touch the normal Chrome profile. No separate Chromium
download is needed for this default.

## Choose a protected profile directory

Use an absolute local path outside the repository. Example:

```text
C:\Users\YOUR-NAME\AppData\Local\InventoryApp\netfacilities-profile
```

Do not use a repository subdirectory, OneDrive/Dropbox, a shared drive, or a location
backed up without a deliberate secret-storage decision. The CLI rejects repository
paths.

## Authenticate manually from the app

Start the configured local application, sign in as Admin/Owner, open **Work Orders**,
and click **Sign in to NetFacilities**. A dedicated Chrome window opens. Complete the
ordinary NetFacilities login, CAPTCHA, SSO, or MFA directly there, return to Inventory
App, and click **I finished signing in**. Inventory App verifies an allowlisted
non-login page, saves Playwright storage state in the protected profile, and closes the
headed browser. **Cancel sign-in**, the configured auth timeout, and application
shutdown also close it without accepting credentials.

The application never accepts a NetFacilities password, CAPTCHA value, or MFA code and
never returns browser storage or protected paths. Sign-in and enrichment share one
process-local gate and cannot use the protected profile concurrently.

## CLI authentication fallback

From `backend/`:

```powershell
.\venv\Scripts\python.exe -m scripts.netfacilities_poc auth `
  --profile-dir "C:\Users\YOUR-NAME\AppData\Local\InventoryApp\netfacilities-profile"
```

A dedicated Chrome window opens. Complete the ordinary NetFacilities login, CAPTCHA,
SSO, or MFA yourself. After NetFacilities shows an authenticated page, return to the
terminal and press Enter. Before closing the browser, the command explicitly saves
Playwright storage state—including session cookies—inside the protected profile. This
is necessary because NetFacilities authentication did not survive a profile-only
close/reopen test.

The fallback command never accepts a password or CAPTCHA value and never prints browser
storage. Neither flow downloads the work-order CSV. The supported application flow
assumes the operator already has the permitted CSV on this computer.

## Use the saved state with the local application

Configure the local backend to use the protected profile directory. The CLI fallback,
when used, must use that exact same path. For example, in the local environment:

```text
NETFACILITIES_ENABLED=true
NETFACILITIES_PROFILE_DIR=C:\Users\YOUR-NAME\AppData\Local\InventoryApp\netfacilities-profile
NETFACILITIES_BROWSER_CHANNEL=chrome
```

Optional positive whole-number settings are
`NETFACILITIES_REQUEST_TIMEOUT_SECONDS`,
`NETFACILITIES_AUTH_TIMEOUT_SECONDS`, and
`NETFACILITIES_BATCH_TIMEOUT_SECONDS`. The app defaults the feature to disabled and
rejects relative/repository profile paths, unknown browser channels, unsupported
platforms, and invalid timeouts. Playwright and Beautiful Soup are runtime dependencies;
interactive browser sign-in remains Windows-only.

Start browser-enabled Uvicorn as a single process without auto-reload. From `backend/`:

```powershell
.\venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8124
```

Do not add `--reload` or configure multiple workers for this local mode. On Windows,
Uvicorn uses `SelectorEventLoop` for those subprocess modes, but Playwright must spawn
its driver on `ProactorEventLoop`. The client detects the incompatible loop and returns
a secret-safe unavailable response rather than starting the browser.

The operator workflow is:

1. Start the local Inventory application and open **Work Orders** as an Admin or Owner.
2. Click **Sign in to NetFacilities**, complete login in the dedicated browser, return
   to Inventory App, and click **I finished signing in**.
3. Click **Import from CSV…** and select the NetFacilities CSV already downloaded on
   the computer.
4. After the normal CSV import succeeds, the app automatically starts the serialized
   enrichment job and polls its aggregate result.
5. If login state is missing or expired, use **Sign in to NetFacilities** again, then
   click **Import Tasks and Priority**. The CSV does not need to be uploaded again.

CSV import remains the only work-order creator. Enrichment may replace only the exact
generated Task/Symptom fallback for the same number and fill only a blank Priority. It
does not overwrite real CSV/manual text, status, archived rows, or other fields.

The application endpoints are Admin+ only:

```text
GET  /integrations/netfacilities/session
POST /integrations/netfacilities/auth/start
POST /integrations/netfacilities/auth/confirm
POST /integrations/netfacilities/auth/cancel
POST /integrations/netfacilities/work-orders/enrich
GET  /integrations/netfacilities/work-orders/enrich/{job_id}
```

They return capability state, operation IDs, safe outcome classes, and counts only.
They never return storage paths, cookies, HTML, headers, or source field contents.

## Provision saved authentication on Render

First complete the authorized local sign-in flow above so the protected profile contains
`playwright-storage-state.json`. Then:

1. Open the Render dashboard for the `inventory-app` service and select
   **Environment**.
2. Under **Secret Files**, add a file named
   `netfacilities-storage-state.json` and paste the complete contents of the locally
   generated `playwright-storage-state.json` into it. Treat this content as a password.
3. Save the secret file. `render.yaml` already supplies:

   ```text
   NETFACILITIES_ENABLED=true
   NETFACILITIES_STORAGE_STATE_PATH=/etc/secrets/netfacilities-storage-state.json
   ```

4. Sync/deploy the Blueprint revision containing this support. In Work Orders, the
   capability should report ready and **Import Tasks and Priority** should be enabled.
   The local **Sign in to NetFacilities** control is intentionally hidden on Render.
5. Import a small authorized CSV and confirm the aggregate enrichment result. The
   default automated tests never make a live source request.

The production image includes Playwright's request runtime and Beautiful Soup but no
Chromium binary. If Render reports authentication missing or expired, repeat the local
sign-in, replace the Render secret file, and redeploy. Do not put storage state in
`render.yaml`, an ordinary environment variable, logs, tickets, or source control.

The hosted extension passed 182 broader work-order/import/application regressions,
including 45 focused hosted client/config/job/route tests, and the final current-tree
suite passed 934 tests. A real Playwright request-only runtime smoke passed with
temporary synthetic storage state and no Chromium/browser launch; `python -m pip check`
and JavaScript syntax checks passed. These checks made no live NetFacilities request.

Transfer of an otherwise valid session can still fail if NetFacilities binds it to a
device, IP address, or other tenant-side signal. In that case the job stops as
`authentication_required`; do not weaken authentication or automate CAPTCHA/MFA.

## Owner-reported live checkpoint

On 2026-08-15 the owner restarted Uvicorn without `--reload` and reported that the
live application imported Task/Symptom correctly and imported Priority correctly. No
source values, work-order identifiers, profile paths, or authentication material were
recorded. The roadmap retains the separate retry, preservation, expiration,
cancellation, timeout, and page-reentry resilience checks. This accepts the local live
happy path only; the first Render-hosted live request remains pending.

## Look up one work order

```powershell
.\venv\Scripts\python.exe -m scripts.netfacilities_poc lookup 12345678 `
  --profile-dir "C:\Users\YOUR-NAME\AppData\Local\InventoryApp\netfacilities-profile"
```

Replace `12345678` with a work-order number the authenticated account is authorized to
view. A successful result is printed as JSON with these Stage 1 fields:

- work-order number;
- description;
- joined and structured location;
- status;
- priority;
- task and work-order types;
- created and scheduled date strings, plus the raw date-like value labeled `Overdue`
  by NetFacilities (`overdue_date`). Its precise business meaning is not normalized in
  Stage 1.

The source HTML is not written to disk. The JSON is operational work-order data; do not
paste it into logs, tickets, source control, or public conversations.

Add `--headed` to the lookup command only when troubleshooting the dedicated browser.

If saved state still does not work, authenticate and look up within one browser process:

```powershell
.\venv\Scripts\python.exe -m scripts.netfacilities_poc lookup 12345678 `
  --profile-dir "C:\Users\YOUR-NAME\AppData\Local\InventoryApp\netfacilities-profile" `
  --reauthenticate
```

Complete login in the opened browser and press Enter. The lookup then runs before that
authenticated browser closes and also refreshes the saved storage state.

## Expected failures

- Authentication required: use the Work Orders sign-in controls and log in manually;
  the CLI `auth` command remains a fallback.
- Permission denied: the NetFacilities account cannot view that work order; do not
  attempt to broaden or bypass its permissions.
- Not found: verify the number in the normal NetFacilities UI.
- Unexpected response/document: stop. NetFacilities may have changed its HTML or
  returned a login/error document; do not import partial data.
- Browser unavailable: verify Chrome is installed and no other process is using the
  dedicated profile.
- Application reports not authenticated/expired: sign in again, then use **Import
  Tasks and Priority** locally; on Render, refresh the secret file and redeploy.
- Application reports unavailable: confirm the current host's required profile or
  saved-state path is configured. Ordinary CSV import remains usable.

## Optional bundled Chromium

The default uses installed Chrome. To use Playwright's bundled Chromium instead:

```powershell
.\venv\Scripts\python.exe -m playwright install chromium
```

Then add `--browser-channel bundled-chromium` to both commands. This is optional for
Stage 1 and does not change the rule that authentication is completed manually.

## Verification boundary

Ordinary tests use only a synthetic, sanitized HTML fixture, fake browser responses,
fake clients, and local database rows. They never call NetFacilities. A successful live
app enrichment must be performed manually by the authorized user because authentication
state is deliberately unavailable to tests and CI.
