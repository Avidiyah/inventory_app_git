"""Dependency-free contracts for the NetFacilities per-user cloud-auth path
(spec D1). Importing this module must never import the Steel SDK or
Playwright -- disabled deployments and service tests use these structural
protocols without constructing the concrete Steel runtime, mirroring
`app.integrations.netfacilities.contracts`.
"""

from __future__ import annotations

from typing import Protocol

from .contracts import NetFacilitiesClientContextProtocol


class CloudLoginSession(Protocol):
    """One in-progress cloud login ceremony, held open for its whole
    lifetime -- never silently reconnected mid-ceremony (spec §4: some
    cloud-browser platforms end the remote session when the CDP socket
    disconnects, so the connection opened in `open_login_session` is reused
    for every poll until `close_login_session`)."""

    session_id: str
    session_viewer_url: str


class CloudBrowserProvider(Protocol):
    """Vendor boundary for the cloud login ceremony, CSV capture (spec D3,
    D4), and per-job reconnect (spec D5). Wrapped behind this protocol so
    swapping to Browserbase later touches one adapter module, not the
    feature (spec D1)."""

    async def open_login_session(self) -> CloudLoginSession:
        """Open a cloud session and connect to it for this ceremony's whole
        lifetime; navigate it to the NetFacilities sign-in page."""

    async def poll_signed_in(self, session: CloudLoginSession) -> str | None:
        """Return the captured `storage_state()` JSON once signed in, else None."""

    async def poll_downloaded_csv(
        self, session: CloudLoginSession
    ) -> tuple[str, bytes] | None:
        """Return `(filename, bytes)` for a newly captured CSV export, else None."""

    async def close_login_session(self, session: CloudLoginSession) -> None:
        """Disconnect and release the cloud session (spec D5: not billed
        continuously once the ceremony ends)."""

    async def open_replay_context(
        self, storage_state: str
    ) -> NetFacilitiesClientContextProtocol:
        """Open a fresh, short-lived session and replay a saved
        `storage_state()` into it for one enrichment job (spec D5)."""
