"""HTTP routes for authentication: `/auth/login`, `/auth/logout`,
`/auth/me`.

Layer: routers (FastAPI). Thin handlers over `app.services.auth`. This
is the only router whose `POST /login` is public; everything else in
the application (including the other two routes here) requires a valid
session via `get_current_user`.

The session token never appears in a response body -- it is set as an
HttpOnly cookie on login and cleared on logout, so client JavaScript
cannot read it. Only its hash reaches the database (see
`app.services.auth`).

`POST /login` is additionally throttled by
`app.services.login_throttle`; a locked-out caller gets 429 with a
`Retry-After` header rather than a delayed response, so the throttle
never occupies a worker thread.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.auth_deps import COOKIE_SECURE, SESSION_COOKIE, get_current_user
from app.database import get_db
from app.domain.errors import DomainError, LoginThrottledError
from app.models import User
from app.routers._errors import to_http
from app.schemas.auth import LoginRequest, MeResponse
from app.services import auth as auth_service
from app.services import login_throttle

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str:
    """Best-effort client address for throttle keying.

    Relies on uvicorn's `--proxy-headers` (set in `entrypoint.sh`) to
    have already resolved `X-Forwarded-For` into `request.client`, rather
    than parsing the header here -- hand-rolled XFF parsing is the usual
    place a spoofable client address sneaks in.

    Falls back to a constant when there is no peer (ASGI test
    transports). That degrades the per-(username, IP) layer to
    per-username within that caller, which is still correct behavior --
    just coarser."""
    client = request.client
    return client.host if client and client.host else "unknown"


@router.post("/login", response_model=MeResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Verify credentials, open a server-side session, and set the
    session cookie. 401 on bad username/password; 429 while throttled.

    The throttle check runs before credentials are examined, so a
    locked-out caller learns nothing about whether the account exists."""
    ip = _client_ip(request)
    try:
        login_throttle.check(db, username=payload.username, ip=ip)
    except LoginThrottledError as exc:
        # Handled here rather than through `to_http`, which has no way to
        # carry the Retry-After header.
        raise HTTPException(
            status_code=429,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after_seconds)},
        )

    try:
        user = auth_service.authenticate(
            db, username=payload.username, password=payload.password
        )
    except DomainError as exc:
        login_throttle.record_failure(db, username=payload.username, ip=ip)
        raise to_http(exc)

    login_throttle.clear(db, username=payload.username, ip=ip)
    token = auth_service.create_session(db, user, remember=payload.remember)
    # Remembered -> a persistent cookie (max_age) that survives a browser
    # restart, matching the session's 12h server-side cap. Otherwise a
    # session cookie (no max_age) that the browser drops on close.
    max_age = (
        int(auth_service.REMEMBER_LIFETIME.total_seconds())
        if payload.remember
        else None
    )
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
        path="/",
    )
    return user


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    response: Response,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Clear the session on the server and remove the cookie. Requires
    a valid session (so an expired cookie returns 401, not 204)."""
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        auth_service.delete_session(db, token)
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me", response_model=MeResponse)
def me(user: User = Depends(get_current_user)):
    """Return the logged-in user's identity, role, and profile timestamps.
    The frontend calls this on boot to decide whether to show the app, gate
    the UI by role, and populate self-service profile cards."""
    return user
