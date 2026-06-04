"""HTTP routes for the `/users` resource.

Layer: routers. CRUD endpoints for the user list that populates
the "performed by" dropdown in the frontend transaction form.
Delete is a hard-delete and is refused by the service when audit
rows reference the user (`UserHasTransactionsError` -> 400).

Mounted by `app/main.py` under the root prefix.
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.domain.errors import DomainError
from app.routers._errors import to_http
from app.schemas.users import UserCreate, UserResponse
from app.services import users as users_service

router = APIRouter(prefix="/users", tags=["users"])


@router.post("/", response_model=UserResponse, status_code=201)
def create_user(payload: UserCreate, db: Session = Depends(get_db)):
    """Create a user. 400 on duplicate username."""
    try:
        return users_service.create_user(db, username=payload.username)
    except DomainError as exc:
        raise to_http(exc)


@router.get("/", response_model=list[UserResponse])
def list_users(db: Session = Depends(get_db)):
    """Return every user, newest first."""
    return users_service.list_users(db)


@router.delete("/{user_id}", status_code=204)
def delete_user(user_id: uuid.UUID, db: Session = Depends(get_db)):
    """Hard-delete a user. 404 if unknown; 400 if the user has
    transactions (audit trail is preserved per the spec)."""
    try:
        users_service.delete_user(db, user_id)
    except DomainError as exc:
        raise to_http(exc)
