"""Tests for C4: FastAPI's built-in docs endpoints are closed in production.

Layer: unit (no DB, no HTTP client). Matches the style of
`test_health_check.py` and `test_route_role_gates.py`.

`app` is module-level and `COOKIE_SECURE` is read at import time, so the two
environments cannot both be exercised by importing `app.main` twice --
`importlib.reload` would re-run `configure_logging()` and re-register every
router. `main._doc_urls` exists as the seam: it is pure, so both branches are
testable directly, and one test then asserts the *running* app actually matches
what the seam returns for this environment. A correct helper nobody wired up
would otherwise pass.

The end-to-end proof (real ASGI requests returning 404 with COOKIE_SECURE=true)
needs a subprocess to control import-time env and is run as a verification step
rather than lived here; see docs/api-hardening-checklist.md -> Shipped -> C4.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI

from app.auth_deps import COOKIE_SECURE
from app.main import _doc_urls, app


# Every route FastAPI mounts for its own documentation. `/docs/oauth2-redirect`
# is easy to forget: it is derived from `docs_url`, not declared separately.
DOC_PATHS = {"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}


def _mounted_paths(application) -> set:
    return {getattr(route, "path", None) for route in application.routes}


# --------------------------------------------------------------------------
# The seam
# --------------------------------------------------------------------------

def test_doc_urls_are_open_outside_production():
    assert _doc_urls(production=False) == {
        "docs_url": "/docs",
        "redoc_url": "/redoc",
        "openapi_url": "/openapi.json",
    }


def test_doc_urls_are_all_none_in_production():
    # None un-mounts. Anything else -- a rewritten path, a sentinel string --
    # would leave a reachable route.
    assert _doc_urls(production=True) == {
        "docs_url": None,
        "redoc_url": None,
        "openapi_url": None,
    }


# --------------------------------------------------------------------------
# The wiring
# --------------------------------------------------------------------------

def test_the_running_app_matches_its_environment():
    # The test that catches a correct helper that was never passed to
    # FastAPI(). Asserts the real app, not a probe.
    mounted = _mounted_paths(app) & DOC_PATHS

    if COOKIE_SECURE:
        assert mounted == set()
    else:
        assert mounted == DOC_PATHS


def test_closing_the_docs_removes_every_doc_route():
    # Includes /docs/oauth2-redirect. A future FastAPI upgrade that added a
    # fourth doc route, or stopped deriving the redirect from docs_url, would
    # fail here rather than silently re-opening something in production.
    closed = FastAPI(title="probe", **_doc_urls(production=True))

    assert _mounted_paths(closed) & DOC_PATHS == set()


def test_leaving_the_docs_open_mounts_all_four_routes():
    opened = FastAPI(title="probe", **_doc_urls(production=False))

    assert DOC_PATHS <= _mounted_paths(opened)


# --------------------------------------------------------------------------
# The regression guard that actually matters
# --------------------------------------------------------------------------

def test_the_schema_is_still_generated_when_the_route_is_closed():
    # Closing `/openapi.json` removes the *route*, not the schema. Every
    # verification table in docs/api-hardening-checklist.md asserts "OpenAPI
    # operations = 73" by calling app.openapi(), and C1 added
    # test_every_gated_work_order_route_documents_its_403, which reads
    # route.responses the same way. Both have to survive openapi_url=None or
    # C4 would silently cost the project its verification coverage.
    closed = FastAPI(title="probe", **_doc_urls(production=True))

    @closed.get("/x", responses={403: {"description": "Requires the admin role or above."}})
    def x():  # pragma: no cover - never called, only introspected
        return {}

    schema = closed.openapi()

    assert isinstance(schema, dict)
    assert "/x" in schema["paths"]
    assert "403" in schema["paths"]["/x"]["get"]["responses"]


def test_the_live_app_still_reports_its_full_schema():
    schema = app.openapi()
    operations = [
        (path, method)
        for path, methods in schema["paths"].items()
        for method in methods
        if method in {"get", "post", "put", "patch", "delete"}
    ]

    # The number itself is pinned by the checklist's evidence tables rather
    # than here -- adding a route should not fail this file. What matters is
    # that the schema is non-empty and readable whichever way C4 resolved.
    assert operations
    assert "/healthz" in schema["paths"]


# --------------------------------------------------------------------------
# Tripwire
# --------------------------------------------------------------------------

def test_no_frontend_code_links_to_the_doc_endpoints():
    # Closing these breaks no frontend code today (0 matches). A future link
    # from the SPA would work locally and 404 only in production, which is the
    # kind of break that reaches users before anyone notices.
    static_dir = Path(__file__).resolve().parent.parent / "static"
    offenders = []

    for path in list(static_dir.rglob("*.js")) + list(static_dir.rglob("*.html")):
        if "vendor" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if any(token in text for token in ('"/docs', "'/docs", "/openapi.json", '"/redoc', "'/redoc")):
            offenders.append(path.name)

    assert offenders == []
