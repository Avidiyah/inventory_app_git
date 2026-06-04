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

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.database import test_connection
from app.routers import items, transactions, users

app = FastAPI(title="Inventory Management API")

# Routers register their own prefixes (`/items`, `/transactions`,
# `/users`); ordering here is irrelevant.
app.include_router(items.router)
app.include_router(transactions.router)
app.include_router(users.router)

# The frontend is a static SPA served from `backend/static/`.
# `index.html` is served at `/`; its `<script type="module">` and
# CSS pull the rest from `/static/...`.
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def read_root():
    """Serve the SPA shell."""
    return FileResponse("static/index.html")


@app.get("/db-test")
def db_test():
    """Liveness probe for the database connection. Returns the
    current database name and connected user so deploys can
    confirm they are pointed at the right environment."""
    database_name, user_name = test_connection()

    return {
        "status": "ok",
        "database": database_name,
        "user": user_name,
    }