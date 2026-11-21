"""Every page renders without an exception, with data and in the empty state."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest
from test_backend import raw_rows

from backend import config, storage, transform

ROOT = Path(__file__).resolve().parents[1]
PAGES = sorted((ROOT / "pages").glob("[0-9]*.py"))


@pytest.fixture
def with_tables(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "TABLES_DIR", tmp_path)
    for name, df in transform.build_tables(raw_rows()).items():
        storage.save(name, df)


@pytest.fixture
def without_tables(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "TABLES_DIR", tmp_path / "missing")


def run(page: Path) -> AppTest:
    return AppTest.from_file(str(page), default_timeout=30).run()


def test_there_are_pages() -> None:
    assert PAGES[0].name == "00_home.py"


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.stem)
def test_page_renders_with_data(page: Path, with_tables: None) -> None:
    at = run(page)

    assert not at.exception
    assert not any("No data yet" in i.value for i in at.info)


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.stem)
def test_page_shows_empty_state(page: Path, without_tables: None) -> None:
    at = run(page)

    assert not at.exception
    assert any("No data yet" in i.value for i in at.info)


def metrics(at: AppTest) -> dict[str, str]:
    return {m.label: m.value for m in at.metric}


def test_map_filters_change_the_counts(with_tables: None) -> None:
    at = run(ROOT / "pages" / "01_map.py")
    assert metrics(at) == {
        "Branches shown": "1",
        "Exact location": "1",
        "Approximate (town centre)": "0",
    }
    assert any("2 matching branches have no location" in c.value for c in at.caption)

    at.multiselect(key="categories").select("Leksehjelp").run()

    assert metrics(at)["Branches shown"] == "0"


def test_map_specific_activity_filter(with_tables: None) -> None:
    at = run(ROOT / "pages" / "01_map.py")
    options = at.multiselect(key="activity_names").options
    assert "Hjelpekorpset i Arendal (1)" in options

    at.multiselect(key="activity_names").select("Hjelpekorpset i Arendal").run()

    assert metrics(at)["Branches shown"] == "1"
    at.multiselect(key="activity_names").unselect("Hjelpekorpset i Arendal")
    at.multiselect(key="activity_names").select("Leksehjelp").run()
    assert metrics(at)["Branches shown"] == "0"  # Grimstad has no location


def test_home_explains_sources_quality_and_credits(with_tables: None) -> None:
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    text = " ".join(m.value for m in at.markdown)

    assert not at.exception
    assert "rodekors.no" in text and "scraped" in text
    assert "Kartverket" in text and "geocoding" in text
    assert "not made by or affiliated with" in text
    assert "see what it does" in text and "Annet" in text
    assert any("OpenAI" in c.value for c in at.caption)
    # data-quality numbers come from the tables: 1 located at the site, 2 without
    assert "1 branches are placed exactly" in text
    assert metrics(at) == {
        "Districts": "2",
        "Local branches": "3",
        "Activities": "3",
        "On the map": "33%",
    }


def test_app_entry_point_runs(with_tables: None) -> None:
    assert (
        not AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run().exception
    )
