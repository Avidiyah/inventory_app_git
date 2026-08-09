"""FastAPI application entrypoint -- the composition root.

Layer: app entry. This file does three things and nothing else:

1. Instantiate the `FastAPI` app.
2. Mount the three resource routers (`items`, `transactions`,
   `users`) and the static-files directory that serves the
   single-page frontend at `/`.
3. Expose the two database probes: `/healthz`, the unauthenticated
   liveness check the deployment platform polls, and `/db-test`, the
   Admin-gated probe deployment scripts use to confirm *which*
   database is connected.

Business logic lives in `app.services`, validation in
`app.schemas`, rules in `app.domain`. Nothing in this file should
ever grow beyond wiring.
"""

from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from sqlalchemy.exc import SQLAlchemyError

from app.auth_deps import COOKIE_SECURE, require_min_role
from starlette.types import Scope
from app.database import check_connection, test_connection
from app.domain import roles
from app.routers import (
    auth,
    barcodes,
    items,
    mass_stages,
    tools,
    transactions,
    user_requests,
    users,
    work_orders,
)

class NoCacheStaticFiles(StaticFiles):
    """StaticFiles that tells browsers to revalidate every asset.

    The SPA has no build step or content hashing, so a cached old
    `main.js` renders a completely blank page (both screens stay hidden
    until the fresh JS runs). `no-cache` forces a conditional request,
    which is cheap (304s) and eliminates that failure mode on phones
    where a hard reload is awkward.
    """

    async def get_response(self, path: str, scope: Scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


app = FastAPI(title="Inventory Management API")


# Content Security Policy. Verified against the whole SPA before being
# enabled: the shell has no inline `<script>` (both tags in
# `shell-tail.html` use `src`), no `on*` handlers, no `<style>` blocks, no
# inline `style=` attributes, no `eval`, and no external resource loads --
# so `'self'` is sufficient everywhere and nothing needs an unsafe- escape.
#
# `blob:`/`data:` on img/media cover canvas frame grabs. The live scanner
# is unaffected either way: it assigns a MediaStream to `video.srcObject`
# (see `static/scan/barcode-decoder.js`), which CSP does not govern.
#
# Known exception: `static/scan-test.html` (a standalone dev harness, not
# part of `SHELL_PARTS`) does use a `<style>` block and one inline
# `style=`, so those will be blocked there. The app itself is unaffected.
CONTENT_SECURITY_POLICY = "; ".join((
    "default-src 'self'",
    "img-src 'self' data: blob:",
    "media-src 'self' blob:",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
))


@app.middleware("http")
async def add_security_headers(request, call_next):
    """Attach the app's response security headers.

    `Permissions-Policy` tells browsers the camera is usable on this
    origin and nowhere else (no cross-origin iframes) -- required by the
    live barcode scanner, harmless for every other route.

    The rest are defence-in-depth and change no response body: a strict
    CSP, MIME-sniffing off, referrer trimmed to the origin, and framing
    denied. HSTS is gated on `COOKIE_SECURE` -- the same signal the
    session cookie already uses to mean "this deployment is HTTPS" -- so
    local http://localhost development is never sent an upgrade
    directive it cannot honour.
    """
    response = await call_next(request)
    response.headers["Permissions-Policy"] = "camera=(self)"
    response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Frame-Options"] = "DENY"
    if COOKIE_SECURE:
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
    return response


# Routers register their own prefixes (`/auth`, `/items`,
# `/transactions`, `/users`); ordering here is irrelevant.
app.include_router(auth.router)
app.include_router(barcodes.router)
app.include_router(items.router)
app.include_router(mass_stages.router)
app.include_router(tools.router)
app.include_router(transactions.router)
app.include_router(user_requests.router)
app.include_router(users.router)
app.include_router(work_orders.router)

# The frontend is a static SPA served from `backend/static/`.
# The shell document is assembled at request time from per-page
# fragments (see `SHELL_PARTS`); its `<script type="module">` and
# CSS pull the rest from `/static/...`.
app.mount("/static", NoCacheStaticFiles(directory="static"), name="static")

# `static/` resolved from this file (not the CWD) so assembly works
# regardless of where the process is launched.
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

# The SPA shell, split into per-page fragments so each page's markup can
# be edited in isolation. Concatenated in this order at request time, the
# result is byte-identical to the former monolithic `index.html` -- the
# frontend DOM contract is unchanged because the browser
# still receives one complete document with every page present on boot.
# Fragments are migrated out of the shell one page at a time; pages not yet
# extracted still live inline in `shell-head.html` / `shell-tail.html`.
SHELL_PARTS = (
    "shell-head.html",          # head, login, header/nav, <main>
    "pages/create-item.html",
    "pages/saved-items.html",
    "pages/create-user.html",
    "pages/saved-users.html",
    "pages/transaction.html",
    "pages/mass-stage.html",
    "pages/work-orders.html",
    "pages/user-requests.html",
    "pages/admin-review.html",
    "pages/tools.html",
    "pages/history.html",
    "shell-tail.html",          # </main>, scan-confirm overlay, scripts, </body></html>
)


def _assemble_index() -> bytes:
    """Concatenate the shell fragments into the full SPA document.

    Reads bytes (not text) so CRLF line endings survive verbatim, and
    reads fresh on every request: `uvicorn --reload` does not restart on
    `.html` edits, so caching here would serve a stale shell after a
    fragment is edited. The cost is a handful of small file reads.
    """
    return b"".join((STATIC_DIR / part).read_bytes() for part in SHELL_PARTS)


@app.get("/")
def read_root():
    """Serve the SPA shell, assembled from per-page fragments."""
    return HTMLResponse(_assemble_index(), headers={"Cache-Control": "no-cache"})


@app.get("/healthz")
def healthz():
    """Unauthenticated liveness probe for the deployment platform.

    `render.yaml` points `healthCheckPath` here. It previously pointed at
    `/`, which assembles the SPA shell from disk and never touches
    Postgres -- so the platform reported the service healthy while the
    database was completely unreachable. This route actually runs a query.

    Deliberately reports **no** database detail: not the name, user, or
    version, and not the driver's error text (psycopg's `OperationalError`
    routinely carries the host, port, and database name from the DSN).
    `/db-test` is the Admin-gated route that reports those.

    `SQLAlchemyError` rather than a bare `except`, so a genuine bug in this
    handler still surfaces as a 500 instead of being laundered into a
    plausible-looking 503.
    """
    try:
        check_connection()
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="Database unavailable.")

    return {"status": "ok"}


@app.get("/db-test", dependencies=[Depends(require_min_role(roles.ROLE_ADMIN))])
def db_test():
    """Liveness probe for the database connection. Restricted to
    Owner/Admin. Returns the current database name and connected user so
    deploys can confirm they are pointed at the right environment."""
    database_name, user_name = test_connection()

    return {
        "status": "ok",
        "database": database_name,
        "user": user_name,
    }
