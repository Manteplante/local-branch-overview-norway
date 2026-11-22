from pathlib import Path

from conftest import fixture_html

from local_branch_overview.scraper.parse import (
    find_activities_link,
    parse_activity_cards,
    parse_activity_categories,
    parse_activity_list,
    parse_branch_page,
    parse_branches,
    parse_contact_page,
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
    assert {a.section for a in details.activities} == {"Tilbud og aktiviteter"}
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


def test_oslo_contact_and_categories() -> None:
    oslo = Path(__file__).parent / "fixtures/oslo"
    contact = parse_contact_page((oslo / "kontakt.html").read_text(encoding="utf-8"))
    assert contact.address == "Hausmanns gate 23, 0182 Oslo"
    assert (contact.latitude, contact.longitude) == (59.9171449, 10.7548383)

    index = "https://www.rodekors.no/lokalforeninger/oslo/aktiviteter/"
    categories = parse_activity_categories(
        (oslo / "aktiviteter.html").read_text(encoding="utf-8"), index
    )
    assert len(categories) == 7
    assert categories[0].url == f"{index}barn-og-unge/"


NESTED = Path(__file__).parent / "fixtures/nested"
BRANCHES = "https://www.rodekors.no/lokalforeninger/"


def _nested(name: str) -> str:
    return (NESTED / f"{name}.html").read_text(encoding="utf-8")


def test_find_activities_link() -> None:
    bodo = f"{BRANCHES}nordland/bodo/"
    assert (
        find_activities_link(_nested("bodo"), bodo) == f"{bodo}om-oss/vare-aktiviteter/"
    )
    kristiansand = f"{BRANCHES}agder/kristiansand/"
    assert (
        find_activities_link(_nested("kristiansand"), kristiansand)
        == f"{kristiansand}aktiviteter/"
    )
    # Cards under another branch do not count.
    assert (
        find_activities_link(_nested("bodo"), f"{BRANCHES}agder/kristiansand/") is None
    )


def test_bodo_activities_subpage_has_expanders() -> None:
    assert parse_branch_page(_nested("bodo")).activities == []
    activities = parse_branch_page(_nested("bodo_aktiviteter")).activities
    assert len(activities) == 16
    assert activities[0].name == "Barnas Røde Kors - BARK"


def test_kristiansand_activity_cards_and_list() -> None:
    hub = f"{BRANCHES}agder/kristiansand/aktiviteter/"
    cards = parse_activity_cards(_nested("kristiansand_aktiviteter"), hub)
    assert [c.name for c in cards] == [
        "Barn og Ungdom",
        "Fellesskap og inkludering",
        "Beredskap",
        "Migrasjon",
    ]
    assert cards[0].url == f"{hub}barn-og-unge/"

    activities = parse_activity_list(_nested("kristiansand_barn-og-unge"))
    assert len(activities) == 7
    assert activities[0].name == "Barnas Røde Kors i Kristiansand"
    assert activities[0].description.startswith("Barnas Røde Kors (BARK) er")


def test_trondheim_activity_teasers() -> None:
    activities = parse_activity_list(_nested("trondheim_barn-og-unge"))
    assert len(activities) == 5
    assert activities[0].name == "Aktiviteter for barn på krisesenter"
    assert activities[0].description.startswith("Aktiviteter på krisesenter er")
