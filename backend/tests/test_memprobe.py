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
