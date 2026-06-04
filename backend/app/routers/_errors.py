"""Domain-to-HTTP exception translator.

Layer: routers (internal helper). This is the single place that
knows how a `DomainError` becomes an `HTTPException`. Every router
catches `DomainError` and re-raises `to_http(exc)`, so adding a
new domain exception only requires registering its status code in
`_STATUS_MAP` here -- routers do not change.

The two-table design separates concerns: `_STATUS_MAP` decides the
status code, `_DEFAULT_DETAILS` overrides the user-facing message
for exceptions whose `str(exc)` is too internal to surface (e.g.
`NegativeQuantityError` carries operand numbers in its message).
"""

from fastapi import HTTPException

from app.domain.errors import (
    DomainError,
    DuplicateBarcodeError,
    DuplicateUsernameError,
    InvalidCredentialsError,
    ItemNotFoundError,
    NegativeQuantityError,
    RoleManagementError,
    UnreadableImageError,
    UserHasTransactionsError,
    UserNotFoundError,
)


# Status code per domain exception. Unknown subclasses fall back
# to 400 in `to_http` -- 404 is reserved for true "not found",
# 401 for authentication failure, 403 for authorization failure.
_STATUS_MAP: dict[type[DomainError], int] = {
    ItemNotFoundError: 404,
    UserNotFoundError: 404,
    DuplicateBarcodeError: 400,
    DuplicateUsernameError: 400,
    UserHasTransactionsError: 400,
    NegativeQuantityError: 400,
    UnreadableImageError: 400,
    InvalidCredentialsError: 401,
    RoleManagementError: 403,
}


# Message overrides for exceptions whose `str(exc)` is unsuitable
# for end users. Anything not listed here uses `str(exc)` directly.
_DEFAULT_DETAILS: dict[type[DomainError], str] = {
    NegativeQuantityError: "Insufficient stock to dispense.",
}


def to_http(exc: DomainError) -> HTTPException:
    """Convert a domain exception to the `HTTPException` a router
    should raise. Defaults: status 400, detail = exception message,
    or `"Request failed."` if the exception carries no message."""
    status = _STATUS_MAP.get(type(exc), 400)
    detail = _DEFAULT_DETAILS.get(type(exc)) or (str(exc) if str(exc) else "Request failed.")
    return HTTPException(status_code=status, detail=detail)
