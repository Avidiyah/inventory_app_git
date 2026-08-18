"""Web Push request/response schemas.

Layer: schemas (Pydantic only). Consumed by `app/routers/push.py`.

`PushSubscriptionRequest` deliberately mirrors the exact JSON shape the
browser produces from `PushSubscription.toJSON()`, nesting the keys under
`keys` rather than flattening them. The frontend can therefore post the
subscription object through unmodified, and any future shape change shows
up here as a validation error rather than as a silently dropped field.
"""

from pydantic import BaseModel


class PushKeys(BaseModel):
    """The browser-generated payload-encryption material.

    Both values come from `PushSubscription.getKey()` and are per-device
    secrets (RFC 8291). They are never logged and never returned.
    """

    p256dh: str
    auth: str


class PushSubscriptionRequest(BaseModel):
    """Body for `POST /push/subscribe` -- a browser subscription verbatim.

    `expirationTime` is present in the browser's object but omitted here:
    it is null on every push service in use, and Pydantic ignores unknown
    fields by default, so posting the whole object works unchanged.
    """

    endpoint: str
    keys: PushKeys


class PushUnsubscribeRequest(BaseModel):
    """Body for `DELETE /push/subscribe`.

    Carries the endpoint rather than relying on the session alone, because
    a user may hold subscriptions on several devices and logging out of one
    must not silence the others.
    """

    endpoint: str


class PushConfigResponse(BaseModel):
    """Body of `GET /push/config`.

    The VAPID public key, which `pushManager.subscribe()` requires as
    `applicationServerKey`. Not a secret -- it reaches every browser that
    subscribes. It is served rather than hardcoded in JavaScript so the
    key cannot drift out of sync with the private half the server signs
    with; a mismatch there is invisible until the first send returns 401.
    """

    public_key: str


class PushTestResponse(BaseModel):
    """Body of `POST /push/test` -- the outcome of one fan-out.

    Three counts rather than a bare success flag, because the interesting
    failure during a rollout is partial: some devices deliver, some are
    stale, some reveal a misconfiguration. `dropped` counts subscriptions
    deleted as dead (404/410); `failed` counts everything else.
    """

    sent: int
    dropped: int
    failed: int
