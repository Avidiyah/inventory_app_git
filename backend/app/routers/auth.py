"""HTTP routes for authentication: `/auth/login`, `/auth/logout`,
`/auth/me`.

Layer: routers (FastAPI). Thin handlers over `app.services.auth`. This
is the only router whose `POST /login` is public; everything else in
the application (including the other two routes here) requires a valid
session via `get_current_user`.

The session token never appears in a response body -- it is set as an
HttpOnly cookie on login and cleared on logout, so client JavaScript
cannot read it.
"""

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.auth_deps import COOKIE_SECURE, SESSION_COOKIE, get_current_user
from app.database import get_db
from app.domain.errors import DomainError
from app.models import User
from app.routers._errors import to_http
from app.schemas.auth import LoginRequest, MeResponse
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=MeResponse)
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)):
    """Verify credentials, open a server-side session, and set the
    session cookie. 401 on bad username/password."""
    try:
        user = auth_service.authenticate(
            db, username=payload.username, password=payload.password
        )
    except DomainError as exc:
        raise to_http(exc)

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
    """Return the currently logged-in user's identity and role. The
    frontend calls this on boot to decide whether to show the app or
    the login screen, and to gate the UI by role."""
    return user
