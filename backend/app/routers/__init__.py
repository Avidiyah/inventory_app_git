"""Routers package.

Layer: routers (FastAPI). Each submodule exposes an `APIRouter`
named `router` that `app/main.py` registers on the application.
Routers are deliberately thin: parse the request, call a service,
catch `DomainError`, translate via `_errors.to_http`. The single
internal helper `_errors.py` keeps the domain-to-HTTP mapping in
one place.
"""
