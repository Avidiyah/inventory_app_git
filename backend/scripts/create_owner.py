"""Bootstrap the initial Owner account.

The Create User UI is itself gated behind an authenticated, sufficiently
ranked user, so there is a chicken-and-egg problem for the very first
account. This one-time CLI breaks it by creating an Owner directly
against the database.

Run from the `backend/` directory with the project virtualenv:

    ./venv/Scripts/python.exe -m scripts.create_owner --username owner

You will be prompted for the password (entered twice, hidden). It must
be at least 4 characters, matching the application's password rule.

Safe to abort at any prompt. Fails cleanly if the username already
exists.
"""

import argparse
import getpass
import sys

# Allow running as `python scripts/create_owner.py` from backend/ as
# well as `python -m scripts.create_owner`.
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal  # noqa: E402
from app.domain.errors import DuplicateUsernameError  # noqa: E402
from app.domain.roles import ROLE_OWNER  # noqa: E402
from app.schemas.auth import MIN_PASSWORD_LENGTH  # noqa: E402
from app.services import auth as auth_service  # noqa: E402
from app.services import users as users_service  # noqa: E402


def _prompt_password() -> str:
    while True:
        password = getpass.getpass("Owner password: ")
        if len(password) < MIN_PASSWORD_LENGTH:
            print(
                f"Password must be at least {MIN_PASSWORD_LENGTH} characters.",
                file=sys.stderr,
            )
            continue
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            print("Passwords did not match. Try again.", file=sys.stderr)
            continue
        return password


def main() -> int:
    parser = argparse.ArgumentParser(description="Create the initial Owner user.")
    parser.add_argument("--username", required=True, help="Owner username.")
    args = parser.parse_args()

    username = args.username.strip()
    if not username:
        print("Username cannot be blank.", file=sys.stderr)
        return 1

    password = _prompt_password()

    db = SessionLocal()
    try:
        user = users_service.create_user(
            db,
            username=username,
            password_hash=auth_service.hash_password(password),
            role=ROLE_OWNER,
        )
    except DuplicateUsernameError:
        print(f'A user named "{username}" already exists.', file=sys.stderr)
        return 1
    finally:
        db.close()

    print(f'Created Owner "{user.username}" ({user.id}).')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
