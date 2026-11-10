from pathlib import Path

import pandas as pd
import pytest

from backend import config, storage, transform
from backend.categories import CATEGORIES, OTHER, categorize
from backend.filters import filter_activities, filter_branches
from backend.mapview import build_map, popup_html


def raw_rows() -> pd.DataFrame:
    """Scraper output for three branches, as `pd.read_csv` returns it (empty -> NaN)."""
    base = {
        "district": "Agder Røde Kors",
        "district_slug": "agder",
        "section": "Aktiviteter",
    }
    nan = float("nan")
    return pd.DataFrame(
        [
            base | {"branch": "Arendal Røde Kors", "branch_slug": "arendal",
                    "address": "Hans Thornes vei 26, 4846 ARENDAL",
                    "latitude": 58.49, "longitude": 8.76,
                    "activity": "Barnas Røde Kors", "description": "BARK for barn",
                    "branch_url": "https://www.rodekors.no/lokalforeninger/agder/arendal/"},
            base | {"branch": "Arendal Røde Kors", "branch_slug": "arendal",
                    "address": "Hans Thornes vei 26, 4846 ARENDAL",
                    "latitude": 58.49, "longitude": 8.76,
                    "activity": "Hjelpekorpset i Arendal", "description": nan,
                    "branch_url": "https://www.rodekors.no/lokalforeninger/agder/arendal/"},
            base | {"branch": "Grimstad Røde Kors", "branch_slug": "grimstad",
                    "address": "Frivoldveien 11, 4877 GRIMSTAD",
                    "latitude": nan, "longitude": nan,
                    "activity": "Leksehjelp", "description": "Hjelp med lekser",
                    "branch_url": "https://www.rodekors.no/lokalforeninger/agder/grimstad/"},
            {"district": "Røde Kors i Trøndelag – Nord", "district_slug": "trondelag-nord",
             "branch": "Flatanger", "branch_slug": "flatanger", "address": nan,
             "latitude": nan, "longitude": nan, "section": nan, "activity": nan,
             "description": nan,
             "branch_url": "https://www.rodekors.no/lokalforeninger/trondelag/flatanger/"},
        ]
    )  # fmt: skip


@pytest.fixture
def tables_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(config, "TABLES_DIR", tmp_path / "tables")
    monkeypatch.setattr(config, "RAW_DIR", tmp_path / "raw")
    return tmp_path


# ── categories ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("name", "category"),
    [
        ("Barnas Røde Kors", "Barnas Røde Kors"),
        ("BARK (Barnas Røde Kors)", "Barnas Røde Kors"),
        ("Barnas Røde Kors Arna og Åsane", "Barnas Røde Kors"),
        ("RØFF (Røde Kors Friluftsliv og Førstehjelp)", "RØFF"),
        ("Hjelpekorpset i Arendal", "Beredskap og hjelpekorps"),
        ("Beredskapsvakt: Bidra når det trengs mest", "Beredskap og hjelpekorps"),
        ("Sanitetsvakt", "Beredskap og hjelpekorps"),
        ("Besøksvenn med hund: – Spre glede med din firbente venn!", "Besøkstjeneste"),
        ("Åpen møteplass/språkkafè", "Norsktrening"),
        ("Flyktningguide/Flerkultur", "Flyktning og migrasjon"),
        ("Våketjenesten", "Våketjeneste"),
        ("Vitnestøtte", "Vitnestøtte"),
        ("Ferie for alle (FFA)", "Ferie for alle"),
        ("Sykehusguide", "Sykehusvert/-guide"),
        ("Treffpunkt", "Møteplasser og ungdom"),
        ("Kameleonkvinnene", OTHER),
        ("", ""),
    ],
)
def test_categorize(name: str, category: str) -> None:
    assert categorize(name) == category
    assert category in CATEGORIES + [""]


# ── transform ─────────────────────────────────────────────────────────────────


def test_build_tables() -> None:
    tables = transform.build_tables(raw_rows())
    branches, activities = tables["branches"], tables["activities"]

    assert len(branches) == 3  # one row per branch
    arendal = branches.set_index("branch_slug").loc["arendal"]
    assert arendal.n_activities == 2
    assert arendal.categories == "Barnas Røde Kors; Beredskap og hjelpekorps"
    assert bool(arendal.has_location)
    assert not branches.set_index("branch_slug").loc["grimstad"].has_location

    flatanger = branches.set_index("branch_slug").loc["flatanger"]
    assert flatanger.n_activities == 0 and flatanger.categories == ""
    assert flatanger.address == ""  # text columns never NaN

    assert set(activities.category) == {
        "Barnas Røde Kors",
        "Beredskap og hjelpekorps",
        "Leksehjelp",
        "",
    }
    assert not activities[transform.TEXT_COLUMNS].isna().any().any()


def test_run_writes_tables_and_skips_without_raw(tables_dir: Path) -> None:
    transform.run()  # no raw folder: nothing written, no crash
    assert storage.tables() == []

    storage.write_frame(tables_dir / "raw" / "agder.csv", raw_rows())
    transform.run()

    assert storage.tables() == ["activities", "branches"]
    branches = storage.load("branches")
    assert len(branches) == 3
    assert branches["has_location"].tolist().count(True) == 1


# ── storage ───────────────────────────────────────────────────────────────────


def test_storage_round_trip_and_missing(tables_dir: Path) -> None:
    df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})

    storage.save("demo", df)

    assert storage.path("demo") == config.TABLES_DIR / "demo.csv"
    pd.testing.assert_frame_equal(storage.load("demo"), df)
    assert storage.load("nope").empty
    assert storage.path("nope") is None


def test_broken_table_reads_as_empty(tables_dir: Path) -> None:
    config.TABLES_DIR.mkdir(parents=True)
    (config.TABLES_DIR / "broken.parquet").write_bytes(b"not parquet")

    assert storage.load("broken").empty


def test_unknown_file_format(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "FILE_FORMAT", "json")
    with pytest.raises(ValueError, match="json"):
        storage.data_suffix()


# ── filters ───────────────────────────────────────────────────────────────────


def test_filter_branches() -> None:
    branches = transform.build_tables(raw_rows())["branches"]

    assert len(filter_branches(branches)) == 3
    assert set(
        filter_branches(branches, districts=["Agder Røde Kors"]).branch_slug
    ) == {"arendal", "grimstad"}
    assert set(filter_branches(branches, categories=["Leksehjelp"]).branch_slug) == {
        "grimstad"
    }
    assert set(filter_branches(branches, search="  ARENDAL ").branch_slug) == {
        "arendal"
    }


def test_filter_activities_drops_rows_without_activity() -> None:
    activities = transform.build_tables(raw_rows())["activities"]

    assert len(filter_activities(activities)) == 3
    assert filter_activities(activities, search="lekser").activity.tolist() == [
        "Leksehjelp"
    ]
    assert filter_activities(activities, categories=["RØFF"]).empty


# ── map ───────────────────────────────────────────────────────────────────────


def test_popup_escapes_scraped_text() -> None:
    row = pd.Series(
        {
            "branch": "<script>alert(1)</script>",
            "address": "A & B",
            "n_activities": 1,
            "categories": "Leksehjelp",
            "branch_url": "https://example.org/?a=1&b='2'",
        }
    )

    html = popup_html(row)

    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "A &amp; B" in html
    assert "&#x27;2&#x27;" in html


def test_map_only_plots_located_branches() -> None:
    branches = transform.build_tables(raw_rows())["branches"]

    rendered = build_map(branches).get_root().render()

    assert "Arendal Røde Kors" in rendered
    assert "Grimstad Røde Kors" not in rendered
    assert "cache.kartverket.no" in rendered
