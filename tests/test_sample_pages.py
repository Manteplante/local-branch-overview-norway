"""The parser against a snapshot of every district and its first two branches.

Refresh the snapshot with `make fixtures` when the site changes.
"""

from pathlib import Path

import pytest
from conftest import FIXTURES, fixture_html

from local_branch_overview.scraper.parse import (
    parse_branch_page,
    parse_branches,
    parse_districts,
    split_by_group,
)

SAMPLE = FIXTURES / "sample"
DISTRICT_PAGES = sorted((SAMPLE / "districts").glob("*.html"))
BRANCH_PAGES = sorted((SAMPLE / "branches").glob("*.html"))

# Roughly mainland Norway plus Svalbard.
LAT, LNG = (57.0, 81.0), (4.0, 32.0)
# Oslo Røde Kors is one organisation with no local branches listed on the site.
WITHOUT_BRANCHES = {"oslo"}
# Branch pages that genuinely list no activities (checked by hand). Any other page without
# activities means the parser missed a layout.
WITHOUT_ACTIVITIES = {
    "nordland__ankenes",  # only an intro text about its hjelpekorps
    "telemark__bo-og-sauherad",  # points to its own website for activities
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_snapshot_covers_every_district() -> None:
    slugs = {d.slug for d in parse_districts(fixture_html("main"))}

    assert {p.stem for p in DISTRICT_PAGES} == slugs
    assert {p.stem.split("__")[0] for p in BRANCH_PAGES} == slugs - WITHOUT_BRANCHES


@pytest.mark.parametrize("page", DISTRICT_PAGES, ids=lambda p: p.stem)
def test_district_lists_its_branches(page: Path) -> None:
    branches = parse_branches(_read(page))

    if page.stem in WITHOUT_BRANCHES:
        assert branches == []
        return
    assert branches, "no branches found"
    assert len({b.slug for b in branches}) == len(branches)
    for branch in branches:
        assert branch.name
        assert branch.url.startswith(
            f"https://www.rodekors.no/lokalforeninger/{page.stem}/"
        )


@pytest.mark.parametrize("page", BRANCH_PAGES, ids=lambda p: p.stem)
def test_branch_has_address_coordinates_and_activities(page: Path) -> None:
    details = parse_branch_page(_read(page))

    assert details.address, "no address"
    # Some branches have an empty map marker; those need geocoding later.
    if details.latitude is not None:
        assert LAT[0] <= details.latitude <= LAT[1]
        assert details.longitude is not None and LNG[0] <= details.longitude <= LNG[1]
    if page.stem in WITHOUT_ACTIVITIES:
        assert details.activities == []
        return
    assert details.activities, "no activities"
    assert all(a.name for a in details.activities)


def test_activities_from_every_section_except_info() -> None:
    # Drammen groups activities under several headings, the first being general info.
    activities = parse_branch_page(
        _read(SAMPLE / "branches" / "buskerud__drammen.html")
    )

    sections = {a.section for a in activities.activities}
    assert "Barn og unge" in sections and "Beredskap og hjelpekorps" in sections
    assert not any("Velkommen" in s for s in sections)
    assert "Barnas Røde Kors (BARK)" in [a.name for a in activities.activities]


def test_info_section_is_skipped() -> None:
    # Asker has "Nyttig informasjon:" (staff, board, renting) before "Våre aktiviteter:".
    details = parse_branch_page(_read(SAMPLE / "branches" / "akershus__asker.html"))

    names = [a.name for a in details.activities]
    assert "Hvem sitter i styret?" not in names
    assert {a.section for a in details.activities} == {"Våre aktiviteter"}


def test_om_oss_section_is_skipped_but_untitled_sections_are_kept() -> None:
    askoy = parse_branch_page(_read(SAMPLE / "branches" / "hordaland__askoy.html"))
    alta = parse_branch_page(_read(SAMPLE / "branches" / "finnmark__alta.html"))

    assert "Styret i Askøy Røde Kors" not in [a.name for a in askoy.activities]
    assert "Hjelpekorps" in [a.name for a in alta.activities if a.section == ""]


def test_trondelag_branches_come_from_its_navigation_menu() -> None:
    branches = parse_branches(_read(SAMPLE / "districts" / "trondelag.html"))

    assert len(branches) == 35
    assert branches[0].slug == "flatanger"
    groups = {g: [b for b in branches if b.group == g] for g in ("Nord", "Sør")}
    assert len(groups["Nord"]) + len(groups["Sør"]) == 35
    assert groups["Nord"][0].slug == "flatanger"
    assert groups["Sør"][0].slug == "gauldal"
    assert "trondheim" in {b.slug for b in groups["Sør"]}


def test_split_by_group_names_the_parts() -> None:
    district = parse_districts(fixture_html("main"))[-3]  # Røde Kors i Trøndelag
    branches = parse_branches(_read(SAMPLE / "districts" / "trondelag.html"))

    parts = split_by_group(district, branches)

    assert [(d.slug, d.name) for d, _ in parts] == [
        ("trondelag-nord", "Røde Kors i Trøndelag – Nord"),
        ("trondelag-sor", "Røde Kors i Trøndelag – Sør"),
    ]


def test_districts_without_groups_are_not_split() -> None:
    district = parse_districts(fixture_html("main"))[0]
    branches = parse_branches(_read(SAMPLE / "districts" / "agder.html"))

    assert split_by_group(district, branches) == [(district, branches)]
