"""Export folder + filename rules for work-order photos (pure, no DB).

Zip layout: ``export_<date>/<Service-Type>/<community tree>/<filename>``. The
service-type folder comes straight from the work order's free-text
``service_type``, so a new service type gets its own folder with no code change.
The export root is added by the zip builder; this module returns the rest.
"""

import re
from datetime import date
from typing import Optional

from .work_orders import normalize_service_type

_FORBIDDEN = re.compile(r'[\\/:*?"<>|\s-]+')
_SEPARATOR = re.compile(r"[:,]")

# Digit units: 3-4 digits, optional room letter. Building = all but the last two digits.
_DIGIT_UNIT = re.compile(r"(?<![A-Za-z\d])(\d{3,4})([A-Za-z]?)(?![A-Za-z\d])")
# Letter units: 13G or J12. Building = the number.
_LETTER_UNIT = re.compile(
    r"(?<![A-Za-z\d])(?:(\d{1,2})[A-Za-z]|[A-Za-z](\d{1,2}))(?![A-Za-z\d])"
)
_YOUNG_ROOM = re.compile(r"(?<![A-Za-z\d])([1-9]\d{2})([AC]?)(?![A-Za-z\d])", re.I)

# (location prefix, folder name, unit rule)
_COMMUNITIES = (
    ("scholars inn apartments", "Scholars", "digits"),
    ("centennial courts apartments", "Centennial", "digits"),
    ("commons apartments", "Commons", "letter"),
    ("cimarron gardens apartments", "Cimarron", "letter"),
    ("young hall", "Young-Hall", "young"),
)


def safe_name(text: str) -> str:
    """Windows-safe path part: spaces/forbidden chars -> single '-', trim dots/dashes."""
    return _FORBIDDEN.sub("-", text or "").strip("-. ")


def _community_parts(location: str) -> tuple[str, str, Optional[str]]:
    """Return (community, building, unit-or-None) for a location string."""
    text = (location or "").strip()
    lowered = text.casefold()
    for prefix, community, rule in _COMMUNITIES:
        if not lowered.startswith(prefix):
            continue
        rest = text[len(prefix):]
        if rule == "young":
            room = _YOUNG_ROOM.search(rest)
            side = room.group(2).upper() if room else ""
            if side:
                gender = "Mens" if side == "A" else "Womens"
                return community, f"Floor-{room.group(1)[0]}-{gender}", room.group(0).upper()
            return community, "Misc", room.group(1) if room else None
        match = (_DIGIT_UNIT if rule == "digits" else _LETTER_UNIT).search(rest)
        if match:
            if rule == "digits":
                building = str(int(match.group(1)[:-2]))
            else:
                building = str(int(match.group(1) or match.group(2)))
            return community, building, match.group(0).upper()
        return community, ("Clubhouse" if "clubhouse" in lowered else "Exterior"), None
    hall = safe_name(_SEPARATOR.split(text, 1)[0])
    if not hall:
        return "_Unsorted", "", None
    return "Academics", hall, None


def photo_path(
    service_type: Optional[str],
    number: str,
    location: Optional[str],
    taken_on: date,
    seq: int,
) -> tuple[str, str]:
    """Return (folder, filename) below the export root.

    folder   = ``<Service-Type>/<Community>[/<building>]``
    filename = ``<WO>_<date>_<Community>_<building>_<unit|NA>[_<seq>].jpg``
    """
    service = safe_name(normalize_service_type(service_type)[1]) or "Unspecified"
    community, building, unit = _community_parts(location or "")
    folder = "/".join(p for p in (service, community, building) if p)
    stem = "_".join(
        (
            safe_name(number),
            taken_on.isoformat(),
            community.lstrip("_"),
            safe_name(building) or "NA",
            safe_name(unit or "") or "NA",
        )
    )
    if seq:
        stem += f"_{seq}"
    return folder, f"{stem}.jpg"
