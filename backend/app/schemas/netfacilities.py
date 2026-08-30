"""Secret-safe HTTP contracts for NetFacilities enrichment."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.schemas.work_orders import WorkOrderImportResult


NetFacilitiesJobState = Literal[
    "queued",
    "running",
    "completed",
    "authentication_required",
    "timed_out",
    "failed",
    "cancelled",
]
NetFacilitiesJobSource = Literal["cloud_session"]


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
    # Which session read the source. Only the caller's own cloud session can,
    # so this is a single value the card can state plainly.
    source: NetFacilitiesJobSource | None = None


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
    # Steel's `debug_url` (WebRTC session player), not `sessionViewerUrl`
    # (Steel's own account-gated dashboard) -- see CloudLoginSession's
    # docstring for why the distinction matters.
    live_view_url: str | None = None
    # The unattended chain (auto-capture spec 4.2, 2a). `import_result` is
    # the whole import summary so the frontend renders the same line a
    # clicked import shows -- reconcile's auto_closed/reopened counts
    # included, once that work lands.
    capture_consumed: bool = False
    import_result: WorkOrderImportResult | None = None
    import_error: str | None = None
    enrichment_job_id: UUID | None = None
    chain_stage: Literal[
        "importing", "imported", "enriching", "done", "failed"
    ] | None = None


class NetFacilitiesCloudCapability(BaseModel):
    """Whether cloud auth is enabled at all, and the calling user's own
    ceremony state -- never anyone else's (spec D2, D7)."""

    available: bool
    message: str
    status: NetFacilitiesCloudSessionStatus | None = None
    has_saved_session: bool = False
