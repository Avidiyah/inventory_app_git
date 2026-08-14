"""Generate a VAPID keypair for Web Push.

Run once per environment. The public half is handed to browsers at subscribe
time; the private half signs a JWT on every send and is a secret on the level
of `DATABASE_URL`.

Run from the `backend/` directory:

    ./venv/Scripts/python.exe -m scripts.generate_vapid_keys

Store the private key in `backend/.env` locally (already gitignored) and in the
Render dashboard for a deployed environment. It must never be committed.

Rotating the keypair invalidates EVERY existing push subscription: the public
key is bound into the subscription by the browser at `subscribe()` time. A
rotation therefore forces every user to opt in again on every device. That is
the accepted cost of a leaked private key, and it is worth rehearsing once
before it is ever needed for real.
"""

import base64
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402


def _b64url(raw: bytes) -> str:
    """URL-safe base64 with padding stripped -- the encoding the Web Push specs
    use throughout, and the only one browsers accept for
    `applicationServerKey`."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def generate_vapid_keypair() -> tuple[str, str]:
    """Return `(private_key_b64, public_key_b64)`.

    The public half is the **raw uncompressed point** (0x04 || X || Y, 65
    bytes), deliberately not DER or PEM: `pushManager.subscribe()` rejects
    anything else, and the failure is quiet enough to be worth stating here as
    well as in the tests.

    The private half is PKCS#8 DER, base64url-encoded -- a form `py_vapid`
    reads with `Vapid02.from_string`, which auto-detects RAW vs DER. That is
    the exact code path `pywebpush` uses to sign, so the keypair round-trips
    through the machinery that will actually use it.
    """
    private_key = ec.generate_private_key(ec.SECP256R1())

    public_raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    private_der = private_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    return _b64url(private_der), _b64url(public_raw)


def main() -> int:
    private, public = generate_vapid_keypair()

    print("VAPID keypair generated. Store the private key as a secret.\n")
    print(f"VAPID_PRIVATE_KEY={private}")
    print(f"VAPID_PUBLIC_KEY={public}")
    print(
        "\nThe public key is not a secret -- browsers receive it. "
        "The private key must never be committed.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
