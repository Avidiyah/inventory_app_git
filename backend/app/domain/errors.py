"""Domain exception vocabulary.

Layer: pure domain (no FastAPI, no SQLAlchemy, no Pydantic).

These exceptions are the language the service layer uses to report
business-rule failures. They are deliberately HTTP-agnostic so that
services can be unit-tested without a web framework and so that the
same rules could be reused from a CLI, a script, or a future API
revision.

Translation to HTTP status codes happens at the router boundary in
`app/routers/_errors.py::to_http`. Anything inheriting from
`DomainError` is recognised there; unknown exception types fall
through to FastAPI's default 500 handler.
"""

from decimal import Decimal


class DomainError(Exception):
    """Base class for every business-rule failure raised by services.

    Routers catch this single type and translate it via `to_http`, so
    every new domain exception added below is automatically handled
    once it inherits from `DomainError` and is registered in
    `_errors._STATUS_MAP`.
    """


class ItemNotFoundError(DomainError):
    """Raised when a service is asked to operate on an item that
    does not exist (lookup by id or barcode)."""


class DuplicateBarcodeError(DomainError):
    """Raised by `services.items.create_item` when the database
    rejects an insert because the barcode UNIQUE constraint fired."""


class DuplicateUsernameError(DomainError):
    """Raised by `services.users.create_user` when the username
    UNIQUE constraint fires."""


class UserHasTransactionsError(DomainError):
    """Raised by `services.users.delete_user` when the FK from
    `transactions.user_id` prevents deletion. The audit trail is
    intentionally preserved — see spec.md decisions log."""


class UserNotFoundError(DomainError):
    """Raised by `services.users.delete_user` when no row matches
    the given user id."""


class NegativeQuantityError(DomainError):
    """Raised by `domain.quantity.apply_delta` when a dispense would
    drop an item's stock below zero.

    Carries the offending numbers so callers (and tests) can inspect
    the exact attempted operation without parsing a message string.
    """

    def __init__(self, current: Decimal, requested: Decimal):
        self.current = current
        self.requested = requested
        super().__init__(
            f"Cannot dispense {requested}: only {current} in stock."
        )


class InvalidCredentialsError(DomainError):
    """Raised by `services.auth.authenticate` when the username does
    not exist or the password does not match. Deliberately does not
    distinguish the two cases so the API cannot be used to enumerate
    valid usernames. Maps to 401."""


class RoleManagementError(DomainError):
    """Raised when an actor attempts to create, reset, or delete a user
    they do not outrank (see `domain.roles.can_manage`). This is an
    authorization failure, not a validation error, so it maps to 403."""


class UnreadableImageError(DomainError):
    """Raised by `services.barcodes.decode_image` when the uploaded bytes
    are not a decodable image (PIL cannot open them). This is a malformed
    request, not a "not found", so it maps to 400. A *readable* image that
    simply contains no barcode is NOT an error -- the service returns an
    empty list and the router responds 200."""
