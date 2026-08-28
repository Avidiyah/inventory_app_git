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
NetFacilitiesJobSource = Literal["live_session", "saved_state", "cloud_session"]


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
    # Which session read the source: the operator's open window or the saved
    # storage-state file. Lets the card say which one it is using.
    source: NetFacilitiesJobSource | None = None


class NetFacilitiesAuthenticationAttempt(BaseModel):
    """Process-local headed sign-in / live-session state.

    ``last_download_filename`` is a bare filename -- never a directory or path;
    the operator already knows where their Downloads folder is.
    """

    attempt_id: UUID
    state: Literal[
        "starting",
        "awaiting_confirmation",
        "confirming",
        "signed_in",
        "closed",
        "failed",
        "cancelled",
        "timed_out",
    ]
    started_at: datetime
    finished_at: datetime | None = None
    failure: Literal["unavailable", "cancelled", "timed_out"] | None = None
    signed_in_at: datetime | None = None
    last_download_filename: str | None = None
    last_download_at: datetime | None = None


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
        "signed_in",
    ]
    message: str
    latest_job: NetFacilitiesEnrichmentJob | None = None
    latest_authentication: NetFacilitiesAuthenticationAttempt | None = None


NetFacilitiesCloudSessionState = Literal[
    "starting",
    "awaiting_sign_in",
    "signed_in",
    "closed",
    "failed",
    "cancelled",
    "timed_out",
]


class NetFacilitiesCloudSessionStatus(BaseModel):
    """Per-user cloud-auth ceremony state (spec D7). Never carries
    `storage_state` or `steel_profile_id` (spec D9)."""

    attempt_id: UUID
    state: NetFacilitiesCloudSessionState
    started_at: datetime
    finished_at: datetime | None = None
    failure: Literal["unavailable", "cancelled", "timed_out"] | None = None
    signed_in_at: datetime | None = None
    last_download_filename: str | None = None
    last_download_at: datetime | None = None
    session_viewer_url: str | None = None


class NetFacilitiesCloudCapability(BaseModel):
    """Whether cloud auth is enabled at all, and the calling user's own
    ceremony state -- never anyone else's (spec D2, D7)."""

    available: bool
    message: str
    status: NetFacilitiesCloudSessionStatus | None = None
    has_saved_session: bool = False
