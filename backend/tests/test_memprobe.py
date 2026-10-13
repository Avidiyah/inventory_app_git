"""Host-side tests for the pure half of scripts/memprobe.py. No HTTP, no
Docker, no database: the acceptance run in the plan covers those."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import memprobe

LINE = (
    "ts=2026-10-13T15:07:38.974Z level=INFO req={req} event=request method=GET "
    "path=/items status={status} ms={ms} rss_mb={rss} cg_mb={cg} "
    "cg_delta_mb={cgd} rss_delta_mb={rssd}"
)


def _line(req, status=200, ms=5, rss=112, cg=178, cgd=0, rssd=0):
    return LINE.format(req=req, status=status, ms=ms, rss=rss, cg=cg, cgd=cgd, rssd=rssd)


def test_parse_keeps_only_wanted_request_ids():
    text = "\n".join([_line("aaa"), _line("bbb"), "==> starting uvicorn", _line("ccc")])
    out = memprobe.parse_request_lines(text, {"aaa", "ccc"})
    assert set(out) == {"aaa", "ccc"}
    assert out["aaa"] == memprobe.Sample("aaa", 200, 5, 112, 178, 0, 0)


def test_parse_treats_dash_as_absent():
    text = _line("aaa", rss="-", cg="-", cgd="-", rssd="-")
    sample = memprobe.parse_request_lines(text, {"aaa"})["aaa"]
    assert (sample.rss_mb, sample.cg_mb, sample.cg_delta_mb, sample.rss_delta_mb) == (None,) * 4
    assert sample.status == 200


def test_parse_accepts_an_error_line_without_status():
    text = (
        "ts=x level=ERROR req=err1 event=request.error method=POST path=/items "
        "ms=12 rss_mb=120 cg_mb=190 cg_delta_mb=8 rss_delta_mb=8"
    )
    sample = memprobe.parse_request_lines(text, {"err1"})["err1"]
    assert sample.status is None
    assert sample.cg_delta_mb == 8


def test_parse_ignores_non_request_events_with_a_matching_id():
    text = "ts=x level=INFO req=aaa event=auth.login_ok user=o ip=1.2.3.4"
    assert memprobe.parse_request_lines(text, {"aaa"}) == {}


def _sent(*ids, status=200):
    return [memprobe.Sent(i, status) for i in ids]


def _samples(*rows):
    """rows: (req, cg_delta, rss_delta, cg_mb, rss_mb, ms)"""
    return {
        r[0]: memprobe.Sample(r[0], 200, r[5], r[4], r[3], r[1], r[2]) for r in rows
    }


def test_aggregate_separates_first_from_rest_and_reports_drift():
    sent = _sent("a", "b", "c")
    samples = _samples(("a", 12, 9, 190, 121, 40), ("b", 1, 1, 191, 122, 5), ("c", 3, 0, 194, 122, 7))
    s = memprobe.aggregate(sent, samples)
    assert s.sent == 3 and s.matched == 3 and s.unmatched == []
    assert s.first == {"cg_delta_mb": 12, "rss_delta_mb": 9}
    assert s.rest["cg_delta_mb"] == {"sum": 4, "max": 3, "mean": 2.0}
    assert s.rest["rss_delta_mb"] == {"sum": 1, "max": 1, "mean": 0.5}
    assert s.drift == {"cg_mb": (190, 194), "rss_mb": (121, 122)}
    assert (s.ms_p50, s.ms_max) == (7, 40)


def test_aggregate_reports_unmatched_ids():
    sent = [memprobe.Sent("a", 200), memprobe.Sent(None, 200), memprobe.Sent("z", 200)]
    s = memprobe.aggregate(sent, _samples(("a", 0, 0, 178, 112, 5)))
    assert s.matched == 1
    assert s.unmatched == ["<no X-Request-ID>", "z"]


def test_aggregate_with_one_request_has_no_rest():
    s = memprobe.aggregate(_sent("a"), _samples(("a", 5, 2, 183, 114, 9)))
    assert s.first["cg_delta_mb"] == 5
    assert s.rest["cg_delta_mb"] == {"sum": 0, "max": None, "mean": None}


def test_aggregate_excludes_absent_readings_from_sums():
    sent = _sent("a", "b", "c")
    samples = _samples(("a", 1, 1, 180, 113, 5), ("c", 2, 2, 182, 115, 5))
    samples["b"] = memprobe.Sample("b", 200, 5, None, None, None, None)
    s = memprobe.aggregate(sent, samples)
    assert s.rest["cg_delta_mb"] == {"sum": 2, "max": 2, "mean": 2.0}
    assert s.readings == 2


def test_aggregate_counts_a_429_as_a_status():
    sent = _sent("a") + _sent("b", status=429)
    samples = _samples(("a", 0, 0, 178, 112, 5), ("b", 0, 0, 178, 112, 1))
    assert memprobe.aggregate(sent, samples).statuses == {200: 1, 429: 1}


def test_render_prints_dashes_for_absent_values():
    s = memprobe.aggregate(_sent("a"), _samples(("a", 5, 2, 183, 114, 9)))
    text = memprobe.render("GET /items", "inventory-local", None, s)
    assert "baseline     -" in text
    assert "rest(max)" in text and "matched      1/1" in text


# --- Phase 2: catalogue model and planner (scripts/memprobe_routes.py) ---

from datetime import datetime, timezone  # noqa: E402

import pytest  # noqa: E402

from scripts import memprobe_routes as mr  # noqa: E402

NOW = datetime(2026, 10, 13, 15, 0, 0, tzinfo=timezone.utc)
TOKENS = {"item_id": "I1", "barcode": "E2E-x-ITEM", "prefix": "E2E-x"}


def test_fill_substitutes_seed_seq_now_and_days_ago():
    out = mr.fill('{"a":"{item_id}","b":"{prefix}-{seq}","c":"{now}","d":"{days_ago:3}","e":"{id}"}', TOKENS, 7, NOW)
    assert out == '{"a":"I1","b":"E2E-x-7","c":"2026-10-13T15:00:00Z","d":"2026-10-10","e":"{id}"}'


def test_fill_raises_on_unknown_token():
    with pytest.raises(KeyError):
        mr.fill("/x/{nope}", TOKENS, 0, NOW)


def _routes():
    return [("GET", "/healthz"), ("GET", "/items/{barcode}"), ("POST", "/items/"),
            ("DELETE", "/items/{item_id}"), ("POST", "/new"), ("GET", "/x/{unknown}")]


def _catalogue():
    return {
        "POST /items/": mr.Entry(body='{"barcode":"{prefix}-{seq}"}', cycle=["POST /items/", "DELETE /items/{item_id}"]),
        "DELETE /items/{item_id}": mr.Entry(path="/items/{id}"),
        "POST /new": mr.Entry(exclude="because"),
    }


def test_plan_groups_cycles_and_token_free_gets():
    p = mr.plan(_routes()[:5], _catalogue(), TOKENS, only=None)
    routes = [[s.route for s in g] for g in p.groups]
    assert routes == [["GET /healthz"], ["GET /items/{barcode}"], ["POST /items/", "DELETE /items/{item_id}"]]
    assert p.excluded == [("POST", "/new")]
    assert p.skipped == []
    assert p.groups[2][1].path == "/items/{id}"


def test_plan_skips_uncatalogued_and_unresolvable():
    p = mr.plan(_routes(), {}, TOKENS, only=None)
    assert ("POST", "/items/") in p.skipped and ("GET", "/x/{unknown}") in p.skipped
    assert ("GET", "/items/{barcode}") not in p.skipped


def test_plan_only_filters_by_substring():
    p = mr.plan(_routes()[:5], _catalogue(), TOKENS, only="/items")
    assert [s.route for g in p.groups for s in g] == ["GET /items/{barcode}", "POST /items/", "DELETE /items/{item_id}"]
    assert p.excluded == []


def test_plan_cycle_declared_once_and_member_in_one_cycle():
    bad = {"POST /items/": mr.Entry(cycle=["POST /items/", "DELETE /items/{item_id}"]),
           "DELETE /items/{item_id}": mr.Entry(cycle=["DELETE /items/{item_id}", "POST /items/"])}
    with pytest.raises(ValueError):
        mr.plan(_routes()[:4], bad, TOKENS, only=None)


def test_every_route_is_catalogued_or_excluded():
    """The drift guard: a new route must get a catalogue entry or an exclude."""
    from app.main import app
    from tests.e2e import _seed
    routes, _ = mr.enumerate_routes(app)
    tokens = {k: "x" for k in vars(_seed.Seed("p", "o", "w", "b"))} | {"barcode": "x", "wo": "x", "prefix": "x"}
    p = mr.plan(routes, mr.CATALOGUE, tokens, only=None)
    assert p.skipped == []
    assert {f"{m} {path}" for m, path in p.excluded} == set(mr.EXCLUDED)
    covered = {s.route for g in p.groups for s in g} | {f"{m} {path}" for m, path in p.excluded}
    assert covered == {f"{m} {path}" for m, path in routes}
    assert mr.SIGNATURE_PNG == _seed.SIGNATURE_PNG


def test_catalogue_keys_are_real_routes():
    from app.main import app
    routes, _ = mr.enumerate_routes(app)
    keys = {f"{m} {p}" for m, p in routes}
    assert set(mr.CATALOGUE) - keys == set()


# --- Phase 2: ranking, CSV, multipart and the cycle driver ---


def _result(route, first=0, rest=(0,), expect=None):
    sent = [memprobe.Sent(f"{route}-{i}", 200) for i in range(1 + len(rest))]
    samples = {s.req: memprobe.Sample(s.req, 200, 5, 100, 200, d, d) for s, d in zip(sent, (first,) + rest)}
    return mr.RouteResult(route, memprobe.aggregate(sent, samples), expect, "measured")


def test_rank_orders_by_rest_sum_then_max_and_tolerates_none():
    rows = mr.rank([_result("GET /a", rest=(1, 1)), _result("GET /b", rest=(2, 0)), _result("GET /c", rest=()),
                    _result("GET /d", rest=(0, 2))])
    assert [r.path for r in rows] == ["/b", "/d", "/a", "/c"]   # sum 2,2,2,0; max 2,2,1; then path
    assert rows[-1].rest_mean_cg is None


def test_rank_marks_unexpected_status_failed_and_expected_ok():
    ok = mr.RouteResult("GET /x", memprobe.aggregate([memprobe.Sent("1", 404)], {"1": memprobe.Sample("1", 404, 1, 1, 1, 0, 0)}), 404, "measured")
    bad = mr.RouteResult("GET /y", memprobe.aggregate([memprobe.Sent("2", 422)], {"2": memprobe.Sample("2", 422, 1, 1, 1, 0, 0)}), None, "measured")
    rows = mr.rank([ok, bad])
    assert {r.path: r.state for r in rows} == {"/x": "measured", "/y": "failed"}


def test_to_csv_writes_one_row_per_route(tmp_path):
    rows = mr.rank([_result("GET /a", rest=(1,))])
    out = tmp_path / "s.csv"
    mr.to_csv(rows, [("POST", "/new")], [("WS", "/ws")], str(out))
    lines = out.read_text().splitlines()
    assert lines[0].startswith("method,path,n,first_cg,rest_sum_cg")
    assert len(lines) == 4 and lines[2].startswith("POST,/new") and lines[3].endswith("excluded")


def test_multipart_body_carries_filename_and_boundary():
    body, ctype = memprobe.multipart("a.csv", b"WORK ORDER\r\n1\r\n")
    boundary = ctype.split("boundary=")[1]
    assert boundary.encode() in body and b'filename="a.csv"' in body and body.endswith(b"--\r\n")


class _FakeOpener:
    def __init__(self, responses): self.calls, self.responses = [], list(responses)
    def open(self, req, timeout=0):
        self.calls.append((req.get_method(), req.full_url, req.data))
        status, body = self.responses.pop(0)
        return _FakeResp(status, body)


class _FakeResp:
    def __init__(self, status, body): self.status, self._b = status, body; self.headers = {"X-Request-ID": f"r{status}{len(body)}"}
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def read(self): return self._b


def test_run_group_fills_id_from_the_create_response():
    group = [mr.Step("POST /items/", "POST", "/items/", '{"b":"{prefix}-{seq}"}', None, None, "owner"),
             mr.Step("DELETE /items/{item_id}", "DELETE", "/items/{id}", None, None, None, "owner")]
    op = _FakeOpener([(200, b'{"id":"X1"}'), (204, b""), (200, b'{"id":"X2"}'), (204, b"")])
    out = memprobe.run_group({"owner": op}, "http://h", group, {"prefix": "p"}, 2, 0, NOW)
    assert [c[1] for c in op.calls] == ["http://h/items/", "http://h/items/X1", "http://h/items/", "http://h/items/X2"]
    assert len(out["POST /items/"]) == 2 and len(out["DELETE /items/{item_id}"]) == 2


def test_sweep_group_records_missing_id_as_failed():
    group = [mr.Step("POST /items/", "POST", "/items/", "{}", None, None, "owner"),
             mr.Step("DELETE /items/{item_id}", "DELETE", "/items/{id}", None, None, None, "owner")]
    op = _FakeOpener([(422, b'{"detail":"no"}')])
    out = memprobe.run_group({"owner": op}, "http://h", group, {}, 1, 0, NOW)
    assert out["DELETE /items/{item_id}"] == [memprobe.Sent(None, 0, None)]
    assert len(op.calls) == 1


def test_plan_marks_technician_groups():
    cat = {"POST /a": mr.Entry(as_user="technician")}
    p = mr.plan([("POST", "/a")], cat, {}, None)
    assert p.groups[0][0].as_user == "technician"
