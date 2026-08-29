"""Composition of application-wide background task lifetimes."""

from __future__ import annotations

import contextlib

from app.services.netfacilities_jobs import coordinator as netfacilities_jobs
from app.services.realtime import start_dispatch, stop_dispatch


@contextlib.asynccontextmanager
async def lifespan(app):
    """Start realtime dispatch and close every owned task on shutdown."""

    start_dispatch()
    try:
        yield
    finally:
        # Cancel any in-flight batch so its reconnected Steel session is
        # released rather than left to the vendor's own timeout.
        await netfacilities_jobs.shutdown()
        await stop_dispatch()
