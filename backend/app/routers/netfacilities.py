"""TechFM OA+ API for NetFacilities sign-in and enrichment jobs."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth_deps import require_min_role
from app.domain import roles
from app.integrations.netfacilities.config import (
    NetFacilitiesConfig,
    load_netfacilities_config,
)
from app.integrations.netfacilities.errors import (
    NetFacilitiesAuthenticationNotPending,
    NetFacilitiesAuthenticationRequired,
    NetFacilitiesError,
    NetFacilitiesOperationInProgress,
    NetFacilitiesUnavailable,
)
from app.models import User
from app.schemas.netfacilities import (
    NetFacilitiesAuthenticationAttempt,
    NetFacilitiesCapability,
    NetFacilitiesEnrichmentCounts,
    NetFacilitiesEnrichmentJob,
)
from app.services.netfacilities_auth import (
    PENDING_STATES,
    NetFacilitiesAuthenticationCoordinator,
    NetFacilitiesAuthenticationSnapshot,
    authentication_coordinator,
)
from app.services.netfacilities_jobs import (
    NetFacilitiesJobCoordinator,
    NetFacilitiesJobSnapshot,
    coordinator,
)


router = APIRouter(prefix="/integrations/netfacilities", tags=["netfacilities"])


def _forbidden() -> dict[int, dict[str, str]]:
    return {
        403: {
            "description": (
                f"Requires the {roles.label(roles.ROLE_TECHFM_OA)} role or higher."
            )
        }
    }


def get_netfacilities_coordinator() -> NetFacilitiesJobCoordinator:
    return coordinator


def get_netfacilities_authentication_coordinator(
) -> NetFacilitiesAuthenticationCoordinator:
    return authentication_coordinator


def _job_response(snapshot: NetFacilitiesJobSnapshot) -> NetFacilitiesEnrichmentJob:
    counts = None
    if snapshot.summary is not None:
        counts = NetFacilitiesEnrichmentCounts(**asdict(snapshot.summary))
    return NetFacilitiesEnrichmentJob(
        job_id=snapshot.job_id,
        state=snapshot.state,
        started_at=snapshot.started_at,
        finished_at=snapshot.finished_at,
        current_work_order_number=snapshot.current_work_order_number,
        failure=snapshot.failure,
        counts=counts,
        source=snapshot.source,
    )


def _authentication_response(
    snapshot: NetFacilitiesAuthenticationSnapshot,
) -> NetFacilitiesAuthenticationAttempt:
    return NetFacilitiesAuthenticationAttempt(
        attempt_id=snapshot.attempt_id,
        state=snapshot.state,
        started_at=snapshot.started_at,
        finished_at=snapshot.finished_at,
        failure=snapshot.failure,
        signed_in_at=snapshot.signed_in_at,
        last_download_filename=snapshot.last_download_filename,
        last_download_at=snapshot.last_download_at,
    )


def _live_session_lost_authentication(
    session: NetFacilitiesAuthenticationSnapshot,
    job: NetFacilitiesJobSnapshot | None,
) -> bool:
    """A job that borrowed *this* window and was told to sign in again."""

    return (
        job is not None
        and job.state == "authentication_required"
        and job.source == "live_session"
        and job.finished_at is not None
        and session.signed_in_at is not None
        and job.finished_at >= session.signed_in_at
    )


def _saved_state_refreshed_after(
    config: NetFacilitiesConfig,
    snapshot: NetFacilitiesJobSnapshot,
) -> bool:
    path = config.storage_state_path
    if path is None or snapshot.finished_at is None:
        return False
    try:
        modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return False
    return modified_at > snapshot.finished_at


@router.get(
    "/session",
    response_model=NetFacilitiesCapability,
    responses=_forbidden(),
)
async def netfacilities_session(
    _user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    jobs: NetFacilitiesJobCoordinator = Depends(get_netfacilities_coordinator),
    authentication: NetFacilitiesAuthenticationCoordinator = Depends(
        get_netfacilities_authentication_coordinator
    ),
) -> NetFacilitiesCapability:
    """Report safe sign-in, capability, and latest-job state."""

    try:
        config = load_netfacilities_config()
    except NetFacilitiesUnavailable:
        return NetFacilitiesCapability(
            available=False,
            state="unavailable",
            message="NetFacilities enrichment is unavailable on this host.",
        )
    if not config.enabled:
        return NetFacilitiesCapability(
            available=False,
            state="unavailable",
            message="NetFacilities enrichment is disabled on this host.",
        )

    latest = await jobs.latest()
    latest_authentication = await authentication.latest()
    latest_response = _job_response(latest) if latest is not None else None
    authentication_response = (
        _authentication_response(latest_authentication)
        if latest_authentication is not None
        else None
    )

    def capability(state: str, message: str) -> NetFacilitiesCapability:
        return NetFacilitiesCapability(
            available=True,
            interactive_authentication_available=(
                config.interactive_authentication_available
            ),
            state=state,
            message=message,
            latest_job=latest_response,
            latest_authentication=authentication_response,
        )

    if latest is not None and latest.state in {"queued", "running"}:
        return capability(
            "running", "NetFacilities is seeking Task/Symptom and Priority data."
        )
    if (
        latest_authentication is not None
        and latest_authentication.state in PENDING_STATES
    ):
        return capability(
            "authenticating",
            "Complete NetFacilities sign-in in the opened browser, then confirm "
            "it here.",
        )
    if latest_authentication is not None and latest_authentication.state == "signed_in":
        if _live_session_lost_authentication(latest_authentication, latest):
            return capability(
                "expired",
                "Your NetFacilities window is no longer logged in. Close it and "
                "log in again.",
            )
        return capability(
            "signed_in",
            "NetFacilities is open and logged in. Export the work-order CSV in "
            "that window; it is saved to your Downloads folder and can be "
            "imported from here.",
        )
    if not config.has_saved_authentication:
        message = (
            "Sign in to NetFacilities before enrichment."
            if config.interactive_authentication_available
            else (
                "Saved NetFacilities authentication is missing; update the Render "
                "secret file."
            )
        )
        return capability("not_authenticated", message)
    if (
        latest is not None
        and latest.state == "authentication_required"
        and not _saved_state_refreshed_after(config, latest)
    ):
        message = (
            "NetFacilities authentication expired; sign in again."
            if config.interactive_authentication_available
            else (
                "NetFacilities authentication expired; refresh the Render secret "
                "file and redeploy."
            )
        )
        return capability("expired", message)
    return capability(
        "ready", "Saved NetFacilities authentication is ready for enrichment."
    )


@router.post(
    "/auth/start",
    response_model=NetFacilitiesAuthenticationAttempt,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        **_forbidden(),
        409: {"description": "Another NetFacilities operation is active."},
        503: {"description": "Local NetFacilities sign-in is unavailable."},
    },
)
async def start_netfacilities_authentication(
    _user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    authentication: NetFacilitiesAuthenticationCoordinator = Depends(
        get_netfacilities_authentication_coordinator
    ),
) -> NetFacilitiesAuthenticationAttempt:
    """Open a headed browser for manual credentials, CAPTCHA, and MFA."""

    try:
        config = load_netfacilities_config()
    except NetFacilitiesUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="NetFacilities sign-in is unavailable on this host.",
        ) from exc
    if not config.enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="NetFacilities sign-in is disabled on this host.",
        )
    if not config.interactive_authentication_available:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Interactive NetFacilities sign-in is unavailable on this host; "
                "refresh the configured saved authentication instead."
            ),
        )
    try:
        snapshot, _created = await authentication.start(config)
    except NetFacilitiesOperationInProgress as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Another NetFacilities operation is already running.",
        ) from exc
    except NetFacilitiesError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="NetFacilities sign-in could not open on this host.",
        ) from exc
    return _authentication_response(snapshot)


@router.post(
    "/auth/confirm",
    response_model=NetFacilitiesAuthenticationAttempt,
    responses={
        **_forbidden(),
        409: {"description": "Sign-in is absent or not complete."},
        503: {"description": "NetFacilities sign-in could not be saved."},
    },
)
async def confirm_netfacilities_authentication(
    _user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    authentication: NetFacilitiesAuthenticationCoordinator = Depends(
        get_netfacilities_authentication_coordinator
    ),
) -> NetFacilitiesAuthenticationAttempt:
    """Verify the allowlisted page and save state after manual sign-in."""

    try:
        snapshot = await authentication.confirm()
    except NetFacilitiesAuthenticationRequired as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "NetFacilities sign-in is not complete in the opened browser. "
                "Finish signing in, then confirm again."
            ),
        ) from exc
    except NetFacilitiesAuthenticationNotPending as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No NetFacilities sign-in is waiting for confirmation.",
        ) from exc
    except NetFacilitiesError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="NetFacilities sign-in state could not be saved.",
        ) from exc
    return _authentication_response(snapshot)


@router.post(
    "/auth/cancel",
    response_model=NetFacilitiesAuthenticationAttempt,
    responses={
        **_forbidden(),
        409: {"description": "No NetFacilities window is open, or enrichment is still using it."},
    },
)
async def cancel_netfacilities_authentication(
    _user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    authentication: NetFacilitiesAuthenticationCoordinator = Depends(
        get_netfacilities_authentication_coordinator
    ),
) -> NetFacilitiesAuthenticationAttempt:
    """Close the dedicated window: a pending sign-in or the live session."""

    try:
        snapshot = await authentication.cancel()
    except NetFacilitiesOperationInProgress as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Enrichment is still using the NetFacilities window; wait for it "
                "to finish."
            ),
        ) from exc
    except NetFacilitiesAuthenticationNotPending as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No NetFacilities sign-in is currently active.",
        ) from exc
    return _authentication_response(snapshot)


@router.post(
    "/work-orders/enrich",
    response_model=NetFacilitiesEnrichmentJob,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        **_forbidden(),
        409: {"description": "Sign in or wait for the active operation."},
        503: {"description": "NetFacilities enrichment is unavailable."},
    },
)
async def start_netfacilities_enrichment(
    _user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    jobs: NetFacilitiesJobCoordinator = Depends(get_netfacilities_coordinator),
    authentication: NetFacilitiesAuthenticationCoordinator = Depends(
        get_netfacilities_authentication_coordinator
    ),
) -> NetFacilitiesEnrichmentJob:
    """Start one batch through the open window if there is one, else the saved state."""

    try:
        config = load_netfacilities_config()
    except NetFacilitiesUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="NetFacilities enrichment is unavailable on this host.",
        ) from exc
    if not config.enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="NetFacilities enrichment is disabled on this host.",
        )
    try:
        live = await authentication.borrow_live_client()
        snapshot, _created = await jobs.start(config, live_client_context=live)
    except NetFacilitiesAuthenticationRequired as exc:
        detail = (
            "Sign in to NetFacilities before enrichment."
            if config.interactive_authentication_available
            else (
                "Refresh the saved NetFacilities authentication secret and redeploy "
                "before enrichment."
            )
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail,
        ) from exc
    except NetFacilitiesOperationInProgress as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Another NetFacilities operation is already running.",
        ) from exc
    return _job_response(snapshot)


@router.get(
    "/work-orders/enrich/{job_id}",
    response_model=NetFacilitiesEnrichmentJob,
    responses={
        **_forbidden(),
        404: {"description": "The process-local enrichment job is unavailable."},
    },
)
async def get_netfacilities_enrichment(
    job_id: UUID,
    _user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    jobs: NetFacilitiesJobCoordinator = Depends(get_netfacilities_coordinator),
) -> NetFacilitiesEnrichmentJob:
    snapshot = await jobs.get(job_id)
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="NetFacilities enrichment job was not found on this process.",
        )
    return _job_response(snapshot)
