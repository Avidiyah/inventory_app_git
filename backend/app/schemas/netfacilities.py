"""Secret-safe HTTP contracts for local NetFacilities enrichment."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


NetFacilitiesJobState = Literal[
    "queued",
    "running",
    "completed",
    "authentication_required",
    "timed_out",
    "failed",
    "cancelled",
]


class NetFacilitiesEnrichmentCounts(BaseModel):
    """Approved aggregate results; source field values are never returned."""

    candidates: int = 0
    requests_attempted: int = 0
    fetched: int = 0
    descriptions_updated: int = 0
    priorities_updated: int = 0
    unchanged: int = 0
    invalid_numbers: int = 0
    not_found: int = 0
    permission_denied: int = 0
    authentication_required: int = 0
    other_failures: int = 0
    remaining: int = 0
    timed_out: bool = False


class NetFacilitiesEnrichmentJob(BaseModel):
    job_id: UUID
    state: NetFacilitiesJobState
    started_at: datetime | None = None
    finished_at: datetime | None = None
    current_work_order_number: str | None = None
    failure: Literal[
        "authentication_required",
        "unavailable",
        "unexpected_failure",
        "cancelled",
    ] | None = None
    counts: NetFacilitiesEnrichmentCounts | None = None


class NetFacilitiesAuthenticationAttempt(BaseModel):
    """Process-local headed sign-in state without browser or profile details."""

    attempt_id: UUID
    state: Literal[
        "starting",
        "awaiting_confirmation",
        "confirming",
        "authenticated",
        "failed",
        "cancelled",
        "timed_out",
    ]
    started_at: datetime
    finished_at: datetime | None = None
    failure: Literal["unavailable", "cancelled", "timed_out"] | None = None


class NetFacilitiesCapability(BaseModel):
    """Capability state without protected paths or browser contents."""

    available: bool
    interactive_authentication_available: bool = False
    state: Literal[
        "unavailable",
        "not_authenticated",
        "ready",
        "running",
        "expired",
        "authenticating",
    ]
    message: str
    latest_job: NetFacilitiesEnrichmentJob | None = None
    latest_authentication: NetFacilitiesAuthenticationAttempt | None = None
