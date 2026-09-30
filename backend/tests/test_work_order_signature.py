"""Witness sign-off on a work order (spec 2026-09-30): migration, service,
and router tests. Router tests go through a real `TestClient`, never a
direct handler call (see `test_work_orders_router.py` for why)."""

import importlib.util
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text


# --------------------------------------------------------------------------
# migration
# --------------------------------------------------------------------------


def _load_migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic" / "versions"
        / "a7c3e9f1b2d4_add_work_order_signatures.py"
    )
    spec = importlib.util.spec_from_file_location("sig_rev", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_drops_and_recreates_the_table(db):
    module = _load_migration()
    ctx = MigrationContext.configure(db.connection())
    exists = lambda: db.execute(text("SELECT to_regclass('work_order_signatures')")).scalar()
    assert exists() is not None  # dev DB is at head
    with Operations.context(ctx):
        module.downgrade()
    assert exists() is None
    with Operations.context(ctx):
        module.upgrade()
    assert exists() is not None
