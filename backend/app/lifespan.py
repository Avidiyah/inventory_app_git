"""Composition of application-wide background task lifetimes."""

from __future__ import annotations

import contextlib

from app.services.netfacilities_auth import (
    authentication_coordinator as netfacilities_authentication,
)
from app.services.netfacilities_jobs import coordinator as netfacilities_jobs
from app.services.realtime import start_dispatch, stop_dispatch


@contextlib.asynccontextmanager
async def lifespan(app):
    """Start realtime dispatch and close every owned task on shutdown."""

    start_dispatch()
    try:
        yield
    finally:
        await netfacilities_authentication.shutdown()
        await netfacilities_jobs.shutdown()
        await stop_dispatch()
