"""Work-order photo routes (spec 2026-11-24) through a real TestClient."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import io
import uuid
import zipfile

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.database import get_db
from app.domain import roles
from app.main import app
from app.models import User, WorkOrderPhoto
from app.services import auth as auth_service
from app.services import work_order_photos as photo_service
from app.services import work_orders as wos


def _jpeg(taken="2026:11:20 09:00:00") -> bytes:
    exif = Image.Exif()
    exif.get_ifd(0x8769)[36867] = taken
    buf = io.BytesIO()
    Image.new("RGB", (1200, 900), (10, 120, 200)).save(buf, "JPEG", exif=exif.tobytes())
    return buf.getvalue()


def _user(db, role):
    user = User(
        username=f"u-{uuid.uuid4().hex[:10]}",
        password_hash=auth_service.hash_password("hunter2"),
        role=role, first_name="Pho", last_name="Tographer",
    )
    db.add(user)
    db.flush()
    return user


def _work_order(db, admin, tech, location="Commons Apartments: 13G", service="WMR27"):
    wo = wos.get_or_create_work_order(
        db, number=f"PH{uuid.uuid4().hex[:6]}", created_by_id=admin.id, assigned_to_id=tech.id
    )
    wo.location, wo.service_type = location, service
    db.flush()
    return wo


class _Client:
    def __init__(self, db, user):
        self.db, self.token = db, auth_service.create_session(db, user)

    def __enter__(self):
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app).__enter__()
        self.client.cookies.set("session", self.token)
        return self.client

    def __exit__(self, *exc):
        self.client.__exit__(*exc)
        del app.dependency_overrides[get_db]


@pytest.fixture(autouse=True)
def _roomy_disk(monkeypatch):
    monkeypatch.setattr(photo_service, "database_size", lambda db: 0)
    monkeypatch.setattr(photo_service, "vacuum_photos", lambda: None)


def _upload(client, wo_id, data=None, name="a.jpg"):
    return client.post(
        f"/work-orders/{wo_id}/photos", files=[("files", (name, data or _jpeg(), "image/jpeg"))]
    )


@pytest.fixture
def people(db):
    # Existing dev-DB photos would leak into export/clear counts; this test's
    # transaction rolls back, so clearing them here is invisible outside it.
    db.query(WorkOrderPhoto).delete()
    return _user(db, roles.ROLE_ADMIN), _user(db, roles.ROLE_TECHNICIAN)


def test_same_day_uploads_get_seq_and_list(db, people):
    admin, tech = people
    wo = _work_order(db, admin, tech)
    with _Client(db, tech) as c:
        assert _upload(c, wo.id).status_code == 201
        r = _upload(c, wo.id)
        assert r.json()[0]["seq"] == 1
        listed = c.get(f"/work-orders/{wo.id}/photos").json()
        assert [p["filename"] for p in listed] == [
            f"{wo.number}_2026-11-20_Commons_13_13G.jpg",
            f"{wo.number}_2026-11-20_Commons_13_13G_1.jpg",
        ]
        preview = c.get(f"/work-order-photos/{listed[0]['id']}/preview")
        assert preview.status_code == 200
        assert preview.headers["cache-control"] == "no-store"
        assert max(Image.open(io.BytesIO(preview.content)).size) <= 800


def test_non_image_400(db, people):
    admin, tech = people
    wo = _work_order(db, admin, tech)
    with _Client(db, tech) as c:
        assert _upload(c, wo.id, data=b"plain text", name="x.txt").status_code == 400


def test_technician_off_crew_403(db, people):
    admin, tech = people
    stranger = _user(db, roles.ROLE_TECHNICIAN)
    wo = _work_order(db, admin, tech)
    with _Client(db, stranger) as c:
        assert _upload(c, wo.id).status_code == 403


def test_full_disk_507(db, people, monkeypatch):
    admin, tech = people
    wo = _work_order(db, admin, tech)
    monkeypatch.setattr(photo_service, "database_size", lambda db: 10**12)
    with _Client(db, tech) as c:
        r = _upload(c, wo.id)
    assert r.status_code == 507
    assert "full" in r.json()["detail"]


def test_export_zip_then_reexport_then_clear(db, people):
    admin, tech = people
    wo = _work_order(db, admin, tech)
    other = _work_order(db, admin, tech, location="", service="SMR27 - Belfor")
    with _Client(db, tech) as c:
        _upload(c, wo.id)
        _upload(c, other.id)
    with _Client(db, admin) as c:
        r = c.get("/work-order-photos/export.zip")
        assert r.status_code == 200
        assert r.headers["content-disposition"].startswith('attachment; filename="export_')
        names = set(zipfile.ZipFile(io.BytesIO(r.content)).namelist())
        assert names == {
            f"WMR27/Commons/13/{wo.number}_2026-11-20_Commons_13_13G.jpg",
            f"SMR27-Belfor/_Unsorted/{other.number}_2026-11-20_Unsorted_NA_NA.jpg",
            "manifest.csv",
        }
        assert db.query(WorkOrderPhoto).filter(WorkOrderPhoto.exported_at.is_(None)).count() == 0
        again = zipfile.ZipFile(io.BytesIO(c.get("/work-order-photos/export.zip").content))
        assert set(again.namelist()) == names

    with _Client(db, tech) as c:
        _upload(c, wo.id)  # new, not exported -> must survive the clear
    with _Client(db, admin) as c:
        cleared = c.post("/work-order-photos/clear-exported").json()
        assert cleared["deleted"] == 2
        assert cleared["storage"]["waiting_photos"] == 1
    assert db.query(WorkOrderPhoto).count() == 1


def test_original_is_byte_identical_in_zip(db, people):
    admin, tech = people
    wo = _work_order(db, admin, tech)
    raw = _jpeg()
    with _Client(db, tech) as c:
        _upload(c, wo.id, data=raw)
    with _Client(db, admin) as c:
        zf = zipfile.ZipFile(io.BytesIO(c.get("/work-order-photos/export.zip").content))
    jpg = next(n for n in zf.namelist() if n.endswith(".jpg"))
    assert zf.read(jpg) == raw


@pytest.mark.parametrize(
    "method, path",
    [("get", "/work-order-photos/storage"), ("get", "/work-order-photos/export.zip"),
     ("post", "/work-order-photos/clear-exported")],
)
def test_admin_routes_403_for_technician(db, people, method, path):
    _, tech = people
    with _Client(db, tech) as c:
        assert getattr(c, method)(path).status_code == 403
