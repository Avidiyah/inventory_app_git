"""User request/response schemas.

Layer: schemas. Used by `app/routers/users.py`. Usernames are the
only identifier — there is no authentication system yet — so the
single validation rule is "must not be blank after stripping".
Uniqueness is enforced by the database and surfaced via
`DuplicateUsernameError` from the service layer.
"""

from uuid import UUID
from datetime import datetime

from pydantic import BaseModel, field_validator


class UserCreate(BaseModel):
    """Payload for `POST /users`."""

    username: str

    @field_validator("username")
    @classmethod
    def username_not_blank(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("Username cannot be blank.")
        return v


class UserResponse(BaseModel):
    """Outbound shape for any endpoint returning a user."""

    id: UUID
    username: str
    created_at: datetime

    model_config = {"from_attributes": True}
