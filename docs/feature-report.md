# Feature Implementation Report

**Date:** 2026-06-04
**Scope:** Three requested features — (1) barcode scanning as an item-search filter, (2) password protection + roles, (3) hosting the app as a website.

This report is grounded in the current codebase: a single FastAPI process (`backend/app/main.py`) that serves a vanilla-JS single-page app from `backend/static/`, with a `routers → services → models` layering, Pydantic schemas, Alembic migrations, and PostgreSQL via psycopg3. There is currently **no authentication** (confirmed in `docs/spec.md` "Known Gaps") and the app runs locally under uvicorn.

---

## TL;DR

| Feature | Effort | Layers touched | Main risk |
|---|---|---|---|
| 1. Barcode scan → search filter | **Small–Medium** | Frontend mostly; backend already supports it | Browser/camera compatibility; needs HTTPS |
| 2. Passwords + roles | **Medium–Large** | Every layer (DB, models, services, routers, frontend) | Security correctness; migration of existing users |
| 3. Host as a website | **Medium** | Infra/config, not much code | TLS, secrets, prod hardening |

**Recommended order:** 3 → 2 → 1. Hosting (with HTTPS) is a prerequisite for the camera (browsers only allow camera access over `https://` or `localhost`), and you do not want to expose the app publicly *before* auth is in place. Barcode scanning is the smallest piece and rides on top.

---

## Feature 1 — Barcode scan as a search filter

> **✅ Implemented (as-built note).** This shipped, but with a different decode strategy than the options weighed below. Decoding is done on the **backend** with `pyzbar` (native `zbar`) via `POST /barcodes/decode`, **not** with a vendored JS library or the `BarcodeDetector` API. Surface is the **Transaction page only**: a file input with `accept="image/*" capture="environment"` (phone camera + desktop upload) → on a single match the items table filters to that row and the Stock/Dispense form auto-opens; unknown barcodes offer an Owner/Admin "Create Item" shortcut; multiple barcodes show a chooser; failures keep the manual fallback. Formats: UPC-A, UPC-E, EAN-13, EAN-8, Code128. New Python deps: `pyzbar`, `Pillow`, `python-multipart` (see `backend/requirements.txt`). No schema/migration change. See `spec.md` decisions log and `interfaces.md` addendum L. The original `zxing-cpp` plan was dropped (no prebuilt wheel for this Python/OS, needs a C++ toolchain). The analysis below is retained for historical context.

### What you already have
- `items.barcode` is a unique, indexed-by-constraint column (`backend/app/models.py:45`).
- A working lookup endpoint already exists: `GET /items/{barcode}` → `items_service.get_item_by_barcode` (`backend/app/routers/items.py:49`).
- The frontend HTTP client already has `apiGetItemByBarcode(barcode)` (`backend/static/api.js:61`).

So the database and most of the API are **already done**. This feature is mostly a frontend capture-and-decode problem plus a small UI addition on the Transaction page.

### What needs to be built

**Frontend (the bulk of the work):**
1. **Camera capture / image upload UI.** Add a "Scan barcode" button + `<input type="file" accept="image/*" capture="environment">` to the Transaction page (`backend/static/index.html`, the `#txn-items-section`). The `capture` attribute makes phones open the camera directly; on desktop it falls back to a file picker.
2. **Barcode decoding.** Two viable paths:
   - **Native `BarcodeDetector` API** — zero dependencies, built into Chrome/Edge/Android. **Not** available in Safari/iOS, so it can't stand alone.
   - **A JS decoding library** — e.g. [`@zxing/library`](https://github.com/zxing-js/library) or [`html5-qrcode`](https://github.com/mebjas/html5-qrcode). Works across browsers, handles both live camera stream and a still uploaded image. Recommended as the primary, with `BarcodeDetector` as a fast path where present.
   - This adds a static JS dependency. Since the app currently uses no build step (plain ES modules), the cleanest fit is to vendor the library file into `backend/static/vendor/` and import it, keeping the no-bundler setup.
3. **Wire decode → filter.** On a successful decode, set the value into a search box and call the existing `apiGetItemByBarcode`, then scroll/highlight the matching row (or open the stock/dispense form directly). Today the Transaction page lists *all* items via `loadTxnItems()` (`backend/static/views/transactions.js:41`) with no filter, so a small filter input + "no match found" message is also needed.

**Backend:** Essentially nothing new required for exact-barcode match. *Optional* enhancement: a partial-match search endpoint (`GET /items/?q=...`) if you want type-ahead or fuzzy barcode/name search — currently `list_items` returns everything unfiltered (`backend/app/services/items.py:46`).

### Constraints & gotchas
- **HTTPS is mandatory** for `getUserMedia()` (live camera). It works on `localhost` for dev, but any real device testing needs Feature 3 first.
- **Decoding accuracy** varies with camera quality, lighting, and symbology (UPC/EAN/Code128/QR). Plan for a manual-entry fallback (the existing text box) — always.
- **Permissions UX:** the browser will prompt for camera access; handle the denied/no-camera case gracefully.

### Effort
~1–3 days of frontend work, most of it spent on camera UX and cross-browser decode testing. No schema change.

---

## Feature 2 — Password protection & roles

This is the largest of the three because it cuts through **every layer** and the app was explicitly built without auth. The `User` model today has only `username` and `created_at` (`backend/app/models.py:23`), and no endpoint checks identity.

### Database & models
- Add columns to `users`: `password_hash` (Text, not null), `role` (Text, not null, default e.g. `"operator"`). Possibly `is_active`.
- Write a new **Alembic migration** (consistent with the existing three under `backend/alembic/versions/`). Existing rows need a backfill strategy — either set a temporary password and force reset, or treat pre-existing users as login-disabled until a password is set.
- Decide the role set. A simple, defensible start: **`admin`** (manage users/items, delete) vs **`operator`** (stock/dispense, read). The current destructive operations (delete item/user) are the obvious things to gate behind `admin`.

### Backend
- Add a password-hashing dependency — **`passlib[bcrypt]`** or **`argon2-cffi`**. (Currently only fastapi, uvicorn, starlette, sqlalchemy, alembic, psycopg are installed; this is a new dependency.)
- **Session strategy.** Two clean options:
  - **Cookie sessions** via Starlette's `SessionMiddleware` (you already have `starlette` and `itsdangerous` is its only need) — simplest for a server-rendered SPA on one origin.
  - **JWT bearer tokens** via `python-jose` — more work, better if you later split frontend/backend or add mobile clients.
  - Recommendation: **cookie sessions** given the co-located single-origin design.
- New endpoints / service module (`app/services/auth.py`, `app/routers/auth.py`): `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`. User creation must now hash passwords (update `users_service.create_user`).
- **Authorization dependencies:** a `get_current_user` FastAPI dependency and a `require_role("admin")` dependency, then apply them to the existing routers. This is the security-critical part — every mutating route (`create_item`, `delete_item`, `create_user`, `delete_user`, `create_transaction`, notes update) must be protected. Currently they are all open.
- The existing `transactions.user_id` already records *who* did a transaction; with auth you can derive that from the logged-in user instead of a dropdown, tightening the "user optional in backend" gap noted in the spec.

### Frontend
- A **login page/screen** before the SPA loads; store the session (cookie is automatic) and redirect.
- `api.js` needs to send credentials (`fetch(..., { credentials: "include" })`) and handle **401/403** globally (redirect to login / show "not permitted").
- **Role-aware UI:** hide or disable admin-only controls (delete buttons, Create User page) for operators. This is UX only — the backend checks are the real enforcement.

### Constraints & gotchas
- **Never store plaintext passwords**; use a slow hash (bcrypt/argon2). Enforce a password policy and a change-password flow.
- **Bootstrapping the first admin:** you need a seed script or a one-time CLI command to create the initial admin, since the UI for creating users will itself be admin-gated.
- Add **rate limiting / lockout** on login to resist brute force (can be basic to start).
- Secrets (session signing key, JWT secret) must come from env/config, not code.

### Effort
~4–7 days. Backend auth plumbing and the migration are the core; frontend login + role gating and careful testing of every protected route add up.

---

## Feature 3 — Host as a website

The app is already a standard ASGI web app, so "make it a website" is mostly **deployment and hardening**, not a rewrite. `main.py` serves both API and the SPA from one process — that's deployment-friendly.

### What's required
1. **A host.** Pick one:
   - **PaaS (recommended for speed):** Render, Railway, or Fly.io — they give you a managed container, a public HTTPS URL/TLS cert, and a managed PostgreSQL add-on with minimal ops. Fastest path to "it's a website."
   - **VPS (more control):** a Linux box (e.g. DigitalOcean/Hetzner) running the app behind **nginx** as a reverse proxy with **Let's Encrypt** TLS, plus a managed or self-run Postgres.
2. **Production ASGI serving.** Run uvicorn (optionally under gunicorn with uvicorn workers) instead of the dev invocation. Add a startup command / Dockerfile.
3. **Managed PostgreSQL.** Today `DATABASE_URL` points at a local DB (`backend/.env`). Production needs its own database and connection string, with migrations (`alembic upgrade head`) run on deploy.
4. **Configuration & secrets via environment**, not files in the repo. The `.env` is fine for dev but production secrets (DB URL, session/JWT key) belong in the host's secret store.
5. **Production hardening (small but important code/config changes):**
   - Turn off SQL echo — `echo=True` is currently hardcoded (`backend/app/database.py:29`) and the spec flags it as a production concern. Make it env-driven.
   - Set `FastAPI(...)` docs exposure as desired; consider disabling `/docs` publicly.
   - Add **HTTPS** (gives you the secure context Feature 1's camera needs).
   - CORS: not needed while frontend and API share one origin (current design); only required if you ever split them.
   - A real `requirements.txt`/lockfile — there isn't one committed today, which deployment will need.

### Constraints & gotchas
- **Do not deploy publicly before Feature 2.** As the spec states, anyone with network access can currently modify or delete anything. Public hosting without auth = open inventory database.
- **Database backups** become your responsibility once it's the system of record.
- **HTTPS/TLS** is the linchpin that connects all three features (security + camera).

### Effort
~2–4 days on a PaaS (mostly config, a Dockerfile/start command, env wiring, and a deploy migration step). More on a self-managed VPS due to nginx/TLS/Postgres setup.

---

## Dependencies between the features

```
Feature 3 (HTTPS hosting)  ──► enables ──►  Feature 1 (camera needs secure context)
Feature 2 (auth)           ──► must precede ──►  public exposure from Feature 3
```

- Build **auth (2)** and **hosting (3)** together, deploy privately/behind a login.
- Layer **barcode scanning (1)** on last — it's self-contained and benefits from the HTTPS that hosting provides.

## New dependencies introduced
- Feature 1: a JS barcode-decoding library (vendored into `static/`), no Python deps.
- Feature 2: a password hashing library (`passlib[bcrypt]` or `argon2-cffi`); optionally `python-jose` if you choose JWT.
- Feature 3: production server config, a `requirements.txt`/lockfile, and a host + managed Postgres. Possibly a `Dockerfile`.

## Rough total
On a PaaS with cookie-session auth and a vendored decode library, a realistic combined estimate is **~2–3 weeks** of focused work including testing, with auth being the dominant slice.
