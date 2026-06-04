"""Service layer.

Layer: services (SQLAlchemy + domain). Allowed to import from
`app.models`, `app.domain`, and `app.schemas` (read-only — used for
*building* response models in the history service). Must not import
anything from FastAPI: services own database transactions and
business rules, but they have no knowledge of HTTP status codes,
request objects, or response objects. That separation is what lets
routers stay one-liners and lets these functions be reused from
scripts or tests.

Each submodule corresponds to a coherent slice of behaviour:

- `items.py`   — CRUD on items.
- `notes.py`   — write path for the JSONB `notes` column.
- `transactions.py` — the locked stock/dispense write.
- `history.py` — paginated, denormalised audit-log read.
- `users.py`   — CRUD on users.
"""
