"""Borrow the signed-in NetFacilities window for one enrichment job.

Layer: services. The job coordinator treats this exactly like the headless
client context it launches itself -- ``async with`` yields a client with
``get_work_order`` -- except that leaving the block hands the window back
instead of closing it (spec D4, D8). The coordinator refuses to close the
window while it is borrowed.
"""

from __future__ import annotations

from types import TracebackType
from typing import TYPE_CHECKING

from app.integrations.netfacilities.contracts import NetFacilitiesClientProtocol

if TYPE_CHECKING:  # pragma: no cover - import cycle guard for type checkers only
    from app.services.netfacilities_auth import (
        NetFacilitiesAuthenticationCoordinator,
    )


class LiveSessionClientContext:
    """Enter to borrow the live client; exit to return it. Never closes it."""

    def __init__(self, coordinator: "NetFacilitiesAuthenticationCoordinator") -> None:
        self._coordinator = coordinator

    async def __aenter__(self) -> NetFacilitiesClientProtocol:
        return await self._coordinator.borrow_started()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._coordinator.borrow_finished()
