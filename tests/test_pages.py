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


def test_map_filters_change_the_count(with_tables: None) -> None:
    at = run(ROOT / "pages" / "01_map.py")
    assert "1 branches shown · 2 without a location" in at.caption[0].value

    at.multiselect(key="categories").select("Leksehjelp").run()

    assert "0 branches shown · 1 without a location" in at.caption[0].value


def test_app_entry_point_runs(with_tables: None) -> None:
    assert (
        not AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run().exception
    )
