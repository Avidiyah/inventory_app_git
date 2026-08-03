"""HTTP routes for the `/users` resource.

Layer: routers. Every route requires a logged-in user. Listing requires
Supervisor or above. Creating, resetting a password, changing a role,
and deleting are all "manage a subordinate" actions: the acting user
must strictly outrank the target's role (`app.domain.roles.can_manage`),
which is why an Owner is never manageable through the API and a
Technician can manage no one. Changing a role additionally requires
Admin or above and applies the same rank rule to the incoming role, so
nobody can promote a user to their own level.

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
from app.schemas.users import (
    UserCreate,
    UserNameUpdate,
    UserResponse,
    UserRoleUpdate,
)
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
            first_name=payload.first_name,
            last_name=payload.last_name,
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
def list_users(
    include_archived: bool = False,
    db: Session = Depends(get_db),
):
    """Return users, newest first. Supervisor or above. By default only
    active users are returned (the Saved Users table); pass
    `include_archived=true` to also include archived users (the History
    "by user" filter does this so a departed user can still be selected)."""
    return users_service.list_users(db, include_archived=include_archived)


@router.patch("/{user_id}/name", response_model=UserResponse)
def update_user_name(
    user_id: uuid.UUID,
    payload: UserNameUpdate,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Set a user's human-facing name, and their login username when the
    payload carries one. Users may update themselves; managers may update a
    subordinate. This gives pre-name-migration accounts a safe, explicit
    remediation path without guessing identity from usernames, and lets a
    mistyped or outdated login name be corrected in place (400 if the new
    username is already taken)."""
    try:
        target = users_service.get_user(db, user_id)
        if actor.id != target.id and not roles.can_manage(actor.role, target.role):
            raise RoleManagementError("You cannot edit this user's name.")
        return users_service.update_name(
            db,
            user_id,
            first_name=payload.first_name,
            last_name=payload.last_name,
            username=payload.username,
        )
    except DomainError as exc:
        raise to_http(exc)


@router.patch(
    "/{user_id}/role",
    response_model=UserResponse,
    dependencies=[Depends(require_min_role(roles.ROLE_ADMIN))],
)
def update_user_role(
    user_id: uuid.UUID,
    payload: UserRoleUpdate,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Change a user's role. Admin or above, and -- as with every other
    subordinate action -- the actor must strictly outrank both the role the
    target holds now and the role being assigned. That pair of checks is
    what stops an Admin from promoting anyone (including themselves) to
    Admin or Owner: `can_manage` is false at equal rank. 404 if unknown;
    403 otherwise. The target's sessions are revoked, so they sign in again
    with a UI that matches their new role."""
    try:
        target = users_service.get_user(db, user_id)
        if not roles.can_manage(actor.role, target.role):
            raise RoleManagementError("You cannot change this user's role.")
        if not roles.can_manage(actor.role, payload.role):
            raise RoleManagementError("You cannot assign this role.")
        return users_service.update_role(db, user_id, role=payload.role)
    except DomainError as exc:
        raise to_http(exc)


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


@router.post("/{user_id}/archive", response_model=UserResponse)
def archive_user(
    user_id: uuid.UUID,
    force_return_tools: bool = False,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Archive (soft-delete) a subordinate user: they can no longer log in
    and their sessions are revoked, but the audit trail is preserved. This
    is the normal "remove a user" action and works even for a user with
    transactions. 404 if unknown; 403 if the actor does not outrank the
    target; 409 while the target has outstanding tool custody.

    Pass `force_return_tools=true` to resolve that 409: every tool still in
    the target's custody is checked in first (recorded as a `return`
    performed by the actor), then the archive proceeds."""
    try:
        target = users_service.get_user(db, user_id)
        if not roles.can_manage(actor.role, target.role):
            raise RoleManagementError("You cannot archive this user.")
        return users_service.archive_user(
            db,
            user_id,
            force_return_tools=force_return_tools,
            performed_by_id=actor.id,
        )
    except DomainError as exc:
        raise to_http(exc)


@router.post("/{user_id}/restore", response_model=UserResponse)
def restore_user(
    user_id: uuid.UUID,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Reactivate an archived subordinate user, allowing login again. 404
    if unknown; 403 if the actor does not outrank the target."""
    try:
        target = users_service.get_user(db, user_id)
        if not roles.can_manage(actor.role, target.role):
            raise RoleManagementError("You cannot restore this user.")
        return users_service.restore_user(db, user_id)
    except DomainError as exc:
        raise to_http(exc)


@router.delete("/{user_id}", status_code=204)
def delete_user(
    user_id: uuid.UUID,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Hard-delete a subordinate user. Kept for removing an unreferenced
    user created in error; the normal removal action is archive, which
    preserves history. 404 if unknown; 403 if the actor does not outrank
    the target; 400 if the user has transactions (use archive instead)."""
    try:
        target = users_service.get_user(db, user_id)
        if not roles.can_manage(actor.role, target.role):
            raise RoleManagementError("You cannot delete this user.")
        users_service.delete_user(db, user_id)
    except DomainError as exc:
        raise to_http(exc)
