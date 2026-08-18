"""HTTP routes for Web Push: `/push/config`, `/push/subscribe`,
`/push/unsubscribe`, `/push/test`.

Layer: routers (FastAPI). Thin handlers over `app.services.push`.

Two different audiences, deliberately not the same gate:

- **Registering a device** is open to any authenticated user. An Admin
  has to be able to enrol their own phone, and nothing about holding a
  subscription grants authority.
- **Triggering a send** is Owner-only. This is the probe's blast
  radius: the only person who can make every Admin's phone buzz is the
  one person above them in `ROLE_RANK`.

`POST /push/unsubscribe` is a POST rather than a `DELETE` carrying a
body. A body on DELETE is legal but widely stripped by proxies, and the
failure mode -- a device that appears unsubscribed but keeps receiving
-- is exactly the privacy bug the endpoint exists to prevent.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth_deps import get_current_user, require_min_role
from app.database import get_db
from app.domain import push as push_policy
from app.domain import roles
from app.models import User
from app.schemas.push import (
    PushConfigResponse,
    PushSubscriptionRequest,
    PushTestResponse,
    PushUnsubscribeRequest,
)
from app.services import push as push_service

router = APIRouter(prefix="/push", tags=["push"])

logger = logging.getLogger(__name__)

# Who receives a test push. Admin and above, so the Owner triggering the
# fan-out is also in the audience and can prove the loop on one device
# without a second person present.
NOTIFY_MIN_ROLE = roles.ROLE_ADMIN


@router.get("/config", response_model=PushConfigResponse)
def push_config(_user: User = Depends(get_current_user)):
    """The VAPID public key the browser needs for `subscribe()`.

    Authenticated only because there is no reason to hand it to anonymous
    callers, not because it is secret -- it is not.

    503 when the server has no private key: without it a subscription
    could still be created but could never be delivered to, and a device
    that believes it is subscribed is worse than one that knows it is
    not.
    """
    if not push_service.is_configured():
        raise HTTPException(
            status_code=503,
            detail="Push is not configured on this server.",
        )
    return PushConfigResponse(public_key=push_service.VAPID_PUBLIC_KEY)


@router.post("/subscribe", status_code=204)
def subscribe(
    payload: PushSubscriptionRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Register this browser's subscription to the logged-in user.

    Rejects any endpoint outside the allowlist before it is ever stored.
    Validating at the boundary means a hostile endpoint never reaches the
    table, so no later code path can be tricked into requesting it --
    `services.push` re-checks anyway, on the principle that the guard
    belongs next to the request it guards.
    """
    if not push_policy.is_allowed_push_endpoint(payload.endpoint):
        raise HTTPException(status_code=400, detail="Unrecognised push endpoint.")

    push_service.save_subscription(
        db,
        user_id=user.id,
        endpoint=payload.endpoint,
        p256dh=payload.keys.p256dh,
        auth=payload.keys.auth,
    )


@router.post("/unsubscribe", status_code=204)
def unsubscribe(
    payload: PushUnsubscribeRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Drop this device's subscription. Called on logout.

    Scoped to the caller, and silent on a miss: unsubscribing a device
    that never subscribed is a normal logout, not an error worth a 404.
    """
    push_service.delete_subscription(db, user_id=user.id, endpoint=payload.endpoint)


@router.post(
    "/test",
    response_model=PushTestResponse,
    responses={
        403: {"description": f"Requires the {roles.label(roles.ROLE_OWNER)} role."},
        503: {"description": "Push is not configured on this server."},
    },
)
def send_test(
    user: User = Depends(require_min_role(roles.ROLE_OWNER)),
    db: Session = Depends(get_db),
):
    """Fan a fixed test notification out to every Admin-and-above device.

    The message is deliberately generic. Notification text renders on a
    locked phone, so nothing here names a person, a customer, or a job --
    a habit worth establishing in the probe rather than discovering after
    the first real notification quotes an address onto a lock screen.
    """
    if not push_service.is_configured():
        raise HTTPException(
            status_code=503,
            detail="Push is not configured on this server.",
        )

    result = push_service.send_to_min_role(
        db,
        minimum=NOTIFY_MIN_ROLE,
        title="Inventory",
        body="Test notification. Push is working on this device.",
    )
    logger.info(
        "push test fan-out by user %s: sent=%s dropped=%s failed=%s",
        user.id,
        result["sent"],
        result["dropped"],
        result["failed"],
    )
    return PushTestResponse(**result)
