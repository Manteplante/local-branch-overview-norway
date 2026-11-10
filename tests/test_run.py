from pathlib import Path

import pandas as pd
import pytest

from local_branch_overview.scraper.parse import DISTRICTS_URL
from local_branch_overview.scraper.run import COLUMNS, scrape

AGDER = "https://www.rodekors.no/lokalforeninger/agder/"
ARENDAL = "https://www.rodekors.no/lokalforeninger/agder/arendal/"
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
    return {DISTRICTS_URL: main_html, AGDER: agder_html, ARENDAL: arendal_html}


def test_writes_one_row_per_activity(tmp_path: Path, pages: dict[str, str]) -> None:
    failed = scrape(FakeClient(pages), tmp_path, only={"agder"}, limit_branches=2)

    df = pd.read_csv(tmp_path / "agder.csv", keep_default_na=False)
    assert failed == []
    assert list(df.columns) == COLUMNS
    arendal = df[df.branch_slug == "arendal"]
    assert len(arendal) == 16
    assert set(arendal.address) == {"Hans Thornes vei 26, 4846 ARENDAL"}
    assert arendal.iloc[0].activity == "Barnas Røde Kors"
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
    assert client.urls == [DISTRICTS_URL]
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
