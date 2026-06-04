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


def normalize_db_url(url: str) -> str:
    """Force the psycopg 3 dialect on a Postgres URL.

    Managed Postgres providers (Render, Heroku, etc.) hand out URLs that
    begin with `postgres://` or `postgresql://`. SQLAlchemy maps both to
    the psycopg2 driver, which this project does not install -- it uses
    psycopg 3. Rewriting the scheme to `postgresql+psycopg://` keeps the
    local `.env` and the deployed `DATABASE_URL` working unchanged.
    """
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set. Check your .env file.")

DATABASE_URL = normalize_db_url(DATABASE_URL)

# `echo` logs every SQL statement -- handy locally, but in production it
# floods the logs and can leak data. Off unless SQL_ECHO=true.
SQL_ECHO = os.getenv("SQL_ECHO", "false").strip().lower() == "true"

engine = create_engine(
    DATABASE_URL,
    echo=SQL_ECHO,
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