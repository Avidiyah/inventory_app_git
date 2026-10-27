"""Route catalogue and pure planning/ranking for `memprobe.py sweep`.
Spec: docs/superpowers/specs/2026-10-13-memory-sweep-p2-design.md.
Never imports app.* at module level: the coverage test imports app.main itself."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

TOKEN_RE = re.compile(r"\{([a-z_0-9]+)(?::(\d+))?\}")
_BUILTIN_TOKENS = ("id", "seq", "now", "days_ago")


@dataclass(frozen=True)
class Entry:
    body: Optional[str] = None
    file: Optional[object] = None  # fixture path, or (filename, text template)
    cycle: Optional[list[str]] = None
    expect: Optional[int] = None
    exclude: Optional[str] = None
    path: Optional[str] = None
    token: Optional[dict[str, str]] = None
    as_user: str = "owner"


@dataclass(frozen=True)
class Step:
    route: str  # the enumerated key, so ranking lines up with app.routes
    method: str
    path: str  # what is actually requested, templates unfilled
    body: Optional[str]
    file: Optional[object]
    expect: Optional[int]
    as_user: str


@dataclass
class Plan:
    groups: list[list[Step]] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    excluded: list[tuple[str, str]] = field(default_factory=list)


def fill(template: str, tokens: dict[str, str], seq: int, now: datetime) -> str:
    def sub(m: re.Match) -> str:
        name, arg = m.group(1), m.group(2)
        if name == "id":
            return m.group(0)  # resolved by the driver from the last response
        if name == "seq":
            return str(seq)
        if name == "now":
            return now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")  # microseconds: a write must land after its punch-in
        if name == "days_ago":
            return (now - timedelta(days=int(arg))).strftime("%Y-%m-%d")
        return tokens[name]  # KeyError = unresolvable, caller decides

    return TOKEN_RE.sub(sub, template)


def enumerate_routes(app) -> tuple[list[tuple[str, str]], list[str]]:
    http, other = [], []
    for r in app.routes:
        methods = getattr(r, "methods", None)
        if methods:
            http += [(m, r.path) for m in sorted(methods - {"HEAD", "OPTIONS"})]
        elif "WebSocketRoute" in type(r).__name__:  # FastAPI's is APIWebSocketRoute
            other.append(f"WS {r.path}")
    return http, other


def _resolvable(template: str, tokens: dict[str, str]) -> bool:
    return all(n in tokens or n in _BUILTIN_TOKENS for n, _ in TOKEN_RE.findall(template))


def _step(method: str, path: str, entry: Entry, tokens: dict[str, str]) -> Optional[Step]:
    def literals(template: Optional[str]) -> Optional[str]:
        for name, value in (entry.token or {}).items():  # entry literals are applied at plan time
            template = template.replace(f"{{{name}}}", value) if template else template
        return template

    requested, body = literals(entry.path or path), literals(entry.body)
    templates = [requested, body or ""] + ([entry.file[1]] if isinstance(entry.file, tuple) else [])
    if not all(_resolvable(t, tokens) for t in templates):
        return None
    return Step(f"{method} {path}", method, requested, body, entry.file, entry.expect, entry.as_user)


def plan(routes, catalogue: dict[str, Entry], tokens: dict[str, str], only: Optional[str]) -> Plan:
    out = Plan()
    owners: dict[str, str] = {}
    for key, e in catalogue.items():
        for member in e.cycle or []:
            if member in owners and owners[member] != key:
                raise ValueError(f"{member} is in two cycles: {owners[member]} and {key}")
            owners[member] = key
    for method, path in routes:
        key = f"{method} {path}"
        if only and only not in key:
            continue
        owner = owners.get(key)
        if owner and owner != key:
            continue  # placed when its cycle's first member was
        entry = catalogue.get(key)
        if entry is None and method != "GET":
            out.skipped.append((method, path))  # a mutation needs a body or a cycle decision
            continue
        entry = entry or Entry()  # a GET resolves its tokens from the seed
        if entry.exclude:
            out.excluded.append((method, path))
            continue
        steps = []
        for m in entry.cycle or [key]:
            m_method, m_path = m.split(" ", 1)
            s = _step(m_method, m_path, catalogue.get(m, Entry()), tokens)
            if s is None:
                out.skipped.append((m_method, m_path))
                steps = []
                break
            steps.append(s)
        if steps:
            out.groups.append(steps)
    return out


# --- ranking and output ----------------------------------------------------

@dataclass
class RouteResult:
    route: str
    summary: object  # memprobe.Summary
    expect: Optional[int]
    state: str  # measured | failed


COLUMNS = ("method", "path", "n", "first_cg", "rest_sum_cg", "rest_max_cg", "rest_mean_cg", "first_rss",
           "rest_sum_rss", "drift_cg", "p50_ms", "max_ms", "statuses", "matched", "state")


@dataclass
class Row:
    method: str
    path: str
    n: int
    first_cg: Optional[int]
    rest_sum_cg: Optional[float]
    rest_max_cg: Optional[float]
    rest_mean_cg: Optional[float]
    first_rss: Optional[int]
    rest_sum_rss: Optional[float]
    drift_cg: Optional[int]
    p50_ms: Optional[int]
    max_ms: Optional[int]
    statuses: str
    matched: str
    state: str


def _state(r: RouteResult) -> str:
    s = r.summary
    bad = any(not (200 <= code < 300) and code != r.expect for code in s.statuses)
    return "failed" if bad or s.unmatched or r.state == "failed" else "measured"


def rank(results: list[RouteResult]) -> list[Row]:
    rows = []
    for r in results:
        s = r.summary
        method, path = r.route.split(" ", 1)
        a, b = s.drift["cg_mb"]
        rows.append(Row(method, path, s.sent, s.first["cg_delta_mb"], s.rest["cg_delta_mb"]["sum"],
                        s.rest["cg_delta_mb"]["max"], s.rest["cg_delta_mb"]["mean"], s.first["rss_delta_mb"],
                        s.rest["rss_delta_mb"]["sum"], None if a is None or b is None else b - a, s.ms_p50, s.ms_max,
                        " ".join(f"{c}x{n}" for c, n in s.statuses.items()), f"{s.matched}/{s.sent}", _state(r)))
    return sorted(rows, key=lambda x: (-(x.rest_sum_cg or 0), -(x.rest_max_cg or 0), x.path))


def to_csv(rows: list[Row], skipped, excluded, path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(COLUMNS)
        for r in rows:
            w.writerow(["" if getattr(r, c) is None else getattr(r, c) for c in COLUMNS])
        for state, pairs in (("skipped", skipped), ("excluded", excluded)):
            for m, p in pairs:
                w.writerow([m, p] + [""] * (len(COLUMNS) - 3) + [state])


def render_sweep(rows: list[Row], start, end, plan: Plan, container: str, n: int) -> str:
    def fmt(v):
        return "-" if v is None else (f"{v:.2f}" if isinstance(v, float) else str(v))

    def base(s):
        return "-" if s is None else f"cg_mb={fmt(s.cg_mb)} rss_mb={fmt(s.rss_mb)}"

    measured = [r for r in rows if r.state == "measured"]
    failed = [r for r in rows if r.state == "failed"]
    out = [f"sweep        routes={len(rows) + len(plan.skipped) + len(plan.excluded)} measured={len(measured)} "
           f"failed={len(failed)} skipped={len(plan.skipped)} excluded={len(plan.excluded)}   n={n}  container={container}",
           f"baseline     start {base(start)}   end {base(end)}", "",
           f"{'rank':>4}  {'route':64} {'first':>5} {'rest(sum)':>9} {'rest(max)':>9} {'rest(mean)':>10} "
           f"{'rss(sum)':>8} {'p50ms':>5}  statuses"]
    for i, r in enumerate(rows, 1):
        out.append(f"{i:>4}  {r.method + ' ' + r.path:64} {fmt(r.first_cg):>5} {fmt(r.rest_sum_cg):>9} "
                   f"{fmt(r.rest_max_cg):>9} {fmt(r.rest_mean_cg):>10} {fmt(r.rest_sum_rss):>8} {fmt(r.p50_ms):>5}  "
                   f"{r.statuses}")
    for title, items in (("failed", [f"{r.method} {r.path}  {r.statuses}  matched {r.matched}" for r in failed]),
                         ("skipped", [f"{m} {p}  no catalogue entry or unresolvable token" for m, p in plan.skipped]),
                         ("excluded", [f"{m} {p}" for m, p in plan.excluded])):
        if items:
            out += ["", title] + [f"  {x}" for x in items]
    return "\n".join(out)


# ---------------------------------------------------------------------------
# The catalogue. Keys are exactly what enumerate_routes prints. Every mutating
# route is here; GETs appear only when they carry a token or need a query.
# Ids come from the seed unless the path carries {id} (the most recent JSON
# response in the cycle). `T` = the seed technician's cookie jar.
# ---------------------------------------------------------------------------
J = json.dumps
T = "technician"
# Same literal as tests/e2e/_seed.SIGNATURE_PNG (this module must not import app.*).
SIGNATURE_PNG = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)

EXCLUDED = (
    "POST /auth/login", "POST /auth/logout",
    "POST /push/subscribe", "POST /push/unsubscribe",
    "POST /users/{user_id}/reset-password",
    "POST /integrations/netfacilities/cloud/auth/start",
    "POST /integrations/netfacilities/work-orders/enrich",
    "POST /integrations/netfacilities/cloud/downloads/import",
    "POST /hub/attendance/week/review",       # marks real dev-DB punches reviewed
    "POST /work-orders/legacy/archive",       # archives real dev-DB rows
)
WO_LIFECYCLE = ["PATCH /work-orders/{work_order_id}", "POST /work-orders/{work_order_id}/start",
                "POST /work-orders/{work_order_id}/hold", "POST /work-orders/{work_order_id}/resume",
                "POST /work-orders/{work_order_id}/complete"]
ATTENDANCE = ["POST /attendance/punch-in", "POST /attendance/punch-out",
              "POST /attendance/punch-in", "POST /hub/attendance/clock-out/{user_id}"]
MATERIAL = ["POST /user-requests/material-request", "POST /user-requests/{request_id}/cancel",
            "POST /user-requests/material-request", "POST /user-requests/{request_id}/mark-stocked",
            "PATCH /user-requests/{request_id}"]
STAGES = ["POST /mass-stages/", "DELETE /mass-stages/{stage_id}",
          "POST /mass-stages/{stage_id}/reuse", "DELETE /mass-stages/{stage_id}"]

CATALOGUE: dict[str, Entry] = {k: Entry(exclude="see EXCLUDED") for k in EXCLUDED} | {
    # --- GETs that need a token or query ---
    "GET /tools/{barcode}": Entry(path="/tools/{tool_barcode}"),
    "GET /work-orders/{work_order_id}/signature.png": Entry(path="/work-orders/{signed_work_order_id}/signature.png"),
    "GET /workorder_card/{number}": Entry(path="/workorder_card/{work_order_number}"),
    "GET /work-orders/lookup": Entry(path="/work-orders/lookup?number={work_order_number}"),
    "GET /integrations/netfacilities/work-orders/enrich/{job_id}": Entry(
        token={"job_id": "00000000-0000-4000-8000-000000000000"}, expect=404),
    "POST /integrations/netfacilities/cloud/auth/cancel": Entry(expect=409),
    # --- attendance (technician punches; owner clocks them out) ---
    "POST /attendance/punch-in": Entry(cycle=ATTENDANCE, as_user=T),
    "POST /attendance/punch-out": Entry(as_user=T),
    "POST /hub/attendance/punches": Entry(
        body=J({"user_id": "{user_id}", "started_at": "{days_ago:3}T08:00:00Z", "ended_at": "{days_ago:3}T09:00:00Z"}),
        cycle=["POST /hub/attendance/punches", "PATCH /hub/attendance/punches/{punch_id}",
               "DELETE /hub/attendance/punches/{punch_id}"]),
    # An edit that changes nothing is a 400, so the PATCH moves the fresh punch's end.
    "PATCH /hub/attendance/punches/{punch_id}": Entry(path="/hub/attendance/punches/{id}",
                                                      body=J({"ended_at": "{days_ago:3}T10:00:00Z", "reason": "memprobe"})),
    "DELETE /hub/attendance/punches/{punch_id}": Entry(path="/hub/attendance/punches/{id}?reason=memprobe"),
    "POST /barcodes/decode": Entry(file="tests/fixtures/code128.png"),
    # --- items ---
    "POST /items/": Entry(body=J({"barcode": "{prefix}-I{seq}", "name": "{prefix} new", "location": "{prefix}-shelf"}),
                          cycle=["POST /items/", "DELETE /items/{item_id}"]),
    "DELETE /items/{item_id}": Entry(path="/items/{id}"),
    "PATCH /items/{item_id}": Entry(body=J({"name": "{prefix} widget"})),
    "PATCH /items/{item_id}/notes": Entry(body=J({"notes": {"memprobe": "x"}})),
    "PATCH /items/{item_id}/barcodes": Entry(body=J({"barcodes": []})),
    "PATCH /items/{item_id}/low-stock-threshold": Entry(body=J({"low_stock_threshold": 1})),
    "POST /items/dispense-exports": Entry(),
    # --- mass stages ---
    "POST /mass-stages/": Entry(body=J({"community": "{prefix} community", "building_name": "B{seq}"}), cycle=STAGES),
    "DELETE /mass-stages/{stage_id}": Entry(path="/mass-stages/{id}"),
    "POST /mass-stages/{stage_id}/reuse": Entry(path="/mass-stages/{completed_stage_id}/reuse"),
    "PATCH /mass-stages/{stage_id}": Entry(body=J({"community": "{prefix} community"})),
    "POST /mass-stages/{stage_id}/work-orders": Entry(
        body=J({"work_order_number": "{signed_work_order_number}"}),
        cycle=["POST /mass-stages/{stage_id}/work-orders", "DELETE /mass-stages/{stage_id}/work-orders/{slot_id}"]),
    "DELETE /mass-stages/{stage_id}/work-orders/{slot_id}": Entry(path="/mass-stages/{stage_id}/work-orders/{id}"),
    "POST /mass-stages/{stage_id}/work-orders/{slot_id}/items": Entry(
        body=J({"item_id": "{item2_id}", "planned_quantity": 1}),
        cycle=["POST /mass-stages/{stage_id}/work-orders/{slot_id}/items",
               "DELETE /mass-stages/{stage_id}/work-orders/{slot_id}/items/{stage_item_id}"]),
    "DELETE /mass-stages/{stage_id}/work-orders/{slot_id}/items/{stage_item_id}": Entry(
        path="/mass-stages/{stage_id}/work-orders/{slot_id}/items/{id}"),
    "PATCH /mass-stages/{stage_id}/work-orders/{slot_id}/items/{stage_item_id}": Entry(body=J({"planned_quantity": 2})),
    "POST /mass-stages/{stage_id}/load": Entry(path="/mass-stages/{loading_stage_id}/load",
                                               body=J({"item_id": "{item_id}", "quantity": 1}),
                                               cycle=["POST /mass-stages/{stage_id}/load", "POST /mass-stages/{stage_id}/return"]),
    "POST /mass-stages/{stage_id}/return": Entry(path="/mass-stages/{loading_stage_id}/return",
                                                 body=J({"item_id": "{item_id}", "quantity": 1})),
    # --- push ---
    "POST /push/test": Entry(),            # add expect=503 if the container has no VAPID keys (acceptance run decides)
    # --- tools ---
    "POST /tools/": Entry(body=J({"barcode": "{prefix}-T{seq}", "name": "{prefix} saw"}),
                          cycle=["POST /tools/", "DELETE /tools/{tool_id}"]),
    "DELETE /tools/{tool_id}": Entry(path="/tools/{id}"),
    "PATCH /tools/{tool_id}": Entry(body=J({"name": "{prefix} drill"})),
    # Adjusting to the current quantity is a 400; "1{seq}" is a new number every request.
    "POST /tools/{tool_id}/adjust": Entry(body='{"new_quantity": 1{seq}, "reason": "memprobe"}'),
    "POST /tools/{tool_id}/checkout": Entry(body=J({"quantity": 1, "assigned_to_id": "{user_id}"}),
                                            cycle=["POST /tools/{tool_id}/checkout", "POST /tools/{tool_id}/return"]),
    "POST /tools/{tool_id}/return": Entry(body=J({"quantity": 1, "assigned_to_id": "{user_id}"})),
    # --- transactions ---
    "POST /transactions/": Entry(body=J({"item_id": "{item_id}", "transaction_type": "stock", "quantity": 1}),
                                 cycle=["POST /transactions/", "DELETE /transactions/{transaction_id}"]),
    "DELETE /transactions/{transaction_id}": Entry(path="/transactions/{id}"),
    "POST /transactions/adjust": Entry(body='{"item_id": "{item_id}", "new_quantity": 1{seq}, "reason": "memprobe"}'),
    "PATCH /transactions/{transaction_id}/billing": Entry(body=J({"billable_quantity": 1})),
    # --- user requests ---
    "POST /user-requests/material-request": Entry(
        body=J({"item_id": "{item_id}", "work_order_id": "{active_work_order_id}", "quantity": 1}), cycle=MATERIAL),
    "POST /user-requests/{request_id}/cancel": Entry(path="/user-requests/{id}/cancel"),
    "POST /user-requests/{request_id}/mark-stocked": Entry(path="/user-requests/{id}/mark-stocked"),
    "PATCH /user-requests/{request_id}": Entry(path="/user-requests/{id}",
                                               body=J({"status": "resolved", "resolution_note": "memprobe"})),
    "POST /user-requests/catalogue-request": Entry(
        body=J({"searched_text": "{prefix} thing {seq}", "source": "find_item", "work_order_id": "{active_work_order_id}"}),
        cycle=["POST /user-requests/catalogue-request", "POST /user-requests/{request_id}/fulfill"]),
    "POST /user-requests/{request_id}/fulfill": Entry(path="/user-requests/{id}/fulfill", body=J({"item_id": "{item_id}"})),
    # --- users ---
    "POST /users/": Entry(body=J({"username": "{prefix}-u{seq}", "first_name": "Eetoo", "last_name": "U",
                                  "password": "e2e-password-1", "role": "technician"}),
                          cycle=["POST /users/", "DELETE /users/{user_id}"]),
    "DELETE /users/{user_id}": Entry(path="/users/{id}"),
    "PATCH /users/{user_id}/name": Entry(body=J({"first_name": "Eetoo", "last_name": "Tech"})),
    "PATCH /users/{user_id}/role": Entry(body=J({"role": "technician"})),
    "POST /users/{user_id}/archive": Entry(cycle=["POST /users/{user_id}/archive", "POST /users/{user_id}/restore"]),
    "POST /users/{user_id}/restore": Entry(),
    # --- work orders ---
    "POST /work-orders/import": Entry(file=("import.csv", "WORK ORDER,LOCATION\r\n{prefix}-IMP{seq},Commons\r\n")),
    "POST /work-orders/smr/import": Entry(file=("smr.csv",
        "WORK ORDER,FILED STATUS,LOCATION,ASSIGNED TO,SERVICE TYPE,SCHEDULE DATE\r\n"
        "{prefix}-SMR{seq},Closed,Commons,,SMR27 - Belfor,\r\n")),
    "POST /work-orders/smr/import-targets": Entry(file=("breakdown.csv",
        "WO#,Hours,Total Material Cost\r\n{prefix}-SMR{seq},0.5,$31.25\r\n")),
    # The seeded work order is not an SMR order, so the cheap refusal path.
    "PUT /work-orders/smr/{work_order_id}/paper-check": Entry(body=J({"checked": True}), as_user=T, expect=400),
    "PATCH /work-orders/{work_order_id}": Entry(body=J({"status": "assigned", "assigned_to_ids": ["{user_id}"]}), cycle=WO_LIFECYCLE),
    "POST /work-orders/{work_order_id}/start": Entry(as_user=T),
    "POST /work-orders/{work_order_id}/hold": Entry(as_user=T),
    "POST /work-orders/{work_order_id}/resume": Entry(as_user=T),
    "POST /work-orders/{work_order_id}/complete": Entry(as_user=T),
    "POST /work-orders/{work_order_id}/tracking/start": Entry(
        path="/work-orders/{active_work_order_id}/tracking/start",
        cycle=["POST /work-orders/{work_order_id}/tracking/start", "POST /work-orders/{work_order_id}/tracking/stop"]),
    "POST /work-orders/{work_order_id}/tracking/stop": Entry(path="/work-orders/{active_work_order_id}/tracking/stop"),
    "POST /work-orders/{work_order_id}/archive": Entry(
        path="/work-orders/{active_work_order_id}/archive",
        cycle=["POST /work-orders/{work_order_id}/archive", "POST /work-orders/{work_order_id}/restore"]),
    "POST /work-orders/{work_order_id}/restore": Entry(path="/work-orders/{active_work_order_id}/restore"),
    "DELETE /work-orders/{work_order_id}/signature": Entry(
        path="/work-orders/{signed_work_order_id}/signature",
        cycle=["DELETE /work-orders/{work_order_id}/signature", "POST /work-orders/{work_order_id}/signature"]),
    "POST /work-orders/{work_order_id}/signature": Entry(
        path="/work-orders/{signed_work_order_id}/signature",
        body=J({"image": SIGNATURE_PNG, "witness_name": "Eetoo Witness", "witness_phone": "5555555555"})),
    "POST /work-orders/{work_order_id}/items": Entry(
        path="/work-orders/{active_work_order_id}/items", body=J({"item_id": "{item2_id}", "quantity": 1}),
        cycle=["POST /work-orders/{work_order_id}/items", "DELETE /work-orders/{work_order_id}/items/{wo_item_id}"]),
    "DELETE /work-orders/{work_order_id}/items/{wo_item_id}": Entry(path="/work-orders/{active_work_order_id}/items/{id}"),
    "PATCH /work-orders/{work_order_id}/items/{wo_item_id}": Entry(
        path="/work-orders/{active_work_order_id}/items/{wo_item_id}", body=J({"quantity": 1})),
    "PATCH /work-orders/{work_order_id}/items/{wo_item_id}/billing": Entry(
        path="/work-orders/{active_work_order_id}/items/{wo_item_id}/billing", body=J({"billable_quantity": 1})),
    "POST /work-orders/{work_order_id}/labor": Entry(
        path="/work-orders/{active_work_order_id}/labor", body=J({"technician_id": "{user_id}", "minutes": 5}),
        cycle=["POST /work-orders/{work_order_id}/labor", "DELETE /work-orders/{work_order_id}/labor/{labor_id}"]),
    "DELETE /work-orders/{work_order_id}/labor/{labor_id}": Entry(path="/work-orders/{active_work_order_id}/labor/{id}"),
    "PATCH /work-orders/{work_order_id}/labor/{labor_id}": Entry(
        path="/work-orders/{active_work_order_id}/labor/{labor_id}", body=J({"minutes": 6})),
}
