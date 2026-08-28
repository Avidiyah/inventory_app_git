"""Generate a Fernet key for NetFacilities cloud-auth session encryption
(spec D9).

Run once per environment, the same way as scripts/generate_vapid_keys.py.

Run from the `backend/` directory:

    ./venv/Scripts/python.exe -m scripts.generate_netfacilities_cloud_encryption_key

Store the result in `backend/.env` locally (already gitignored) and in the
Render dashboard for a deployed environment as
`NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY`. Rotating it makes every
previously captured cloud session undecryptable -- every enrolled user must
log in again.
"""

import sys

from cryptography.fernet import Fernet


def main() -> int:
    key = Fernet.generate_key().decode("ascii")
    print("NetFacilities cloud-auth encryption key generated. Store it as a secret.\n")
    print(f"NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY={key}")
    print(
        "\nRotating this key makes every previously captured cloud session "
        "undecryptable -- every enrolled user must log in again.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
