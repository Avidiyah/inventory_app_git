"""Validator for the free-form `notes` dict attached to items.

Layer: pure domain (no Pydantic, no FastAPI, no SQLAlchemy).

The `items.notes` column is JSONB so users can attach arbitrary
key/value metadata without a schema migration per field. This
flexibility needs a single, well-defined gate so the database never
stores nested structures or non-primitive values that the frontend
cannot render.

The rules (mirrored in the frontend's notes editor):
- Keys are non-blank strings (stripped before storage).
- Values are exactly one of: `str`, `int`, `float`, `bool`.
- Nested objects, arrays, `None`, and any other type are rejected.

Called by `app/schemas/items.py::ItemNotesUpdate` as a Pydantic
field validator. Lives outside the schema so it can be unit-tested
on a plain dict without instantiating a Pydantic model.
"""

NoteValue = str | int | float | bool


def validate_notes(notes: dict) -> dict[str, NoteValue]:
    """Return a cleaned copy of `notes` or raise `ValueError`.

    Cleaning consists of stripping whitespace from keys. Values are
    accepted unchanged once their type passes the whitelist.

    Note that `bool` is checked BEFORE `int`/`float` because Python's
    `bool` is a subclass of `int` -- without this ordering, `True`
    would be silently stored as `1`.
    """
    if not isinstance(notes, dict):
        raise ValueError("Notes must be an object.")

    cleaned: dict[str, NoteValue] = {}
    for raw_key, value in notes.items():
        if not isinstance(raw_key, str):
            raise ValueError("Note keys must be strings.")
        key = raw_key.strip()
        if not key:
            raise ValueError("Note keys cannot be blank.")

        if isinstance(value, bool):
            cleaned[key] = value
        elif isinstance(value, (int, float)):
            cleaned[key] = value
        elif isinstance(value, str):
            cleaned[key] = value
        else:
            raise ValueError(
                f"Note '{key}' has unsupported value type. "
                "Allowed: string, number, boolean."
            )
    return cleaned
