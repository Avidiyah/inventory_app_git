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
from typing import Optional


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


class ArchivedBarcodeConflictError(DomainError):
    """Raised when a barcode being applied (on create, primary-barcode
    edit, or additional-barcode add) is already held by an *archived*
    (soft-deleted) item rather than a live one.

    This is a recoverable conflict, not a hard duplicate: the caller can
    retry with `override_archived=True` to free the code -- the archived
    holder is purged if it has no history, or has just the conflicting
    code released (keeping its shell for the audit trail) if it does. It
    maps to 409 Conflict so the frontend can prompt
    "Barcode exists but is archived. Continue?" and re-submit, distinct
    from the 400 a live-item `DuplicateBarcodeError` returns."""


class DuplicateUsernameError(DomainError):
    """Raised by `services.users.create_user` when the username
    UNIQUE constraint fires."""


class InvalidUserNameError(DomainError):
    """Raised when a first or last name is blank after trimming."""


class InvalidUsernameError(DomainError):
    """Raised when a login username is blank after trimming. Separate from
    `InvalidUserNameError` (the human name) so the message can name the
    right field. Maps to 400."""


class UserHasTransactionsError(DomainError):
    """Raised by `services.users.delete_user` when the FK from
    `transactions.user_id` prevents deletion. The audit trail is
    intentionally preserved; see docs/current-state.md."""


class UserHasCheckedOutToolsError(DomainError):
    """Raised when an archive would hide a user who still has positive
    tool custody, since the user-first custody workflow could no longer
    reach those tools.

    Like `ArchivedBarcodeConflictError`, this is a recoverable conflict
    rather than a dead end: the caller can retry with
    `force_return_tools=True` to check every outstanding tool in first.
    It maps to 409 so the frontend can tell it apart from a plain 400 and
    offer that retry."""


class ItemHasTransactionsError(DomainError):
    """Raised by `services.items.delete_item` when the item is
    referenced by one or more rows in `transactions`. Mirrors
    `UserHasTransactionsError`: the audit trail wins over the
    convenience of deletion, and `transactions.item_id` is pinned
    `ON DELETE RESTRICT` at the DB level to match."""


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


class TransactionNotFoundError(DomainError):
    """Raised by `services.transactions.void_transaction` when no row
    matches the given transaction id (or it is already voided, so it is
    no longer visible to act on). Maps to 404."""


class TransactionVoidError(DomainError):
    """Raised by `services.transactions.void_transaction` when undoing a
    transaction's effect on stock would drive the item's quantity below
    zero -- e.g. voiding a stock-in whose units have since been
    dispensed. Wraps the lower-level `NegativeQuantityError` so the user
    gets a void-specific message rather than the dispense wording. Maps
    to 400."""


class BillingQuantityError(DomainError):
    """Raised by `domain.billing.validate_billable_quantity` when an
    Admin's billable-quantity override is invalid -- negative, larger than
    the units actually recorded, or applied to an `adjust` (correction)
    row that cannot be billed. A pure validation failure, so it maps to
    400."""


class NoChangeError(DomainError):
    """Raised by `services.transactions.apply_correction` when the
    requested `new_quantity` matches the item's current quantity, so
    the correction would create an empty audit row. The user almost
    always means a typo here; a clean 400 makes the no-op explicit."""


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


class StageNotFoundError(DomainError):
    """Raised when a mass-staging service is asked to operate on a stage
    (`mass_stages` row) that does not exist. Maps to 404."""


class RoomNotFoundError(DomainError):
    """Raised when a stage room (`mass_stage_rooms` row) is not found, or
    does not belong to the stage named in the request. Maps to 404."""


class StageItemNotFoundError(DomainError):
    """Raised when a planned stage item is not found -- including a load
    request for an item that no room in the stage planned (loading an
    unplanned item is the mid-job plain-dispense path, not a stage load).
    Maps to 404."""


class DuplicateBuildingStageError(DomainError):
    """Raised when creating a stage for a building that already has an
    active (non-completed) stage. Mirrors the DB partial unique index
    `uq_mass_stages_active_building`; the service pre-checks so callers get
    a clean 400 rather than a raw IntegrityError."""


class InvalidStageTransitionError(DomainError):
    """Raised by `domain.mass_staging.validate_transition` when a stage
    status change is not allowed. The lifecycle is forward-only
    (`planning -> loading -> completed`); every backward, same-state, or
    unknown move is rejected. Carries both ends for tests and messaging.
    Maps to 400."""

    def __init__(self, current: str, target: str):
        self.current = current
        self.target = target
        super().__init__(
            f"Cannot change stage status from {current!r} to {target!r}."
        )


class ReturnExceedsLoadedError(DomainError):
    """Raised by `domain.mass_staging.allocate_return` when the quantity to
    return exceeds what is still loaded (net of prior returns) across the
    item's rooms. Carries the requested amount and the returnable cap so
    callers and tests can inspect them. Maps to 400."""

    def __init__(self, requested: Decimal, returnable: Decimal):
        self.requested = requested
        self.returnable = returnable
        super().__init__(
            f"Cannot return {requested}: only {returnable} loaded."
        )


class StageStateError(DomainError):
    """Raised when a mass-staging operation is not allowed in the stage's
    current status -- e.g. editing rooms/items once the stage has left
    `planning`, or loading/returning before it reaches `loading`.
    A single generic state guard rather than several niche errors; the
    message states the specific rule. Maps to 400."""


class InvalidAssigneeError(DomainError):
    """Raised when a work order (room) is assigned to a user who does not
    exist or is not a technician. Work orders are assigned only to
    technicians (`domain.roles.ROLE_TECHNICIAN`); an unassigned room (None)
    is always valid. Maps to 400."""


class InvalidSupervisorError(DomainError):
    """Raised when work-order routing targets a missing, archived, or
    non-Supervisor user. An unrouted work order (None) is always valid. Maps to
    400."""


class WorkOrderNotFoundError(DomainError):
    """Raised when a service is asked to operate on a work order that does not
    exist, is archived, or is not visible to the caller. Visibility failures
    deliberately surface as not-found rather than 403 so the API does not reveal
    the existence of work orders a user may not see
    (`domain.work_orders.can_view_work_order`).

    Also raised by `services.work_orders.resolve_work_order` when a scan-and-go
    or Mass Stage reference names a number no import has brought in: work orders
    are import-only, so an unknown number is a dead end, not a new work order.
    Maps to 404."""


class WorkOrderAssignmentConflictError(DomainError):
    """Raised when a work-order routing write is based on a stale supervisor
    value. Carries the current supervisor's display name when one is assigned
    and maps to 409."""

    def __init__(self, supervisor_name: Optional[str] = None):
        self.supervisor_name = supervisor_name
        if supervisor_name:
            message = (
                "This Work Order was already assigned to "
                f"{supervisor_name}"
            )
        else:
            message = "This Work Order assignment changed. Refresh and try again."
        super().__init__(message)


class WorkOrderStateError(DomainError):
    """Raised for a work-order lifecycle or mode violation -- for example, a
    status outside the live Created-to-Review workflow, closing before Review,
    or a mode outside `dispense` / `retroactive`. Maps to 400."""


class ToolNotFoundError(DomainError):
    """Raised when a service is asked to operate on a tool (by id or
    barcode) that does not exist, or is archived. Maps to 404."""


class DuplicateToolBarcodeError(DomainError):
    """Raised by `services.tools.create_tool` / `update_tool` when the
    barcode is already held by a *live* tool. Unlike items, tools have no
    archived-conflict/override flow -- an archived tool's barcode is simply
    free to reuse. Maps to 400."""


class ToolHasOutstandingCustodyError(DomainError):
    """Raised when an archive would hide a tool that still has a positive
    outstanding balance for one or more users. Maps to 400."""


class ToolReturnExceedsCheckedOutError(DomainError):
    """Raised by `services.tools.return_tool` when the quantity being
    returned exceeds what that user currently has checked out for this tool
    (`domain.tools.validate_return`). Carries both numbers for tests and
    messaging, mirroring `ReturnExceedsLoadedError`. Maps to 400."""

    def __init__(self, requested: Decimal, outstanding: Decimal):
        self.requested = requested
        self.outstanding = outstanding
        super().__init__(
            f"Cannot return {requested}: only {outstanding} checked out."
        )
