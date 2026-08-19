"""Tests for the deep-linked work-order card shell route.

Layer: unit (no DB, no HTTP client). Matches the "call the handler
directly" style of `test_health_check.py`.

`/workorder_card/{number}` exists for one reason: the Work Orders page
pushes that URL when a card is opened, so a refresh, a bookmark, or a
pasted link must reach the app instead of a 404. It serves the *same*
document as `/` -- there is only one document. Two of these are
regression guards rather than behavior tests:

- `test_the_number_is_never_reflected_into_the_document` -- this path is
  the one URL in the app that a user composes and sends to someone else.
  Substituting the segment into the HTML would make it an injection
  surface. The client reads the number back off `location.pathname`.
- `test_the_shell_route_has_no_auth_dependency` -- a deep link is
  followed by a browser with no session yet. An auth dependency here
  would 401 before the login screen could ever render, so the link would
  be unusable for exactly the person it was shared with.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.routing import APIRoute

from app import main


def _shell_route():
    for route in main.app.routes:
        if isinstance(route, APIRoute) and route.endpoint.__name__ == "workorder_card_shell":
            return route
    raise AssertionError("route 'workorder_card_shell' not found on the app")


def test_it_serves_the_same_document_as_the_root():
    assert main.workorder_card_shell("12345").body == main.read_root().body


def test_it_returns_html_with_a_200():
    response = main.workorder_card_shell("12345")

    assert response.status_code == 200
    assert response.media_type == "text/html"


def test_it_is_not_cached():
    # Matches `read_root`: the shell is assembled from fragments on every
    # request, and a cached copy would serve stale markup after an edit.
    assert main.workorder_card_shell("12345").headers["cache-control"] == "no-cache"


def test_the_number_is_never_reflected_into_the_document():
    hostile = "<script>alert(1)</script>"

    assert hostile.encode() not in main.workorder_card_shell(hostile).body


def test_the_route_path_matches_the_client_prefix():
    # static/views/workOrders.js pushes SOLO_PATH_PREFIX + the number. The
    # two strings are the whole contract between the client and this route.
    assert _shell_route().path == "/workorder_card/{number}"


def test_the_shell_route_has_no_auth_dependency():
    route = _shell_route()

    assert route.dependant.dependencies == []
    assert route.dependencies == []
