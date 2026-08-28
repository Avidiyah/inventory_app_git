"""Dependency-free contracts for NetFacilities application wiring.

Importing this module must never import the Playwright transport or the HTML
parser. Disabled deployments and service tests use these structural protocols without
constructing the concrete integration runtime.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
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
    """Client lifetime owned by one enrichment job."""

    async def __aenter__(self) -> "NetFacilitiesClientProtocol": ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...


class NetFacilitiesAuthenticationClientProtocol(NetFacilitiesClientProtocol, Protocol):
    """Headed-browser actions for the in-app sign-in and the live session.

    The same client reads work orders once signed in, which is why this extends
    the read protocol: enrichment borrows it instead of launching a second
    browser (spec D4).
    """

    async def open_authentication_page(self) -> None: ...

    async def verify_authentication_page(self) -> None: ...

    async def prime_session(self) -> None: ...

    async def persist_authentication_state(self) -> None: ...

    def capture_downloads(
        self,
        destination: Path,
        on_saved: Callable[[Path], Awaitable[None]],
    ) -> None: ...

    def on_context_closed(self, callback: Callable[[], None]) -> None: ...


class NetFacilitiesAuthenticationContextProtocol(Protocol):
    """Context kept open only while an administrator signs in manually."""

    async def __aenter__(self) -> NetFacilitiesAuthenticationClientProtocol: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...
