"""The office-PC sort script: copies new files, skips existing, never overwrites."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import zipfile

import photo_sort


def _zip(path, files):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return path


FILES = {
    "WMR27/Commons/13/1_2026-11-20_Commons_13_13G.jpg": b"one",
    "SMR27-Belfor/_Unsorted/2_2026-11-20_Unsorted_NA_NA.jpg": b"two",
    "manifest.csv": b"path\n",
}


def test_first_run_copies_second_skips(tmp_path):
    drive = tmp_path / "drive"
    drive.mkdir()
    z = _zip(tmp_path / "export_2026-11-24_0900.zip", FILES)
    assert photo_sort.sort_zip(z, drive) == (2, 0, 1)
    assert (drive / "WMR27/Commons/13/1_2026-11-20_Commons_13_13G.jpg").read_bytes() == b"one"
    assert not (drive / "manifest.csv").exists()
    assert photo_sort.sort_zip(z, drive) == (0, 2, 0)


def test_existing_file_left_untouched(tmp_path):
    drive = tmp_path / "drive"
    target = drive / "WMR27/Commons/13/1_2026-11-20_Commons_13_13G.jpg"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"already in drive")
    photo_sort.sort_zip(_zip(tmp_path / "export_x.zip", FILES), drive)
    assert target.read_bytes() == b"already in drive"


def test_newest_zip_and_remembered_path(tmp_path, monkeypatch):
    old = _zip(tmp_path / "export_a.zip", {})
    new = _zip(tmp_path / "export_b.zip", {})
    os.utime(old, (1, 1))
    assert photo_sort.find_zip(["script"], tmp_path) == new
    remember = tmp_path / "last.txt"
    monkeypatch.setattr("builtins.input", lambda _: str(tmp_path))
    assert photo_sort.ask_drive(remember) == tmp_path
    monkeypatch.setattr("builtins.input", lambda _: "")
    assert photo_sort.ask_drive(remember) == tmp_path
