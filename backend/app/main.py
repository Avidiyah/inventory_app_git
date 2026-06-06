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

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.auth_deps import require_min_role
from starlette.types import Scope
from app.database import test_connection
from app.domain import roles
from app.routers import auth, barcodes, items, transactions, users

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
app.include_router(transactions.router)
app.include_router(users.router)

# The frontend is a static SPA served from `backend/static/`.
# `index.html` is served at `/`; its `<script type="module">` and
# CSS pull the rest from `/static/...`.
app.mount("/static", NoCacheStaticFiles(directory="static"), name="static")


@app.get("/")
def read_root():
    """Serve the SPA shell."""
    return FileResponse(
        "static/index.html", headers={"Cache-Control": "no-cache"}
    )


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