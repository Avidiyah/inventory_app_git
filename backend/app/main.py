"""FastAPI application entrypoint -- the composition root.

Layer: app entry. This file does three things and nothing else:

1. Instantiate the `FastAPI` app.
2. Mount the three resource routers (`items`, `transactions`,
   `users`) and the static-files directory that serves the
   single-page frontend at `/`.
3. Expose a `/db-test` probe used by deployment scripts to confirm
   the database connection is reachable.

Business logic lives in `app.services`, validation in
`app.schemas`, rules in `app.domain`. Nothing in this file should
ever grow beyond wiring.
"""

from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse

from app.auth_deps import require_min_role
from starlette.types import Scope
from app.database import test_connection
from app.domain import roles
from app.routers import auth, barcodes, items, mass_stages, transactions, users

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


@app.middleware("http")
async def add_permissions_policy(request, call_next):
    """Tell browsers the camera is usable on this origin and nowhere
    else (no cross-origin iframes). Required by the live barcode
    scanner; harmless for every other route."""
    response = await call_next(request)
    response.headers["Permissions-Policy"] = "camera=(self)"
    return response


# Routers register their own prefixes (`/auth`, `/items`,
# `/transactions`, `/users`); ordering here is irrelevant.
app.include_router(auth.router)
app.include_router(barcodes.router)
app.include_router(items.router)
app.include_router(mass_stages.router)
app.include_router(transactions.router)
app.include_router(users.router)

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
# frozen DOM contract (docs/interfaces.md) is unchanged because the browser
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