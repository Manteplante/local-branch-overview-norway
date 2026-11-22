from pathlib import Path

import pandas as pd
import pytest

from local_branch_overview.scraper.parse import DISTRICTS_URL, Branch, District
from local_branch_overview.scraper.run import (
    COLUMNS,
    rescrape_empty,
    scrape,
    scrape_district,
)

SAMPLE_TRONDELAG = Path(__file__).parent / "fixtures/sample/districts/trondelag.html"

AGDER = "https://www.rodekors.no/lokalforeninger/agder/"
ARENDAL = "https://www.rodekors.no/lokalforeninger/agder/arendal/"
TRONDELAG_INDEX = "https://www.rodekors.no/lokalforeninger/trondelag/finn-fram/"
NO_ACTIVITIES = "<html><body><dl><dt>Adresse</dt><dd>Storgata 1</dd></dl></body></html>"


class FakeClient:
    """Serves saved pages; any other URL is a branch page without activities."""

    def __init__(
        self, pages: dict[str, str], fail: frozenset[str] = frozenset()
    ) -> None:
        self.pages = pages
        self.fail = fail
        self.urls: list[str] = []

    def get(self, url: str) -> str:
        self.urls.append(url)
        if url in self.fail:
            raise RuntimeError("boom")
        return self.pages.get(url, NO_ACTIVITIES)


@pytest.fixture
def pages(main_html: str, agder_html: str, arendal_html: str) -> dict[str, str]:
    return {
        DISTRICTS_URL: main_html,
        AGDER: agder_html,
        ARENDAL: arendal_html,
        TRONDELAG_INDEX: SAMPLE_TRONDELAG.read_text(encoding="utf-8"),
    }


def test_writes_one_row_per_activity(tmp_path: Path, pages: dict[str, str]) -> None:
    failed = scrape(FakeClient(pages), tmp_path, only={"agder"}, limit_branches=2)

    df = pd.read_csv(tmp_path / "agder.csv", keep_default_na=False)
    assert failed == []
    assert list(df.columns) == COLUMNS
    arendal = df[df.branch_slug == "arendal"]
    assert len(arendal) == 16
    assert set(arendal.address) == {"Hans Thornes vei 26, 4846 ARENDAL"}
    assert arendal.iloc[0].activity == "Barnas Røde Kors"
    assert arendal.iloc[0].section == "Tilbud og aktiviteter"
    # A branch without activities still gets one row.
    grimstad = df[df.branch_slug == "grimstad"]
    assert len(grimstad) == 1
    assert grimstad.iloc[0].activity == ""
    assert list(tmp_path.iterdir()) == [tmp_path / "agder.csv"]  # no temp files left


def test_skips_existing_csv_unless_forced(
    tmp_path: Path, pages: dict[str, str]
) -> None:
    (tmp_path / "agder.csv").write_text("old")

    client = FakeClient(pages)
    scrape(client, tmp_path, only={"agder"}, limit_branches=1)
    assert client.urls == [DISTRICTS_URL, AGDER]  # index only, no branch pages
    assert (tmp_path / "agder.csv").read_text() == "old"

    scrape(FakeClient(pages), tmp_path, only={"agder"}, limit_branches=1, force=True)
    assert (tmp_path / "agder.csv").read_text() != "old"


def test_failed_branch_is_reported_and_others_are_kept(
    tmp_path: Path, pages: dict[str, str]
) -> None:
    client = FakeClient(pages, fail=frozenset({ARENDAL}))

    failed = scrape(client, tmp_path, only={"agder"}, limit_branches=2)

    df = pd.read_csv(tmp_path / "agder.csv")
    assert failed == [ARENDAL]
    assert set(df.branch_slug) == {"grimstad"}


def test_unknown_district_is_rejected(tmp_path: Path, pages: dict[str, str]) -> None:
    with pytest.raises(SystemExit, match="narnia"):
        scrape(FakeClient(pages), tmp_path, only={"narnia"})


def test_trondelag_is_split_into_nord_and_sor(
    tmp_path: Path, pages: dict[str, str]
) -> None:
    scrape(FakeClient(pages), tmp_path, only={"trondelag"}, limit_branches=1)

    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "trondelag-nord.csv",
        "trondelag-sor.csv",
    ]
    nord = pd.read_csv(tmp_path / "trondelag-nord.csv")
    assert set(nord.district) == {"Røde Kors i Trøndelag – Nord"}
    assert set(nord.district_slug) == {"trondelag-nord"}


def test_half_done_split_district_resumes_the_missing_part(
    tmp_path: Path, pages: dict[str, str]
) -> None:
    (tmp_path / "trondelag-nord.csv").write_text("old")

    scrape(FakeClient(pages), tmp_path, only={"trondelag"}, limit_branches=1)

    assert (tmp_path / "trondelag-nord.csv").read_text() == "old"
    assert (tmp_path / "trondelag-sor.csv").exists()


OSLO = "https://www.rodekors.no/lokalforeninger/oslo/"
OSLO_FIXTURES = Path(__file__).parent / "fixtures/oslo"


def _oslo_pages(pages: dict[str, str]) -> dict[str, str]:
    def read(name: str) -> str:
        return (OSLO_FIXTURES / f"{name}.html").read_text(encoding="utf-8")

    return pages | {
        f"{OSLO}om-organisasjonen/kontakt/": read("kontakt"),
        f"{OSLO}aktiviteter/": read("aktiviteter"),
        f"{OSLO}aktiviteter/barn-og-unge/": read("barn-og-unge"),
    }


def test_oslo_is_one_branch_with_activities_from_category_pages(
    tmp_path: Path, pages: dict[str, str]
) -> None:
    client = FakeClient(_oslo_pages(pages))

    failed = scrape(client, tmp_path, only={"oslo"}, limit_branches=2)

    df = pd.read_csv(tmp_path / "oslo.csv", keep_default_na=False)
    assert failed == []
    assert set(df.branch_slug) == {"oslo"}
    assert set(df.address) == {"Hausmanns gate 23, 0182 Oslo"}
    assert set(df.latitude) == {59.9171449}
    # 2 categories: barn-og-unge has 13 activities, the other page (fake) none.
    assert len(df) == 13
    assert set(df.section) == {"Tilbud og aktiviteter for barn og unge i Oslo"}
    assert len(client.urls) == 5  # districts, contact, activities, 2 categories


def test_oslo_contact_page_failure_writes_nothing(
    tmp_path: Path, pages: dict[str, str]
) -> None:
    contact = f"{OSLO}om-organisasjonen/kontakt/"
    client = FakeClient(_oslo_pages(pages), fail=frozenset({contact}))

    failed = scrape(client, tmp_path, only={"oslo"})

    assert failed == [contact]
    assert not (tmp_path / "oslo.csv").exists()


NESTED_FIXTURES = Path(__file__).parent / "fixtures/nested"
BODO = "https://www.rodekors.no/lokalforeninger/nordland/bodo/"
KRISTIANSAND = "https://www.rodekors.no/lokalforeninger/agder/kristiansand/"


def _nested(name: str) -> str:
    return (NESTED_FIXTURES / f"{name}.html").read_text(encoding="utf-8")


def _branch(url: str) -> Branch:
    return Branch(name=url.rstrip("/").rsplit("/", 1)[1], slug="x", url=url)


DISTRICT = District(
    name="D", slug="d", url="https://www.rodekors.no/lokalforeninger/d/"
)


def test_activities_from_linked_subpage() -> None:
    client = FakeClient(
        {
            BODO: _nested("bodo"),
            f"{BODO}om-oss/vare-aktiviteter/": _nested("bodo_aktiviteter"),
        }
    )

    df, failed, incomplete = scrape_district(client, DISTRICT, [_branch(BODO)])

    assert failed == []
    assert incomplete == []
    assert len(df) == 16
    assert set(df.address) == {"Storgata 54, 8006 BODØ"}  # from the branch page
    assert client.urls == [BODO, f"{BODO}om-oss/vare-aktiviteter/"]


def test_activities_from_linked_category_pages() -> None:
    hub = f"{KRISTIANSAND}aktiviteter/"
    client = FakeClient(
        {
            KRISTIANSAND: _nested("kristiansand"),
            hub: _nested("kristiansand_aktiviteter"),
            f"{hub}barn-og-unge/": _nested("kristiansand_barn-og-unge"),
        }
    )

    df, failed, incomplete = scrape_district(
        client, DISTRICT, [_branch(KRISTIANSAND)], limit_categories=2
    )

    assert failed == []
    assert incomplete == [KRISTIANSAND]
    # 2 categories: barn-og-unge has 7 activities, the other page (fake) none.
    assert len(df) == 7
    assert set(df.section) == {"Barn og Ungdom"}
    assert len(client.urls) == 4  # branch, hub, 2 categories


def test_failed_activities_subpage_keeps_the_branch() -> None:
    subpage = f"{BODO}om-oss/vare-aktiviteter/"
    client = FakeClient({BODO: _nested("bodo")}, fail=frozenset({subpage}))

    df, failed, incomplete = scrape_district(client, DISTRICT, [_branch(BODO)])

    assert failed == []
    assert incomplete == [BODO]
    assert len(df) == 1
    assert df.iloc[0].activity == ""
    assert df.iloc[0].address == "Storgata 54, 8006 BODØ"


def test_failed_category_keeps_metadata_and_marks_scrape_incomplete() -> None:
    hub = f"{KRISTIANSAND}aktiviteter/"
    failed_category = f"{hub}fellesskap-inkludering/"
    client = FakeClient(
        {
            KRISTIANSAND: _nested("kristiansand"),
            hub: _nested("kristiansand_aktiviteter"),
            f"{hub}barn-og-unge/": _nested("kristiansand_barn-og-unge"),
        },
        fail=frozenset({failed_category}),
    )

    df, failed, incomplete = scrape_district(
        client, DISTRICT, [_branch(KRISTIANSAND)], limit_categories=2
    )

    assert failed == []
    assert incomplete == [KRISTIANSAND]
    assert len(df) == 7
    assert set(df.address) == {"Vesterveien 6, 4616 KRISTIANSAND S"}


def _raw_csv(path: Path) -> None:
    """Agder CSV: arendal with an activity, bodo without (any branch URL will do)."""
    base = {"district": "Agder", "district_slug": "agder", "latitude": "58.1"}
    rows = [
        base
        | {
            "branch": "Arendal",
            "branch_slug": "arendal",
            "address": "A 1",
            "section": "S",
            "activity": "Leksehjelp",
            "description": "D",
            "branch_url": ARENDAL,
        },
        base
        | {
            "branch": "Bodø",
            "branch_slug": "bodo",
            "address": "Old 1",
            "section": "",
            "activity": "",
            "description": "",
            "branch_url": BODO,
        },
    ]
    pd.DataFrame(rows, columns=COLUMNS).to_csv(path, index=False)


def test_rescrape_empty_replaces_only_empty_branches(tmp_path: Path) -> None:
    path = tmp_path / "agder.csv"
    _raw_csv(path)
    before = path.read_text(encoding="utf-8").splitlines()
    client = FakeClient(
        {
            BODO: _nested("bodo"),
            f"{BODO}om-oss/vare-aktiviteter/": _nested("bodo_aktiviteter"),
        }
    )

    failed = rescrape_empty(client, tmp_path)

    df = pd.read_csv(path, keep_default_na=False)
    assert failed == []
    assert client.urls == [BODO, f"{BODO}om-oss/vare-aktiviteter/"]  # not arendal
    assert path.read_text(encoding="utf-8").splitlines()[:2] == before[:2]
    assert list(df.branch_slug) == ["arendal"] + ["bodo"] * 16
    assert set(df[df.branch_slug == "bodo"].address) == {"Storgata 54, 8006 BODØ"}


def test_rescrape_empty_keeps_old_rows_on_failure(tmp_path: Path) -> None:
    path = tmp_path / "agder.csv"
    _raw_csv(path)
    before = path.read_text(encoding="utf-8")

    failed = rescrape_empty(FakeClient({}, fail=frozenset({BODO})), tmp_path)

    assert failed == [BODO]
    assert path.read_text(encoding="utf-8") == before


def test_rescrape_empty_keeps_old_rows_when_a_linked_category_fails(
    tmp_path: Path,
) -> None:
    path = tmp_path / "agder.csv"
    old = pd.DataFrame(
        [
            {
                "district": "Agder",
                "district_slug": "agder",
                "branch": "Kristiansand",
                "branch_slug": "kristiansand",
                "address": "Old address",
                "latitude": "",
                "longitude": "",
                "section": "",
                "activity": "",
                "description": "",
                "branch_url": KRISTIANSAND,
            }
        ],
        columns=COLUMNS,
    )
    old.to_csv(path, index=False)
    before = path.read_text(encoding="utf-8")
    hub = f"{KRISTIANSAND}aktiviteter/"
    failed_category = f"{hub}fellesskap-inkludering/"
    client = FakeClient(
        {
            KRISTIANSAND: _nested("kristiansand"),
            hub: _nested("kristiansand_aktiviteter"),
            f"{hub}barn-og-unge/": _nested("kristiansand_barn-og-unge"),
        },
        fail=frozenset({failed_category}),
    )

    failed = rescrape_empty(client, tmp_path)

    assert failed == []
    assert path.read_text(encoding="utf-8") == before
