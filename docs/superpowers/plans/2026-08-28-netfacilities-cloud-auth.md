# NetFacilities Cloud Auth (Per-User) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let any authorized user (TechFM OA+/Admin), on any device, log into
NetFacilities live through a cloud browser (Steel) from the deployed Render
app, so enrichment can read work orders on their behalf without needing the
owner's Windows machine.

**Architecture:** A `CloudBrowserProvider` protocol isolates the Steel SDK
behind one adapter module (`cloud_steel.py`), exactly the way
`NetFacilitiesClientContextProtocol` already isolates Playwright. The login
ceremony reuses `NetFacilitiesClient`'s existing verify/prime logic by
injecting a Steel-provided, CDP-connected Playwright context into it (the
class already supports this via its `_context` constructor parameter) — no
read/parse logic is rewritten, only how the browser context is obtained.
Captured `storage_state()` is Fernet-encrypted and stored per-user in a new
Postgres table; enrichment reconnects by replaying it into a fresh, short-
lived Steel session per job.

**Tech Stack:** FastAPI, SQLAlchemy/Alembic, Playwright (existing), Steel
Python SDK (`steel-sdk`, new), `cryptography` (already installed
transitively, newly pinned direct).

**Spec:** `docs/superpowers/specs/2026-08-28-netfacilities-cloud-auth-design.md`
(decisions D1–D11 referenced by letter throughout this plan). Builds on
`docs/superpowers/specs/2026-08-28-netfacilities-live-session-design.md`
(IMP-039), which is not modified.

## Global Constraints

- `NETFACILITIES_CLOUD_AUTH_ENABLED` must default `false` (spec §4) and
  additionally requires the base `NETFACILITIES_ENABLED` capability to be on
  (spec §2) — this is additive, never a replacement.
- Steel's 15-minute session cap bounds both the login ceremony and each
  reconnect-per-job enrichment run (spec §4). The login ceremony's own idle
  timeout must stay under 15 minutes with margin (840s default).
- The Steel API key and the storage-state encryption key are both secrets
  with production blast radius; never in `render.yaml`, only in Render's
  secret store, read via `os.getenv` the same way `VAPID_PRIVATE_KEY` is
  (spec §4, D9).
- `storage_state` must never appear in a log line or an API response body,
  and neither must `steel_profile_id` (spec D9).
- `services/netfacilities_auth.py`, `services/netfacilities_live_session.py`,
  and the existing shared-secret-file path are not modified by this plan
  (spec §2).
- Offline-fakes testing only (spec D11): no automated test may call the real
  Steel API. The one thing that cannot be tested offline — whether raw
  `storage_state()` replay works against a fresh Steel session — is Task 1,
  done once, by a human, before any other task is built on the assumption.

---

## Task 1: Manual D5/D6 replay spike (human-run, gates the reconnect design)

Confirms the single open question the whole reconnect design (D5) depends
on: does a Playwright `storage_state()` snapshot, captured once and replayed
into a brand-new Steel session later with no further vendor involvement,
actually work? Spec §1 and D11 are explicit that this cannot be tested
offline — it needs a real Steel account and a real NetFacilities login.

This task does not follow the usual failing-test → implementation cycle:
there is nothing to unit-test here, only a real vendor and a real human to
run it once.

**Files:**
- Create: `backend/scripts/netfacilities_cloud_replay_spike.py`

**Interfaces:**
- Produces: nothing any later task imports. This script is throwaway --
  its only output is a PASS/FAIL finding recorded in the spec file (Step 6).

- [ ] **Step 1: Write the spike script**

```python
"""Manual, human-run verification of the NetFacilities cloud-auth D5/D6
replay assumption (spec S1, D5, D6, D11).

Not part of the application and never run in CI. Requires a real Steel
account (STEEL_API_KEY) and real NetFacilities credentials.

Run from the `backend/` directory:

    STEEL_API_KEY=... ./venv/Scripts/python.exe -m scripts.netfacilities_cloud_replay_spike capture
    STEEL_API_KEY=... ./venv/Scripts/python.exe -m scripts.netfacilities_cloud_replay_spike replay

`capture` opens a Steel session, prints its live-view URL, waits for you to
sign into NetFacilities in that tab, then saves the session's
`storage_state()` to `netfacilities_cloud_spike_state.json` in the current
directory.

`replay` opens a brand-new Steel session -- no relation to the one `capture`
used -- replays the saved state into it via `new_context(storage_state=...)`,
and makes one read-only GET of `/myhome`. Prints PASS if NetFacilities
accepted the replayed cookies without redirecting to the login page, FAIL
otherwise. The exact attribute names used below
(`session.session_viewer_url`, `session.websocket_url`) are the Python SDK's
documented snake_case convention as of 2026-08-28 -- if either raises
AttributeError, run `print(session.model_dump())` and correct the name
before treating a failure as a real D5 finding.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from playwright.async_api import async_playwright

STATE_FILE = "netfacilities_cloud_spike_state.json"
HOME_URL = "https://system.netfacilities.com/myhome"
LOGIN_PATH_PREFIX = "/account/login"


def _api_key() -> str:
    key = os.environ.get("STEEL_API_KEY", "").strip()
    if not key:
        raise SystemExit("Set STEEL_API_KEY before running this script.")
    return key


async def _capture(api_key: str) -> None:
    from steel import AsyncSteel

    client = AsyncSteel(steel_api_key=api_key)
    session = await client.sessions.create()
    print(f"Live view: {session.session_viewer_url}")
    print("Log into NetFacilities in that tab now.")
    await asyncio.to_thread(
        input,
        "Press Enter once you are signed in and the NetFacilities home page "
        "has loaded: ",
    )

    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(
            f"{session.websocket_url}&apiKey={api_key}"
        )
        try:
            context = browser.contexts[0]
            state = await context.storage_state()
        finally:
            await browser.close()

    with open(STATE_FILE, "w", encoding="utf-8") as handle:
        json.dump(state, handle)
    await client.sessions.release(session.id)
    print(f"Saved {STATE_FILE}. Now run: ... replay")


async def _replay(api_key: str) -> None:
    from steel import AsyncSteel

    client = AsyncSteel(steel_api_key=api_key)
    session = await client.sessions.create()
    print(f"Live view (nothing to do here): {session.session_viewer_url}")

    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(
            f"{session.websocket_url}&apiKey={api_key}"
        )
        try:
            context = await browser.new_context(storage_state=STATE_FILE)
            page = await context.new_page()
            response = await page.goto(HOME_URL, wait_until="domcontentloaded")
            landed_on_login = LOGIN_PATH_PREFIX in page.url
            status = response.status if response is not None else None
        finally:
            await browser.close()

    await client.sessions.release(session.id)
    if status == 200 and not landed_on_login:
        print("PASS -- raw storage_state() replay worked against a fresh "
              "Steel session. D5 holds; build the reconnect path on it.")
        return
    print(f"FAIL -- status={status} landed_on_login={landed_on_login}. "
          "D5 does not hold as researched; implement the D6 Profiles-API "
          "fallback instead before writing Task 8.")
    sys.exit(1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["capture", "replay"])
    args = parser.parse_args()
    api_key = _api_key()
    if args.mode == "capture":
        asyncio.run(_capture(api_key))
    else:
        asyncio.run(_replay(api_key))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Prepare a real Steel account**

Sign up at steel.dev (free credit per spec §1's research), create an API
key, and `pip install steel-sdk==0.19.0` into the local venv temporarily
(this becomes a permanent `requirements.txt` entry in Task 5 only once this
spike confirms the design is worth building).

- [ ] **Step 3: Run the capture phase**

```bash
cd backend
STEEL_API_KEY=<your key> ./venv/Scripts/python.exe -m scripts.netfacilities_cloud_replay_spike capture
```

Open the printed live-view URL, sign into NetFacilities for real (this is
the owner's real vendor account -- coordinate with them before running
this), then press Enter as prompted.

- [ ] **Step 4: Run the replay phase**

```bash
STEEL_API_KEY=<your key> ./venv/Scripts/python.exe -m scripts.netfacilities_cloud_replay_spike replay
```

Note the exact PASS/FAIL line and, on FAIL, the `status=`/`landed_on_login=`
values printed.

- [ ] **Step 5: Record the finding in the spec**

Edit `docs/superpowers/specs/2026-08-28-netfacilities-cloud-auth-design.md`
and add, immediately after the D5 row of the decisions table in §3:

```markdown
**Spike result (recorded <date>):** <PASS -- raw replay confirmed working
against a fresh Steel session, no Profiles API needed. | FAIL -- raw replay
did not carry the session; Task 8 must implement the D6 Profiles-API path
instead of the raw-replay path.> Observed: status=<status>,
landed_on_login=<bool>.
```

- [ ] **Step 6: Commit**

```bash
git add backend/scripts/netfacilities_cloud_replay_spike.py docs/superpowers/specs/2026-08-28-netfacilities-cloud-auth-design.md
git commit -m "spike: verify NetFacilities cloud storage_state replay (D5/D6)"
```

If the result is FAIL, stop here and get the plan owner to confirm Task 8
should be rewritten for the D6 Profiles-API path before continuing to Task
2 — this is a design fork, not a code fix, and the remaining tasks below
are written assuming a PASS.

---

## Task 2: Cloud-session encryption at rest (spec D9)

Resolves spec §5's third open question. `cryptography` (Fernet) is already
installed transitively via `pywebpush` → `py_vapid` at version `50.0.0` in
this environment (verified: `python -c "import cryptography;
print(cryptography.__version__)"` → `50.0.0`) — this task makes it a direct,
pinned dependency since the new code below imports it directly, following
the same "one secret in the environment, never in the database" precedent
`VAPID_PRIVATE_KEY` already establishes in `app/services/push.py`.

**Files:**
- Create: `backend/app/services/netfacilities_cloud_crypto.py`
- Create: `backend/scripts/generate_netfacilities_cloud_encryption_key.py`
- Test: `backend/tests/test_netfacilities_cloud_crypto.py`
- Modify: `backend/requirements.txt`

**Interfaces:**
- Produces: `encrypt_storage_state(raw: str) -> bytes`,
  `decrypt_storage_state(token: bytes) -> str`, `is_configured() -> bool`,
  `NetFacilitiesCloudCryptoUnavailable` (exception). Task 6 (the login
  coordinator) and Task 8 (the reconnect factory) both depend on these three
  functions and this one exception type.

- [ ] **Step 1: Write the failing tests**

```python
"""Offline tests for NetFacilities cloud-session encryption at rest (D9)."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from app.services import netfacilities_cloud_crypto as crypto


VALID_KEY = Fernet.generate_key().decode("ascii")


def test_encrypt_then_decrypt_round_trips(monkeypatch):
    monkeypatch.setenv("NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY", VALID_KEY)
    token = crypto.encrypt_storage_state('{"cookies": []}')
    assert crypto.decrypt_storage_state(token) == '{"cookies": []}'


def test_is_configured_true_with_valid_key(monkeypatch):
    monkeypatch.setenv("NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY", VALID_KEY)
    assert crypto.is_configured() is True


def test_is_configured_false_when_unset(monkeypatch):
    monkeypatch.delenv("NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY", raising=False)
    assert crypto.is_configured() is False


def test_encrypt_raises_when_key_missing(monkeypatch):
    monkeypatch.delenv("NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY", raising=False)
    with pytest.raises(crypto.NetFacilitiesCloudCryptoUnavailable):
        crypto.encrypt_storage_state("{}")


def test_encrypt_raises_when_key_malformed(monkeypatch):
    monkeypatch.setenv("NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY", "not-a-fernet-key")
    with pytest.raises(crypto.NetFacilitiesCloudCryptoUnavailable):
        crypto.encrypt_storage_state("{}")


def test_decrypt_raises_when_token_was_encrypted_with_a_different_key(monkeypatch):
    monkeypatch.setenv("NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY", VALID_KEY)
    token = crypto.encrypt_storage_state("{}")
    monkeypatch.setenv(
        "NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY",
        Fernet.generate_key().decode("ascii"),
    )
    with pytest.raises(crypto.NetFacilitiesCloudCryptoUnavailable):
        crypto.decrypt_storage_state(token)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_netfacilities_cloud_crypto.py -v`
Expected: FAIL / ImportError — `app.services.netfacilities_cloud_crypto` does not exist yet.

- [ ] **Step 3: Implement the crypto module**

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/Scripts/python.exe -m pytest tests/test_netfacilities_cloud_crypto.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Write the key-generation script**

```python
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
```

- [ ] **Step 6: Pin the dependency explicitly**

In `backend/requirements.txt`, add after the `pywebpush` block:

```
# Encrypts NetFacilities cloud-auth session state at rest (spec D9). Already
# present transitively via pywebpush -> py_vapid at this exact version
# (verified via `python -c "import cryptography; print(cryptography.__version__)"`
# -> 50.0.0); pinned directly now that app code imports it, not just a
# transitive dependency's transitive dependency.
cryptography==50.0.0
```

- [ ] **Step 7: Run the full test suite and commit**

Run: `./venv/Scripts/python.exe -m pytest -q`
Expected: PASS, no regressions.

```bash
git add backend/app/services/netfacilities_cloud_crypto.py backend/scripts/generate_netfacilities_cloud_encryption_key.py backend/tests/test_netfacilities_cloud_crypto.py backend/requirements.txt
git commit -m "feat(netfacilities): encrypt cloud-auth session state at rest (D9)"
```

---

## Task 3: `netfacilities_cloud_sessions` table (spec D8)

**Files:**
- Modify: `backend/app/models.py`
- Create: `backend/alembic/versions/fcbc2524ea62_add_netfacilities_cloud_sessions.py`
- Test: `backend/tests/test_models_netfacilities_cloud_session.py`

**Interfaces:**
- Produces: `app.models.NetFacilitiesCloudSession` with columns `id`,
  `user_id` (unique FK), `storage_state` (`Text`, Fernet ciphertext from
  Task 2's `encrypt_storage_state`), `steel_profile_id` (`Text`, nullable),
  `signed_in_at`, `last_download_filename`, `last_download_at`,
  `expires_at`, `created_at`. Task 6 writes rows here; Task 8 and Task 9
  read them.

- [ ] **Step 1: Write the failing test**

```python
"""Schema-level test for the netfacilities_cloud_sessions table (D8)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import NetFacilitiesCloudSession, User


def _user(db):
    user = User(
        username=f"tech-{uuid.uuid4().hex[:8]}",
        first_name="Test",
        last_name="User",
        password_hash="x",
        role="technician",
    )
    db.add(user)
    db.commit()
    return user


def test_one_cloud_session_per_user(db_session):
    # A plain str, not bytes: the column stores the ascii-decoded Fernet
    # token (see Task 6's `_persist`), never raw ciphertext bytes.
    user = _user(db_session)
    db_session.add(
        NetFacilitiesCloudSession(
            id=uuid.uuid4(),
            user_id=user.id,
            storage_state="ciphertext-one",
            signed_in_at=datetime.now(timezone.utc),
        )
    )
    db_session.commit()

    db_session.add(
        NetFacilitiesCloudSession(
            id=uuid.uuid4(),
            user_id=user.id,
            storage_state="ciphertext-two",
            signed_in_at=datetime.now(timezone.utc),
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_cascade_deletes_with_user(db_session):
    user = _user(db_session)
    db_session.add(
        NetFacilitiesCloudSession(
            id=uuid.uuid4(),
            user_id=user.id,
            storage_state="ciphertext",
            signed_in_at=datetime.now(timezone.utc),
        )
    )
    db_session.commit()

    db_session.delete(user)
    db_session.commit()

    assert db_session.query(NetFacilitiesCloudSession).count() == 0
```

Check `backend/tests/conftest.py` for the exact name of the fixture that
gives a real transactional session against the test database (it is
`db_session` in the existing `test_work_order_import.py`-style tests; use
whatever `conftest.py` actually defines if it differs).

- [ ] **Step 2: Run the test to verify it fails**

Run: `./venv/Scripts/python.exe -m pytest tests/test_models_netfacilities_cloud_session.py -v`
Expected: FAIL — `ImportError: cannot import name 'NetFacilitiesCloudSession'`.

- [ ] **Step 3: Add the model**

In `backend/app/models.py`, add near `PushSubscription` (both are per-user,
FK-unique-style tables):

```python
class NetFacilitiesCloudSession(Base):
    """One user's captured NetFacilities cloud-auth session (spec D8, D9).

    Per-user, not shared (spec D2): `user_id` is unique, so each authorized
    user has at most one captured session. `storage_state` is Fernet
    ciphertext (`app.services.netfacilities_cloud_crypto`), never the
    plaintext Playwright snapshot -- decrypt it only at the moment a
    reconnect needs it (Task 8), and never return it or `steel_profile_id`
    in any API response. `steel_profile_id` is populated only if the D6
    Profiles-API fallback is in use; both columns exist from day one so
    that fallback needs no migration, only a code path change.

    `expires_at` is set only once an enrichment attempt actually reports
    `authentication_required` against this session (Task 9), mirroring how
    the existing saved-state expiry is detected today
    (`routers/netfacilities.py::_saved_state_refreshed_after`) rather than
    guessed from a TTL.
    """

    __tablename__ = "netfacilities_cloud_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    storage_state = Column(Text, nullable=False)
    steel_profile_id = Column(Text, nullable=True)
    signed_in_at = Column(DateTime(timezone=True), nullable=False)
    last_download_filename = Column(Text, nullable=True)
    last_download_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    user = relationship("User", foreign_keys=[user_id])
```

And on `User`, alongside the existing `push_subscriptions` relationship:

```python
    netfacilities_cloud_session = relationship(
        "NetFacilitiesCloudSession",
        back_populates=None,
        uselist=False,
        cascade="all, delete-orphan",
    )
```

- [ ] **Step 4: Write the migration**

```python
"""add netfacilities_cloud_sessions

Revision ID: fcbc2524ea62
Revises: a2c4e6b8d0f1
Create Date: 2026-08-28 12:00:00.000000

Backs the per-user NetFacilities cloud-auth path (spec
docs/superpowers/specs/2026-08-28-netfacilities-cloud-auth-design.md, D8).
Nothing to backfill: no cloud session can exist before this feature ships.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "fcbc2524ea62"
down_revision: Union[str, Sequence[str], None] = "a2c4e6b8d0f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "netfacilities_cloud_sessions",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "user_id",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("storage_state", sa.Text(), nullable=False),
        sa.Column("steel_profile_id", sa.Text(), nullable=True),
        sa.Column("signed_in_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_download_filename", sa.Text(), nullable=True),
        sa.Column("last_download_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("netfacilities_cloud_sessions")
```

- [ ] **Step 5: Run the migration and the test**

```bash
./venv/Scripts/python.exe -m alembic upgrade head
./venv/Scripts/python.exe -m pytest tests/test_models_netfacilities_cloud_session.py -v
```
Expected: migration applies cleanly, both tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/models.py backend/alembic/versions/fcbc2524ea62_add_netfacilities_cloud_sessions.py backend/tests/test_models_netfacilities_cloud_session.py
git commit -m "feat(netfacilities): add netfacilities_cloud_sessions table (D8)"
```

---

## Task 4: Cloud config + feature flag + `CloudBrowserProvider` protocol (spec D1, §4)

**Files:**
- Create: `backend/app/integrations/netfacilities/cloud_config.py`
- Create: `backend/app/integrations/netfacilities/cloud_contracts.py`
- Test: `backend/tests/test_netfacilities_cloud_config.py`

**Interfaces:**
- Consumes: `NetFacilitiesConfig` (from `.config`, Task-independent,
  already exists), `netfacilities_cloud_crypto.is_configured()` (Task 2).
- Produces: `NetFacilitiesCloudConfig` (fields: `enabled: bool`,
  `steel_api_key: str | None`, `login_timeout_seconds: int`,
  `batch_session_seconds: int`), `load_netfacilities_cloud_config(base,
  environ=None) -> NetFacilitiesCloudConfig`, and the `CloudBrowserProvider`
  Protocol + `CloudLoginSession` Protocol that Task 5's adapter implements
  and Task 6's coordinator depends on.

- [ ] **Step 1: Write the failing tests**

```python
"""Offline tests for cloud-auth configuration (spec D1, §4)."""

from __future__ import annotations

from cryptography.fernet import Fernet

from app.integrations.netfacilities.cloud_config import load_netfacilities_cloud_config
from app.integrations.netfacilities.config import NetFacilitiesConfig


VALID_KEY = Fernet.generate_key().decode("ascii")
ENABLED_BASE = NetFacilitiesConfig(
    enabled=True,
    profile_dir=None,
    browser_channel="chrome",
    request_timeout_seconds=30,
    auth_timeout_seconds=900,
    batch_timeout_seconds=1_800,
)
DISABLED_BASE = NetFacilitiesConfig(
    enabled=False,
    profile_dir=None,
    browser_channel="chrome",
    request_timeout_seconds=30,
    auth_timeout_seconds=900,
    batch_timeout_seconds=1_800,
)


def _environ(**overrides):
    base = {
        "NETFACILITIES_CLOUD_AUTH_ENABLED": "true",
        "STEEL_API_KEY": "test-key",
        "NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY": VALID_KEY,
    }
    base.update(overrides)
    return base


def test_disabled_when_base_capability_off():
    config = load_netfacilities_cloud_config(DISABLED_BASE, _environ())
    assert config.enabled is False


def test_disabled_when_flag_unset():
    config = load_netfacilities_cloud_config(
        ENABLED_BASE, _environ(NETFACILITIES_CLOUD_AUTH_ENABLED="")
    )
    assert config.enabled is False


def test_disabled_when_steel_api_key_missing():
    config = load_netfacilities_cloud_config(ENABLED_BASE, _environ(STEEL_API_KEY=""))
    assert config.enabled is False


def test_disabled_when_encryption_key_missing():
    config = load_netfacilities_cloud_config(
        ENABLED_BASE, _environ(NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY="")
    )
    assert config.enabled is False


def test_enabled_with_every_prerequisite():
    config = load_netfacilities_cloud_config(ENABLED_BASE, _environ())
    assert config.enabled is True
    assert config.steel_api_key == "test-key"
    assert config.login_timeout_seconds == 840


def test_custom_login_timeout():
    config = load_netfacilities_cloud_config(
        ENABLED_BASE,
        _environ(NETFACILITIES_CLOUD_LOGIN_TIMEOUT_SECONDS="300"),
    )
    assert config.login_timeout_seconds == 300
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/Scripts/python.exe -m pytest tests/test_netfacilities_cloud_config.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Write the dependency-free contracts module**

```python
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
```

- [ ] **Step 4: Write the config module**

```python
"""Fail-closed configuration for the per-user NetFacilities cloud-auth path.

Additive to `app.integrations.netfacilities.config` (spec §2): this feature
requires a paid third-party account and a database encryption key, so it
must default fully off, independently of the existing `NETFACILITIES_ENABLED`
capability. Safe to call even when the base capability is disabled -- it
always reports `enabled=False` in that case, never raises.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os

from app.services import netfacilities_cloud_crypto

from .config import NetFacilitiesConfig
from .errors import NetFacilitiesUnavailable

# Steel's session cap is 15 minutes (spec §1, §4); both defaults leave margin
# for the ceremony/job to notice expiry and close cleanly rather than being
# cut off mid-request.
DEFAULT_LOGIN_TIMEOUT_SECONDS = 840
DEFAULT_BATCH_SESSION_SECONDS = 840


@dataclass(frozen=True, slots=True)
class NetFacilitiesCloudConfig:
    """Validated cloud-auth capability settings with no network side effects."""

    enabled: bool
    steel_api_key: str | None = None
    login_timeout_seconds: int = DEFAULT_LOGIN_TIMEOUT_SECONDS
    batch_session_seconds: int = DEFAULT_BATCH_SESSION_SECONDS


def load_netfacilities_cloud_config(
    base: NetFacilitiesConfig,
    environ: Mapping[str, str] | None = None,
) -> NetFacilitiesCloudConfig:
    """Read cloud-auth configuration. Disabled unless every prerequisite holds:
    the base capability, the feature flag, a Steel API key, and a working
    encryption key (spec D9)."""

    values = os.environ if environ is None else environ
    if not base.enabled:
        return NetFacilitiesCloudConfig(enabled=False)
    if not _enabled(values.get("NETFACILITIES_CLOUD_AUTH_ENABLED")):
        return NetFacilitiesCloudConfig(enabled=False)

    api_key = values.get("STEEL_API_KEY", "").strip()
    if not api_key:
        return NetFacilitiesCloudConfig(enabled=False)

    # is_configured() reads NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY from
    # os.environ directly; when `environ` overrides it for a test, mirror
    # that override so the check sees the same value being tested.
    encryption_key = values.get("NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY")
    if environ is not None:
        if not encryption_key or not encryption_key.strip():
            return NetFacilitiesCloudConfig(enabled=False)
        os.environ["NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY"] = encryption_key
    if not netfacilities_cloud_crypto.is_configured():
        return NetFacilitiesCloudConfig(enabled=False)

    return NetFacilitiesCloudConfig(
        enabled=True,
        steel_api_key=api_key,
        login_timeout_seconds=_positive_seconds(
            values,
            "NETFACILITIES_CLOUD_LOGIN_TIMEOUT_SECONDS",
            DEFAULT_LOGIN_TIMEOUT_SECONDS,
        ),
        batch_session_seconds=_positive_seconds(
            values,
            "NETFACILITIES_CLOUD_BATCH_SESSION_SECONDS",
            DEFAULT_BATCH_SESSION_SECONDS,
        ),
    )


def _enabled(raw: str | None) -> bool:
    if raw is None or not raw.strip():
        return False
    normalized = raw.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise NetFacilitiesUnavailable(
        "NETFACILITIES_CLOUD_AUTH_ENABLED must be either true or false."
    )


def _positive_seconds(values: Mapping[str, str], name: str, default: int) -> int:
    raw = values.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        seconds = int(raw)
    except ValueError as exc:
        raise NetFacilitiesUnavailable(f"{name} must be a positive whole number.") from exc
    if seconds <= 0:
        raise NetFacilitiesUnavailable(f"{name} must be a positive whole number.")
    return seconds
```

Note on Step 4's `_environ` test override: `netfacilities_cloud_crypto.is_configured()`
reads the real `os.environ`, not the `environ` mapping passed into
`load_netfacilities_cloud_config`. The implementation above bridges this by
writing the test's encryption key into `os.environ` when an override
mapping is supplied — acceptable here because `monkeypatch.setenv` in the
test suite already isolates and restores `os.environ` per test; production
calls (with `environ=None`) never take this branch.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `./venv/Scripts/python.exe -m pytest tests/test_netfacilities_cloud_config.py -v`
Expected: PASS (6 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/integrations/netfacilities/cloud_config.py backend/app/integrations/netfacilities/cloud_contracts.py backend/tests/test_netfacilities_cloud_config.py
git commit -m "feat(netfacilities): cloud-auth config and CloudBrowserProvider contract (D1)"
```

---

## Task 5: Steel adapter (spec D1, D3, D4)

Only this module imports the Steel SDK, mirroring how `factory.py` isolates
Playwright behind `NetFacilitiesClientContextProtocol`. Reuses
`NetFacilitiesClient`'s existing `verify_authentication_page` /
`prime_session` / `open_authentication_page` by injecting a Steel-provided,
CDP-connected context into it via the class's existing `_context`
constructor parameter — no read/parse logic is duplicated.

**Files:**
- Create: `backend/app/integrations/netfacilities/cloud_steel.py`
- Test: `backend/tests/test_netfacilities_cloud_steel.py`
- Modify: `backend/requirements.txt`

**Interfaces:**
- Consumes: `CloudBrowserProvider`/`CloudLoginSession` (Task 4),
  `NetFacilitiesClient` (existing, `client.py`).
- Produces: `SteelCloudBrowserProvider(api_key: str)` implementing
  `CloudBrowserProvider`. Task 6 constructs one per process; Task 8 reuses
  `open_replay_context`.

- [ ] **Step 1: Write the failing tests against a fake Steel/Playwright seam**

The adapter's own vendor calls (`AsyncSteel`, `connect_over_cdp`) cannot be
exercised offline (spec D11) — these tests fake the two functions the
adapter calls at its vendor boundary (`_create_steel_client` and
`_connect_over_cdp`, both defined as small seams in Step 2 specifically so
tests can monkeypatch them) and assert the adapter's own state machine:
which context it hands to `NetFacilitiesClient`, when it calls
`sessions.release`, and how it tracks "new since last poll" CSV filenames.

This project has no `pytest-asyncio` (verified: absent from
`requirements-dev.txt`, and `test_netfacilities_auth.py` wraps every async
exercise in a plain `def test_...(): asyncio.run(...)` instead) — follow
that exact convention below, not `@pytest.mark.asyncio`.

```python
"""Offline tests for the Steel cloud-browser adapter (spec D1, D3, D4).

Fakes stand in for the Steel SDK and Playwright's CDP connection -- the
adapter's own state machine (session bookkeeping, seen-files tracking,
session teardown) is what these tests verify, not the real vendor.
"""

from __future__ import annotations

import asyncio

from app.integrations.netfacilities import cloud_steel


class FakePage:
    def __init__(self, url):
        self.url = url


class FakeContext:
    def __init__(self, *, pages=None, state=None):
        self.pages = pages or []
        self._state = state or {"cookies": []}
        self.closed = False

    async def storage_state(self):
        return self._state

    def on(self, *_args, **_kwargs):
        return None


class FakeBrowser:
    def __init__(self, context):
        self.contexts = [context]
        self.closed = False

    async def close(self):
        self.closed = True


class FakeSteelSession:
    def __init__(self, session_id="sess-1"):
        self.id = session_id
        self.session_viewer_url = f"https://app.steel.dev/sessions/{session_id}"
        self.websocket_url = f"wss://connect.steel.dev/{session_id}"


class FakeSessionsResource:
    def __init__(self):
        self.created = []
        self.released = []

    async def create(self):
        session = FakeSteelSession()
        self.created.append(session)
        return session

    async def release(self, session_id):
        self.released.append(session_id)


class FakeSteelClient:
    def __init__(self):
        self.sessions = FakeSessionsResource()


async def _resolved(value):
    return value


def _provider(monkeypatch):
    provider = cloud_steel.SteelCloudBrowserProvider.__new__(cloud_steel.SteelCloudBrowserProvider)
    provider._api_key = "test-key"
    fake_client = FakeSteelClient()
    provider._client = fake_client
    return provider, fake_client


def test_open_login_session_creates_and_tracks_a_context(monkeypatch):
    provider, fake_client = _provider(monkeypatch)
    context = FakeContext(pages=[FakePage("https://system.netfacilities.com/account/login")])
    browser = FakeBrowser(context)
    monkeypatch.setattr(
        cloud_steel, "_connect_over_cdp", lambda *_args, **_kwargs: _resolved((None, browser))
    )

    session = asyncio.run(provider.open_login_session())

    assert session.session_id == "sess-1"
    assert session.session_viewer_url.endswith("sess-1")
    assert len(fake_client.sessions.created) == 1


def test_poll_signed_in_returns_none_before_login(monkeypatch):
    provider, _fake_client = _provider(monkeypatch)
    context = FakeContext(pages=[FakePage("https://system.netfacilities.com/account/login")])
    browser = FakeBrowser(context)
    monkeypatch.setattr(
        cloud_steel, "_connect_over_cdp", lambda *_args, **_kwargs: _resolved((None, browser))
    )

    async def _exercise():
        session = await provider.open_login_session()
        return await provider.poll_signed_in(session)

    result = asyncio.run(_exercise())

    assert result is None


def test_poll_signed_in_returns_state_json_after_login(monkeypatch):
    provider, _fake_client = _provider(monkeypatch)
    context = FakeContext(
        pages=[FakePage("https://system.netfacilities.com/myhome")],
        state={"cookies": [{"name": "session", "value": "abc"}]},
    )
    browser = FakeBrowser(context)
    monkeypatch.setattr(
        cloud_steel, "_connect_over_cdp", lambda *_args, **_kwargs: _resolved((None, browser))
    )

    async def _exercise():
        session = await provider.open_login_session()
        return await provider.poll_signed_in(session)

    result = asyncio.run(_exercise())

    assert result is not None
    assert "abc" in result


def test_close_login_session_releases_the_steel_session(monkeypatch):
    provider, fake_client = _provider(monkeypatch)
    context = FakeContext(pages=[FakePage("https://system.netfacilities.com/myhome")])
    browser = FakeBrowser(context)
    monkeypatch.setattr(
        cloud_steel, "_connect_over_cdp", lambda *_args, **_kwargs: _resolved((None, browser))
    )

    async def _exercise():
        session = await provider.open_login_session()
        await provider.close_login_session(session)

    asyncio.run(_exercise())

    assert browser.closed is True
    assert fake_client.sessions.released == ["sess-1"]
```

`_connect_over_cdp` (Step 3) returns `(playwright, browser)` — the fakes
above stub the pair as `(None, browser)` since these tests never touch the
`playwright` handle itself, only what the adapter does with `browser`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/Scripts/python.exe -m pytest tests/test_netfacilities_cloud_steel.py -v`
Expected: FAIL — `cloud_steel` module does not exist.

- [ ] **Step 3: Implement the adapter**

```python
"""Steel-backed implementation of `CloudBrowserProvider` (spec D1, D3, D4).

Only this module imports the Steel SDK or opens a CDP connection -- every
other cloud-auth module depends on `cloud_contracts.CloudBrowserProvider`,
so swapping vendors later is contained here.

One CDP connection is opened per login ceremony and reused for every poll
until `close_login_session` (spec §4: some cloud-browser platforms end the
remote session when the CDP socket disconnects, so this never reconnects
mid-ceremony). `_connect_over_cdp` and `_create_steel_client` are separated
into module-level functions purely so tests can monkeypatch the vendor
boundary without touching the adapter's own state machine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging

import httpx
from playwright.async_api import async_playwright

from .client import NetFacilitiesClient
from .errors import NetFacilitiesAuthenticationRequired, NetFacilitiesUnavailable

STEEL_FILES_API_BASE = "https://api.steel.dev/v1"
CSV_SUFFIX = ".csv"
DOWNLOAD_PATH = "/downloads"

logger = logging.getLogger(__name__)


def _create_steel_client(api_key: str):
    from steel import AsyncSteel

    return AsyncSteel(steel_api_key=api_key)


async def _connect_over_cdp(websocket_url: str, api_key: str):
    playwright = await async_playwright().start()
    browser = await playwright.chromium.connect_over_cdp(f"{websocket_url}&apiKey={api_key}")
    return playwright, browser


@dataclass
class _SteelLoginSession:
    session_id: str
    session_viewer_url: str
    _playwright: object
    _browser: object
    _client: NetFacilitiesClient
    _seen_files: set[str] = field(default_factory=set)


class SteelCloudBrowserProvider:
    """One `AsyncSteel` client, reused across every session this process opens."""

    def __init__(self, *, api_key: str) -> None:
        self._api_key = api_key
        self._client = _create_steel_client(api_key)

    async def open_login_session(self) -> _SteelLoginSession:
        try:
            steel_session = await self._client.sessions.create()
        except Exception as exc:  # vendor SDK's exception hierarchy, reclassified
            raise NetFacilitiesUnavailable(
                "Could not open a NetFacilities cloud browser session."
            ) from exc

        playwright, browser = await _connect_over_cdp(
            steel_session.websocket_url, self._api_key
        )
        context = browser.contexts[0]
        try:
            cdp_session = await context.new_cdp_session(await context.new_page())
            await cdp_session.send(
                "Browser.setDownloadBehavior",
                {"behavior": "allow", "downloadPath": DOWNLOAD_PATH, "eventsEnabled": True},
            )
        except Exception:
            logger.error("netfacilities.cloud_download_behavior_setup_failed")

        client = NetFacilitiesClient(profile_dir=None, headless=True, _context=context)
        await client.open_authentication_page()

        return _SteelLoginSession(
            session_id=steel_session.id,
            session_viewer_url=steel_session.session_viewer_url,
            _playwright=playwright,
            _browser=browser,
            _client=client,
        )

    async def poll_signed_in(self, session: _SteelLoginSession) -> str | None:
        try:
            await session._client.verify_authentication_page()
            await session._client.prime_session()
        except NetFacilitiesAuthenticationRequired:
            return None
        context = session._browser.contexts[0]
        state = await context.storage_state()
        return json.dumps(state)

    async def poll_downloaded_csv(
        self, session: _SteelLoginSession
    ) -> tuple[str, bytes] | None:
        async with httpx.AsyncClient(
            headers={"steel-api-key": self._api_key}, timeout=30.0
        ) as http:
            response = await http.get(
                f"{STEEL_FILES_API_BASE}/sessions/{session.session_id}/files"
            )
            response.raise_for_status()
            for entry in response.json().get("data", []):
                path = entry.get("path", "")
                if not path.casefold().endswith(CSV_SUFFIX):
                    continue
                if path in session._seen_files:
                    continue
                session._seen_files.add(path)
                file_response = await http.get(
                    f"{STEEL_FILES_API_BASE}/sessions/{session.session_id}/files/{path}"
                )
                file_response.raise_for_status()
                return path.rsplit("/", 1)[-1], file_response.content
        return None

    async def close_login_session(self, session: _SteelLoginSession) -> None:
        await session._browser.close()
        await self._client.sessions.release(session.session_id)

    async def open_replay_context(self, storage_state: str):
        """Open a fresh, short-lived session and replay saved storage_state
        into it (spec D5). Task 8 wraps the returned context."""

        try:
            steel_session = await self._client.sessions.create()
        except Exception as exc:
            raise NetFacilitiesUnavailable(
                "Could not open a NetFacilities cloud browser session for enrichment."
            ) from exc
        playwright, browser = await _connect_over_cdp(
            steel_session.websocket_url, self._api_key
        )
        context = await browser.new_context(storage_state=json.loads(storage_state))
        return _SteelEnrichmentContext(
            client=self,
            steel_session_id=steel_session.id,
            playwright=playwright,
            browser=browser,
            context=context,
        )


@dataclass
class _SteelEnrichmentContext:
    """Implements `NetFacilitiesClientContextProtocol` for one reconnected job."""

    client: "SteelCloudBrowserProvider"
    steel_session_id: str
    playwright: object
    browser: object
    context: object
    _wrapped: NetFacilitiesClient | None = None

    async def __aenter__(self) -> NetFacilitiesClient:
        self._wrapped = NetFacilitiesClient(
            profile_dir=None, headless=True, _context=self.context
        )
        return self._wrapped

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        try:
            await self.context.close()
            await self.browser.close()
        finally:
            await self.client._client.sessions.release(self.steel_session_id)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/Scripts/python.exe -m pytest tests/test_netfacilities_cloud_steel.py -v`
Expected: PASS

- [ ] **Step 5: Pin the new dependencies**

In `backend/requirements.txt`, after the `cryptography` line added in Task 2:

```
# Per-user NetFacilities cloud-auth login (spec D1). Verified against
# vendor docs 2026-08-28: package name `steel-sdk`, imports as `from steel
# import AsyncSteel`. Confirm session.session_viewer_url /
# session.websocket_url attribute names still match at upgrade time --
# they are Stainless-generated snake_case conversions of the vendor's
# camelCase API fields, not hand-documented.
steel-sdk==0.19.0
# Async HTTP client for Steel's Files API (spec D4) -- ships transitively
# with steel-sdk (Stainless SDKs are httpx-based) but pinned directly since
# cloud_steel.py imports it itself.
httpx>=0.27,<1
```

- [ ] **Step 6: Run the full test suite and commit**

Run: `./venv/Scripts/python.exe -m pytest -q`
Expected: PASS, no regressions.

```bash
git add backend/app/integrations/netfacilities/cloud_steel.py backend/tests/test_netfacilities_cloud_steel.py backend/requirements.txt
git commit -m "feat(netfacilities): Steel cloud-browser adapter (D1, D3, D4)"
```

---

## Task 6: Per-user login ceremony coordinator (spec D2, D3, D7)

Mirrors `NetFacilitiesAuthenticationCoordinator` (`services/netfacilities_auth.py`)
structurally, but keyed per `user_id` instead of one process-global window,
and persists the successful capture to the database instead of a local file.

**Files:**
- Create: `backend/app/services/netfacilities_cloud_auth.py`
- Test: `backend/tests/test_netfacilities_cloud_auth.py`

**Interfaces:**
- Consumes: `CloudBrowserProvider` (Task 4/5), `NetFacilitiesCloudConfig`
  (Task 4), `netfacilities_cloud_crypto.encrypt_storage_state` (Task 2),
  `NetFacilitiesCloudSession` model (Task 3), `app.database.SessionLocal`.
- Produces: `NetFacilitiesCloudAuthenticationSnapshot` (fields: `user_id`,
  `attempt_id`, `state`, `started_at`, `finished_at`, `failure`,
  `signed_in_at`, `last_download_filename`, `last_download_at`,
  `session_viewer_url`), `NetFacilitiesCloudAuthenticationCoordinator` with
  `async def start(user_id, config) -> NetFacilitiesCloudAuthenticationSnapshot`,
  `async def latest(user_id) -> NetFacilitiesCloudAuthenticationSnapshot | None`,
  `async def cancel(user_id) -> NetFacilitiesCloudAuthenticationSnapshot`,
  `def captured_csv_bytes(user_id) -> tuple[str, bytes] | None`. Task 7's
  routes call all four; Task 9 reads persisted DB rows this coordinator writes.

- [ ] **Step 1: Write the failing tests**

```python
"""Offline tests for the per-user NetFacilities cloud-auth coordinator
(spec D2, D3, D7)."""

from __future__ import annotations

import asyncio
import uuid

from cryptography.fernet import Fernet

from app.integrations.netfacilities.cloud_config import NetFacilitiesCloudConfig
from app.models import NetFacilitiesCloudSession, User
from app.services.netfacilities_cloud_auth import (
    NetFacilitiesCloudAuthenticationCoordinator,
)


class FakeLoginSession:
    def __init__(self, session_id="sess-1"):
        self.session_id = session_id
        self.session_viewer_url = f"https://app.steel.dev/sessions/{session_id}"


class FakeCloudBrowserProvider:
    def __init__(self):
        self.signed_in_after_polls = 1
        self._polls = 0
        self.closed_sessions = []
        self.csv_to_return = None

    async def open_login_session(self):
        return FakeLoginSession()

    async def poll_signed_in(self, session):
        self._polls += 1
        if self._polls < self.signed_in_after_polls:
            return None
        return '{"cookies": [{"name": "session", "value": "abc"}]}'

    async def poll_downloaded_csv(self, session):
        return self.csv_to_return

    async def close_login_session(self, session):
        self.closed_sessions.append(session.session_id)

    async def open_replay_context(self, storage_state):
        raise NotImplementedError


def _config(**overrides):
    settings = {"enabled": True, "steel_api_key": "test-key", "login_timeout_seconds": 60}
    settings.update(overrides)
    return NetFacilitiesCloudConfig(**settings)


def _user(db_session):
    user = User(
        username=f"tech-{uuid.uuid4().hex[:8]}",
        first_name="Test",
        last_name="User",
        password_hash="x",
        role="technician",
    )
    db_session.add(user)
    db_session.commit()
    return user


def test_start_then_captures_state_and_writes_encrypted_row(
    db_session, session_factory, monkeypatch
):
    monkeypatch.setenv(
        "NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY", Fernet.generate_key().decode()
    )
    user = _user(db_session)
    provider = FakeCloudBrowserProvider()
    coordinator = NetFacilitiesCloudAuthenticationCoordinator(
        provider_factory=lambda _config: provider,
        session_factory=session_factory,
        poll_seconds=0.01,
    )

    async def _run():
        snapshot = await coordinator.start(user.id, _config())
        assert snapshot.session_viewer_url.endswith("sess-1")
        for _ in range(200):
            latest = await coordinator.latest(user.id)
            if latest.state == "signed_in":
                return latest
            await asyncio.sleep(0.01)
        raise AssertionError("never reached signed_in")

    signed_in = asyncio.run(_run())
    assert signed_in.signed_in_at is not None

    row = (
        db_session.query(NetFacilitiesCloudSession)
        .filter_by(user_id=user.id)
        .one()
    )
    assert row.storage_state != '{"cookies": [{"name": "session", "value": "abc"}]}'


def test_two_users_get_independent_ceremonies(db_session, session_factory, monkeypatch):
    monkeypatch.setenv("NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY", Fernet.generate_key().decode())
    user_a = _user(db_session)
    user_b = _user(db_session)
    coordinator = NetFacilitiesCloudAuthenticationCoordinator(
        provider_factory=lambda _config: FakeCloudBrowserProvider(),
        session_factory=session_factory,
        poll_seconds=0.01,
    )

    async def _run():
        snap_a = await coordinator.start(user_a.id, _config())
        snap_b = await coordinator.start(user_b.id, _config())
        return snap_a, snap_b

    snap_a, snap_b = asyncio.run(_run())
    assert snap_a.attempt_id != snap_b.attempt_id


def test_cancel_closes_the_cloud_session(db_session, session_factory, monkeypatch):
    monkeypatch.setenv("NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY", Fernet.generate_key().decode())
    user = _user(db_session)
    provider = FakeCloudBrowserProvider()
    provider.signed_in_after_polls = 10_000  # never signs in during this test
    coordinator = NetFacilitiesCloudAuthenticationCoordinator(
        provider_factory=lambda _config: provider,
        session_factory=session_factory,
        poll_seconds=0.01,
    )

    async def _run():
        await coordinator.start(user.id, _config())
        await asyncio.sleep(0.02)
        return await coordinator.cancel(user.id)

    result = asyncio.run(_run())
    assert result.state == "cancelled"
    assert provider.closed_sessions == ["sess-1"]
```

`session_factory` here is a `pytest` fixture returning a callable that opens
a new SQLAlchemy `Session` against the same test database `db_session`
uses — check `backend/tests/conftest.py` for whether one already exists
(`test_netfacilities_jobs.py` needs the same thing for `NetFacilitiesJobCoordinator`'s
`session_factory` parameter); reuse it if present rather than adding a
second one.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/Scripts/python.exe -m pytest tests/test_netfacilities_cloud_auth.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the coordinator**

```python
"""Per-user NetFacilities cloud-auth login ceremony (spec D2, D3, D7).

Structurally mirrors `NetFacilitiesAuthenticationCoordinator`
(`services/netfacilities_auth.py`) -- same starting/signed_in/closed state
machine, same auto-poll-until-signed-in idea -- but keyed per `user_id`
instead of one process-global window, and persisting the successful capture
to `netfacilities_cloud_sessions` (encrypted, spec D9) instead of a local
file. No sharing between users (spec D2): each user's ceremony and captured
session are independent.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import logging
from typing import Literal, TypeAlias
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.integrations.netfacilities.cloud_config import NetFacilitiesCloudConfig
from app.integrations.netfacilities.cloud_contracts import CloudBrowserProvider
from app.integrations.netfacilities.errors import NetFacilitiesError
from app.models import NetFacilitiesCloudSession
from app.services import netfacilities_cloud_crypto as crypto


logger = logging.getLogger(__name__)

CloudAuthenticationState: TypeAlias = Literal[
    "starting", "awaiting_sign_in", "signed_in", "closed", "failed", "cancelled", "timed_out"
]
CloudAuthenticationFailure: TypeAlias = Literal["unavailable", "cancelled", "timed_out"]
ProviderFactory: TypeAlias = Callable[[NetFacilitiesCloudConfig], CloudBrowserProvider]
SessionFactory: TypeAlias = Callable[[], Session]

ACTIVE_STATES: frozenset[str] = frozenset({"starting", "awaiting_sign_in"})
DEFAULT_POLL_SECONDS = 1.0


@dataclass(frozen=True, slots=True)
class NetFacilitiesCloudAuthenticationSnapshot:
    """Secret-free per-user state safe to return to that user."""

    user_id: UUID
    attempt_id: UUID
    state: CloudAuthenticationState
    started_at: datetime
    finished_at: datetime | None = None
    failure: CloudAuthenticationFailure | None = None
    signed_in_at: datetime | None = None
    last_download_filename: str | None = None
    last_download_at: datetime | None = None
    session_viewer_url: str | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class _Ceremony:
    snapshot: NetFacilitiesCloudAuthenticationSnapshot
    provider: CloudBrowserProvider
    cloud_session: object
    poll_task: "asyncio.Task[None] | None" = None
    captured_csv: tuple[str, bytes] | None = None


class NetFacilitiesCloudAuthenticationCoordinator:
    """Own one login ceremony per user, keyed by `user_id`."""

    def __init__(
        self,
        *,
        provider_factory: ProviderFactory,
        session_factory: SessionFactory = SessionLocal,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
    ) -> None:
        self._provider_factory = provider_factory
        self._session_factory = session_factory
        self._poll_seconds = poll_seconds
        self._lock = asyncio.Lock()
        self._ceremonies: dict[UUID, _Ceremony] = {}

    async def start(
        self, user_id: UUID, config: NetFacilitiesCloudConfig
    ) -> NetFacilitiesCloudAuthenticationSnapshot:
        async with self._lock:
            existing = self._ceremonies.get(user_id)
            if existing is not None and existing.snapshot.state in ACTIVE_STATES | {"signed_in"}:
                return existing.snapshot

            provider = self._provider_factory(config)
            attempt = NetFacilitiesCloudAuthenticationSnapshot(
                user_id=user_id,
                attempt_id=uuid4(),
                state="starting",
                started_at=_now(),
            )
            try:
                cloud_session = await provider.open_login_session()
            except NetFacilitiesError:
                failed = replace(
                    attempt, state="failed", finished_at=_now(), failure="unavailable"
                )
                self._ceremonies[user_id] = _Ceremony(
                    snapshot=failed, provider=provider, cloud_session=None
                )
                raise

            awaiting = replace(
                attempt,
                state="awaiting_sign_in",
                session_viewer_url=cloud_session.session_viewer_url,
            )
            ceremony = _Ceremony(snapshot=awaiting, provider=provider, cloud_session=cloud_session)
            self._ceremonies[user_id] = ceremony
            ceremony.poll_task = asyncio.create_task(
                self._poll_until_signed_in(user_id, attempt.attempt_id, config),
                name=f"netfacilities-cloud-auth-{user_id}",
            )
            return awaiting

    async def latest(self, user_id: UUID) -> NetFacilitiesCloudAuthenticationSnapshot | None:
        async with self._lock:
            ceremony = self._ceremonies.get(user_id)
            return ceremony.snapshot if ceremony is not None else None

    async def cancel(self, user_id: UUID) -> NetFacilitiesCloudAuthenticationSnapshot:
        async with self._lock:
            ceremony = self._ceremonies.get(user_id)
            if ceremony is None:
                raise NetFacilitiesError("No NetFacilities cloud session is active.")
            if ceremony.poll_task is not None:
                ceremony.poll_task.cancel()
            await ceremony.provider.close_login_session(ceremony.cloud_session)
            finished = replace(
                ceremony.snapshot, state="cancelled", finished_at=_now(), failure="cancelled"
            )
            ceremony.snapshot = finished
            return finished

    def captured_csv_bytes(self, user_id: UUID) -> tuple[str, bytes] | None:
        ceremony = self._ceremonies.get(user_id)
        return ceremony.captured_csv if ceremony is not None else None

    async def _poll_until_signed_in(
        self, user_id: UUID, attempt_id: UUID, config: NetFacilitiesCloudConfig
    ) -> None:
        deadline = asyncio.get_running_loop().time() + config.login_timeout_seconds
        try:
            while asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(self._poll_seconds)
                async with self._lock:
                    ceremony = self._ceremonies.get(user_id)
                    if ceremony is None or ceremony.snapshot.attempt_id != attempt_id:
                        return
                    provider, cloud_session = ceremony.provider, ceremony.cloud_session
                state_json = await provider.poll_signed_in(cloud_session)
                if state_json is None:
                    continue
                await self._persist(user_id, state_json)
                async with self._lock:
                    ceremony = self._ceremonies.get(user_id)
                    if ceremony is None or ceremony.snapshot.attempt_id != attempt_id:
                        return
                    ceremony.snapshot = replace(
                        ceremony.snapshot, state="signed_in", signed_in_at=_now()
                    )
                await self._poll_for_csv(user_id, attempt_id)
                return
            await self._timeout(user_id, attempt_id)
        except asyncio.CancelledError:
            pass

    async def _poll_for_csv(self, user_id: UUID, attempt_id: UUID) -> None:
        while True:
            await asyncio.sleep(self._poll_seconds * 3)
            async with self._lock:
                ceremony = self._ceremonies.get(user_id)
                if (
                    ceremony is None
                    or ceremony.snapshot.attempt_id != attempt_id
                    or ceremony.snapshot.state != "signed_in"
                ):
                    return
                provider, cloud_session = ceremony.provider, ceremony.cloud_session
            found = await provider.poll_downloaded_csv(cloud_session)
            if found is None:
                continue
            filename, data = found
            async with self._lock:
                ceremony = self._ceremonies.get(user_id)
                if ceremony is None or ceremony.snapshot.attempt_id != attempt_id:
                    return
                ceremony.captured_csv = (filename, data)
                ceremony.snapshot = replace(
                    ceremony.snapshot,
                    last_download_filename=filename,
                    last_download_at=_now(),
                )
            logger.info(
                "netfacilities.cloud_csv_captured",
                extra={"fields": {"user_id": str(user_id)}},
            )

    async def _persist(self, user_id: UUID, state_json: str) -> None:
        token = crypto.encrypt_storage_state(state_json)
        db = self._session_factory()
        try:
            row = (
                db.query(NetFacilitiesCloudSession)
                .filter_by(user_id=user_id)
                .one_or_none()
            )
            if row is None:
                row = NetFacilitiesCloudSession(user_id=user_id, signed_in_at=_now())
                db.add(row)
            row.storage_state = token
            row.signed_in_at = _now()
            row.expires_at = None
            db.commit()
        finally:
            db.close()

    async def _timeout(self, user_id: UUID, attempt_id: UUID) -> None:
        async with self._lock:
            ceremony = self._ceremonies.get(user_id)
            if ceremony is None or ceremony.snapshot.attempt_id != attempt_id:
                return
            provider, cloud_session = ceremony.provider, ceremony.cloud_session
            ceremony.snapshot = replace(
                ceremony.snapshot, state="timed_out", finished_at=_now(), failure="timed_out"
            )
        await provider.close_login_session(cloud_session)
        logger.info(
            "netfacilities.cloud_auth_timed_out",
            extra={"fields": {"user_id": str(user_id)}},
        )
```

Note `row.storage_state = token` above assigns `bytes` (Fernet's output)
into a `Text` column — SQLAlchemy/psycopg accepts `bytes` for a `Text`
column only if it is ASCII-decodable; Fernet tokens are urlsafe-base64 and
therefore pure ASCII, so `row.storage_state = token.decode("ascii")` is the
correct line (fix this when translating the sketch above into the actual
file — the test in Step 1 asserts the round trip end-to-end and will catch
it if missed).

- [ ] **Step 4: Fix the bytes/str mismatch and run the tests**

Apply the `token.decode("ascii")` correction from the note above, then:

Run: `./venv/Scripts/python.exe -m pytest tests/test_netfacilities_cloud_auth.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Run the full test suite and commit**

Run: `./venv/Scripts/python.exe -m pytest -q`
Expected: PASS, no regressions.

```bash
git add backend/app/services/netfacilities_cloud_auth.py backend/tests/test_netfacilities_cloud_auth.py
git commit -m "feat(netfacilities): per-user cloud login ceremony coordinator (D2, D3, D7)"
```

---

## Task 7: Cloud-auth routes and schemas (spec D7, D9)

**Files:**
- Modify: `backend/app/schemas/netfacilities.py`
- Modify: `backend/app/routers/netfacilities.py`
- Test: `backend/tests/test_netfacilities_cloud_routes.py`

**Interfaces:**
- Consumes: `NetFacilitiesCloudAuthenticationCoordinator` (Task 6),
  `load_netfacilities_cloud_config` (Task 4), `require_min_role`,
  `run_csv_import` (existing).
- Produces: `GET /integrations/netfacilities/cloud/session`,
  `POST /integrations/netfacilities/cloud/auth/start`,
  `POST /integrations/netfacilities/cloud/auth/cancel`,
  `POST /integrations/netfacilities/cloud/downloads/import`.

- [ ] **Step 1: Write the failing route tests**

This codebase's route tests call router functions directly with fake
dependencies and `asyncio.run(...)` — no `TestClient`, no HTTP layer, no
role-header fixtures (verified: `test_netfacilities_routes.py` calls
`router.netfacilities_session(_user=SimpleNamespace(), jobs=FakeJobs(),
authentication=FakeAuthentication())` directly; role gating itself is
checked separately, by static introspection, in
`test_route_role_gates.py`). Follow that exact pattern, not `TestClient`.

```python
"""Route tests for the per-user NetFacilities cloud-auth endpoints (D7, D9)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.integrations.netfacilities.config import NetFacilitiesConfig
from app.routers import netfacilities as router
from app.services.netfacilities_cloud_auth import (
    NetFacilitiesCloudAuthenticationSnapshot,
)


def _enabled_config(tmp_path):
    return NetFacilitiesConfig(
        enabled=True,
        profile_dir=tmp_path,
        browser_channel="chrome",
        request_timeout_seconds=30,
        auth_timeout_seconds=900,
        batch_timeout_seconds=1_800,
    )


class FakeCloudAuth:
    def __init__(self, snapshot=None, *, start_error=None, cancel_error=None):
        self.snapshot = snapshot
        self.start_error = start_error
        self.cancel_error = cancel_error

    async def latest(self, _user_id):
        return self.snapshot

    async def start(self, _user_id, _config):
        if self.start_error is not None:
            raise self.start_error
        return self.snapshot

    async def cancel(self, _user_id):
        if self.cancel_error is not None:
            raise self.cancel_error
        return self.snapshot

    def captured_csv_bytes(self, _user_id):
        return None


class FakeDbNoRow:
    def query(self, *_args, **_kwargs):
        return self

    def filter_by(self, *_args, **_kwargs):
        return self

    def first(self):
        return None

    def one_or_none(self):
        return None


def _snapshot(*, state="awaiting_sign_in", user_id=None):
    now = datetime.now(timezone.utc)
    return NetFacilitiesCloudAuthenticationSnapshot(
        user_id=user_id or uuid4(),
        attempt_id=uuid4(),
        state=state,
        started_at=now,
        session_viewer_url="https://app.steel.dev/sessions/sess-1",
    )


def test_cloud_session_reports_unavailable_when_flag_off(tmp_path, monkeypatch):
    monkeypatch.setattr(router, "load_netfacilities_config", lambda: _enabled_config(tmp_path))
    monkeypatch.delenv("NETFACILITIES_CLOUD_AUTH_ENABLED", raising=False)

    result = asyncio.run(
        router.netfacilities_cloud_session(
            user=SimpleNamespace(id=uuid4()),
            db=FakeDbNoRow(),
            cloud_auth=FakeCloudAuth(),
        )
    )

    assert result.available is False


def test_cloud_session_response_never_carries_storage_state(tmp_path, monkeypatch):
    monkeypatch.setattr(router, "load_netfacilities_config", lambda: _enabled_config(tmp_path))
    monkeypatch.setenv("NETFACILITIES_CLOUD_AUTH_ENABLED", "true")
    monkeypatch.setenv("STEEL_API_KEY", "test-key")
    from cryptography.fernet import Fernet

    monkeypatch.setenv("NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY", Fernet.generate_key().decode())

    result = asyncio.run(
        router.netfacilities_cloud_session(
            user=SimpleNamespace(id=uuid4()),
            db=FakeDbNoRow(),
            cloud_auth=FakeCloudAuth(_snapshot(state="signed_in")),
        )
    )

    dumped = str(result.model_dump())
    assert "storage_state" not in dumped
    assert "steel_profile_id" not in dumped
```

Role gating itself is not tested in this file at all — it is added as a
static-introspection check in `test_route_role_gates.py` in Step 6 below,
matching how the four existing NetFacilities routes are already checked
there (`test_netfacilities_routes_require_techfm_oa_and_document_403`).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/Scripts/python.exe -m pytest tests/test_netfacilities_cloud_routes.py -v`
Expected: FAIL — `router.netfacilities_cloud_session` does not exist.

- [ ] **Step 3: Add the schemas**

In `backend/app/schemas/netfacilities.py`, add:

```python
NetFacilitiesCloudSessionState = Literal[
    "starting",
    "awaiting_sign_in",
    "signed_in",
    "closed",
    "failed",
    "cancelled",
    "timed_out",
]


class NetFacilitiesCloudSessionStatus(BaseModel):
    """Per-user cloud-auth ceremony state (spec D7). Never carries
    `storage_state` or `steel_profile_id` (spec D9)."""

    attempt_id: UUID
    state: NetFacilitiesCloudSessionState
    started_at: datetime
    finished_at: datetime | None = None
    failure: Literal["unavailable", "cancelled", "timed_out"] | None = None
    signed_in_at: datetime | None = None
    last_download_filename: str | None = None
    last_download_at: datetime | None = None
    session_viewer_url: str | None = None


class NetFacilitiesCloudCapability(BaseModel):
    """Whether cloud auth is enabled at all, and the calling user's own
    ceremony state -- never anyone else's (spec D2, D7)."""

    available: bool
    message: str
    status: NetFacilitiesCloudSessionStatus | None = None
    has_saved_session: bool = False
```

- [ ] **Step 4: Add the routes**

In `backend/app/routers/netfacilities.py`, add imports for the new modules
and a module-level singleton mirroring `authentication_coordinator`:

```python
from app.integrations.netfacilities.cloud_config import load_netfacilities_cloud_config
from app.integrations.netfacilities.cloud_steel import SteelCloudBrowserProvider
from app.schemas.netfacilities import (
    NetFacilitiesCloudCapability,
    NetFacilitiesCloudSessionStatus,
)
from app.services.netfacilities_cloud_auth import (
    NetFacilitiesCloudAuthenticationCoordinator,
)


cloud_authentication_coordinator = NetFacilitiesCloudAuthenticationCoordinator(
    provider_factory=lambda config: SteelCloudBrowserProvider(api_key=config.steel_api_key),
)


def get_netfacilities_cloud_authentication_coordinator(
) -> NetFacilitiesCloudAuthenticationCoordinator:
    return cloud_authentication_coordinator


def _cloud_status_response(
    snapshot,
) -> NetFacilitiesCloudSessionStatus:
    return NetFacilitiesCloudSessionStatus(
        attempt_id=snapshot.attempt_id,
        state=snapshot.state,
        started_at=snapshot.started_at,
        finished_at=snapshot.finished_at,
        failure=snapshot.failure,
        signed_in_at=snapshot.signed_in_at,
        last_download_filename=snapshot.last_download_filename,
        last_download_at=snapshot.last_download_at,
        session_viewer_url=snapshot.session_viewer_url,
    )


@router.get("/cloud/session", response_model=NetFacilitiesCloudCapability)
async def netfacilities_cloud_session(
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    db: Session = Depends(get_db),
    cloud_auth: NetFacilitiesCloudAuthenticationCoordinator = Depends(
        get_netfacilities_cloud_authentication_coordinator
    ),
) -> NetFacilitiesCloudCapability:
    try:
        config = load_netfacilities_config()
    except NetFacilitiesUnavailable:
        return NetFacilitiesCloudCapability(available=False, message="NetFacilities is unavailable on this host.")
    cloud_config = load_netfacilities_cloud_config(config)
    if not cloud_config.enabled:
        return NetFacilitiesCloudCapability(
            available=False,
            message="NetFacilities cloud sign-in is not enabled on this host.",
        )

    from app.models import NetFacilitiesCloudSession

    has_saved = (
        db.query(NetFacilitiesCloudSession).filter_by(user_id=user.id).first() is not None
    )
    latest = await cloud_auth.latest(user.id)
    return NetFacilitiesCloudCapability(
        available=True,
        message="Log in to NetFacilities from any device." if latest is None else "",
        status=_cloud_status_response(latest) if latest is not None else None,
        has_saved_session=has_saved,
    )


@router.post(
    "/cloud/auth/start",
    response_model=NetFacilitiesCloudSessionStatus,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_forbidden(), 503: {"description": "Cloud sign-in is unavailable."}},
)
async def start_netfacilities_cloud_authentication(
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    cloud_auth: NetFacilitiesCloudAuthenticationCoordinator = Depends(
        get_netfacilities_cloud_authentication_coordinator
    ),
) -> NetFacilitiesCloudSessionStatus:
    try:
        config = load_netfacilities_config()
    except NetFacilitiesUnavailable as exc:
        raise HTTPException(status_code=503, detail="NetFacilities is unavailable on this host.") from exc
    cloud_config = load_netfacilities_cloud_config(config)
    if not cloud_config.enabled:
        raise HTTPException(status_code=503, detail="NetFacilities cloud sign-in is not enabled on this host.")
    try:
        snapshot = await cloud_auth.start(user.id, cloud_config)
    except NetFacilitiesError as exc:
        raise HTTPException(status_code=503, detail="Could not open a NetFacilities cloud session.") from exc
    return _cloud_status_response(snapshot)


@router.post(
    "/cloud/auth/cancel",
    response_model=NetFacilitiesCloudSessionStatus,
    responses={**_forbidden(), 409: {"description": "No cloud session is active."}},
)
async def cancel_netfacilities_cloud_authentication(
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    cloud_auth: NetFacilitiesCloudAuthenticationCoordinator = Depends(
        get_netfacilities_cloud_authentication_coordinator
    ),
) -> NetFacilitiesCloudSessionStatus:
    try:
        snapshot = await cloud_auth.cancel(user.id)
    except NetFacilitiesError as exc:
        raise HTTPException(status_code=409, detail="No NetFacilities cloud session is active.") from exc
    return _cloud_status_response(snapshot)


@router.post(
    "/cloud/downloads/import",
    response_model=WorkOrderImportResult,
    responses={**_forbidden(), 409: {"description": "No CSV has been captured yet."}},
)
def import_netfacilities_cloud_download(
    background: BackgroundTasks,
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    db: Session = Depends(get_db),
    cloud_auth: NetFacilitiesCloudAuthenticationCoordinator = Depends(
        get_netfacilities_cloud_authentication_coordinator
    ),
) -> WorkOrderImportResult:
    found = cloud_auth.captured_csv_bytes(user.id)
    if found is None:
        raise HTTPException(
            status_code=409,
            detail="No CSV has been exported through the NetFacilities cloud window yet.",
        )
    _filename, data = found
    return run_csv_import(db, background, data=data, user=user)
```

`_forbidden`, `roles`, `require_min_role`, `get_db`, `NetFacilitiesError`,
`load_netfacilities_config`, `NetFacilitiesUnavailable`, `run_csv_import`,
`WorkOrderImportResult`, `status`, `HTTPException`, `Depends`, `Session`,
and `User` are all already imported at the top of
`backend/app/routers/netfacilities.py` — no new imports beyond the four
listed at the start of this step.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `./venv/Scripts/python.exe -m pytest tests/test_netfacilities_cloud_routes.py -v`
Expected: PASS

- [ ] **Step 6: Register the new routes' role gate**

In `backend/tests/test_route_role_gates.py`, find the parametrized list
feeding `test_netfacilities_routes_require_techfm_oa_and_document_403`
(around line 208-222 as of this plan) — it currently lists:

```python
        "netfacilities_session",
        "start_netfacilities_authentication",
        "confirm_netfacilities_authentication",
        "cancel_netfacilities_authentication",
        "start_netfacilities_enrichment",
        "get_netfacilities_enrichment",
        "import_netfacilities_download",
```

Add the four new route function names to that same list:

```python
        "netfacilities_cloud_session",
        "start_netfacilities_cloud_authentication",
        "cancel_netfacilities_cloud_authentication",
        "import_netfacilities_cloud_download",
```

This is the codebase's actual role-gate test (static introspection of each
route's `require_min_role` dependency plus its documented 403 response) —
it replaces the bespoke 403-by-HTTP-call test this plan's Step 1 originally
sketched and then dropped in favor of this existing mechanism.

- [ ] **Step 7: Run the full test suite and commit**

Run: `./venv/Scripts/python.exe -m pytest -q`
Expected: PASS, no regressions.

```bash
git add backend/app/schemas/netfacilities.py backend/app/routers/netfacilities.py backend/tests/test_netfacilities_cloud_routes.py backend/tests/test_route_role_gates.py
git commit -m "feat(netfacilities): per-user cloud-auth routes (D7, D9)"
```

---

## Task 8: Reconnect-per-job enrichment client (spec D5, D6)

Only write the D6 branch of this task if Task 1's spike recorded FAIL. As
written, this task assumes Task 1 recorded PASS (raw replay works).

**Files:**
- Modify: `backend/app/integrations/netfacilities/factory.py`
- Test: `backend/tests/test_netfacilities_cloud_enrichment_factory.py`

**Interfaces:**
- Consumes: `SteelCloudBrowserProvider.open_replay_context` (Task 5),
  `netfacilities_cloud_crypto.decrypt_storage_state` (Task 2).
- Produces: `create_netfacilities_cloud_enrichment_client(cloud_config,
  encrypted_storage_state: bytes) -> NetFacilitiesClientContextProtocol`.
  Task 9 calls this to build the calling user's `cloud_client_context`.

- [ ] **Step 1: Write the failing test**

```python
"""Offline test for the reconnect-per-job cloud enrichment client factory (D5)."""

from __future__ import annotations

import asyncio

from cryptography.fernet import Fernet

from app.integrations.netfacilities.cloud_config import NetFacilitiesCloudConfig
from app.integrations.netfacilities.factory import (
    create_netfacilities_cloud_enrichment_client,
)
from app.services import netfacilities_cloud_crypto as crypto


def test_decrypts_and_delegates_to_the_provider(monkeypatch):
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY", key)
    token = crypto.encrypt_storage_state('{"cookies": []}')

    captured = {}

    class FakeContext:
        async def __aenter__(self):
            return "fake-client"

        async def __aexit__(self, *args):
            return None

    class FakeProvider:
        def __init__(self, *, api_key):
            captured["api_key"] = api_key

        async def open_replay_context(self, storage_state):
            captured["storage_state"] = storage_state
            return FakeContext()

    # `factory.py`'s implementation imports SteelCloudBrowserProvider lazily,
    # inside the function body, specifically so this patch on its source
    # module -- not on `factory`'s own namespace, which never binds the name
    # at module level -- takes effect on the next call.
    monkeypatch.setattr(
        "app.integrations.netfacilities.cloud_steel.SteelCloudBrowserProvider", FakeProvider
    )

    config = NetFacilitiesCloudConfig(enabled=True, steel_api_key="test-key")
    context = create_netfacilities_cloud_enrichment_client(config, token)

    async def _enter_and_exit():
        async with context as client:
            return client

    client = asyncio.run(_enter_and_exit())

    assert client == "fake-client"
    assert captured["api_key"] == "test-key"
    assert captured["storage_state"] == '{"cookies": []}'
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./venv/Scripts/python.exe -m pytest tests/test_netfacilities_cloud_enrichment_factory.py -v`
Expected: FAIL — `create_netfacilities_cloud_enrichment_client` does not exist.

- [ ] **Step 3: Implement the factory function**

In `backend/app/integrations/netfacilities/factory.py`, add:

```python
def create_netfacilities_cloud_enrichment_client(
    config: "NetFacilitiesCloudConfig",
    encrypted_storage_state: bytes,
) -> NetFacilitiesClientContextProtocol:
    """Reconnect to a fresh, short-lived Steel session and replay a user's
    saved storage_state() for one enrichment job (spec D5, verified by the
    Task 1 manual spike). A context whose `__aenter__` returns a client with
    `get_work_order` -- exactly the shape `NetFacilitiesJobCoordinator`
    already expects from `create_netfacilities_client`."""

    from app.services import netfacilities_cloud_crypto as crypto

    from .cloud_steel import SteelCloudBrowserProvider

    if not config.enabled or config.steel_api_key is None:
        raise NetFacilitiesUnavailable(
            "NetFacilities cloud enrichment is disabled on this host."
        )
    storage_state = crypto.decrypt_storage_state(encrypted_storage_state)
    provider = SteelCloudBrowserProvider(api_key=config.steel_api_key)
    return _CloudEnrichmentContextAdapter(provider, storage_state)


class _CloudEnrichmentContextAdapter:
    """Defers `open_replay_context` (async) until `__aenter__`, since
    `create_netfacilities_cloud_enrichment_client` itself is sync -- matching
    every other factory function in this module."""

    def __init__(self, provider, storage_state: str) -> None:
        self._provider = provider
        self._storage_state = storage_state
        self._inner = None

    async def __aenter__(self):
        self._inner = await self._provider.open_replay_context(self._storage_state)
        return await self._inner.__aenter__()

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        if self._inner is not None:
            await self._inner.__aexit__(exc_type, exc, traceback)
```

Add `from app.integrations.netfacilities.cloud_config import
NetFacilitiesCloudConfig` under `TYPE_CHECKING` at the top of the file (the
existing module only imports `NetFacilitiesConfig` and the two contracts,
so this needs a new `if TYPE_CHECKING:` block to avoid `cloud_config.py`
importing `factory.py` in a cycle — `cloud_config.py` does not currently
import `factory.py`, so check that adding this import does not introduce
one before relying on the string-quoted annotation above).

**If Task 1 recorded FAIL** (D6 fallback): replace the body of
`create_netfacilities_cloud_enrichment_client` above with a version that
reads `steel_profile_id` from the passed-in `NetFacilitiesCloudSession` row
instead of `encrypted_storage_state`, and calls
`self._client.sessions.create(profile_id=steel_profile_id)` inside
`SteelCloudBrowserProvider.open_replay_context` (added as a second code
path in Task 5's adapter, selected by whether `storage_state` or
`profile_id` was passed) rather than `new_context(storage_state=...)`. The
data model (Task 3) already carries `steel_profile_id` for exactly this
switch, per spec D6.

- [ ] **Step 4: Run the test to verify it passes**

Run: `./venv/Scripts/python.exe -m pytest tests/test_netfacilities_cloud_enrichment_factory.py -v`
Expected: PASS

- [ ] **Step 5: Run the full test suite and commit**

Run: `./venv/Scripts/python.exe -m pytest -q`
Expected: PASS, no regressions.

```bash
git add backend/app/integrations/netfacilities/factory.py backend/tests/test_netfacilities_cloud_enrichment_factory.py
git commit -m "feat(netfacilities): reconnect-per-job cloud enrichment client (D5)"
```

---

## Task 9: Enrichment routing integration (spec D10)

**Files:**
- Modify: `backend/app/services/netfacilities_jobs.py`
- Modify: `backend/app/schemas/netfacilities.py`
- Modify: `backend/app/routers/netfacilities.py`
- Test: `backend/tests/test_netfacilities_jobs.py` (extend)
- Test: `backend/tests/test_netfacilities_cloud_routes.py` (extend)

**Interfaces:**
- Consumes: `create_netfacilities_cloud_enrichment_client` (Task 8),
  `NetFacilitiesCloudSession` model (Task 3).
- Produces: `JobSource` gains `"cloud_session"`; `NetFacilitiesJobCoordinator.start`
  gains an optional `cloud_client_context` parameter, tried after
  `live_client_context` and before `saved_state`, matching the existing
  precedence for the local live session.

- [ ] **Step 1: Write the failing job-coordinator test**

Add to `backend/tests/test_netfacilities_jobs.py` (read the file first for
its exact existing fixtures/fakes and match their style rather than
introducing a second set):

```python
def test_cloud_session_source_used_when_no_live_session(coordinator_factory):
    """A cloud_client_context, with no live_client_context, sources the job
    as cloud_session and never takes the shared profile lease (spec D10) --
    `NetFacilitiesOperationGate.active_kind()` stays None because a cloud
    session is not the physical resource that gate arbitrates."""

    coordinator, gate = coordinator_factory()
    cloud_context = FakeEnrichmentContext()

    async def _run():
        snapshot, created = await coordinator.start(
            _config(enabled=True), cloud_client_context=cloud_context
        )
        assert created is True
        assert snapshot.source == "cloud_session"
        assert await gate.active_kind() is None
        return snapshot

    asyncio.run(_run())
```

Match `_config`, `FakeEnrichmentContext`, and `coordinator_factory` (or
equivalent) to whatever this file's existing helpers are actually named —
`test_netfacilities_auth.py`'s `_config`/`FakeEnrichmentContext` shown
earlier in this plan are the closest known shapes but
`test_netfacilities_jobs.py` may define its own; use that file's own
helpers.

- [ ] **Step 2: Run the test to verify it fails**

Run: `./venv/Scripts/python.exe -m pytest tests/test_netfacilities_jobs.py -k cloud_session -v`
Expected: FAIL — `start()` has no `cloud_client_context` parameter.

- [ ] **Step 3: Extend `JobSource` and `start()`**

In `backend/app/services/netfacilities_jobs.py`:

```python
JobSource: TypeAlias = Literal["live_session", "saved_state", "cloud_session"]
```

Change `start`'s signature and body:

```python
    async def start(
        self,
        config: NetFacilitiesConfig,
        *,
        live_client_context: NetFacilitiesClientContextProtocol | None = None,
        cloud_client_context: NetFacilitiesClientContextProtocol | None = None,
    ) -> tuple[NetFacilitiesJobSnapshot, bool]:
        """Start a batch, or return the currently active batch unchanged.

        Precedence: the operator's open live window (spec D4, D8) first, then
        the calling user's own cloud session (spec D10), then the shared
        saved-state file. A cloud session never takes the shared profile
        lease -- it is not the same physical resource live_session/saved_state
        contend for (spec D10)."""

        if not config.enabled:
            raise NetFacilitiesAuthenticationRequired(
                "NetFacilities enrichment is not enabled on this host."
            )
        if (
            live_client_context is None
            and cloud_client_context is None
            and not config.has_saved_authentication
        ):
            raise NetFacilitiesAuthenticationRequired(
                "Sign in to NetFacilities before enrichment."
            )

        async with self._lock:
            if self._task is not None and not self._task.done():
                if self._latest is None:
                    raise RuntimeError("active NetFacilities task has no job state")
                return self._latest, False

            if live_client_context is not None:
                source: JobSource = "live_session"
            elif cloud_client_context is not None:
                source = "cloud_session"
            else:
                source = "saved_state"
            client_context = live_client_context or cloud_client_context
            lease = None
            if client_context is None:
                lease = await self._profile_gate.acquire("enrichment")
            job = NetFacilitiesJobSnapshot(job_id=uuid4(), state="queued", source=source)
            self._latest = job
            self._lease = lease
            try:
                self._task = asyncio.create_task(
                    self._run(job.job_id, config, client_context, source),
                    name=f"netfacilities-enrichment-{job.job_id}",
                )
            except BaseException:
                self._lease = None
                if lease is not None:
                    await self._profile_gate.release(lease)
                raise
            return job, True
```

`_run`'s existing `live_client_context: ... | None` parameter is renamed to
`client_context` to match (it already falls back to
`self._client_factory(config)` when `None`, which is unchanged — a
`saved_state` job with neither live nor cloud context still goes through
that path exactly as today).

- [ ] **Step 4: Add `"cloud_session"` to the response schema**

In `backend/app/schemas/netfacilities.py`:

```python
NetFacilitiesJobSource = Literal["live_session", "saved_state", "cloud_session"]
```

- [ ] **Step 5: Wire the router to resolve the calling user's cloud session**

In `backend/app/routers/netfacilities.py`, modify
`start_netfacilities_enrichment`:

```python
async def start_netfacilities_enrichment(
    user: User = Depends(require_min_role(roles.ROLE_TECHFM_OA)),
    db: Session = Depends(get_db),
    jobs: NetFacilitiesJobCoordinator = Depends(get_netfacilities_coordinator),
    authentication: NetFacilitiesAuthenticationCoordinator = Depends(
        get_netfacilities_authentication_coordinator
    ),
) -> NetFacilitiesEnrichmentJob:
    """Start one batch: the operator's open window, else the calling user's
    own cloud session, else the shared saved state."""

    try:
        config = load_netfacilities_config()
    except NetFacilitiesUnavailable as exc:
        raise HTTPException(status_code=503, detail="NetFacilities enrichment is unavailable on this host.") from exc
    if not config.enabled:
        raise HTTPException(status_code=503, detail="NetFacilities enrichment is disabled on this host.")

    live = await authentication.borrow_live_client()
    cloud_context = None
    if live is None:
        cloud_context = _resolve_cloud_enrichment_context(config, db, user)
    try:
        snapshot, _created = await jobs.start(
            config, live_client_context=live, cloud_client_context=cloud_context
        )
    except NetFacilitiesAuthenticationRequired as exc:
        detail = (
            "Sign in to NetFacilities before enrichment."
            if config.interactive_authentication_available
            else "Refresh the saved NetFacilities authentication secret and redeploy before enrichment."
        )
        raise HTTPException(status_code=409, detail=detail) from exc
    except NetFacilitiesOperationInProgress as exc:
        raise HTTPException(status_code=409, detail="Another NetFacilities operation is already running.") from exc
    return _job_response(snapshot)


def _resolve_cloud_enrichment_context(config, db: Session, user: User):
    from app.integrations.netfacilities.cloud_config import load_netfacilities_cloud_config
    from app.integrations.netfacilities.factory import (
        create_netfacilities_cloud_enrichment_client,
    )
    from app.models import NetFacilitiesCloudSession

    cloud_config = load_netfacilities_cloud_config(config)
    if not cloud_config.enabled:
        return None
    row = db.query(NetFacilitiesCloudSession).filter_by(user_id=user.id).one_or_none()
    if row is None or row.expires_at is not None:
        return None
    return create_netfacilities_cloud_enrichment_client(
        cloud_config, row.storage_state.encode("ascii")
    )
```

Note `db` is added as a new parameter to `start_netfacilities_enrichment`,
which did not previously take a database session — add
`db: Session = Depends(get_db)` and confirm `Session` is already imported
(it is, at the top of the file for the other routes).

- [ ] **Step 6: Handle expiry the same way saved_state does**

Add a helper mirroring `_saved_state_refreshed_after`, used when a job's
`source == "cloud_session"` reports `authentication_required`, so a stale
row's `expires_at` gets set (spec D8's own description: "set only once an
enrichment attempt actually reports `authentication_required`"). In
`netfacilities.py`'s router module, near `_live_session_lost_authentication`:

```python
def _mark_cloud_session_expired_if_needed(db: Session, job: NetFacilitiesJobSnapshot) -> None:
    if job.source != "cloud_session" or job.state != "authentication_required":
        return
    from app.models import NetFacilitiesCloudSession

    row = db.query(NetFacilitiesCloudSession).filter_by(user_id=job.user_id).one_or_none()
    if row is not None and row.expires_at is None:
        row.expires_at = job.finished_at
        db.commit()
```

This requires threading `user_id` onto `NetFacilitiesJobSnapshot` (it has
none today — jobs are process-global, not user-scoped) and calling this
helper from `get_netfacilities_enrichment` after fetching a finished
snapshot. Since `NetFacilitiesJobSnapshot` is a frozen dataclass shared by
every job source, add `user_id: UUID | None = None` as a new optional field
(defaulting `None` for `live_session`/`saved_state` jobs, which are not
user-scoped), set only when `source == "cloud_session"` in
`NetFacilitiesJobCoordinator.start`. Update `NetFacilitiesEnrichmentJob`
schema NOT to expose `user_id` (it is an internal expiry-detection detail,
not part of the safe-to-return response shape) — read it off the
dataclass, not the Pydantic model, in the helper above.

- [ ] **Step 7: Add a router-level test for cloud-session routing**

Add to `backend/tests/test_netfacilities_cloud_routes.py`:

```python
class FakeDbWithCloudRow:
    """Returns one NetFacilitiesCloudSession-shaped row for any query."""

    def __init__(self, row):
        self._row = row

    def query(self, *_args, **_kwargs):
        return self

    def filter_by(self, *_args, **_kwargs):
        return self

    def one_or_none(self):
        return self._row


def test_enrichment_uses_the_callers_cloud_session_when_no_live_window(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace as NS

    from app.integrations.netfacilities import factory as factory_module

    monkeypatch.setattr(router, "load_netfacilities_config", lambda: _enabled_config(tmp_path))
    monkeypatch.setenv("NETFACILITIES_CLOUD_AUTH_ENABLED", "true")
    monkeypatch.setenv("STEEL_API_KEY", "test-key")
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode()
    monkeypatch.setenv("NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY", key)

    from app.services import netfacilities_cloud_crypto as crypto

    token = crypto.encrypt_storage_state('{"cookies": []}').decode("ascii")
    row = NS(storage_state=token, expires_at=None)
    db = FakeDbWithCloudRow(row)

    captured = {}

    def fake_create(config, encrypted_storage_state):
        captured["called"] = True
        return object()

    monkeypatch.setattr(
        factory_module, "create_netfacilities_cloud_enrichment_client", fake_create
    )

    class NoLiveAuth:
        async def borrow_live_client(self):
            return None

    from app.services.netfacilities_jobs import NetFacilitiesJobSnapshot
    import uuid as uuid_module

    snapshot = NetFacilitiesJobSnapshot(job_id=uuid_module.uuid4(), state="queued", source="cloud_session")

    class FakeJobsCapturingCloud:
        async def start(self, _config, *, live_client_context=None, cloud_client_context=None):
            captured["cloud_client_context"] = cloud_client_context
            return snapshot, True

    result = asyncio.run(
        router.start_netfacilities_enrichment(
            user=SimpleNamespace(id=uuid4()),
            db=db,
            jobs=FakeJobsCapturingCloud(),
            authentication=NoLiveAuth(),
        )
    )

    assert result.source == "cloud_session"
    assert captured["called"] is True
    assert captured["cloud_client_context"] is not None
```

This monkeypatches `create_netfacilities_cloud_enrichment_client` at its
call site inside `_resolve_cloud_enrichment_context` (which does `from
app.integrations.netfacilities.factory import
create_netfacilities_cloud_enrichment_client` as a local import each call —
same lazy-import pattern as Task 8's factory function, patched the same
way for the same reason) so this test never touches Steel or Playwright.

- [ ] **Step 8: Run the tests and the full suite**

```bash
./venv/Scripts/python.exe -m pytest tests/test_netfacilities_jobs.py tests/test_netfacilities_routes.py tests/test_netfacilities_cloud_routes.py -v
./venv/Scripts/python.exe -m pytest -q
```
Expected: PASS, no regressions.

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/netfacilities_jobs.py backend/app/schemas/netfacilities.py backend/app/routers/netfacilities.py backend/tests/test_netfacilities_jobs.py backend/tests/test_netfacilities_cloud_routes.py
git commit -m "feat(netfacilities): route enrichment through the caller's cloud session (D10)"
```

---

## Task 10: Frontend — per-user cloud login (spec D3, D7)

**Files:**
- Modify: `backend/static/pages/integrations.html`
- Modify: `backend/static/views/workOrders.js`
- Modify: `backend/static/api.js`

**Interfaces:**
- Consumes: `GET /cloud/session`, `POST /cloud/auth/start`,
  `POST /cloud/auth/cancel`, `POST /cloud/downloads/import` (Task 7).

This task has no automated test — the existing frontend for this feature
(`workOrders.js`) has no test harness of its own (verify this is still true
by checking for a `workOrders.test.js` or similar before skipping tests;
if the codebase added frontend tests since this plan was written, add one
following that convention instead of skipping). Verify manually per Step 4.

- [ ] **Step 1: Add markup**

In `backend/static/pages/integrations.html`, inside the existing `.filter-row`,
after the local `wo-netfacilities-cancel-btn` button:

```html
<button id="wo-netfacilities-cloud-sign-in-btn" type="button" class="secondary-btn" hidden>Log in to NetFacilities (any device)</button>
<button id="wo-netfacilities-cloud-cancel-btn" type="button" class="secondary-btn" hidden>Close cloud session</button>
<button id="wo-netfacilities-cloud-import-download-btn" type="button" hidden>Import downloaded CSV (cloud)</button>
```

- [ ] **Step 2: Add API functions**

In `backend/static/api.js`, after `apiImportNetFacilitiesDownload`:

```javascript
// Per-user NetFacilities cloud sign-in (spec D2, D7). Never returns
// storage_state or steel_profile_id.
export async function apiGetNetFacilitiesCloudSession() {
  return liveGet("/integrations/netfacilities/cloud/session");
}

export async function apiStartNetFacilitiesCloudAuthentication() {
  return parseResponse(await fetch(
    "/integrations/netfacilities/cloud/auth/start",
    { method: "POST", credentials: "include" },
  ));
}

export async function apiCancelNetFacilitiesCloudAuthentication() {
  return parseResponse(await fetch(
    "/integrations/netfacilities/cloud/auth/cancel",
    { method: "POST", credentials: "include" },
  ));
}

export async function apiImportNetFacilitiesCloudDownload() {
  return parseResponse(await fetch(
    "/integrations/netfacilities/cloud/downloads/import",
    { method: "POST", credentials: "include" },
  ));
}
```

- [ ] **Step 3: Wire the state machine**

In `backend/static/views/workOrders.js`, add to the existing import block
(around line 42-48):

```javascript
  apiGetNetFacilitiesCloudSession,
  apiStartNetFacilitiesCloudAuthentication,
  apiCancelNetFacilitiesCloudAuthentication,
  apiImportNetFacilitiesCloudDownload,
```

Add DOM references alongside the existing ones (around line 96-101):

```javascript
const netFacilitiesCloudSignInBtn = document.getElementById("wo-netfacilities-cloud-sign-in-btn");
const netFacilitiesCloudCancelBtn = document.getElementById("wo-netfacilities-cloud-cancel-btn");
const netFacilitiesCloudImportDownloadBtn = document.getElementById("wo-netfacilities-cloud-import-download-btn");
```

Add a polling function near `refreshNetFacilitiesSession` (around line
1047-1053), following the same pattern the local flow already uses for
`pollNetFacilitiesJob` (around line 2214):

```javascript
let netFacilitiesCloudPollTimer = null;

async function refreshNetFacilitiesCloudSession() {
  let capability;
  try {
    capability = await apiGetNetFacilitiesCloudSession();
  } catch {
    capability = null;
  }
  updateNetFacilitiesCloudControls(capability);
  return capability;
}

function updateNetFacilitiesCloudControls(capability) {
  const available = Boolean(capability && capability.available);
  const cloudStatus = capability && capability.status;
  const awaitingSignIn = cloudStatus && cloudStatus.state === "awaiting_sign_in";
  const signedIn = cloudStatus && cloudStatus.state === "signed_in";
  const hasCsv = signedIn && Boolean(cloudStatus.last_download_filename);

  if (netFacilitiesCloudSignInBtn) {
    netFacilitiesCloudSignInBtn.hidden = !available || awaitingSignIn || signedIn;
  }
  if (netFacilitiesCloudCancelBtn) {
    netFacilitiesCloudCancelBtn.hidden = !(awaitingSignIn || signedIn);
  }
  if (netFacilitiesCloudImportDownloadBtn) {
    netFacilitiesCloudImportDownloadBtn.hidden = !hasCsv;
  }

  const shouldPoll = available && (awaitingSignIn || signedIn) && !netFacilitiesCloudPollTimer;
  if (shouldPoll) {
    netFacilitiesCloudPollTimer = setInterval(refreshNetFacilitiesCloudSession, NETFACILITIES_SESSION_POLL_MS);
  } else if (!awaitingSignIn && !signedIn && netFacilitiesCloudPollTimer) {
    clearInterval(netFacilitiesCloudPollTimer);
    netFacilitiesCloudPollTimer = null;
  }
}

if (netFacilitiesCloudSignInBtn) {
  netFacilitiesCloudSignInBtn.addEventListener("click", async () => {
    const capability = await apiStartNetFacilitiesCloudAuthentication();
    if (capability && capability.session_viewer_url) {
      window.open(capability.session_viewer_url, "_blank", "noopener");
    }
    await refreshNetFacilitiesCloudSession();
  });
}

if (netFacilitiesCloudCancelBtn) {
  netFacilitiesCloudCancelBtn.addEventListener("click", async () => {
    await apiCancelNetFacilitiesCloudAuthentication();
    await refreshNetFacilitiesCloudSession();
  });
}

if (netFacilitiesCloudImportDownloadBtn) {
  netFacilitiesCloudImportDownloadBtn.addEventListener("click", async () => {
    await apiImportNetFacilitiesCloudDownload();
    await loadWorkOrders();
    await refreshNetFacilitiesCloudSession();
  });
}
```

`apiStartNetFacilitiesCloudAuthentication()`'s response is a
`NetFacilitiesCloudSessionStatus`, which carries `session_viewer_url`
directly (not nested under `.status`) — this matches the plain object
`window.open` call above. Call `void refreshNetFacilitiesCloudSession();`
next to the existing `void refreshNetFacilitiesSession();` call (around
line 1053) so the cloud card state loads on page entry.

- [ ] **Step 4: Manual verification**

Do not start the server on the implementer's behalf, per the owner's
standing preference — hand this list to the owner once
`NETFACILITIES_CLOUD_AUTH_ENABLED=true` and the other env vars from Tasks 2,
4, and 5 are set locally:

1. Integrations page shows "Log in to NetFacilities (any device)".
2. Clicking it opens a new tab at Steel's live-view URL and the button
   hides while the local card shows an in-progress cloud state.
3. Signing into NetFacilities in that tab flips the card to a signed-in
   cloud state within a few polls, without clicking anything else.
4. Exporting the CSV in that tab makes "Import downloaded CSV (cloud)"
   appear within a similar window to the local flow's ~3s.
5. Clicking it imports work orders through the existing pipeline and the
   list reloads.
6. "Close cloud session" ends it and the sign-in button reappears.

- [ ] **Step 5: Commit**

```bash
git add backend/static/pages/integrations.html backend/static/views/workOrders.js backend/static/api.js
git commit -m "feat(netfacilities): per-user cloud sign-in UI (D3, D7)"
```

---

## Task 11: Batch sizing vs. the 15-minute cap, and docs (spec §4, §12 pattern)

**Files:**
- Modify: `backend/app/services/netfacilities.py` (or wherever
  `enrich_work_orders`'s batch loop lives — confirm via the import in
  `netfacilities_jobs.py`: `from app.services.netfacilities import
  NetFacilitiesEnrichmentSummary, SessionFactory, enrich_work_orders`)
- Modify: `docs/open-work.md`
- Modify: `docs/current-state.md`
- Modify: `docs/endpoint-map.md`
- Test: extend whichever test file already covers `enrich_work_orders`'s
  timeout behavior (`test_netfacilities_service.py`, per the earlier file
  listing)

**Interfaces:**
- Consumes: `NetFacilitiesCloudConfig.batch_session_seconds` (Task 4).
- Produces: a `cloud_session_deadline_seconds: float | None` parameter on
  `enrich_work_orders`, checked between work orders exactly the way
  `batch_timeout_seconds` already is, so a cloud-sourced batch stops and
  reports a partial `timed_out` result before Steel's own 15-minute cap
  would otherwise sever the connection mid-request.

- [ ] **Step 1: Read the existing batch-timeout mechanism**

Before writing anything, read `enrich_work_orders` in
`backend/app/services/netfacilities.py` and find where
`batch_timeout_seconds` is already checked in the per-work-order loop
(`NetFacilitiesEnrichmentSummary.timed_out` is set there). This task adds a
second, tighter deadline alongside it — it does not replace the existing
mechanism, since the two govern different things (total configured batch
time vs. the vendor's own hard session cap).

- [ ] **Step 2: Write the failing test**

Add a test asserting that when `cloud_session_deadline_seconds` is smaller
than the number of fake work orders would otherwise take, the job stops
early with `timed_out=True` and a partial `fetched` count less than the
candidate count — modeled directly on however the existing
`batch_timeout_seconds` test in that same file already asserts this, since
the new check is deliberately symmetric with it.

- [ ] **Step 3: Run the test to verify it fails**

Run whatever the existing file's pytest invocation is (matching the path
found in Step 1), e.g.:
`./venv/Scripts/python.exe -m pytest tests/test_netfacilities_service.py -k cloud_session_deadline -v`
Expected: FAIL — the new parameter doesn't exist.

- [ ] **Step 4: Add the deadline check**

Add `cloud_session_deadline_seconds: float | None = None` to
`enrich_work_orders`'s signature, and in the same loop location as the
existing `batch_timeout_seconds` check, add a second early-exit condition
comparing elapsed time against `cloud_session_deadline_seconds` when it is
not `None`, setting the same `timed_out` outcome. In
`NetFacilitiesJobCoordinator._run` (`netfacilities_jobs.py`), pass
`cloud_session_deadline_seconds=cloud_config.batch_session_seconds` only
when `source == "cloud_session"` — this requires threading the
`NetFacilitiesCloudConfig` (or just the one number) into `_run`, e.g. as a
new optional constructor/call parameter alongside the existing `config:
NetFacilitiesConfig`.

- [ ] **Step 5: Run the tests and the full suite**

```bash
./venv/Scripts/python.exe -m pytest tests/test_netfacilities_service.py tests/test_netfacilities_jobs.py -v
./venv/Scripts/python.exe -m pytest -q
```
Expected: PASS, no regressions.

- [ ] **Step 6: Update docs**

- `docs/open-work.md`: add an entry for this feature (`NetFacilities cloud
  auth — per-user Steel login`) with a link to the spec and this plan,
  following the exact style of the existing `IMP-039` entry referenced in
  that spec's own §12.
- `docs/current-state.md`: add the four new env vars
  (`NETFACILITIES_CLOUD_AUTH_ENABLED`, `STEEL_API_KEY`,
  `NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY`,
  `NETFACILITIES_CLOUD_LOGIN_TIMEOUT_SECONDS`,
  `NETFACILITIES_CLOUD_BATCH_SESSION_SECONDS`) to wherever
  `NETFACILITIES_ENABLED` and friends are already documented, and the new
  `netfacilities_cloud_sessions` table to the schema summary.
- `docs/endpoint-map.md`: add the four new routes from Task 7 to the
  `/integrations/netfacilities` section, matching the existing entries'
  format exactly.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/netfacilities.py backend/app/services/netfacilities_jobs.py backend/tests/test_netfacilities_service.py docs/open-work.md docs/current-state.md docs/endpoint-map.md
git commit -m "feat(netfacilities): bound cloud enrichment batches to the 15-minute session cap"
```
