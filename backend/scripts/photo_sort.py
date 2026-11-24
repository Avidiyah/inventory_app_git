"""Copy a TechFM photo export into the Google Drive folder (spec 2026-11-24).

Keep this script in the photo-export folder on the office PC (e.g.
Desktop\\Photo_Export) and double-click it, or drag a zip onto it. Stdlib
only, so the PC needs nothing installed beyond Python.

1. Takes the dragged zip, or the newest ``export_*.zip`` in this folder or in
   Downloads, and extracts it here (no zip is fine: whatever is already
   extracted here is used).
2. Asks for the Drive folder (remembered next to this script; Enter reuses it).
3. Copies every photo here into ``<drive>/<Service-Type>/...``, creating
   folders as needed. It never overwrites or deletes anything in Drive.
"""

import shutil
import sys
import zipfile
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent
REMEMBER = HERE / "photo_sort_last_path.txt"


def find_zip(argv: list, folders: list) -> Optional[Path]:
    if len(argv) > 1:
        return Path(argv[1])
    zips = [z for folder in folders if folder.is_dir() for z in folder.glob("export_*.zip")]
    return max(zips, key=lambda p: p.stat().st_mtime) if zips else None


def ask_drive(remember: Path = REMEMBER) -> Path:
    last = remember.read_text(encoding="utf-8").strip() if remember.exists() else ""
    print()
    if last:
        print(f"Last time the photos went to: {last}")
        prompt = "Press Enter to use it again, or paste a different Google Drive folder: "
    else:
        prompt = "Paste the Google Drive folder the photos should go to: "
    answer = input(prompt).strip().strip('"')
    drive = Path(answer or last)
    if not (answer or last) or not drive.is_dir():
        raise SystemExit(f"That folder does not exist: {drive}")
    remember.write_text(str(drive), encoding="utf-8")
    return drive


def extract(zip_path: Path, dest: Path) -> None:
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest)


def copy_photos(src: Path, drive: Path) -> tuple:
    """Copy every .jpg under `src` to the same relative path under `drive`.
    Return (copied, skipped, unsorted)."""
    copied = skipped = unsorted = 0
    for photo in sorted(src.rglob("*.jpg")):
        rel = photo.relative_to(src)
        target = drive / rel
        if target.exists():
            skipped += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(photo, target)
        copied += 1
        if "_Unsorted" in rel.parts:
            unsorted += 1
    return copied, skipped, unsorted


def main() -> None:
    try:
        zip_path = find_zip(sys.argv, [HERE, Path.home() / "Downloads"])
        if zip_path:
            print(f"Unzipping {zip_path.name}")
            extract(zip_path, HERE)
        else:
            print("No export zip found; using the photos already in this folder.")
        drive = ask_drive()
        copied, skipped, unsorted = copy_photos(HERE, drive)
        print()
        print(f"Done. {copied} new photo(s) copied, {skipped} were already in Drive.")
        if unsorted:
            print(f"{unsorted} had no location and went to the _Unsorted folder.")
    except BaseException as exc:  # the window must not vanish on any error
        print(f"Stopped: {exc}")
    input("\nPress Enter to close")


if __name__ == "__main__":
    main()
