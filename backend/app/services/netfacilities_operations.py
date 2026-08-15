"""Single-owner admission control for the protected NetFacilities profile."""

from __future__ import annotations

import asyncio
from typing import Literal, TypeAlias
from uuid import UUID, uuid4

from app.integrations.netfacilities.errors import NetFacilitiesOperationInProgress


OperationKind: TypeAlias = Literal["authentication", "enrichment"]


class NetFacilitiesOperationGate:
    """Issue one opaque lease so browser operations cannot share a profile."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._lease: UUID | None = None
        self._kind: OperationKind | None = None

    async def acquire(self, kind: OperationKind) -> UUID:
        async with self._lock:
            if self._lease is not None:
                raise NetFacilitiesOperationInProgress(
                    "Another NetFacilities operation is already running."
                )
            lease = uuid4()
            self._lease = lease
            self._kind = kind
            return lease

    async def release(self, lease: UUID) -> None:
        async with self._lock:
            if self._lease == lease:
                self._lease = None
                self._kind = None

    async def active_kind(self) -> OperationKind | None:
        async with self._lock:
            return self._kind


operation_gate = NetFacilitiesOperationGate()
