"""Pure domain layer.

Modules in this package never import from FastAPI, SQLAlchemy, or
Pydantic. They define the business vocabulary (exception types in
`errors.py`) and the business rules (`quantity.py`,
`notes_validation.py`) used by the service layer. Keeping the
domain framework-free is what makes the rest of the stack
unit-testable without spinning up a web server or a database.
"""
