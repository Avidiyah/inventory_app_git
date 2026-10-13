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
            return now.strftime("%Y-%m-%dT%H:%M:%SZ")
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
    merged = {**tokens, **(entry.token or {})}
    requested = entry.path or path
    templates = [requested, entry.body or ""] + ([entry.file[1]] if isinstance(entry.file, tuple) else [])
    if not all(_resolvable(t, merged) for t in templates):
        return None
    return Step(f"{method} {path}", method, requested, entry.body, entry.file, entry.expect, entry.as_user)


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
              "POST /attendance/punch-in", "POST /attendance/self-close",
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
    "POST /attendance/self-close": Entry(body=J({"ended_at": "{now}"}), as_user=T),
    "POST /hub/attendance/punches": Entry(
        body=J({"user_id": "{user_id}", "started_at": "{days_ago:3}T08:00:00Z", "ended_at": "{days_ago:3}T09:00:00Z"}),
        cycle=["POST /hub/attendance/punches", "DELETE /hub/attendance/punches/{punch_id}"]),
    "DELETE /hub/attendance/punches/{punch_id}": Entry(path="/hub/attendance/punches/{id}?reason=memprobe"),
    "PATCH /hub/attendance/punches/{punch_id}": Entry(body=J({"needs_review": False, "reason": "memprobe"})),
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
    "POST /tools/{tool_id}/adjust": Entry(body=J({"new_quantity": 5, "reason": "memprobe"})),
    "POST /tools/{tool_id}/checkout": Entry(body=J({"quantity": 1, "assigned_to_id": "{user_id}"}),
                                            cycle=["POST /tools/{tool_id}/checkout", "POST /tools/{tool_id}/return"]),
    "POST /tools/{tool_id}/return": Entry(body=J({"quantity": 1, "assigned_to_id": "{user_id}"})),
    # --- transactions ---
    "POST /transactions/": Entry(body=J({"item_id": "{item_id}", "transaction_type": "stock", "quantity": 1}),
                                 cycle=["POST /transactions/", "DELETE /transactions/{transaction_id}"]),
    "DELETE /transactions/{transaction_id}": Entry(path="/transactions/{id}"),
    "POST /transactions/adjust": Entry(body=J({"item_id": "{item_id}", "new_quantity": 5, "reason": "memprobe"})),
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
