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
