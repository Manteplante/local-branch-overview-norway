"""Hand-entered locations: seeding the file and validating what people type into it."""

from pathlib import Path

import pandas as pd
import pytest

from backend import config, transform
from backend.overrides import (
    COLUMNS,
    OverrideError,
    load_overrides,
    seed,
    unknown_keys,
)

HEADER = ",".join(COLUMNS)


def branches(*rows: tuple[str, str, str]) -> pd.DataFrame:
    """(district_slug, branch_slug, location_source) -> a minimal branches table."""
    return pd.DataFrame(
        [
            {
                "district_slug": d,
                "branch_slug": b,
                "branch": b.title(),
                "location_source": s,
            }
            for d, b, s in rows
        ]
    )


def write(path: Path, *lines: str) -> Path:
    path.write_text("\n".join([HEADER, *lines]) + "\n", encoding="utf-8")
    return path


# ── seed ──────────────────────────────────────────────────────────────────────


def test_seed_adds_only_branches_without_location(tmp_path: Path) -> None:
    path = tmp_path / "overrides.csv"
    table = branches(
        ("hedmark", "solor", "none"),
        ("agder", "lista", "none"),
        ("agder", "arendal", "site"),
        ("agder", "grimstad", "kartverket"),
    )

    assert seed(table, path) == 2
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    assert list(df.columns) == COLUMNS
    assert list(df.branch_slug) == ["lista", "solor"]  # sorted by key
    assert (df.latitude == "").all() and (df.longitude == "").all()
    assert seed(table, path) == 0  # rerunning adds nothing


def test_seed_keeps_filled_rows_and_their_order(tmp_path: Path) -> None:
    path = write(
        tmp_path / "overrides.csv",
        "hedmark,solor,Solør,60.79,12.01,Flisa",
        "agder,lista,Lista,,,",
    )
    before = path.read_text(encoding="utf-8")

    added = seed(
        branches(("agder", "lista", "none"), ("finnmark", "langfjord", "none")), path
    )

    assert added == 1
    after = path.read_text(encoding="utf-8")
    assert after.startswith(before)  # existing rows untouched, new ones appended
    assert after.splitlines()[-1].startswith("finnmark,langfjord,")


# ── load / validate ───────────────────────────────────────────────────────────


def test_load_returns_filled_rows_only(tmp_path: Path) -> None:
    path = write(
        tmp_path / "overrides.csv",
        "agder,lista,Lista,58.10, 6.69 ,Vanse",  # surrounding spaces are fine
        "hedmark,solor,Solør,,,",
    )

    df = load_overrides(path)

    assert df.to_dict("records") == [
        {
            "district_slug": "agder",
            "branch_slug": "lista",
            "latitude": 58.1,
            "longitude": 6.69,
        }
    ]


def test_missing_file_means_no_overrides(tmp_path: Path) -> None:
    assert load_overrides(tmp_path / "missing.csv").empty


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ("agder,lista,Lista,58.10,,", "both latitude and longitude"),
        ("agder,lista,Lista,58,10,6.69,", "Use a dot"),
        ("agder,lista,Lista,abc,6.69,", "not a number"),
        ("agder,lista,Lista,6.69,58.10,swapped", "outside Norway"),
        ("agder,lista,Lista,58.10,40.0,", "longitude 40.0 is outside"),
    ],
)
def test_bad_rows_raise_with_the_line(tmp_path: Path, line: str, message: str) -> None:
    path = write(tmp_path / "overrides.csv", "hedmark,solor,Solør,,,", line)
    with pytest.raises(OverrideError, match=message):
        load_overrides(path)


def test_bad_row_names_its_line(tmp_path: Path) -> None:
    path = write(
        tmp_path / "overrides.csv", "hedmark,solor,Solør,,,", "agder,lista,Lista,x,1,"
    )
    with pytest.raises(OverrideError, match=r"line 3 \(Lista\)"):
        load_overrides(path)


def test_duplicate_key_raises(tmp_path: Path) -> None:
    path = write(
        tmp_path / "overrides.csv",
        "agder,lista,Lista,,,",
        "agder,lista,Lista,58.1,6.7,",
    )
    with pytest.raises(OverrideError, match="more than once"):
        load_overrides(path)


def test_unknown_keys() -> None:
    manual = pd.DataFrame(
        [
            {
                "district_slug": "agder",
                "branch_slug": "gone",
                "latitude": 58.0,
                "longitude": 7.0,
            }
        ]
    )
    assert unknown_keys(manual, branches(("agder", "lista", "none"))) == [
        ("agder", "gone")
    ]


def test_transform_stops_on_a_bad_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        config, "OVERRIDES", write(tmp_path / "o.csv", "agder,lista,L,1,1,")
    )
    monkeypatch.setattr(transform, "read_raw", lambda: pd.DataFrame({"x": [1]}))
    monkeypatch.setattr(transform, "load_cache", dict)
    with pytest.raises(SystemExit, match="outside Norway"):
        transform.run()
