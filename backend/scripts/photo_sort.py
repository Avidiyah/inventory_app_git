"""Copy a TechFM photo export into the Google Drive folder (spec 2026-11-24).

Double-click on the office PC (or drag a zip onto it). Stdlib only, so the PC
needs nothing installed beyond Python. It takes the dragged zip or the newest
``export_*.zip`` in Downloads, asks for the Drive folder (remembered next to
this script), and copies each photo into ``<drive>/<Service-Type>/...``,
creating folders as needed. It never overwrites or deletes anything.
"""

import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

REMEMBER = Path(__file__).with_name("photo_sort_last_path.txt")


def find_zip(argv: list, downloads: Path) -> Path:
    if len(argv) > 1:
        return Path(argv[1])
    zips = sorted(downloads.glob("export_*.zip"), key=lambda p: p.stat().st_mtime)
    if not zips:
        raise SystemExit(f"No export_*.zip found in {downloads}. Download one from TechFM first.")
    return zips[-1]


def ask_drive(remember: Path = REMEMBER) -> Path:
    last = remember.read_text(encoding="utf-8").strip() if remember.exists() else ""
    hint = f" [Enter = {last}]" if last else ""
    answer = input(f"Paste the Google Drive folder path (e.g. G:\\My Drive){hint}: ").strip().strip('"')
    drive = Path(answer or last)
    if not str(drive) or not drive.is_dir():
        raise SystemExit(f"That folder does not exist: {drive}")
    remember.write_text(str(drive), encoding="utf-8")
    return drive


def sort_zip(zip_path: Path, drive: Path) -> tuple:
    """Return (copied, skipped, unsorted)."""
    copied = skipped = unsorted = 0
    tmp = Path(tempfile.mkdtemp(prefix="photo_sort_"))
    try:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp)
        for src in sorted(tmp.rglob("*.jpg")):
            rel = src.relative_to(tmp)
            target = drive / rel
            if target.exists():
                skipped += 1
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
            copied += 1
            if "_Unsorted" in rel.parts:
                unsorted += 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return copied, skipped, unsorted


def main() -> None:
    try:
        zip_path = find_zip(sys.argv, Path.home() / "Downloads")
        print(f"Zip: {zip_path}")
        drive = ask_drive()
        copied, skipped, unsorted = sort_zip(zip_path, drive)
        print(f"Copied {copied}, skipped {skipped} (already there), unsorted {unsorted}")
    except BaseException as exc:  # the window must not vanish on any error
        print(f"Stopped: {exc}")
    input("Press Enter to close")


if __name__ == "__main__":
    main()
