"""Authentication / authorization FastAPI dependencies.

Layer: routers (internal helper), sibling to `_errors.py`. This is the
HTTP-layer glue between the cookie/session machinery in
`app.services.auth` and the route handlers. It is the one place that
knows the cookie name and produces the two security status codes:

- **401** -- there is no valid session (missing cookie, unknown token,
  or expired). Raised by `get_current_user`.
- **403** -- there *is* a valid session but the user's role is not
  permitted for the route. Raised by the `require_*` dependencies.

Routes opt in by declaring `Depends(get_current_user)` (any logged-in
user) or `Depends(require_min_role("admin"))` (role gate). Handlers
that need the identity -- e.g. to attribute a transaction -- take the
dependency as a parameter; handlers that only need the gate list it in
the decorator's `dependencies=[...]`.
"""

import os

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.domain import roles
from app.models import User
from app.services import auth as auth_service

# Cookie that carries the opaque session token. HttpOnly + SameSite=Lax
# are set when it is issued in the auth router.
SESSION_COOKIE = "session"

# Whether to set the Secure flag on the session cookie. Off by default
# so local http://localhost development works; set COOKIE_SECURE=true in
# any environment served over HTTPS.
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").strip().lower() == "true"


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """Resolve the request's session cookie to the logged-in `User`, or
    raise 401. Touching the session (sliding the idle timeout) happens
    inside `get_active_session_user`."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated.")

    user = auth_service.get_active_session_user(db, token)
    if user is None:
        raise HTTPException(status_code=401, detail="Session expired or invalid.")
    return user


def require_min_role(minimum: str):
    """Dependency factory: require the logged-in user to hold at least
    `minimum` rank. Returns the user so handlers can also use it."""

    def dependency(user: User = Depends(get_current_user)) -> User:
        if not roles.role_at_least(user.role, minimum):
            raise HTTPException(
                status_code=403,
                detail="You do not have permission to perform this action.",
            )
        return user

    return dependency
