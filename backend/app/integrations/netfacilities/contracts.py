"""Dependency-free contracts for NetFacilities application wiring.

Importing this module must never import the Playwright transport or the HTML
parser.  Disabled deployments and service tests use these structural protocols
without installing the local-only integration dependencies.
"""

from __future__ import annotations

from types import TracebackType
from typing import Protocol


class NetFacilitiesWorkOrderProjection(Protocol):
    """The only source fields the application enrichment service may consume."""

    work_order_number: str
    description: str
    priority: str | None


class NetFacilitiesClientProtocol(Protocol):
    """Small async boundary implemented by the concrete client and test fakes."""

    async def get_work_order(
        self,
        work_order_number: str,
    ) -> NetFacilitiesWorkOrderProjection:
        """Return one normalized, read-only source projection."""


class NetFacilitiesClientContextProtocol(NetFacilitiesClientProtocol, Protocol):
    """Client lifetime owned by one local enrichment job."""

    async def __aenter__(self) -> "NetFacilitiesClientProtocol": ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...


class NetFacilitiesAuthenticationClientProtocol(Protocol):
    """Headed-browser actions used by the in-app manual sign-in ceremony."""

    async def open_authentication_page(self) -> None: ...

    async def verify_authentication_page(self) -> None: ...

    async def persist_authentication_state(self) -> None: ...


class NetFacilitiesAuthenticationContextProtocol(Protocol):
    """Context kept open only while an administrator signs in manually."""

    async def __aenter__(self) -> NetFacilitiesAuthenticationClientProtocol: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...
