"""The office-PC sort script: extracts beside itself, copies new files, skips
existing ones, never overwrites."""

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


def _folders(tmp_path):
    here, drive = tmp_path / "Photo_Export", tmp_path / "drive"
    here.mkdir()
    drive.mkdir()
    return here, drive


def test_extract_here_then_copy_then_skip(tmp_path):
    here, drive = _folders(tmp_path)
    photo_sort.extract(_zip(here / "export_2026-11-24_0900.zip", FILES), here)
    assert (here / "WMR27/Commons/13/1_2026-11-20_Commons_13_13G.jpg").exists()
    assert photo_sort.copy_photos(here, drive) == (2, 0, 1)
    assert (drive / "WMR27/Commons/13/1_2026-11-20_Commons_13_13G.jpg").read_bytes() == b"one"
    assert not (drive / "manifest.csv").exists()
    assert photo_sort.copy_photos(here, drive) == (0, 2, 0)


def test_existing_file_left_untouched(tmp_path):
    here, drive = _folders(tmp_path)
    target = drive / "WMR27/Commons/13/1_2026-11-20_Commons_13_13G.jpg"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"already in drive")
    photo_sort.extract(_zip(here / "export_x.zip", FILES), here)
    photo_sort.copy_photos(here, drive)
    assert target.read_bytes() == b"already in drive"


def test_newest_zip_across_folders_or_none(tmp_path):
    here, downloads = tmp_path / "here", tmp_path / "dl"
    here.mkdir()
    downloads.mkdir()
    assert photo_sort.find_zip(["script"], [here, downloads]) is None
    old = _zip(here / "export_a.zip", {})
    new = _zip(downloads / "export_b.zip", {})
    os.utime(old, (1, 1))
    assert photo_sort.find_zip(["script"], [here, downloads]) == new
    assert photo_sort.find_zip(["script", str(old)], [here]) == old


def test_remembered_path(tmp_path, monkeypatch):
    remember = tmp_path / "last.txt"
    monkeypatch.setattr("builtins.input", lambda _: str(tmp_path))
    assert photo_sort.ask_drive(remember) == tmp_path
    monkeypatch.setattr("builtins.input", lambda _: "")
    assert photo_sort.ask_drive(remember) == tmp_path
