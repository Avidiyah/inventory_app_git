# Feature Implementation Report

**Current status:** The original three feature areas are implemented: barcode scanning, authentication/roles, and website deployment. This document is now an as-built report rather than a pre-implementation estimate.

---

## TL;DR

| Feature | Status | Current implementation |
|---|---|---|
| Barcode scan as item lookup | Shipped | Upload decode with backend `pyzbar`; live decode with vendored `@zxing/browser` |
| Passwords and roles | Shipped | Server-side sessions, HttpOnly cookie, scrypt password hashes, four-role hierarchy |
| Hosted website deployment | Shipped | Docker web service on Render plus managed Postgres via `render.yaml` |

---

## 1. Barcode Scanning

Barcode scanning exists on both the Transaction page and Saved Items page.

### Upload Mode

The upload/still-photo path is server decoded:

1. User chooses or captures an image with the file input.
2. Frontend posts the file to `POST /barcodes/decode`.
3. Backend opens bytes with Pillow and decodes supported barcodes with `pyzbar`.
4. Returned text is resolved through `GET /items/{barcode}`.
5. The caller decides what to do with the matched item.

Supported upload formats are UPC-A, UPC-E, EAN-13, EAN-8, and Code128.

The image is decoded in memory and never persisted. A readable image with no supported barcode returns `200` and an empty list; unreadable image bytes return `400`.

### Live Mode

The live camera path is client decoded:

1. User taps Scan.
2. Browser opens `getUserMedia` from that user gesture.
3. `@zxing/browser` decodes frames from the video stream.
4. `FrameDebouncer` accepts a value only after it appears in at least 5 of the last 10 decoded frames.
5. The accepted text calls `GET /items/{barcode}` directly; live mode does not call `/barcodes/decode`.

The camera is stopped on page leave, hidden tab, reset/cancel flows, and after accepted scans where the UI moves into a form. Torch is shown only when the video track exposes `torch` capability.

### Why This Shape

- Backend upload decode keeps the still-photo path testable and independent of browser barcode APIs.
- Live mode avoids the reliability issues of single still photos on phones.
- ZXing is vendored rather than loaded from a CDN to keep the app single-origin and reproducible.
- Upload mode remains as fallback for browsers or permissions states where live camera is unavailable.

---

## 2. Authentication And Roles

Auth is implemented with server-side sessions, not JWTs.

### Backend

Current auth pieces:

- `POST /auth/login`
- `POST /auth/logout`
- `GET /auth/me`
- `app/auth_deps.py`
- `app/services/auth.py`
- `users.password_hash`
- `users.role`
- `sessions` table

Password hashes use standard-library `hashlib.scrypt`, stored in a self-describing format:

```text
scrypt$n$r$p$salt_hex$hash_hex
```

Session tokens are opaque random strings stored in the `sessions` table and carried in an HttpOnly `session` cookie. The session has a sliding idle timeout.

### Roles

Role hierarchy:

```text
owner > admin > supervisor > technician
```

Route gates:

- `get_current_user` for any authenticated route.
- `require_min_role(...)` for minimum-rank gates.
- `roles.can_manage(actor, target)` for user-management actions.

Owner is bootstrap-only via `backend/scripts/create_owner.py`. API user management requires the actor to strictly outrank the target role.

### Frontend

The frontend has:

- Login screen.
- Logout button.
- Global 401 handler.
- Role-aware navigation visibility.
- Role-aware item/user action controls.

This frontend gating is only UX. The backend remains authoritative.

---

## 3. Hosted Website Deployment

Deployment is defined by `render.yaml` and `backend/Dockerfile`.

Current production shape:

- One Docker web service: FastAPI serves API and static SPA.
- One managed Render Postgres database.
- `DATABASE_URL` injected by Render.
- `COOKIE_SECURE=true` for HTTPS cookies.
- `SQL_ECHO=false` in production.
- `entrypoint.sh` runs `alembic upgrade head` before Uvicorn starts.

Docker installs `libzbar0` so `pyzbar` works in the Linux container.

See `docs/deploy-render.md` for the operational deployment flow and one-time data import.

---

## Follow-On Work

The original feature report is no longer the roadmap. Practical next improvements are:

- Add CI for lint/test gates.
- Add stronger frontend test coverage.
- Document backup/restore and monitoring expectations for production data.
- Decide whether Render free tier is acceptable for the actual operational need.
- Consider soft deletes for items/users instead of permanent deletion.
- Consider partial notes merge behavior if full replacement becomes risky.

