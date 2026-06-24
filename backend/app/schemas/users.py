"""User request/response schemas.

Layer: schemas. Used by `app/routers/users.py`. A user now carries a
login `password` (write-only, never echoed back) and a `role`. The
password rule is "at least 4 characters, case-sensitive"; the username
rule is "non-blank after stripping". Uniqueness is enforced by the
database and surfaced via `DuplicateUsernameError` from the service.

Whether the *caller* is allowed to assign the requested role is an
authorization decision made in the router via `app.domain.roles`, not
here -- this schema only checks that the role is a recognised value.
"""

from uuid import UUID
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator

from app.domain.roles import is_valid_role
from app.schemas.auth import MIN_PASSWORD_LENGTH


class UserCreate(BaseModel):
    """Payload for `POST /users`."""

    username: str
    password: str
    role: str

    @field_validator("username")
    @classmethod
    def username_not_blank(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("Username cannot be blank.")
        return v

    @field_validator("password")
    @classmethod
    def password_long_enough(cls, v):
        if len(v) < MIN_PASSWORD_LENGTH:
            raise ValueError(
                f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
            )
        return v

    @field_validator("role")
    @classmethod
    def role_recognised(cls, v):
        if not is_valid_role(v):
            raise ValueError("Unknown role.")
        return v


class UserResponse(BaseModel):
    """Outbound shape for any endpoint returning a user. The password
    hash is never included. `archived_at` is NULL for an active user and
    a timestamp for an archived (soft-deleted) one, so the Saved Users
    table can mark archived rows and offer Restore."""

    id: UUID
    username: str
    role: str
    created_at: datetime
    archived_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
