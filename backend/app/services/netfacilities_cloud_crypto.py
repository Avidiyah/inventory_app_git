"""Encryption at rest for captured NetFacilities cloud-auth session state.

`storage_state` (spec D8) is a bearer-equivalent credential -- the same
class of secret as `playwright-storage-state.json` today -- but this is the
first time such a credential lives in the primary Postgres database rather
than one trusted local file or Render secret file (spec D9). The key is
held only in the environment, never in the database, so a database dump
alone cannot decrypt any captured session.

`NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY` must be a urlsafe-base64
32-byte Fernet key -- generate one with
`python -m scripts.generate_netfacilities_cloud_encryption_key`. Missing or
malformed keeps the capability unavailable rather than silently storing
plaintext, mirroring `NetFacilitiesUnavailable`'s fail-closed pattern in
`app.integrations.netfacilities.config`.
"""

from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken


class NetFacilitiesCloudCryptoUnavailable(Exception):
    """Raised when the encryption key is missing, malformed, or rejects a token."""


def _fernet() -> Fernet:
    raw = os.getenv("NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY", "").strip()
    if not raw:
        raise NetFacilitiesCloudCryptoUnavailable(
            "NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY is not configured."
        )
    try:
        return Fernet(raw.encode("ascii"))
    except ValueError as exc:
        raise NetFacilitiesCloudCryptoUnavailable(
            "NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY is malformed."
        ) from exc


def is_configured() -> bool:
    try:
        _fernet()
    except NetFacilitiesCloudCryptoUnavailable:
        return False
    return True


def encrypt_storage_state(raw: str) -> bytes:
    """Encrypt a Playwright `storage_state()` JSON string for storage."""

    return _fernet().encrypt(raw.encode("utf-8"))


def decrypt_storage_state(token: bytes) -> str:
    """Decrypt a stored token back into the `storage_state()` JSON string."""

    try:
        return _fernet().decrypt(token).decode("utf-8")
    except InvalidToken as exc:
        raise NetFacilitiesCloudCryptoUnavailable(
            "Stored NetFacilities cloud session state could not be decrypted."
        ) from exc
