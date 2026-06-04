"""SQLAlchemy engine, session factory, and FastAPI dependency.

Layer: infrastructure. This is the single place that knows how to
connect to PostgreSQL. Everything else imports `Base` (for model
declaration), `SessionLocal` (rare), or -- by far the most common
-- depends on `get_db` to receive a per-request session.

The engine is created at import time; missing `DATABASE_URL`
fails fast with a clear error rather than blowing up on the first
query. `echo=True` keeps SQL visible during development; production
should flip this off via configuration when that step is added.
"""

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set. Check your .env file.")

engine = create_engine(
    DATABASE_URL,
    echo=True,
    connect_args={"connect_timeout": 5},
)

# `autoflush=False` is deliberate: services control when SQL is
# emitted, which makes the order of operations in
# `services.transactions.apply_transaction` predictable around the
# `SELECT ... FOR UPDATE` row lock.
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)


class Base(DeclarativeBase):
    """Declarative base every ORM model in `app.models` inherits."""
    pass


def test_connection() -> tuple[str, str]:
    """Probe used by `/db-test`. Returns `(database, user)` from a
    single round-trip; raises if the connection cannot be opened."""
    with engine.connect() as connection:
        result = connection.execute(text("SELECT current_database(), current_user;"))
        database_name, user_name = result.one()
        return database_name, user_name
    
def get_db():
    """FastAPI dependency: yields a session per request and
    guarantees it is closed afterward. Every router's `db:
    Session = Depends(get_db)` parameter is wired through here."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()