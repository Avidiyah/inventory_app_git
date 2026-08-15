"""Secret-safe exception vocabulary for the NetFacilities boundary."""


class NetFacilitiesError(Exception):
    """Base class for expected NetFacilities integration failures."""


class NetFacilitiesInvalidWorkOrderNumber(NetFacilitiesError, ValueError):
    """Raised before I/O when a work-order number is not a positive integer."""


class NetFacilitiesAuthenticationRequired(NetFacilitiesError):
    """Raised when the dedicated NetFacilities session is not authenticated."""


class NetFacilitiesWorkOrderNotFound(NetFacilitiesError):
    """Raised when NetFacilities reports that the requested work order is absent."""


class NetFacilitiesPermissionDenied(NetFacilitiesError):
    """Raised when the authenticated account may not view the work order."""


class NetFacilitiesUnavailable(NetFacilitiesError):
    """Raised for browser startup, timeout, or upstream availability failures."""


class NetFacilitiesOperationInProgress(NetFacilitiesError):
    """Raised when authentication and enrichment would overlap one profile."""


class NetFacilitiesAuthenticationNotPending(NetFacilitiesError):
    """Raised when confirm/cancel has no active headed sign-in ceremony."""


class NetFacilitiesUnexpectedResponse(NetFacilitiesError):
    """Raised when status, redirect, host, or content type violates the contract."""


class NetFacilitiesUnexpectedDocument(NetFacilitiesError):
    """Raised when returned HTML is not the expected work-order document."""


class NetFacilitiesUnsafeProfilePath(NetFacilitiesError, ValueError):
    """Raised when browser authentication state would be stored in the repository."""
