# NetFacilities Work-Order Integration Investigation

Last updated: 2026-08-14
Status: Stage 1 live saved-state lookup accepted; local application Milestones 0-5 are
implemented and await operator-run live app acceptance

## Evidence labels

- **Confirmed** — directly supported by the repository, an official vendor source,
  or a read-only public request.
- **Likely** — the available evidence points strongly in one direction, but the
  behavior has not been observed in an authenticated NetFacilities session.
- **Unknown** — no reliable evidence is currently available.
- **Requires manual verification** — an authorized person must inspect their own
  tenant/session or obtain a product-specific answer from MRI.
- **User-confirmed subscription constraint** — reported by the subscription user/owner
  for this tenant; authoritative for this project's planning, but not a claim about
  every NetFacilities customer or contract.

## 1. Executive Summary

The subscription user has confirmed that this NetFacilities subscription provides no
API, no in-product integration/documentation screen, and no third-party integration
support. The official/vendor-supported branch is therefore closed for this project.
This is a **user-confirmed subscription constraint**, not a vendor-global claim.

An authorized capture has now confirmed a hybrid request model:

- The initial work-order document is fully populated, server-rendered HTML (**Model A**)
  and contains the core work-order fields.
- First-party page JavaScript then calls structured AJAX endpoints for secondary data,
  including labor, material usage, vendor cost, billable items, completion notes,
  attachments, audit entries, and recurring-work-order parts.
- A numeric work-order identifier is embedded in the document and reused by work-order
  action links and the secondary requests.

These internal pages/endpoints must be treated as unsupported unless MRI later says
otherwise; lack of support does not by itself establish whether the contract permits or
prohibits automated access.

**Implemented architecture update:** the NetFacilities-specific client still uses a
dedicated, single-user Playwright profile authenticated manually by the authorized user,
retrieves the server-rendered work-order document through `BrowserContext.request`, and
parses semantic HTML without calling secondary or mutation endpoints. The separate CLI
`auth` command saves protected storage state. The local application now exposes three
Admin-only capability/start/poll endpoints and one serialized job that may conditionally
write only exact fallback Task/Symptom and blank Priority on existing live work orders.
CSV import remains the sole creator. Do not use copied cookies or the user's everyday
Chrome profile.

The first live attempt established that closing and reopening the persistent Chrome
profile alone did not preserve this tenant's authenticated lookup state. **Confirmed:**
the original `auth` command completed successfully, closed its browser, and the next
lookup was redirected to authentication. Stage 1 now explicitly saves Playwright
storage state before closing and loads that state for later lookups. A
`lookup --reauthenticate` fallback performs manual authentication and the read-only
lookup within the same browser process if serialized state is still insufficient.
After that correction, the owner reran the normal saved-state flow and confirmed a
successful live work-order lookup without `--reauthenticate`. **Confirmed:** the local
transport, saved authentication state, authenticated HTML request, and parser work
end-to-end for this tenant.

The headed browser did not produce a usable CSV because downloads remain disabled. The
owner resolved that gate by removing download automation from scope: the operator
selects a CSV already present on the computer through the existing Work Orders chooser.
The later owner decision added Admin+ browser-lifecycle routes on the same local Windows
host; they start/confirm/cancel manual login but never accept credentials, CAPTCHA, SSO,
or MFA fields. The application still does not manage CSV downloads.

The current free Render web-service shape is not a reliable home for a persistent
browser session: its filesystem is ephemeral, free instances spin down, and Chromium
adds material memory/runtime requirements. Production browser automation would require
a paid, single-instance service, a narrowly mounted persistent disk or equivalent
secure secret provisioning, explicit session recovery, and an accepted owner decision
to operate an unsupported integration. A browser session on a developer's Windows
computer does not transfer automatically to Render.

No authentication bypass, CAPTCHA automation, cookie harvesting, or reuse of another
person's profile is recommended.

## 2. Current Repository Architecture

### Runtime and organization

**Confirmed:**

- `backend/app/main.py` is the FastAPI composition root and serves the static SPA.
- Backend flow follows `routers -> schemas/services -> domain/models -> database`.
- The frontend is HTML, CSS, and plain JavaScript ES modules under `backend/static`.
- PostgreSQL persistence uses SQLAlchemy and Alembic.
- The repository deploys one Docker web service through `render.yaml`.
- The container is based on Python 3.12 slim, runs as a non-root user, applies Alembic
  migrations at startup, and then starts Uvicorn.
- Configuration uses environment variables and `python-dotenv`; there is no central
  Pydantic Settings object.
- The active production dependency pins observed during this review include FastAPI
  0.136.3, Starlette 1.3.1, Uvicorn 0.48.0, Pydantic 2.13.4, SQLAlchemy 2.0.50,
  Alembic 1.18.4, psycopg 3.3.4, python-dotenv 1.2.2, and pytest 9.0.3.

### Work-order path

**Confirmed:**

- The work-order SQLAlchemy model is in `backend/app/models.py`.
- Work-order routing, contracts, business rules, and persistence are split across:
  - `backend/app/routers/work_orders.py`
  - `backend/app/schemas/work_orders.py`
  - `backend/app/domain/work_orders.py`
  - `backend/app/services/work_orders.py`
- Work orders are currently created by an Admin-or-higher CSV import at
  `POST /work-orders/import`.
- Existing CSV source columns are `WORK ORDER`, `LOCATION`, `OUTPUT TO`,
  `ASSIGNED TO`, `SERVICE TYPE`, `SCHEDULE DATE`, and `SYMPTOM/TASK`.
- The current import parses all rows before writes, but row helpers own commits. It is
  not yet a previewed, fully batch-atomic import.
- Existing source links use
  `https://system.netfacilities.com/tools/viewworkorders/{work-order-number}`.
- The Work Orders interface is `backend/static/pages/work-orders.html`, with behavior
  in `backend/static/views/workOrders.js` and request wrappers in
  `backend/static/api.js`.
- Frontend API requests use same-origin `fetch` with `credentials: "include"`.
- There is no OCR workflow. Image decoding in the repository is barcode recognition,
  not document OCR.

### Application authentication

**Confirmed:** the application has its own server-side authorization system. It uses
opaque session tokens whose hashes are stored server-side, an HttpOnly cookie,
SameSite=Lax, Secure cookies in production, a 12-hour absolute session ceiling, and
Technician/Supervisor/Admin/Owner role gates. NetFacilities access must be protected by
these backend gates; hiding a frontend button is not authorization.

### Tests

**Confirmed:** tests live under `backend/tests`. The current environment collected 802
pytest tests during this investigation. Ordinary tests do not need a live external
system today.

## 3. Relevant Capabilities Already Present in Our Stack

- FastAPI lifespan management, already used for application lifecycle wiring.
- Pydantic v2 models for typed request, normalized preview, and error contracts.
- Server-side role dependencies suitable for restricting lookup/import/re-authentication.
- SQLAlchemy transaction and row-lock patterns that can be reused for a later atomic,
  idempotent import.
- Request IDs and structured production logging that can record outcome metadata
  without recording upstream secrets or payloads.
- A no-build frontend that can add a small lookup and preview panel without changing
  frameworks.
- Docker deployment, which provides a reproducible place to add Chromium system
  dependencies if Playwright becomes necessary.
- Existing work-order normalization concepts and a stable case-insensitive work-order
  number identity.

## 4. Missing Capabilities

### Needed for every transport

- A NetFacilities-specific client interface and normalized external work-order model.
- Admin-only lookup/preview and confirmed-import APIs.
- Source provenance, external fingerprint/idempotency rules, and duplicate behavior.
- Sanitized upstream error handling and integration-specific observability.
- An explicit configuration and secret-handling design.

### Needed for direct HTTP

- The real `httpx` package. The current dev dependency named `httpx2` is not an
  equivalent substitute for HTTPX.
- Confirmed authentication, refresh, CSRF, response, and session-expiration contracts.

### Needed for browser automation

- Python Playwright.
- A pinned compatible Chromium installation and its Debian runtime libraries.
- A tolerant semantic HTML parser. `beautifulsoup4` is the recommended proof-of-concept
  dependency because it is pure Python and sufficient for this server-rendered document;
  it is not currently in the repository.
- A browser/session manager, concurrency admission, crash recovery, and clean shutdown.
- Secure persistent storage and a manual reauthentication procedure.
- A paid production runtime sized and tested for Chromium.

## 5. NetFacilities Authentication Findings

| Finding | Status | Evidence/meaning |
| --- | --- | --- |
| Public login is served by Microsoft IIS/ASP.NET | **Confirmed** | Public response headers include Microsoft-IIS and ASP.NET. |
| Sign-in submits JSON to `/Account/SignIn/` | **Confirmed** | Public login JavaScript posts email, password, `Persistent`, and return URL. |
| “Remember Me” sets a `Persistent` sign-in option | **Confirmed** | The public login flow includes that Boolean. This does not prove which cookie/token is issued. |
| CAPTCHA is present in the interactive login flow | **Confirmed** | It must remain a manual authentication step. |
| Some users may be redirected to Okta | **Confirmed** | Public JavaScript checks whether the user exists on CI and can route to `/Account/LoginWithOkta?Email=...`. |
| An unauthenticated work-order URL redirects to login with `ReturnUrl` | **Confirmed** | `/tools/viewworkorders/{number}` returned a login redirect during read-only inspection. |
| Successful authentication is cookie-based/forms authentication | **Likely** | IIS/ASP.NET, persistent sign-in, and redirect behavior strongly suggest it, but an authenticated response was not captured. |
| Exact cookie names, attributes, domains, and lifetimes | **Requires manual verification** | Record names and attributes only; never copy values into the report. |
| localStorage/sessionStorage bearer or refresh tokens | **Unknown** | Must be inspected in an authorized session. |
| Anti-forgery/CSRF mechanism | **Unknown** | Must be observed on the work-order request and any sign-in/session-refresh requests. |
| MFA, device binding, IP binding, or fingerprinting | **Unknown** | These may vary by account/SSO policy. |

“Remember Me” therefore means only that NetFacilities asks for persistent sign-in. It
does not yet prove that one exported cookie is sufficient or supported.

## 6. NetFacilities Work-Order Request/Data Flow

The authenticated capture confirms a **hybrid Model A/C flow**.

### Core document — confirmed server-rendered HTML

The initial authenticated work-order document contains the core data directly in HTML;
it is not an empty JavaScript shell. Confirmed field groups include:

- work-order number/identifier and status;
- created and scheduled dates;
- facility/site and a multi-level location;
- originator/requester organization information;
- task/category and free-text procedure/description;
- assignee plus a separate numeric user identifier;
- priority, a date-like value labeled `Overdue`, approver, actual hours, and billable
  flag;
- time zone, firm/recurring/frequency values, and work-order type.

The document exposes a numeric identifier in its heading, a page-level `_woid` variable,
action URLs, attachment actions, and audit element IDs. In the captured example, the
visible work-order number and this numeric identifier were the same. Verify that equality
with a few additional work orders before treating it as a permanent invariant.

The authorized Network capture confirms the core lookup contract:

```text
GET /tools/viewworkorders/{work_order_number}
-> 200 OK
-> HTML response
-> no redirect observed for a valid authenticated lookup
```

The work-order number is therefore sufficient user input for Stage 1. The client must
still validate the final URL, status, content type, expected work-order markers, and
returned identifier before accepting the response.

The document also contains stable semantic structure—section headings, element IDs, and
table IDs. Core extraction should therefore parse the returned HTML document rather
than render the page and scrape pixel/layout-dependent selectors.

The document includes links/actions that can close, edit, reassign, reschedule, cancel,
copy, print, discuss, or attach files. The lookup client must never invoke those mutation
paths. Allowlist only the read document and explicitly selected read-only secondary
requests.

### Secondary data — confirmed first-party AJAX calls

The page's referenced first-party `Viewworkorders.js` calls these same-origin internal
endpoints with JSON-shaped request bodies:

| Data | Endpoint path | Request keys visible in first-party JavaScript |
| --- | --- | --- |
| Labor tracking | `/WorkOrder/GetLaborCost` | `woid` |
| Material usage | `/Inventory/GetProductUsageItemsByID` | `IPUsageID` |
| Vendor cost | `/WorkOrder/GetVendorCostItems` | `woid` |
| Billable items | `/WorkOrder/GetBillable` | `woid`, `vendorid` |
| Completion notes | `/WorkOrder/GetCompletionNotes` | `woid` |
| Attachment metadata | `/WorkOrderFile/GetList` | `take`, `skip`, `woid`, `PresetID` |
| Audit trail | `/Discuss/GetAuditList` | `woid` |
| Recurring-work-order parts | `/PM/GetWOIPartsByRecurringID` | `recurringID` |

The JavaScript expects structured objects with flags/counts and `Items` arrays. It also
contains separate framed routes for user information and discussion. The exact HTTP
method, content type, CSRF requirements, status codes, and session-expiry behavior still
require one small sanitized Network/Headers capture because those details are hidden
inside the shared `nf.ajax` wrapper.

One captured secondary response confirms this envelope variant:

| Field | Observed type/semantics |
| --- | --- |
| `HasError` | Boolean; `false` indicates success |
| `ErrorMessage` | String; empty on the captured success response |
| `Items` | Array; an empty array is a valid successful “no records” result |
| Aggregate totals | Decimal strings, not JSON numbers |

The aggregate keys in that response are consistent with the labor/cost request. The
parser must convert decimal strings deliberately and must not interpret an empty
`Items` array as “work order not found.” The endpoint path/method should be associated
from request metadata before that optional parser is implemented.

### Optional secondary-request metadata

No further capture is required for the Stage 1 core lookup. Before implementing any
secondary dataset, inspect one matching Fetch/XHR entry and record only its path, method,
request/response content types, status, request key names, and CSRF/header names without
values. Do not retain another response body, use **Copy as cURL**, save an unsanitized
HAR, or record work-order/personal data.

The primary data-flow question is resolved: parse authenticated server-rendered HTML
for the core record, and use structured secondary endpoints only for fields the import
actually needs.

## 7. Official API / Integration Findings

| Finding | Status |
| --- | --- |
| MRI markets NetFacilities work-order, assignment, priority, reporting, material, time, and cost capabilities | **Confirmed** ([official product page](https://www.mrisoftware.com/products/netfacilities/)) |
| MRI has a Partner Connect integration ecosystem | **Confirmed** ([Partner Connect](https://partners.mrisoftware.com/)) |
| MRI provides a dedicated NetFacilities support portal | **Confirmed** ([MRI support directory](https://www.mrisoftware.com/contact-support/), [portal](https://netfacilitiessupport.zendesk.com/)) |
| This subscription provides a supported read API | **No — user-confirmed subscription constraint** |
| This tenant provides an integration/documentation screen | **No — user-confirmed subscription constraint** |
| Third-party integration support is available for this subscription | **No — user-confirmed subscription constraint** |
| Automated internal-web-endpoint access is explicitly permitted or prohibited | **Unknown; unsupported is not the same as expressly prohibited** |

For this project, stop spending time searching for an official API or in-product
integration documentation. These findings are scoped to this subscription and should
not be generalized to every NetFacilities customer. The remaining work is a technical
browser-flow investigation plus an owner decision on accepting the operational and
contractual risk of an unsupported integration.

## 8. Direct HTTP Feasibility

Direct HTTP through `httpx.AsyncClient` is attractive if the authenticated browser flow
can be reduced to documented or stable requests.

### Advantages

- Much lower memory and startup cost than Chromium.
- Straightforward connection pooling, timeouts, cancellation, and unit testing.
- Easier Docker and Render deployment.
- Smaller crash/failure surface.
- Easier request/response schema validation.

### Conditions for viability

- The required state consists of legitimate cookies/tokens that can be securely
  maintained server-side.
- JavaScript is not required to generate dynamic signatures or continuously refresh
  state.
- CSRF/anti-forgery state can be obtained and refreshed through ordinary requests.
- Redirect/login detection is deterministic.
- The organization has reviewed applicable terms and accepts using an unsupported
  access method within the authorized user's existing permissions.
- The endpoint and schema are stable enough for the accepted maintenance burden.

### Assessment

**Feasible as a Playwright-context hybrid; standalone HTTPX remains unproven.** The core
work order is an ordinary authenticated HTML document, and the secondary calls use
structured same-origin requests. Use Playwright to preserve the legitimate login and
`BrowserContext.request` to retrieve both document and optional secondary data through
the shared cookie jar. This avoids copying cookies and does not require page rendering
for normal lookup.

Only consider replacing the context request client with `httpx.AsyncClient` if a later
proof demonstrates that authentication/refresh/CSRF state can be maintained deliberately
without exporting browser state. All internal routes remain unsupported and require
strict response validation.

Use explicit timeout budgets rather than indefinite defaults: an initial design target
is a five-second queue/admission wait, a 30-second upstream operation timeout, and a
45-second whole-lookup deadline. Tune after measurement.

## 9. Playwright Feasibility

Playwright fits the Python/FastAPI stack and can preserve cookies and web storage in an
authorized browser context.

### Persistent browser context

`chromium.launch_persistent_context(user_data_dir=...)` stores the dedicated profile's
state. It is the best default when the login can depend on more than cookies or
localStorage. Only one process should own the profile at a time. Never point it at the
user's everyday Chrome profile.

### Saved storage state

Playwright storage state can capture cookies, localStorage, and optionally IndexedDB.
It is easier to provision but does not automatically preserve sessionStorage and is a
bearer-equivalent secret. Use only if manual verification proves it preserves all
required authentication state.

### Long-running browser

One browser/context per FastAPI process is preferable to launching Chromium on every
lookup. It preserves the session, reduces latency and login pressure, and gives the
application one place to detect and recover from crashes. A new page can be created per
lookup only when UI navigation is required; structured requests should use the shared
context request client.

### Response parsing before rendered-DOM scraping

The core response is now confirmed to be populated HTML, while secondary data uses
structured AJAX responses. Retrieve the document through the context request client and
parse semantic headings/IDs/table structure. Call only the secondary endpoints required
for the selected import fields. Rendered-page selectors remain less desirable because
layout, CSS classes, and timing can change independently of the returned data.

### Constraints

- Playwright APIs are not thread-safe. Keep all browser work on the async event loop and
  never pass pages/contexts to threadpool code.
- Start with one serialized upstream lookup using an `asyncio.Lock` or semaphore of one.
- Chromium and its Debian libraries increase build size and memory requirements.
- A headed manual-login workflow is easy locally but requires an explicit secure
  administrative mechanism in production.

Official references: [Playwright authentication](https://playwright.dev/python/docs/auth),
[persistent contexts](https://playwright.dev/python/docs/api/class-browsertype),
[network observation](https://playwright.dev/python/docs/network), and
[context request cookies](https://playwright.dev/python/docs/api/class-apirequestcontext).

## 10. Existing Credentialed Session Strategy

### Recommended session ownership

Use a dedicated application-owned NetFacilities browser profile rather than the user's
default browser profile:

1. An authorized administrator launches the dedicated authentication browser.
2. The administrator completes password, SSO, MFA, and CAPTCHA manually.
3. Playwright persists only that dedicated context/profile in a protected path.
4. Automated lookup reuses that state while NetFacilities accepts it.
5. On authentication loss, automated lookup stops and asks an administrator to
   reauthenticate.

This is session reuse, not authentication bypass.

### Local versus production

- **Local:** use a headed dedicated Chromium profile on the developer/admin machine.
- **Production:** Render is a different machine. It needs its own manually established
  server-side session or an approved encrypted provisioning workflow. A local Windows
  Chrome login is not implicitly available in the Linux container.

### Local-browser-owned alternative

A normal frontend page cannot make this work reliably: same-origin/CORS rules constrain
cross-origin calls and HttpOnly cookies are deliberately unavailable to JavaScript. A
browser extension can obtain cross-origin and cookie permissions, but adds an extension
distribution, update, permission, and security lifecycle. A localhost helper adds a
second deployed service on each workstation. Use either only if MRI prohibits a shared
server-side session or business rules require each lookup to run under each user's own
NetFacilities identity.

## 11. Work-Order Field Mapping

The authenticated HTML capture confirms the presence of the core fields below without
retaining any captured values or personal data. Secondary field groups are confirmed by
the first-party JavaScript endpoint calls; their exact response variants still need
sanitized fixtures.

| NetFacilities field | Current application field | Transformation/policy | Status |
| --- | --- | --- | --- |
| Work-order number | `WorkOrder.number` | Trim; case-insensitive identity; validate allowed shape; verify number/internal-ID equality across more records | **Confirmed in HTML** |
| Location hierarchy | `location` and possibly community/building/unit | Preserve levels separately in source model; join/split only under an approved rule | **Confirmed in HTML; partial local match** |
| Output To | `output_to` | Trim/normalize blank | Existing CSV field; **not observed in this HTML capture** |
| Assigned To | assignee/assignees | Resolve by stable identity; do not silently create or guess users | **Confirmed in HTML with separate numeric user ID** |
| Service/work-order type | `service_type` | Keep source task/category and WO type distinct until mapping is approved | **Confirmed in HTML; normalization required** |
| Schedule Date | raw `schedule_date` | Preserve source string; parse only under existing approved rules | **Confirmed in HTML** |
| Symptom/Task | `description` | Preserve text and newline semantics; size-limit | **Confirmed in HTML** |
| Status | local work-order status | Keep external status separate until an explicit lifecycle mapping is approved | **Confirmed in HTML; local field exists** |
| Priority | no clearly equivalent persisted source field | Preview first; add storage only after schema decision | **Confirmed in HTML; storage gap** |
| Facility/site/building/floor/area | community/building/unit/location candidates | Needs tenant-specific hierarchy rules | **Confirmed in HTML; partial local match** |
| Requester/originator | no confirmed direct import target | Decide whether to store a source snapshot; treat as personal data | **Confirmed in HTML; storage gap** |
| Created/scheduled/overdue/completed values | local created/updated timestamps are not source dates | Preserve the source label and raw value; do not infer that `Overdue` is the due date until verified; never overwrite audit timestamps | Created/scheduled and a date-like `Overdue` value **confirmed in HTML**; completion data available through secondary endpoint |
| Category/problem type | service type/description candidates | Do not conflate task category and WO type | **Confirmed in HTML** |
| Notes/instructions | append-only local notes and description candidates | Source snapshot vs local authored note must remain distinguishable | Procedure text confirmed; completion notes available through secondary endpoint |
| Labor | local labor records | Preview only until identity/rate/duplication rules exist | **Structured secondary endpoint confirmed; do not auto-import** |
| Materials | local item/transaction records | Never mutate stock during lookup; explicit confirmed import only | **Structured secondary endpoints confirmed; high-integrity mapping required** |
| Attachments | no current attachment persistence | Metadata/link only unless a separate secure file design is approved | **Attachment-list endpoint confirmed; local gap** |
| Vendor/technician | `vendor_assignee`/assignee concepts | Normalize stable IDs and display names separately | Assignee/vendor display confirmed; partial local match |
| Audit trail | no direct import target | Operational diagnostics/provenance only unless separately approved | **Structured secondary endpoint confirmed** |

The proof of concept should return a small source model rather than force every possible
field into the database.

## 12. FastAPI Integration Architecture

Recommended structure, consistent with repository conventions:

```text
backend/app/
  integrations/
    netfacilities/
      client.py
      models.py
      parser.py
      errors.py
      session.py
      transports/
        official_api.py
        browser.py
        http.py
  routers/
    netfacilities.py
  schemas/
    netfacilities.py
  services/
    netfacilities.py
```

Core boundary:

```text
NetFacilitiesClient.get_work_order(identifier)
    -> NetFacilitiesWorkOrder
```

The service and application routes should not know whether the client used an official
API, an internal JSON endpoint, authenticated HTML, or DOM extraction.

### Proposed flow

`POST /integrations/netfacilities/work-orders/lookup`

```json
{
  "work_order_number": "123456"
}
```

Flow:

```text
Admin authorization
  -> identifier validation
  -> NetFacilities client
  -> authenticated retrieval
  -> strict upstream validation
  -> normalized preview + source fingerprint
  -> no database mutation
```

A separate endpoint, for example
`POST /integrations/netfacilities/work-orders/import`, should accept the selected
preview and confirmation. The server should re-fetch or validate a signed/short-lived
fingerprint so a stale or client-edited preview cannot silently create a different work
order. Import should be atomic, idempotent, attributable, and auditable.

Separating preview from import is safer because it prevents accidental creation,
exposes lossy mappings, and matches the repository's documented import-hardening work.

## 13. Browser Lifecycle Architecture

1. **Launch timing:** register a browser/session manager in FastAPI's existing lifespan,
   but lazily launch Chromium on first use. NetFacilities availability should not block
   inventory-app startup or health checks.
2. **Context:** keep one long-lived asynchronous browser context per application
   process.
3. **Pages:** use the context request client for structured requests; otherwise create
   one page per lookup and close it in `finally`.
4. **Concurrency:** begin with a semaphore of one. Multiple simultaneous lookups queue
   briefly and then return a controlled busy/timeout response.
5. **Thread safety:** do not use a shared Playwright object from worker threads.
6. **Session manager:** own start, authentication status, lock, page cleanup, one
   controlled restart, and shutdown.
7. **Crash behavior:** invalidate the context, restart once, then return
   `NetFacilitiesUnavailable` and emit a secret-free operational event.
8. **Shutdown:** close pages, context, browser, and Playwright in lifespan cleanup.
9. **Timeouts:** start with five seconds for admission, 30 seconds upstream, and 45
   seconds end to end; measure and revise.
10. **Login response:** check final URL, redirect chain, content type, expected schema,
    and known login markers. Never feed a login document to a work-order parser.

Recommended failure types:

- `NetFacilitiesAuthenticationRequired`
- `NetFacilitiesSessionExpired`
- `NetFacilitiesWorkOrderNotFound`
- `NetFacilitiesPermissionDenied`
- `NetFacilitiesRateLimited`
- `NetFacilitiesTimeout`
- `NetFacilitiesUnavailable`
- `NetFacilitiesUnexpectedResponse`

Map upstream authentication loss to a stable application response such as HTTP 409,
not 401, so the frontend does not confuse an expired NetFacilities session with the
user's inventory-app session.

## 14. Render / Production Deployment Analysis

**Confirmed:** the current repository deploys a Docker-based Render web service.

**Confirmed from current Render documentation:** free web services have limited CPU and
memory, spin down when idle, use an ephemeral filesystem, and cannot attach a persistent
disk. Persistent disks are paid, preserve only their mount path, constrain the service
to one instance, and change deployment behavior. See [Render free services](https://render.com/docs/free),
[compute plans](https://render.com/docs/compute-plans), and
[persistent disks](https://render.com/docs/disks).

Consequences:

- The current free shape is unsuitable for reliable browser-session ownership.
- Add Playwright/Chromium in Docker only after the network proof of concept proves it is
  needed.
- Benchmark a paid Render instance; a 2 GB class is a safer initial browser trial than
  a 512 MB class, but measurements—not assumption—should set the production size.
- Mount only a narrow runtime directory, for example
  `/app/runtime/netfacilities`, not the repository or broad application root.
- Run exactly one application instance while it owns the browser profile. Multiple
  instances cannot safely open the same profile and can produce session conflicts.
- Headless Chromium is appropriate for normal lookups; reauthentication still needs a
  secure manual workflow.
- A restart/deploy terminates the browser. Persistent profile/storage can survive only
  if written to the configured persistent mount. Even then, NetFacilities may expire or
  revoke the upstream session.
- Sleep/spin-down and rolling redeploys undermine the long-running context; paid
  always-on service plus controlled startup recovery is required.
- Treat storage-state/profile data as a secret. Render secret files are useful for
  provisioned artifacts, but deployment changes can restart the service. A persistent
  disk is better for browser-mutated state.

## 15. Security Analysis

### Protected assets

- Persistent browser profile or storage-state file.
- Cookies, bearer/refresh tokens, CSRF tokens, and session identifiers.
- Work-order content and attachments.
- NetFacilities account identity and permitted tenant scope.

### Threats and controls

| Threat | Control |
| --- | --- |
| Stolen profile/storage state | Dedicated least-privilege account; encrypted provider storage; narrow path; owner-only permissions; rotation/revocation runbook |
| Cookies/tokens in logs | Central redaction; log only outcome, request ID, timing, hashed/truncated external identifier where appropriate; never headers/body/storage |
| Secret committed to Git | Ignore runtime secret paths; CI secret scanning; never place samples with real values in docs or fixtures |
| Frontend exposure | Browser/session artifacts remain backend-only; return normalized fields only |
| Database exposure | Do not store session artifacts in PostgreSQL without a deliberate encrypted secret design |
| Unauthorized inventory-app user | Backend Admin-or-higher gate for lookup/import; Owner-only or separately approved gate for session administration |
| Authorized app user probes arbitrary upstream URLs | Accept a constrained work-order identifier, never an arbitrary URL; hard-code/allowlist the NetFacilities host and paths |
| User requests an upstream-forbidden work order | Let NetFacilities enforce its permissions; treat 403/login/tenant mismatch distinctly; do not broaden account permissions |
| Session fixation/substitution | Dedicated profile, controlled authentication ceremony, account identity check after login, revoke state on unexpected identity |
| Duplicate/incorrect import | Preview, explicit confirmation, source fingerprint, idempotency, transaction ownership, audit actor, and reversible provenance |
| Debug artifacts leak content | Disable production HAR/traces/screenshots by default; sanitize before retaining any diagnostic fixture |

The upstream integration account should have only read access to the required work
orders. If a supported service account is unavailable, document whose identity owns the
session and how departure/role changes revoke it.

## 16. Failure Modes

| Failure | Detection | Error behavior | Logging and recovery |
| --- | --- | --- | --- |
| Session expires | Login redirect/final URL/login markers or failed identity probe | `NetFacilitiesSessionExpired`; no parse/import | Log category and request ID only; manual reauth |
| Browser crashes | Playwright disconnected/target closed | One controlled restart, then unavailable | Count crash/restart; no profile dump |
| Network timeout | Explicit connect/read/whole-operation deadline | Retry only a safe read once if budget allows | Log stage and duration; do not log URL query secrets |
| Work order absent | Verified 404/not-found response or supported API code | `NetFacilitiesWorkOrderNotFound` | Normal outcome, no stack trace |
| Permission denied | 403 or explicit access-denied schema distinct from login | `NetFacilitiesPermissionDenied` | Audit actor and external number safely; do not retry |
| Rate limit | 429/retry hint | Stable rate-limited response | Honor `Retry-After`; back off; no bypass |
| Maintenance/outage | 5xx/known maintenance response | `NetFacilitiesUnavailable` | Bounded retry; alert on sustained errors |
| Unexpected redirect | Host/path allowlist fails | `NetFacilitiesUnexpectedResponse` | Stop; record sanitized destination host/path |
| Endpoint/JSON schema changes | Strict required-field/schema validation | No partial import; unexpected response | Store only a sanitized schema summary/fixture after review |
| HTML selector changes | Expected unique labels/selectors absent | Unexpected response; no guessed fields | Update parser only after controlled capture |
| Duplicate import | Case-insensitive number plus source identity/fingerprint | Return existing/diff/explicit update choice | Audit idempotent result |
| Partial upstream data | Required/optional field validation | Preview marks missing optional fields; reject missing identity | No database writes during lookup |

## 17. Testing Strategy

### Unit tests — ordinary `pytest`

- Parse sanitized JSON and HTML fixtures into `NetFacilitiesWorkOrder`.
- Validate field normalization, missing fields, dates, identifiers, and size limits.
- Detect login, permission, not-found, malformed, and schema-drift responses.
- Test error-to-HTTP mapping and ensure error text contains no secrets.
- Test preview fingerprint/idempotency rules.
- Test import mapping and transaction rollback using the existing test database.

### Integration tests — still offline by default

- Use mocked HTTP responses for redirect, cookies, CSRF, timeout, 429, and 5xx flows.
- Mock a narrow browser/session-manager protocol rather than Playwright internals across
  every service test.
- Run a small optional Playwright test against a local fake NetFacilities server to
  prove network observation, shared cookies, context lifecycle, and crash recovery.
- Keep captured fixtures sanitized and reviewed; never commit session artifacts or raw
  HAR files.

### Live NetFacilities tests — manual/explicit only

- Mark tests, for example, `live_netfacilities` and exclude them from normal pytest and
  CI.
- Require explicit environment configuration and an authorized non-production/test
  work order.
- Keep them read-only until the owner accepts the unsupported-integration risk and the
  import path has independent tests.
- Run only on demand and never print response bodies or authentication state.

## 18. Approach Comparison

| Current rank | Approach | Feasibility | Reliability | Security | Deployment complexity | Maintenance |
| ---: | --- | --- | --- | --- | --- | --- |
| Excluded | Official API | **Unavailable for this subscription (user-confirmed)** | Would have been highest | Would have been highest | Low to medium | Lowest |
| 1 | Playwright-authenticated document request + semantic HTML parsing | **Confirmed data model; recommended** | Good for core fields; unsupported HTML may still change | Good with dedicated single-user profile and no cookie export | Medium to high | Medium |
| 2 | Internal authenticated JSON endpoints through the Playwright context | **Confirmed for secondary data; unsupported** | Good technically, but no vendor contract/change support | Good with strict host/schema validation | Medium to high | Medium to high; endpoints may change without notice |
| 3 | Playwright + network interception/request reuse | **High technical feasibility; useful for discovery/fallback** | Better than rendered DOM and tolerates browser auth | Good with dedicated profile; profile is a high-value secret | High | Medium to high |
| 4 | Direct authenticated HTTP outside Playwright | **Unknown pending auth/CSRF analysis; unsupported** | High if browser-generated state is simple; otherwise brittle | Good only if state transfer is deliberately secured | Low to medium | Medium to high |
| 5 | Playwright + DOM scraping | **Technically feasible but unnecessary for core fields** | Lowest; selectors/rendering can change | Same browser-secret burden plus more diagnostic-content risk | High | Highest |

This ranking assumes legal/contractual permission. A technically callable internal
endpoint is not automatically a supported integration surface.

## 19. Recommended Architecture

**Recommended proof-of-concept architecture:**

```text
Authorized user
  -> dedicated local Playwright persistent context
  -> manual NetFacilities login when required
  -> BrowserContext.request retrieves the work-order document
  -> semantic HTML parser extracts core fields
  -> optional context requests retrieve required secondary JSON data
  -> strict normalized Pydantic object
  -> local proof-of-concept output only; no database write
```

After that works, put the same transport behind `NetFacilitiesClient` and the
administrator-only FastAPI preview endpoint. Decide separately whether production owns
a dedicated session on paid Render or the integration remains a local operator tool.

**Why:** the supported vendor path is unavailable, but the captured document proves the
core data can be retrieved without rendered-DOM automation. This design preserves
legitimate manual authentication, avoids exporting/copying a user's normal-browser
cookies, uses semantic HTML for the core record and structured responses for optional
secondary data, and proves the fragile upstream boundary before adding server lifecycle
and deployment complexity.

**Fallback:** use a Playwright page and narrowly scoped DOM extraction only for behavior
that cannot be reproduced through `BrowserContext.request` and response parsing.

**Do not use:** the user's everyday Chrome profile; ad hoc cookie copying; frontend
cross-origin requests; CAPTCHA automation; arbitrary user-supplied URLs; unsanitized
HAR/storage files; immediate save during lookup; multi-instance profile sharing; the
current free Render service for production Chromium; or continued API/vendor-document
search as an implementation prerequisite.

## 20. Incremental Implementation Roadmap

### Stage 1 — Proof of Concept

- **Status:** **Implemented locally on 2026-08-14.** See
  [`docs/netfacilities-stage1-poc.md`](netfacilities-stage1-poc.md). The owner completed
  a successful live authenticated lookup using saved state without `--reauthenticate`.
- **Objective:** given one known permitted identifier, retrieve one work order and
  return/print number, description, location, status, and priority from the authenticated
  HTML document; no DB and no secondary endpoint required initially.
- **Implemented files:** `backend/app/integrations/netfacilities/{client,parser,errors}.py`,
  `backend/scripts/netfacilities_poc.py`, sanitized fixture and focused tests, and the
  local runbook. No production route or database code was added.
- **Dependencies:** pinned development-only `playwright==1.62.0` and
  `beautifulsoup4==4.15.0`. The default uses locally installed Chrome; no browser binary
  was added to the production image.
- **Acceptance:** repeatable `BrowserContext.request` retrieval and semantic parsing;
  required fields fail closed; login HTML is detected; no secret or captured personal
  data appears in output/repo/logs.
- **Verification completed:** 27 focused offline tests, the full 829-test backend suite,
  Python compilation, dependency integrity, and a local headless Chrome launch smoke
  test, plus the owner-controlled live lookup. Live access remains deliberately absent
  from automated tests and CI.
- **Risks:** unsupported HTML contract, SSO/CAPTCHA/session binding, and assuming the
  visible number always equals the internal identifier from only one captured example.

### Stage 2 — Normalize

- **Objective:** map the source into a typed `NetFacilitiesWorkOrder` with required,
  optional, and raw-source provenance rules.
- **Likely files:** integration `models.py`, `parser.py`, `errors.py`; unit tests and
  sanitized fixtures.
- **Dependencies:** Pydantic already exists; no additional dependency expected.
- **Acceptance:** deterministic parsing and explicit failures across all captured cases.
- **Risks:** schema drift and incorrect field conflation.

### Stage 3 — FastAPI Endpoint

- **Objective:** add Admin-only lookup/preview with stable errors and bounded admission.
- **Likely files:** `routers/netfacilities.py`, `schemas/netfacilities.py`,
  `services/netfacilities.py`, `main.py`, role/error tests.
- **Dependencies:** chosen transport dependency.
- **Acceptance:** authorized user receives normalized preview; unauthorized users are
  denied server-side; no database mutation; timeout/auth errors are distinct.
- **Risks:** event-loop misuse, leaked errors, request pile-up.

### Stage 4 — Frontend

- **Objective:** add work-order-number input, lookup button, field/difference preview,
  and clear error states.
- **Likely files:** `static/pages/work-orders.html`, `static/views/workOrders.js`,
  `static/api.js`, `static/styles.css` if needed.
- **Dependencies:** none.
- **Acceptance:** no automatic save; preview labels missing/changed fields; button is UX
  gated while backend remains authoritative.
- **Risks:** stale previews and duplicate submission.

### Stage 5 — Database Integration

- **Objective:** atomically import a confirmed preview with source provenance,
  idempotency, attribution, and duplicate/update behavior.
- **Likely files:** work-order service/domain/schema/model, integration service, Alembic
  only if approved provenance fields require it, and focused DB tests.
- **Dependencies:** none beyond current stack unless schema is extended.
- **Acceptance:** duplicate calls have one effect; any failure rolls back the whole
  import; imported source is traceable and safely reversible.
- **Risks:** transaction ownership, identity mapping, materials causing stock mutation.

### Stage 6 — Session Recovery

- **Objective:** reliably detect expiry and enable manual administrator reauthentication.
- **Likely files:** integration `session.py`, lifespan wiring, admin route/UI or secured
  operational script, runbook.
- **Dependencies:** Playwright only if browser transport selected.
- **Acceptance:** login pages are never parsed; normal lookups stop while expired;
  manual login restores operation; all secrets remain out of logs.
- **Risks:** production interactive-login ergonomics and session-owner turnover.

### Stage 7 — Production Deployment

- **Objective:** build, persist, observe, secure, and rehearse the selected transport on
  paid Render infrastructure.
- **Likely files:** Dockerfile, `render.yaml`, environment/runbook docs, deployment and
  smoke checks.
- **Dependencies:** pinned Playwright/Chromium and runtime libraries if selected.
- **Acceptance:** cold start, restart, crash, session expiry, timeout, backup/revoke,
  and redeploy drills pass within approved budgets on one instance.
- **Risks:** memory pressure, disk lifecycle, single-instance availability, vendor
  session policy.

## 21. Open Questions Requiring Manual Browser Inspection

1. What method/content type does the shared `nf.ajax` wrapper use, and do secondary
   requests require a CSRF/anti-forgery header or field?
2. Which cookie/storage mechanisms are used after successful login, and what are their
   attributes/lifetimes? Record names and attributes only.
3. How is expiry expressed: 302 to login, 401/403, HTML with 200, or structured JSON?
4. Is the session tied to device, IP, browser context, SSO policy, or concurrent-login
   limits?
5. Does the visible work-order number equal the internal `_woid` across multiple work
   orders, or was that equality specific to the captured record?
6. Which optional secondary datasets are actually required by the application, and
   what sanitized response variants must their parsers support?
## 22. Exact Next Action

Application wiring and the Admin+ in-app manual sign-in controls are implemented. The
same-host decision is resolved for this release: FastAPI and the dedicated headed
browser run on the same Admin-controlled Windows computer. The next action is the
secret-safe local live acceptance in repository-root `handoff.md`: start sign-in from
Work Orders, complete credentials/CAPTCHA/MFA directly in Chrome, confirm in the app,
choose a permitted CSV already on the computer, and verify that only exact fallback
Task/Symptom and blank Priority change. Verify retry, expiry/reauthentication,
manual-value preservation, archived-row exclusion, and no status/other-field mutation.
Record counts and pass/fail only.

This does not establish a Render or remote-browser design. A normal tab on an Admin's
computer cannot authenticate a Playwright context running on Render; that deployment
boundary remains explicitly deferred.

### A. Historical vendor-verification checklist — closed for this subscription

The following checklist is retained as decision history. It is not the next action.

#### Step 1 — Identify the contractual and support owner

Ask internally who owns the MRI/NetFacilities subscription. Obtain, without putting
secrets in the repository:

- legal customer/organization name;
- MRI or NetFacilities Client ID;
- tenant URL;
- product/edition and current version if displayed;
- account manager/customer-success contact;
- Designated Support Contact (DSC) or NetFacilities support-portal administrator;
- current order form, product schedule, statement of work, renewal, and amendments.

MRI's support policy says only designated contacts may open support cases in the main
support process, so involve the DSC first. If nobody knows the DSC, ask the subscription
owner or contract/procurement contact to identify or change it.

#### Step 2 — Review the agreement before relying on generic product claims

Search the current signed documents for these exact terms:

```text
API
application programming interface
web service
REST
SOAP
integration
data feed
reporting
scheduled report
scheduled export
webhook
service account
integration account
non-human user
SSO
OAuth
additional fees
usage limits
```

Record the document title, effective date, section, entitlement, restrictions, and any
separate SKU. Do not assume a generic MRI master agreement grants a NetFacilities API.
The product-specific order documents control subscription entitlement.

#### Step 3 — Search authenticated vendor documentation

1. Open the [official MRI support directory](https://www.mrisoftware.com/contact-support/).
2. Find **NETfacilities** and open the
   [NetFacilities Online Portal](https://netfacilitiessupport.zendesk.com/).
3. Sign in with the organization's authorized support identity. If the organization
   instead uses MyMRI, have the DSC use the [MyMRI client portal](https://mymri.mrisoftware.com/).
4. Search the knowledge base/product documentation using each of the contract terms
   above plus `work order API`, `work order export`, `report scheduler`, and
   `integration guide`.
5. Save links/titles and document versions—not credentials, cookies, tokens, or
   sensitive work-order samples.
6. Look in NetFacilities administration screens for **Integrations**, **API**,
   **Web Services**, **Reports**, **Scheduled Reports**, **Exports**, **Data Feeds**,
   **Users**, **Service Accounts**, and **SSO**. Do not enable or create anything yet.

#### Step 4 — Open one written support case

Classify it as a general product/integration inquiry, not a production outage. Include
the Client ID, product, tenant, business purpose, read-only scope, and the exact
questions below. Do not attach a HAR, cookies, passwords, tokens, or a browser profile.

Suggested case title:

```text
NETfacilities work-order read integration options for our subscription
```

Suggested case body:

```text
We are an authorized NETfacilities customer evaluating a read-only integration from
our internal FastAPI application. The integration would retrieve individual work orders
that our authorized users are already permitted to view. We will not bypass CAPTCHA,
MFA, authentication, tenant boundaries, or role permissions.

Please answer specifically for Client ID [CLIENT ID], tenant [TENANT], product/edition
[EDITION], and our current subscription/order documents:

1. Does our subscription include a supported read API for work orders? If yes, please
   provide the current product-specific documentation, base URL, version, work-order
   lookup identifiers, and a sample sanitized response schema.
2. Are REST, SOAP, reporting/data-feed, scheduled export, or webhook options available?
   For each available option, is it read-only or read/write, real-time or scheduled,
   and included or separately licensed?
3. Is a non-human service/integration account supported? Can it be restricted to
   read-only work-order access and selected facilities? Are shared named-user sessions
   prohibited?
4. What authentication method, scopes/roles, token lifetime/rotation, IP restrictions,
   rate/concurrency limits, audit requirements, support policy, and licensing or
   professional-services fees apply?
5. If no supported API/feed/export meets this need, does MRI permit automated read-only
   access to the same internal endpoints used by the NETfacilities web application when
   the request uses a legitimate authorized session? If permitted, which endpoint or
   method is supported, what usage limits apply, and will MRI provide change notice or
   support? If not permitted, please state that explicitly and recommend the approved
   alternative.

Please distinguish capabilities that exist in the product from capabilities enabled
and licensed for our specific subscription. Please link the controlling documentation
and identify any order-form amendment, partner program, professional services, or
security review required.
```

#### Step 5 — Ask the account/commercial owner in parallel

Send the same case number and questions to the MRI account manager/customer-success
contact. Support can confirm technical capability; the account team must confirm
entitlement, pricing, professional services, and contract amendments. Ask for written
answers and a product-specific order form or quote when an option is separately
licensed.

Partner Connect is relevant only if MRI says this integration must be delivered through
its partner program. Do not enroll or build against a generic MRI partner API without
confirmation that it covers NetFacilities work orders.

#### Step 6 — Require a complete, testable answer

For every option MRI says is available, obtain:

- authoritative documentation URL/document and version;
- tenant/base URL and environment model (production/sandbox);
- supported lookup identifiers;
- supported work-order fields and attachment behavior;
- authentication and credential rotation flow;
- role/scope/facility restrictions;
- rate, concurrency, pagination, payload, and retention limits;
- availability/SLA, versioning, deprecation, and change-notice policy;
- service-account and audit-log behavior;
- licensing SKU, fees, professional services, and approval steps;
- explicit permission or prohibition for automated internal-web-endpoint access.

If the response says only “an API exists,” reply to the same case with the missing
items. Do not close discovery until the answer is subscription-specific.

#### Step 7 — Record the decision without secrets

Add the vendor case number, response date, responder, controlling documents, and each
answer to the project decision record. Mark every answer `Confirmed`, `Unavailable`, or
`Still unknown`. Never paste credentials, secret headers, cookies, tokens, raw HARs, or
customer work-order content.

### B. Optional future capture — secondary request metadata

The HTML, main document metadata, first-party JavaScript, and one secondary response have
resolved the Stage 1 data-flow model. Only collect the following if a secondary dataset
enters implementation scope:

```text
One /WorkOrder/Get... request method/status:
That request's request/response content types:
That request's request field names (no values):
Authentication mechanism names (no values):
CSRF mechanism names (no values):
Cookie names and attributes (no values):
```

No additional work-order response body is needed. Do not paste personal data, cookie
values, request headers, or secondary JSON contents.

### Go/no-go decision after the capture

1. If `BrowserContext.request` can retrieve the same populated HTML -> implement the
   local proof of concept using semantic HTML parsing.
2. If context requests fail but page navigation succeeds -> keep document retrieval in
   a Playwright page and parse the response/page content without copying cookies.
3. Add individual secondary JSON calls only when a required application field is absent
   from the core HTML.
4. If the owner does not accept the operational/contractual risk of an unsupported
   integration -> stop automation and retain the current manual/CSV workflow.

## Sources

### Repository and canonical project memory

- `docs/current-state.md`
- `docs/endpoint-map.md`
- `docs/open-work.md`
- Obsidian mirror under
  `4. Notes/Repository-Docs/inventory-app-git/reviews/`

### Vendor and platform documentation

- [MRI NetFacilities product page](https://www.mrisoftware.com/products/netfacilities/)
- [MRI support directory](https://www.mrisoftware.com/contact-support/)
- [NetFacilities support portal](https://netfacilitiessupport.zendesk.com/)
- [MRI Global Client Support Policy](https://www.mrisoftware.com/wp-content/uploads/2022/04/MRI-Global-Client-Support-Policy-1.pdf)
- [MRI Partner Connect](https://partners.mrisoftware.com/)
- [Playwright authentication](https://playwright.dev/python/docs/auth)
- [Playwright network handling](https://playwright.dev/python/docs/network)
- [Playwright persistent contexts](https://playwright.dev/python/docs/api/class-browsertype)
- [Playwright context request client](https://playwright.dev/python/docs/api/class-apirequestcontext)
- [HTTPX clients](https://www.python-httpx.org/advanced/clients/)
- [Render free services](https://render.com/docs/free)
- [Render compute plans](https://render.com/docs/compute-plans)
- [Render persistent disks](https://render.com/docs/disks)
