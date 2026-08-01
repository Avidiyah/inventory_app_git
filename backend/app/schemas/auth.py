"""Authentication request/response schemas.

Layer: schemas (Pydantic only). Consumed by `app/routers/auth.py` and
`app/routers/users.py` (password reset). Passwords are validated for
minimum length only -- they are case-sensitive and intentionally not
stripped or otherwise transformed.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, field_validator

# The product rule: passwords are at least 4 characters, case-sensitive.
MIN_PASSWORD_LENGTH = 4


class LoginRequest(BaseModel):
    """Body for `POST /auth/login`."""

    username: str
    password: str
    # Opt-in "Remember this device": when True the server issues a
    # 12h-capped session and a persistent cookie. Defaults off.
    remember: bool = False


class MeResponse(BaseModel):
    """Identity returned by `POST /auth/login` and `GET /auth/me`.

    The timestamps let self-service pages render the same compact profile
    information that Supervisor+ receives from `UserResponse`. An archived
    user cannot authenticate, so `archived_at` is normally NULL here; it is
    retained in the contract so the identity shape describes user status
    explicitly.
    """

    id: UUID
    username: str
    role: str
    created_at: datetime
    archived_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class PasswordResetRequest(BaseModel):
    """Body for `POST /users/{user_id}/reset-password`."""

    password: str

    @field_validator("password")
    @classmethod
    def password_long_enough(cls, v):
        if len(v) < MIN_PASSWORD_LENGTH:
            raise ValueError(
                f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
            )
        return v
