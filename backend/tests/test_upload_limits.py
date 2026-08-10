"""Tests for the upload size caps (`app/routers/_uploads.py`) and their
two call sites.

Layer: unit (no DB, no HTTP client). Matches the "call the handler
directly, monkeypatch anything that would touch Postgres" style of
`test_logging.py` and `test_health_check.py`.

The two that carry the item are `test_the_read_never_pulls_more_than_the
_cap_plus_one_byte` and `test_an_upload_with_no_declared_size_is_still
_capped`. Everything else would still pass if `read_capped` simply
checked `file.size` and then called `file.file.read()` with no argument
-- which would leave the unbounded read B1 exists to close exactly where
it was, just behind a check that a caller can defeat by not declaring a
size.
"""

import io
import logging
import os
import sys
from tempfile import SpooledTemporaryFile
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi import HTTPException, UploadFile

from app.domain import roles
from app.routers import barcodes as barcodes_router
from app.routers import work_orders as work_orders_router
from app.routers._uploads import (
    MAX_CSV_UPLOAD_BYTES,
    MAX_IMAGE_UPLOAD_BYTES,
    read_capped,
)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _upload(data: bytes, *, declare_size: bool = True) -> UploadFile:
    """An `UploadFile` over real bytes.

    `declare_size=False` reproduces the case Starlette's parser never
    produces but every direct construction does: `size` is `None`, so
    only the bounded read stands between the caller and an unbounded
    `.read()`.
    """
    spooled = SpooledTemporaryFile(max_size=1024 * 1024)
    spooled.write(data)
    spooled.seek(0)
    return UploadFile(
        file=spooled,
        size=len(data) if declare_size else None,
        filename="upload.bin",
    )


class _RecordingFile(io.BytesIO):
    """A file object that remembers the sizes it was asked to read, so a
    test can assert the cap bounds the read itself rather than being
    checked after the fact."""

    def __init__(self, data: bytes):
        super().__init__(data)
        self.read_sizes: list = []

    def read(self, size=-1):
        self.read_sizes.append(size)
        return super().read(size)


def _declared_oversize(limit: int) -> UploadFile:
    """An upload that *claims* to be one byte over `limit` without
    allocating it.

    The declared-size check refuses before reading, so the bytes are
    never needed -- and materialising 25 MB in a unit test to prove the
    cap is 25 MB is the exact waste the cap exists to prevent. The
    bounded-read path is covered separately, on small payloads, above.
    """
    return UploadFile(file=_RecordingFile(b""), size=limit + 1, filename="upload.bin")


def _admin():
    return SimpleNamespace(id=1, role=roles.ROLE_ADMIN, username="adm")


def _technician():
    return SimpleNamespace(id=2, role=roles.ROLE_TECHNICIAN, username="tech")


# --------------------------------------------------------------------------
# read_capped
# --------------------------------------------------------------------------

def test_a_file_under_the_cap_reads_through_byte_identically():
    payload = b"\x89PNG\r\n\x1a\n" + b"x" * 4096

    data = read_capped(_upload(payload), limit=MAX_IMAGE_UPLOAD_BYTES, what="Image")

    assert data == payload


def test_a_file_exactly_at_the_cap_is_allowed():
    # The boundary is inclusive: `limit` bytes is within the limit. An
    # off-by-one here rejects a file the message says is acceptable.
    payload = b"z" * 64

    data = read_capped(_upload(payload), limit=64, what="Image")

    assert data == payload


def test_one_byte_over_the_cap_is_refused():
    with pytest.raises(HTTPException) as exc:
        read_capped(_upload(b"z" * 65), limit=64, what="Image")

    assert exc.value.status_code == 413


def test_an_upload_with_no_declared_size_is_still_capped():
    # `UploadFile.size` is None whenever the object was not built by the
    # multipart parser. If the declared-size check were the only guard,
    # this is the request that walks straight past it.
    oversized = _upload(b"z" * 65, declare_size=False)

    with pytest.raises(HTTPException) as exc:
        read_capped(oversized, limit=64, what="Image")

    assert exc.value.status_code == 413


def test_the_read_never_pulls_more_than_the_cap_plus_one_byte():
    # The actual property B1 buys. A 50 MB upload must not become a
    # 50 MB bytes object on the way to being rejected.
    recording = _RecordingFile(b"z" * 5000)
    upload = UploadFile(file=recording, size=None, filename="upload.bin")

    with pytest.raises(HTTPException):
        read_capped(upload, limit=64, what="Image")

    assert recording.read_sizes == [65]


def test_a_declared_oversize_is_refused_without_reading_at_all():
    recording = _RecordingFile(b"z" * 5000)
    upload = UploadFile(file=recording, size=5000, filename="upload.bin")

    with pytest.raises(HTTPException):
        read_capped(upload, limit=64, what="Image")

    assert recording.read_sizes == []


def test_the_message_names_the_thing_and_states_the_cap_in_mb():
    two_mb = 2 * 1024 * 1024

    with pytest.raises(HTTPException) as exc:
        read_capped(_declared_oversize(two_mb), limit=two_mb, what="CSV file")

    assert exc.value.detail == "CSV file is too large. The maximum upload size is 2 MB."


def test_a_rejection_is_logged_with_the_size_and_the_cap(caplog):
    # A 413 with no server-side trace is the gap N1 just closed; a user
    # reporting "the scanner stopped working" needs something behind it.
    caplog.set_level(logging.WARNING)

    with pytest.raises(HTTPException):
        read_capped(_upload(b"z" * 65), limit=64, what="Image")

    record = next(
        r for r in caplog.records if r.getMessage() == "upload.rejected_too_large"
    )
    assert record.fields == {"what": "Image", "size": 65, "limit": 64}


def test_an_accepted_upload_logs_nothing(caplog):
    caplog.set_level(logging.DEBUG)

    read_capped(_upload(b"z" * 64), limit=64, what="Image")

    assert [r for r in caplog.records if r.name == "app.routers._uploads"] == []


# --------------------------------------------------------------------------
# POST /barcodes/decode
# --------------------------------------------------------------------------

def test_decode_passes_a_normal_image_through_to_the_service(monkeypatch):
    payload = b"\x89PNG\r\n\x1a\n" + b"x" * 1024
    seen = {}

    def fake_decode(data):
        seen["data"] = data
        return []

    monkeypatch.setattr(barcodes_router.barcodes_service, "decode_image", fake_decode)

    response = barcodes_router.decode_barcode(_upload(payload))

    assert seen["data"] == payload
    assert response.barcodes == []


def test_decode_refuses_an_image_over_ten_megabytes(monkeypatch):
    def never(data):  # pragma: no cover - the point is that it is not reached
        raise AssertionError("decode_image must not see an oversized upload")

    monkeypatch.setattr(barcodes_router.barcodes_service, "decode_image", never)

    with pytest.raises(HTTPException) as exc:
        barcodes_router.decode_barcode(_declared_oversize(MAX_IMAGE_UPLOAD_BYTES))

    assert exc.value.status_code == 413
    assert exc.value.detail == "Image is too large. The maximum upload size is 10 MB."


# --------------------------------------------------------------------------
# POST /work-orders/import
# --------------------------------------------------------------------------

_EMPTY_SUMMARY = {
    "total": 0, "created": 0, "opened": 0, "closed": 0,
    "supervisors_matched": 0, "supervisors_unmatched": 0, "skipped": 0,
}


def test_import_passes_a_normal_csv_through_to_the_service(monkeypatch):
    payload = b"WORK ORDER,LOCATION\r\n12345,Scholars 4\r\n"
    seen = {}

    def fake_import(db, *, csv_bytes, user):
        seen["csv_bytes"] = csv_bytes
        return dict(_EMPTY_SUMMARY, total=1, created=1)

    monkeypatch.setattr(work_orders_router.wo_service, "import_work_orders", fake_import)

    result = work_orders_router.import_work_orders(
        file=_upload(payload), user=_admin(), db=None
    )

    assert seen["csv_bytes"] == payload
    assert result.created == 1


def test_import_refuses_a_csv_over_twenty_five_megabytes(monkeypatch):
    def never(db, *, csv_bytes, user):  # pragma: no cover - must not be reached
        raise AssertionError("import_work_orders must not see an oversized upload")

    monkeypatch.setattr(work_orders_router.wo_service, "import_work_orders", never)

    with pytest.raises(HTTPException) as exc:
        work_orders_router.import_work_orders(
            file=_declared_oversize(MAX_CSV_UPLOAD_BYTES), user=_admin(), db=None
        )

    assert exc.value.status_code == 413
    assert exc.value.detail == "CSV file is too large. The maximum upload size is 25 MB."


def test_the_role_gate_still_runs_before_the_size_check():
    # Order matters: an unauthorised caller should learn that they are
    # unauthorised, not what the upload cap is. This is the one place the
    # two guards could have been transposed by accident.
    with pytest.raises(HTTPException) as exc:
        work_orders_router.import_work_orders(
            file=_declared_oversize(MAX_CSV_UPLOAD_BYTES), user=_technician(), db=None
        )

    assert exc.value.status_code == 403
