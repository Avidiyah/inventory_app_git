"""HTTP routes for the `/users` resource.

Layer: routers. Every route requires a logged-in user. Listing requires
Supervisor or above. Creating, resetting a password, and deleting are
all "manage a subordinate" actions: the acting user must strictly
outrank the target's role (`app.domain.roles.can_manage`), which is why
an Owner is never manageable through the API and a Technician can manage
no one.

The subordinate-rank check lives here (it needs the *actor*); the
service layer stays unaware of who is calling, consistent with the rest
of the codebase.

Mounted by `app/main.py` under the root prefix.
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth_deps import get_current_user, require_min_role
from app.database import get_db
from app.domain import roles
from app.domain.errors import DomainError, RoleManagementError
from app.models import User
from app.routers._errors import to_http
from app.schemas.auth import PasswordResetRequest
from app.schemas.users import UserCreate, UserResponse
from app.services import auth as auth_service
from app.services import users as users_service

router = APIRouter(prefix="/users", tags=["users"])


@router.post("/", response_model=UserResponse, status_code=201)
def create_user(
    payload: UserCreate,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a user. The actor may only assign a role they strictly
    outrank (403 otherwise); 400 on duplicate username."""
    if not roles.can_manage(actor.role, payload.role):
        raise to_http(
            RoleManagementError("You cannot create a user with this role.")
        )
    password_hash = auth_service.hash_password(payload.password)
    try:
        return users_service.create_user(
            db,
            username=payload.username,
            password_hash=password_hash,
            role=payload.role,
        )
    except DomainError as exc:
        raise to_http(exc)


@router.get(
    "/",
    response_model=list[UserResponse],
    dependencies=[Depends(require_min_role(roles.ROLE_SUPERVISOR))],
)
def list_users(db: Session = Depends(get_db)):
    """Return every user, newest first. Supervisor or above."""
    return users_service.list_users(db)


@router.post("/{user_id}/reset-password", status_code=204)
def reset_password(
    user_id: uuid.UUID,
    payload: PasswordResetRequest,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Set a new password for a subordinate user. 404 if unknown; 403 if
    the actor does not outrank the target."""
    try:
        target = users_service.get_user(db, user_id)
    except DomainError as exc:
        raise to_http(exc)
    if not roles.can_manage(actor.role, target.role):
        raise to_http(
            RoleManagementError("You cannot reset this user's password.")
        )
    users_service.reset_password(
        db, user_id, auth_service.hash_password(payload.password)
    )


@router.delete("/{user_id}", status_code=204)
def delete_user(
    user_id: uuid.UUID,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Hard-delete a subordinate user. 404 if unknown; 403 if the actor
    does not outrank the target; 400 if the user has transactions (audit
    trail is preserved per the spec)."""
    try:
        target = users_service.get_user(db, user_id)
        if not roles.can_manage(actor.role, target.role):
            raise RoleManagementError("You cannot delete this user.")
        users_service.delete_user(db, user_id)
    except DomainError as exc:
        raise to_http(exc)
