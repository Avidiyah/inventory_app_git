"""Top-level FastAPI application package.

Sub-packages, in dependency order (each may only import the ones
above it):

- `domain/`   -- pure business rules and exception vocabulary.
- `schemas/`  -- Pydantic request/response shapes.
- `models.py` -- SQLAlchemy ORM tables.
- `database.py` -- engine, session, and `get_db` dependency.
- `services/` -- SQLAlchemy + domain code that owns transactions.
- `routers/`  -- thin FastAPI handlers.
- `main.py`   -- composition root.
"""
