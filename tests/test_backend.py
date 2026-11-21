from pathlib import Path

import pandas as pd
import pytest

from backend import config, storage, transform
from backend.categories import CATEGORIES, OTHER, categorize
from backend.filters import filter_activities, filter_branches
from backend.geocode import GeocodeResult
from backend.mapview import branch_payloads, build_map, excerpt


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
    monkeypatch.setattr(config, "GEOCODE_CACHE", tmp_path / "geocode_cache.csv")
    monkeypatch.setattr(config, "OVERRIDES", tmp_path / "overrides.csv")
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
    assert branches.set_index("branch_slug").location_source.to_dict() == {
        "arendal": "site",
        "grimstad": "none",
        "flatanger": "none",
    }


def test_geocodes_fill_only_missing_coordinates() -> None:
    geocodes = {
        "Grimstad, Agder | Frivoldveien 11, 4877 GRIMSTAD": GeocodeResult(
            query="Grimstad, Agder | Frivoldveien 11, 4877 GRIMSTAD", status="found", method="address",
            latitude=58.34, longitude=8.59, matched_name="Frivoldveien 11, 4877 GRIMSTAD",
            place_type="Adresse", municipality="Grimstad",
        ),
        "Arendal, Agder | Hans Thornes vei 26, 4846 ARENDAL": GeocodeResult(  # site wins
            query="Arendal, Agder | Hans Thornes vei 26, 4846 ARENDAL", status="found",
            method="address", latitude=1.0, longitude=1.0,
        ),
        "Flatanger, Trøndelag": GeocodeResult(
            query="Flatanger, Trøndelag", status="no_match",
        ),
    }  # fmt: skip

    branches = transform.build_tables(raw_rows(), geocodes)["branches"]

    by_slug = branches.set_index("branch_slug")
    assert by_slug.loc["arendal", "latitude"] == 58.49
    assert by_slug.loc["arendal", "location_source"] == "site"
    grimstad = by_slug.loc["grimstad"]
    assert (grimstad.latitude, grimstad.longitude) == (58.34, 8.59)
    assert grimstad.location_source == "address" and bool(grimstad.has_location)
    assert grimstad.address == "Frivoldveien 11, 4877 GRIMSTAD"  # site address kept
    assert by_slug.loc["flatanger", "location_source"] == "none"


def test_shared_site_coordinates_across_districts_are_placeholders() -> None:
    raw = raw_rows()
    flatanger = raw["branch_slug"] == "flatanger"
    arendal = raw["branch_slug"] == "arendal"
    # Flatanger (Trøndelag) gets Arendal's (Agder) exact point: a stand-in
    raw.loc[flatanger, ["latitude", "longitude"]] = (
        raw.loc[arendal, ["latitude", "longitude"]].iloc[0].values
    )

    by_slug = transform.build_tables(raw)["branches"].set_index("branch_slug")

    assert by_slug.loc["arendal", "location_source"] == "none"
    assert by_slug.loc["flatanger", "location_source"] == "none"
    assert pd.isna(by_slug.loc["flatanger", "latitude"])


def test_shared_site_coordinates_within_a_district_are_kept() -> None:
    raw = raw_rows()
    grimstad = raw["branch_slug"] == "grimstad"
    arendal = raw["branch_slug"] == "arendal"
    raw.loc[grimstad, ["latitude", "longitude"]] = (
        raw.loc[arendal, ["latitude", "longitude"]].iloc[0].values
    )

    by_slug = transform.build_tables(raw)["branches"].set_index("branch_slug")

    assert set(by_slug.loc[["arendal", "grimstad"], "location_source"]) == {"site"}


def test_manual_overrides_beat_every_source() -> None:
    geocodes = {
        "Grimstad, Agder | Frivoldveien 11, 4877 GRIMSTAD": GeocodeResult(
            query="Grimstad, Agder | Frivoldveien 11, 4877 GRIMSTAD",
            status="found",
            method="address",
            latitude=58.34,
            longitude=8.59,
        )
    }
    manual = pd.DataFrame(
        [
            {"district_slug": "agder", "branch_slug": "arendal",  # beats site
             "latitude": 58.5, "longitude": 8.8},
            {"district_slug": "agder", "branch_slug": "grimstad",  # beats kartverket
             "latitude": 58.3, "longitude": 8.6},
            {"district_slug": "trondelag-nord", "branch_slug": "flatanger",  # fills none
             "latitude": 64.5, "longitude": 10.9},
        ]
    )  # fmt: skip

    branches = transform.build_tables(raw_rows(), geocodes, manual)["branches"]

    by_slug = branches.set_index("branch_slug")
    assert set(by_slug.location_source) == {"manual"}
    assert by_slug.has_location.all()
    assert (
        by_slug.loc["flatanger", "latitude"],
        by_slug.loc["flatanger", "longitude"],
    ) == (
        64.5,
        10.9,
    )
    assert by_slug.loc["arendal", "latitude"] == 58.5


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


def map_tables() -> tuple[pd.DataFrame, pd.DataFrame]:
    tables = transform.build_tables(raw_rows())
    return tables["branches"], tables["activities"]


def test_excerpt_cuts_at_a_word_with_ellipsis() -> None:
    assert excerpt("short text") == "short text"
    assert excerpt("  spaced   out \n text ") == "spaced out text"
    cut = excerpt("word " * 100, limit=22)
    assert cut == "word word word word…" and len(cut) <= 23


def test_branch_payloads_only_located_with_grouped_activities() -> None:
    branches, activities = map_tables()

    payloads = branch_payloads(branches, activities)

    assert [p["name"] for p in payloads] == [
        "Arendal Røde Kors"
    ]  # the only located one
    arendal = payloads[0]
    assert (arendal["lat"], arendal["lon"]) == (58.49, 8.76)
    assert arendal["approximate"] is False
    groups = [g["category"] for g in arendal["groups"]]
    assert groups == sorted(groups, key=str.casefold)  # alphabetical without highlight
    assert sum(len(g["items"]) for g in arendal["groups"]) == 2  # empty rows skipped


def test_branch_payloads_highlight_first_and_flag_approximate() -> None:
    branches, activities = map_tables()
    branches.loc[branches.branch_slug == "arendal", "location_source"] = "place"

    payload = branch_payloads(
        branches, activities, highlight=["Beredskap og hjelpekorps"]
    )[0]

    assert payload["groups"][0]["category"] == "Beredskap og hjelpekorps"
    assert payload["groups"][0]["highlight"] is True
    assert payload["approximate"] is True


def test_map_has_panel_cluster_options_and_hit_tolerance() -> None:
    branches, activities = map_tables()

    rendered = build_map(branches, activities).get_root().render()

    assert "cache.kartverket.no" in rendered
    assert '"disableClusteringAtZoom": 10' in rendered
    assert "L.canvas({tolerance: 8})" in rendered
    assert 'position: "topleft"' in rendered
    assert "Arendal Røde Kors" in rendered
    assert "Grimstad Røde Kors" not in rendered  # no coordinates


def test_map_data_cannot_break_out_of_the_script() -> None:
    branches, activities = map_tables()
    evil = "</script><script>alert(1)</script>"
    branches.loc[branches.branch_slug == "arendal", "branch"] = evil
    activities.loc[activities.branch_slug == "arendal", "description"] = "a & <b>"

    rendered = build_map(branches, activities).get_root().render()

    assert evil not in rendered and "alert(1)" in rendered
    assert "\\u003c/script\\u003e" in rendered
    assert "<b>" not in rendered


def test_map_opens_on_the_mainland_even_with_svalbard() -> None:
    branches, activities = map_tables()
    svalbard = branches[branches.branch_slug == "arendal"].assign(
        branch_slug="longyearbyen",
        branch="Longyearbyen",
        latitude=78.22,
        longitude=15.65,
    )
    branches = pd.concat([branches, svalbard], ignore_index=True)
    branches.loc[
        branches.branch_slug == "grimstad", ["latitude", "longitude", "has_location"]
    ] = [58.34, 8.59, True]

    rendered = build_map(branches, activities).get_root().render()

    assert "78.22" in rendered  # the marker is there
    bounds = rendered.split("fitBounds(")[1].split(")")[0]
    assert "78.22" not in bounds
