"""FastAPI application entrypoint -- the composition root.

Layer: app entry. This file does four things and nothing else:

1. Configure logging and instantiate the `FastAPI` app -- including whether
   its built-in docs endpoints exist at all, which depends on the
   environment (see `_doc_urls`).
2. Mount the three resource routers (`items`, `transactions`,
   `users`) and the static-files directory that serves the
   single-page frontend at `/`.
3. Expose the two database probes: `/healthz`, the unauthenticated
   liveness check the deployment platform polls, and `/db-test`, the
   Admin-gated probe deployment scripts use to confirm *which*
   database is connected.
4. Wrap every request in the middleware pair: the security headers and
   the logging/request-id scope.

Business logic lives in `app.services`, validation in
`app.schemas`, rules in `app.domain`. Nothing in this file should
ever grow beyond wiring.
"""

import logging
import time
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.auth_deps import COOKIE_SECURE, SESSION_COOKIE, require_min_role
from starlette.types import Scope
from app.database import check_connection, test_connection
from app.domain import rate_limit as rate_limit_policy
from app.domain import roles
from app.logging_config import (
    configure_logging,
    new_request_context,
    request_context,
)
from app.services import rate_limit as rate_limit_service
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


# Before the app, so anything logged during import or startup is already
# formatted and routed. Idempotent -- the test suite imports this module
# too. See `app/logging_config.py`.
configure_logging()

logger = logging.getLogger(__name__)

def _doc_urls(*, production: bool) -> dict:
    """URLs for FastAPI's built-in docs, or `None` for each in production.

    `None` **un-mounts** the route rather than hiding it, so there is nothing
    left to authenticate against. `/docs/oauth2-redirect` is tied to `docs_url`
    and disappears with it.

    Of the three, `/openapi.json` is the one that matters. It is 113 KB of
    plain JSON describing all 73 operations, 63 request/response models with
    every field and validation rule, and -- since C1 -- the role each gated
    route requires. `/docs` and `/redoc` are closed alongside it for tidiness
    rather than for risk: A4's CSP is `default-src 'self'` and FastAPI loads
    Swagger UI and ReDoc from `cdn.jsdelivr.net`, so both pages have rendered
    blank everywhere, local included, since A4 shipped. See the Tier 2 note in
    `docs/api-hardening-checklist.md`.

    Gated on `COOKIE_SECURE` -- the flag A4 already established as "this
    deployment is HTTPS/production" when it used it for HSTS -- rather than a
    second, differently-named production flag, which would give the codebase
    two answers to one question. There is deliberately no override: turning
    these back on in production takes an edit and a deploy, so nothing can be
    switched on and forgotten.
    """
    if production:
        return {"docs_url": None, "redoc_url": None, "openapi_url": None}
    return {
        "docs_url": "/docs",
        "redoc_url": "/redoc",
        "openapi_url": "/openapi.json",
    }


app = FastAPI(
    title="Inventory Management API",
    **_doc_urls(production=COOKIE_SECURE),
)


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
async def rate_limit(request, call_next):
    """Refuse more than `MAX_REQUESTS` API requests per second per caller.

    **Registered before `add_security_headers` on purpose**, which makes
    it the *innermost* of the three: Starlette's `add_middleware` inserts
    at the front of the list and the front is outermost, so defining this
    first leaves both of the others wrapping it. That is what this needs
    -- a 429 raised here still passes back out through
    `add_security_headers` (so it carries the CSP and HSTS headers every
    other response carries) and through `log_request` (so it gets an
    `X-Request-ID` and appears in the log stream like any other request).
    A limiter whose rejections were invisible to the logs would be the
    hardest possible thing to diagnose.

    Exempt paths are skipped before the counter is touched, so page loads
    neither consume the budget nor can be refused; see
    `domain.rate_limit.is_exempt`.

    The response is built directly rather than by raising `HTTPException`
    because exception handlers are installed around the router, inside
    this middleware -- an exception raised here would escape as a 500.
    """
    path = request.url.path
    if rate_limit_policy.is_exempt(path):
        return await call_next(request)

    # `request.client` is already the real client rather than Render's
    # proxy: `entrypoint.sh` runs uvicorn with `--proxy-headers`, which
    # resolves X-Forwarded-For before the app sees it. Parsing that
    # header here instead is the usual way a spoofable address sneaks in
    # (see `routers/auth.py:_client_ip`, which relies on the same thing).
    client = request.client
    key = rate_limit_service.caller_key(
        request.cookies.get(SESSION_COOKIE),
        client.host if client and client.host else "unknown",
    )

    retry_after = rate_limit_service.check_and_record(key, time.monotonic())
    if retry_after is not None:
        logger.warning(
            "request.rate_limited",
            extra={"fields": {
                "method": request.method,
                "path": path,
                "retry_after": retry_after,
            }},
        )
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many requests. Please slow down."},
            headers={"Retry-After": str(retry_after)},
        )

    return await call_next(request)


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


@app.middleware("http")
async def log_request(request, call_next):
    """Open a logging scope for the request and log its completion.

    **Registered after `add_security_headers` on purpose.** Starlette's
    `add_middleware` inserts at the front of the list and the front of
    the list is outermost, so the last one defined here wraps everything
    -- which is what this needs: the request id must exist before any
    other code runs, and the duration must cover the whole stack.

    The request id is echoed as `X-Request-ID` so a user reporting "it
    broke around 2:15" can be matched to an exact line. It is always
    generated here and never read from the incoming request: trusting a
    caller-supplied value would let an anonymous client collide ids and
    poison correlation.

    Only the path is logged, never `request.url.query` -- a query string
    is caller-controlled and is exactly the kind of place a token ends up
    by accident.

    Unhandled exceptions are logged with the request's context and
    re-raised. Deliberately **without** `exc_info`: uvicorn logs the
    traceback for the same exception a moment later (it sits outside all
    application middleware), so including it here would print every
    production traceback twice. The exception *type* is recorded because
    that is the part uvicorn's line does not correlate to a request id;
    its message is not, since a driver error routinely quotes the DSN.
    """
    context = new_request_context(uuid.uuid4().hex[:12])
    token = request_context.set(context)
    started = time.perf_counter()

    def elapsed_ms() -> int:
        return round((time.perf_counter() - started) * 1000)

    try:
        try:
            response = await call_next(request)
        except Exception as exc:
            logger.error(
                "request.error",
                extra={"fields": {
                    "method": request.method,
                    "path": request.url.path,
                    "exc_type": type(exc).__name__,
                    "ms": elapsed_ms(),
                }},
            )
            raise

        response.headers["X-Request-ID"] = context["req"]
        logger.info(
            "request",
            extra={"fields": {
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "ms": elapsed_ms(),
            }},
        )
        return response
    finally:
        request_context.reset(token)


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

    The exception is **logged with its traceback** before being discarded.
    That is the whole point of N1 here: withholding the detail from an
    anonymous caller is correct, but until this line existed a database
    outage produced no diagnosable artifact anywhere in the system. The
    log is server-side and the response body is unchanged.
    """
    try:
        check_connection()
    except SQLAlchemyError:
        logger.error("healthz.db_unreachable", exc_info=True)
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
