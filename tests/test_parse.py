from conftest import fixture_html

from local_branch_overview.scraper.parse import (
    parse_branch_page,
    parse_branches,
    parse_districts,
)


def test_parse_districts(main_html: str) -> None:
    districts = parse_districts(main_html)

    assert len(districts) == 17
    assert districts[0].name == "Agder Røde Kors"
    assert districts[0].slug == "agder"
    assert districts[0].url == "https://www.rodekors.no/lokalforeninger/agder/"
    assert {d.slug for d in districts} >= {"more-og-romsdal", "trondelag", "ostfold"}


def test_parse_branches(agder_html: str) -> None:
    branches = parse_branches(agder_html)

    assert len(branches) == 17
    assert branches[0].name == "Arendal Røde Kors"
    assert branches[0].slug == "arendal"
    assert branches[0].url == "https://www.rodekors.no/lokalforeninger/agder/arendal/"
    assert (
        len({b.slug for b in branches}) == 17
    )  # "Les mer" links are not counted twice


def test_parse_branch_page(arendal_html: str) -> None:
    details = parse_branch_page(arendal_html)

    assert details.address == "Hans Thornes vei 26, 4846 ARENDAL"
    assert (details.latitude, details.longitude) == (58.4887604, 8.7585903)

    names = [a.name for a in details.activities]
    assert len(names) == 16
    assert names[0] == "Barnas Røde Kors"
    assert names[-1] == "Åpen møteplass/språkkafè"

    bark = details.activities[0].description
    assert bark.startswith("BARK er barnas aktivitetsklubb")
    assert "Barna lærer førstehjelp" not in bark  # figcaption dropped
    assert "  " not in bark and "\n" not in bark


def test_parse_branch_page_with_other_activities_heading() -> None:
    # Grimstad titles the section "Aktiviteter" instead of "Tilbud og aktiviteter".
    details = parse_branch_page(fixture_html("grimstad"))

    assert details.address == "Frivoldveien 11, 4877 GRIMSTAD"
    assert [a.name for a in details.activities] == [
        "Hjelpekorps",
        "Besøkstjenesten",
        "Norsktrening",
        "Barnas Røde Kors",
    ]


def test_parse_branch_page_without_activities_or_address() -> None:
    html = "<html><body><dl><dt>Adresse</dt><dd>-</dd></dl></body></html>"

    details = parse_branch_page(html)

    assert details.address == ""
    assert details.latitude is None and details.longitude is None
    assert details.activities == []
