"""TechFM OA+ API for NetFacilities enrichment jobs (per-user Steel cloud auth)."""

from __future__ import annotations

from dataclasses import asdict
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth_deps import require_min_role
from app.database import get_db
from app.domain import roles
from app.integrations.netfacilities.cloud_config import load_netfacilities_cloud_config
from app.integrations.netfacilities.cloud_steel import SteelCloudBrowserProvider
from app.integrations.netfacilities.config import (
    NetFacilitiesConfig,
    load_netfacilities_config,
)
from app.integrations.netfacilities.errors import (
    NetFacilitiesAuthenticationRequired,
    NetFacilitiesError,
    NetFacilitiesOperationInProgress,
    NetFacilitiesUnavailable,
)
from app.models import User
from app.routers.work_orders import run_csv_import
from app.schemas.netfacilities import (
    NetFacilitiesCloudCapability,
    NetFacilitiesCloudSessionStatus,
    NetFacilitiesEnrichmentCounts,
    NetFacilitiesEnrichmentJob,
)
from app.schemas.work_orders import WorkOrderImportResult
from app.services.netfacilities_cloud_auth import (
    NetFacilitiesCloudAuthenticationCoordinator,
)
from app.services.netfacilities_jobs import (
    NetFacilitiesJobCoordinator,
    NetFacilitiesJobSnapshot,
    coordinator,
)


router = APIRouter(prefix="/integrations/netfacilities", tags=["netfacilities"])

cloud_authentication_coordinator = NetFacilitiesCloudAuthenticationCoordinator(
    provider_factory=lambda config: SteelCloudBrowserProvider(api_key=config.steel_api_key),
)


def get_netfacilities_cloud_authentication_coordinator(
) -> NetFacilitiesCloudAuthenticationCoordinator:
    return cloud_authentication_coordinator


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
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    db: Session = Depends(get_db),
    jobs: NetFacilitiesJobCoordinator = Depends(get_netfacilities_coordinator),
) -> NetFacilitiesEnrichmentJob:
    """Start one batch using the calling user's own NetFacilities cloud session."""

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
        cloud_context, cloud_batch_seconds = _resolve_cloud_enrichment_context(
            config, db, user
        )
        snapshot, _created = await jobs.start(
            config,
            cloud_client_context=cloud_context,
            cloud_user_id=user.id if cloud_context is not None else None,
            cloud_batch_session_seconds=cloud_batch_seconds,
        )
    except NetFacilitiesAuthenticationRequired as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Sign in to NetFacilities before enrichment.",
        ) from exc
    except NetFacilitiesOperationInProgress as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Another NetFacilities operation is already running.",
        ) from exc
    return _job_response(snapshot)


def _resolve_cloud_enrichment_context(
    config: NetFacilitiesConfig,
    db: Session,
    user: User,
):
    """The calling user's own cloud session, ready to reconnect, and the
    batch deadline it must respect (spec §4), or `(None, None)` if they have
    none or theirs has expired (spec D10)."""

    cloud_config = load_netfacilities_cloud_config(config)
    if not cloud_config.enabled:
        return None, None
    from app.integrations.netfacilities.factory import (
        create_netfacilities_cloud_enrichment_client,
    )
    from app.models import NetFacilitiesCloudSession

    row = db.query(NetFacilitiesCloudSession).filter_by(user_id=user.id).one_or_none()
    if row is None or row.expires_at is not None:
        return None, None
    context = create_netfacilities_cloud_enrichment_client(
        cloud_config,
        row.storage_state.encode("ascii"),
        render_document=config.render_document,
        render_settle_ms=config.render_settle_ms,
    )
    return context, cloud_config.batch_session_seconds


def _mark_cloud_session_expired_if_needed(
    db: Session, job: NetFacilitiesJobSnapshot
) -> None:
    """A cloud-sourced job that lost authentication expires that user's saved
    session (spec D8: set only once an attempt actually reports it)."""

    if job.source != "cloud_session" or job.state != "authentication_required":
        return
    from app.models import NetFacilitiesCloudSession

    row = (
        db.query(NetFacilitiesCloudSession)
        .filter_by(user_id=job.user_id)
        .one_or_none()
    )
    if row is not None and row.expires_at is None:
        row.expires_at = job.finished_at
        db.commit()


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
    db: Session = Depends(get_db),
    jobs: NetFacilitiesJobCoordinator = Depends(get_netfacilities_coordinator),
) -> NetFacilitiesEnrichmentJob:
    snapshot = await jobs.get(job_id)
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="NetFacilities enrichment job was not found on this process.",
        )
    _mark_cloud_session_expired_if_needed(db, snapshot)
    return _job_response(snapshot)


def _cloud_status_response(
    snapshot,
) -> NetFacilitiesCloudSessionStatus:
    return NetFacilitiesCloudSessionStatus(
        attempt_id=snapshot.attempt_id,
        state=snapshot.state,
        started_at=snapshot.started_at,
        finished_at=snapshot.finished_at,
        failure=snapshot.failure,
        signed_in_at=snapshot.signed_in_at,
        last_download_filename=snapshot.last_download_filename,
        last_download_at=snapshot.last_download_at,
        live_view_url=snapshot.live_view_url,
    )


@router.get("/cloud/session", response_model=NetFacilitiesCloudCapability, responses=_forbidden())
async def netfacilities_cloud_session(
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    db: Session = Depends(get_db),
    cloud_auth: NetFacilitiesCloudAuthenticationCoordinator = Depends(
        get_netfacilities_cloud_authentication_coordinator
    ),
) -> NetFacilitiesCloudCapability:
    try:
        config = load_netfacilities_config()
    except NetFacilitiesUnavailable:
        return NetFacilitiesCloudCapability(
            available=False, message="NetFacilities is unavailable on this host."
        )
    cloud_config = load_netfacilities_cloud_config(config)
    if not cloud_config.enabled:
        return NetFacilitiesCloudCapability(
            available=False,
            message="NetFacilities cloud sign-in is not enabled on this host.",
        )

    from app.models import NetFacilitiesCloudSession

    has_saved = (
        db.query(NetFacilitiesCloudSession).filter_by(user_id=user.id).first() is not None
    )
    latest = await cloud_auth.latest(user.id)
    return NetFacilitiesCloudCapability(
        available=True,
        message="Log in to NetFacilities from any device." if latest is None else "",
        status=_cloud_status_response(latest) if latest is not None else None,
        has_saved_session=has_saved,
    )


@router.post(
    "/cloud/auth/start",
    response_model=NetFacilitiesCloudSessionStatus,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_forbidden(), 503: {"description": "Cloud sign-in is unavailable."}},
)
async def start_netfacilities_cloud_authentication(
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    cloud_auth: NetFacilitiesCloudAuthenticationCoordinator = Depends(
        get_netfacilities_cloud_authentication_coordinator
    ),
) -> NetFacilitiesCloudSessionStatus:
    try:
        config = load_netfacilities_config()
    except NetFacilitiesUnavailable as exc:
        raise HTTPException(status_code=503, detail="NetFacilities is unavailable on this host.") from exc
    cloud_config = load_netfacilities_cloud_config(config)
    if not cloud_config.enabled:
        raise HTTPException(status_code=503, detail="NetFacilities cloud sign-in is not enabled on this host.")
    try:
        snapshot = await cloud_auth.start(user.id, cloud_config)
    except NetFacilitiesError as exc:
        raise HTTPException(status_code=503, detail="Could not open a NetFacilities cloud session.") from exc
    return _cloud_status_response(snapshot)


@router.post(
    "/cloud/auth/cancel",
    response_model=NetFacilitiesCloudSessionStatus,
    responses={**_forbidden(), 409: {"description": "No cloud session is active."}},
)
async def cancel_netfacilities_cloud_authentication(
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    cloud_auth: NetFacilitiesCloudAuthenticationCoordinator = Depends(
        get_netfacilities_cloud_authentication_coordinator
    ),
) -> NetFacilitiesCloudSessionStatus:
    try:
        snapshot = await cloud_auth.cancel(user.id)
    except NetFacilitiesError as exc:
        raise HTTPException(status_code=409, detail="No NetFacilities cloud session is active.") from exc
    return _cloud_status_response(snapshot)


@router.post(
    "/cloud/downloads/import",
    response_model=WorkOrderImportResult,
    responses={**_forbidden(), 409: {"description": "No CSV has been captured yet."}},
)
def import_netfacilities_cloud_download(
    background: BackgroundTasks,
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    db: Session = Depends(get_db),
    cloud_auth: NetFacilitiesCloudAuthenticationCoordinator = Depends(
        get_netfacilities_cloud_authentication_coordinator
    ),
) -> WorkOrderImportResult:
    found = cloud_auth.captured_csv_bytes(user.id)
    if found is None:
        raise HTTPException(
            status_code=409,
            detail="No CSV has been exported through the NetFacilities cloud window yet.",
        )
    _filename, data = found
    return run_csv_import(db, background, data=data, user=user)
