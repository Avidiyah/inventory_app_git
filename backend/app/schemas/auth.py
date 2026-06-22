"""Authentication request/response schemas.

Layer: schemas (Pydantic only). Consumed by `app/routers/auth.py` and
`app/routers/users.py` (password reset). Passwords are validated for
minimum length only -- they are case-sensitive and intentionally not
stripped or otherwise transformed.
"""

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
    """Identity returned by `POST /auth/login` and `GET /auth/me`. Only
    the fields the frontend needs to gate UI are exposed."""

    id: UUID
    username: str
    role: str

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
