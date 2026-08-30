"""Resolving one user's saved cloud session into an enrichment context.

Lifted out of `routers/netfacilities.py` because the unattended capture
chain (`netfacilities_cloud_auth.dispatch_capture`) needs it too, and the
two must not drift (auto-capture spec §4.3). Takes a `user_id` rather than
a `User`: the router only ever read `user.id`, and the chain has no ORM
user to hand it.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.integrations.netfacilities.cloud_config import load_netfacilities_cloud_config
from app.integrations.netfacilities.config import NetFacilitiesConfig


def resolve_cloud_enrichment_context(
    config: NetFacilitiesConfig,
    db: Session,
    user_id: UUID,
):
    """The user's own cloud session, ready to reconnect, and the batch
    deadline it must respect (cloud-auth spec §4), or `(None, None)` if they
    have none or theirs has expired (spec D10)."""

    cloud_config = load_netfacilities_cloud_config(config)
    if not cloud_config.enabled:
        return None, None
    from app.integrations.netfacilities.factory import (
        create_netfacilities_cloud_enrichment_client,
    )
    from app.models import NetFacilitiesCloudSession

    row = db.query(NetFacilitiesCloudSession).filter_by(user_id=user_id).one_or_none()
    if row is None or row.expires_at is not None:
        return None, None
    context = create_netfacilities_cloud_enrichment_client(
        cloud_config,
        row.storage_state.encode("ascii"),
        render_document=config.render_document,
        render_settle_ms=config.render_settle_ms,
    )
    return context, cloud_config.batch_session_seconds
