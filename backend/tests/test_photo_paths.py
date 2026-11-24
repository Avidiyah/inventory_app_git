"""Pure tests for the photo export folder/filename rules (no DB)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date

import pytest

from app.domain.photo_paths import photo_path, safe_name

DAY = date(2026, 11, 24)


@pytest.mark.parametrize(
    "location, folder, filename",
    [
        ("Scholars Inn Apartments: 1633", "Scholars/16", "1_2026-11-24_Scholars_16_1633.jpg"),
        ("Scholars Inn Apartments, 1333D", "Scholars/13", "1_2026-11-24_Scholars_13_1333D.jpg"),
        ("Scholars Inn Apartments: 1632-1", "Scholars/16", "1_2026-11-24_Scholars_16_1632.jpg"),
        ("Scholars Inn Apartments: Buildings 3,9", "Scholars/Exterior", "1_2026-11-24_Scholars_Exterior_NA.jpg"),
        ("Centennial Courts Apartments: 614", "Centennial/6", "1_2026-11-24_Centennial_6_614.jpg"),
        ("Centennial Courts Apartments: 1133", "Centennial/11", "1_2026-11-24_Centennial_11_1133.jpg"),
        ("Centennial Courts Apartments: Clubhouse kitchen", "Centennial/Clubhouse", "1_2026-11-24_Centennial_Clubhouse_NA.jpg"),
        ("Commons Apartments: 13G", "Commons/13", "1_2026-11-24_Commons_13_13G.jpg"),
        ("Cimarron Gardens Apartments: J12", "Cimarron/12", "1_2026-11-24_Cimarron_12_J12.jpg"),
        ("Cimarron Gardens Apartments: Cimarron 12J", "Cimarron/12", "1_2026-11-24_Cimarron_12_12J.jpg"),
        ("Young Hall: 208A-A", "Young-Hall/Floor-2-Mens", "1_2026-11-24_Young-Hall_Floor-2-Mens_208A.jpg"),
        ("Young Hall: 315C- A", "Young-Hall/Floor-3-Womens", "1_2026-11-24_Young-Hall_Floor-3-Womens_315C.jpg"),
        ("Young Hall: 326 - Entire Area", "Young-Hall/Misc", "1_2026-11-24_Young-Hall_Misc_326.jpg"),
        ("Young Hall: Lobby", "Young-Hall/Misc", "1_2026-11-24_Young-Hall_Misc_NA.jpg"),
        ("University Women/Health Clinic: Room 4", "Academics/University-Women-Health-Clinic",
         "1_2026-11-24_Academics_University-Women-Health-Clinic_NA.jpg"),
        ("Science Hall, 2nd floor", "Academics/Science-Hall", "1_2026-11-24_Academics_Science-Hall_NA.jpg"),
        ("", "_Unsorted", "1_2026-11-24_Unsorted_NA_NA.jpg"),
        (None, "_Unsorted", "1_2026-11-24_Unsorted_NA_NA.jpg"),
    ],
)
def test_community_tree(location, folder, filename):
    got_folder, got_name = photo_path("WMR27", "1", location, DAY, 0)
    assert got_folder == f"WMR27/{folder}"
    assert got_name == filename


@pytest.mark.parametrize(
    "service_type, top",
    [
        ("WMR27", "WMR27"),
        ("SMR27 - Belfor", "SMR27-Belfor"),
        ("  New Type?  ", "New-Type"),
        ("", "Unspecified"),
        (None, "Unspecified"),
    ],
)
def test_service_type_folder(service_type, top):
    folder, _ = photo_path(service_type, "1", "Commons Apartments: 13G", DAY, 0)
    assert folder == f"{top}/Commons/13"


def test_seq_suffix():
    assert photo_path("WMR27", "12345", "Commons Apartments: 13G", DAY, 2)[1] == (
        "12345_2026-11-24_Commons_13_13G_2.jpg"
    )


def test_safe_name():
    assert safe_name(' a  b/c:d*?"<>| . ') == "a-b-c-d"
