"""Router-boundary tests for the Work Orders list endpoint.

Drives the route over real HTTP rather than calling the handler function
directly, following `test_hub_router.py`'s
`test_graphs_route_accepts_the_default_week_count_over_real_http`: a
direct call never exercises FastAPI's query-string parsing, which is
where this repo has already been bitten once (FastAPI 0.136 / Pydantic
2.13 and int `Literal` params).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models import User
from app.services import auth as auth_service
from app.services import work_orders as wos


def _seed_user(db, role):
    user = User(
        username=f"u-{uuid.uuid4().hex[:10]}",
        password_hash=auth_service.hash_password("hunter2"),
        role=role,
    )
    db.add(user)
    db.flush()
    return user


def _numbers(db, token, query):
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            client.cookies.set("session", token)
            response = client.get(f"/work-orders/{query}")
    finally:
        del app.dependency_overrides[get_db]
    assert response.status_code == 200, response.text
    return {card["number"] for card in response.json()}


def test_mine_returns_a_work_order_routed_to_the_caller(db):
    """The deployment bug: an Admin routes a work order to a Supervisor and
    the Supervisor's User Hub "My Work Orders" tab stays empty, because that
    tab filtered on `assigned_to_id` -- which tests worker assignment only
    and cannot see routing."""
    admin = _seed_user(db, "admin")
    supervisor = _seed_user(db, "supervisor")
    prefix = f"WO-HTTP-{uuid.uuid4().hex[:8]}"

    routed = wos.get_or_create_work_order(
        db, number=f"{prefix}-R", created_by_id=admin.id, supervisor_id=supervisor.id
    )
    db.commit()
    token = auth_service.create_session(db, supervisor)

    # Every query carries the number prefix so the assertions stay
    # independent of how many work orders the database already holds --
    # otherwise `MAX_LIST_ROWS` could quietly drop the fixture row.
    assert routed.number in _numbers(db, token, f"?mine=true&q={prefix}")
    # The old hub filter, kept here as the contrast that explains the flag.
    assert routed.number not in _numbers(
        db, token, f"?assigned_to_id={supervisor.id}&q={prefix}"
    )


def test_mine_defaults_to_off(db):
    """Omitting the flag must not silently narrow an Admin's company-wide
    list -- the standalone Work Orders page sends no `mine`."""
    admin = _seed_user(db, "admin")
    other_supervisor = _seed_user(db, "supervisor")
    prefix = f"WO-HTTPOFF-{uuid.uuid4().hex[:8]}"

    someone_elses = wos.get_or_create_work_order(
        db,
        number=f"{prefix}-X",
        created_by_id=admin.id,
        supervisor_id=other_supervisor.id,
    )
    db.commit()
    token = auth_service.create_session(db, admin)

    assert someone_elses.number in _numbers(db, token, f"?q={prefix}")
    assert someone_elses.number not in _numbers(
        db, token, f"?mine=true&q={prefix}"
    )




def test_location_q_and_task_q_filter_over_real_http(db):
    admin = _seed_user(db, "admin")
    prefix = f"WO-KW-{uuid.uuid4().hex[:8]}"
    match = wos.get_or_create_work_order(
        db,
        number=f"{prefix}-M",
        created_by_id=admin.id,
        location="Building 2312",
        description="leaking sink trap",
    )
    miss = wos.get_or_create_work_order(
        db,
        number=f"{prefix}-X",
        created_by_id=admin.id,
        location="Building 9000",
        description="door hinge",
    )
    db.commit()
    token = auth_service.create_session(db, admin)

    by_location = _numbers(db, token, f"?q={prefix}&location_q=2312")
    assert match.number in by_location and miss.number not in by_location

    by_task = _numbers(db, token, f"?q={prefix}&task_q=sink")
    assert match.number in by_task and miss.number not in by_task

    # All three text searches AND together: location matches only -M,
    # task matches only -X, so their intersection is empty.
    assert _numbers(db, token, f"?q={prefix}&location_q=2312&task_q=hinge") == set()


def test_blank_keyword_params_are_noops_over_real_http(db):
    admin = _seed_user(db, "admin")
    prefix = f"WO-KWB-{uuid.uuid4().hex[:8]}"
    work_order = wos.get_or_create_work_order(
        db, number=f"{prefix}-B", created_by_id=admin.id
    )
    db.commit()
    token = auth_service.create_session(db, admin)

    assert work_order.number in _numbers(
        db, token, f"?q={prefix}&location_q=&task_q="
    )

# --- UI wiring guards ----------------------------------------------------
#
# Same idiom as `test_work_order_priority.py::test_work_orders_ui_wires_a_
# priority_filter`: the browser half has no test framework in this repo, so
# the wiring that connects it to the API above is pinned as source text.

def _view(name):
    static_dir = Path(__file__).resolve().parents[1] / "static"
    return (static_dir / "views" / name).read_text(encoding="utf-8")


def _code(name):
    """`_view` with `//` comment lines dropped.

    These files carry long explanatory comments that name the very
    identifiers under test -- including the ones recording why they were
    removed -- so a raw substring check reads the prose and fails.
    """
    return "\n".join(
        line
        for line in _view(name).splitlines()
        if not line.lstrip().startswith("//")
    )


def test_hub_work_orders_tab_requests_mine_not_assigned_to_id():
    """The Supervisor's dashboard tab must ask for `mine`. `assignedToId`
    cannot see routing, which is what emptied the tab in deployment."""
    code = _code("hubTechnician.js")

    assert "lockedFilter.mine = true" in code
    assert "assignedToId" not in code


def test_the_tab_label_count_is_live_and_reads_mine_total():
    """Two separate defects, both pinned here.

    The number: `counts.assigned` is worker assignment only, so it read "(0)"
    for a Supervisor whose work was all routed to them.

    The liveness: the label used to be written in exactly one place, inside
    `loadUserHub`. Every background refresh replaced `latestPayload` without
    touching it, so the count only moved on a full page re-entry.
    """
    code = _code("userHub.js")

    assert "`My Work Orders (${latestPayload.mine_total})`" in code
    assert "counts.assigned" not in code
    # Rendered from a helper rather than inline, and called on the refresh
    # path as well as the initial load -- that pair is what makes it live.
    assert "function renderWorkOrdersTabLabel()" in code
    assert code.count("renderWorkOrdersTabLabel();") >= 2

    refresh_body = code.split("async function refreshPersonal")[1]
    assert "renderWorkOrdersTabLabel();" in refresh_body
    # The cards move with the number. A live count over a stale list is the
    # same disagreement wearing a different hat.
    assert "refreshHubWorkOrders();" in refresh_body
    assert "export function refreshHubWorkOrders()" in _code("hubTechnician.js")


def test_api_client_sends_the_mine_flag():
    view = _view("../api.js")

    assert 'params.set("mine", "true")' in view


def test_only_the_solo_card_suppresses_its_own_click():
    """A card's click handler must decide from the card, not from the
    module-global `soloActive`. That global is cleared only inside
    `loadWorkOrders`, so leaving the card page for the User Hub left it set
    and the hub's own cards stopped responding to clicks entirely."""
    code = _code("workOrders.js")

    assert "function buildCard(card, { onOpen, solo = false } = {})" in code
    assert "if (solo) return;" in code
    assert "if (soloActive) return;" not in code
    # The card page's own card is the one that opts in.
    assert "buildCard(detail, { solo: true })" in code



def test_work_orders_ui_wires_location_and_task_searches():
    """The two keyword filters exist in the grid, feed currentFilters, clear
    with Clear filters, and reach the API as `location_q` / `task_q` --
    without inheriting the number bar's archived-restore lookup."""
    html = (
        Path(__file__).resolve().parents[1] / "static" / "pages" / "work-orders.html"
    ).read_text(encoding="utf-8")
    assert 'id="work-orders-location-search"' in html
    assert 'id="work-orders-task-search"' in html
    # Both live in their own inline row beneath the number-search bar --
    # deliberately out of the filter grid.
    assert '<div class="filter-row wo-keyword-search-row">' in html

    code = _code("workOrders.js")
    assert 'getElementById("work-orders-location-search")' in code
    assert 'getElementById("work-orders-task-search")' in code
    assert "locationQ: locationSearchInput" in code
    assert "taskQ: taskSearchInput" in code
    assert "wireKeywordSearch(locationSearchInput)" in code
    assert "wireKeywordSearch(taskSearchInput)" in code
    assert 'if (locationSearchInput) locationSearchInput.value = "";' in code
    assert 'if (taskSearchInput) taskSearchInput.value = "";' in code

    view = _view("../api.js")
    assert 'params.set("location_q", locationQ)' in view
    assert 'params.set("task_q", taskQ)' in view
    assert 'params.set("location_q", filters.locationQ)' in view
    assert 'params.set("task_q", filters.taskQ)' in view
