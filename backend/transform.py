"""Raw scraper CSVs (data/raw/) -> app tables (data/tables/).

    make transform

`branches`    one row per local branch, for the map. Coordinates the site lacks come
              from the geocode cache (`make geocode`: Kartverket street address or
              place) or by hand (`make overrides`); `location_source` (site | address |
              place | manual | none) says which.
`activities`  one row per activity, with a `category` for filtering
"""

from __future__ import annotations

import pandas as pd

from . import config, overrides, storage
from .categories import categorize
from .geocode import GeocodeResult, branch_query, load_cache

TEXT_COLUMNS = [
    "district",
    "district_slug",
    "branch",
    "branch_slug",
    "address",
    "section",
    "activity",
    "description",
    "branch_url",
]
BRANCH_KEY = ["district_slug", "branch_slug"]


def read_raw() -> pd.DataFrame:
    """Every raw file, stacked. Reads CSV, Parquet and Excel alike."""
    frames = []
    for path in sorted(config.RAW_DIR.rglob("*")):
        if path.suffix.lower() not in storage.DATA_SUFFIXES:
            continue
        try:
            df = storage.read_file(path)
        except storage.READ_ERRORS as exc:
            print(f"  [skip] {path.name}: {exc}")
            continue
        if not df.empty:
            frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def build_activities(raw: pd.DataFrame) -> pd.DataFrame:
    """The raw rows plus `category`; text columns use "" (never NaN) for "none"."""
    df = raw.copy()
    for column in TEXT_COLUMNS:
        df[column] = df[column].fillna("").astype(str) if column in df else ""
    df["category"] = df["activity"].map(categorize)
    return df


def placeholder_coordinates(branches: pd.DataFrame) -> pd.Series:
    """Site coordinates that are a stand-in, not the branch's location.

    rodekors.no puts some branches without a map location at one shared point in
    central Oslo (59.9155, 10.7578: Karasjok, Nordkapp, Bø, Siljan in 2026-11). Real
    offices in *different* districts never share exact coordinates, so such points are
    treated as missing and the branch is geocoded like the rest.
    """
    has = branches["latitude"].notna() & branches["longitude"].notna()
    point = branches["latitude"].astype(str) + "," + branches["longitude"].astype(str)
    districts = branches[has].groupby(point[has])["district_slug"].nunique()
    return has & point.map(districts).gt(1)


def build_branches(
    activities: pd.DataFrame,
    geocodes: dict[str, GeocodeResult] | None = None,
    manual: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """One row per branch, with its activity count and categories.

    Branches without site coordinates get them from `geocodes` (query -> result), if
    there is a match. `manual` (from `overrides.load_overrides`) beats every source.
    """

    def summarize(group: pd.DataFrame) -> pd.Series:
        first = group.iloc[0]
        named = group[group["activity"] != ""]
        categories = sorted(set(named["category"]))
        return pd.Series(
            {
                "district": first["district"],
                "branch": first["branch"],
                "address": first["address"],
                "latitude": first["latitude"],
                "longitude": first["longitude"],
                "n_activities": len(named),
                "categories": "; ".join(categories),
                "branch_url": first["branch_url"],
            }
        )

    branches = (
        activities.groupby(BRANCH_KEY, sort=False)
        .apply(summarize, include_groups=False)
        .reset_index()
    )
    placeholder = placeholder_coordinates(branches)
    branches.loc[placeholder, ["latitude", "longitude"]] = float("nan")
    site = branches["latitude"].notna() & branches["longitude"].notna()
    branches["location_source"] = site.map({True: "site", False: "none"})
    for i in branches.index[~site]:
        row = branches.loc[i]
        key = branch_query(row["branch"], row["district"], row["address"])
        result = (geocodes or {}).get(key)
        if result is None or not result.found:
            continue
        # `address` stays as scraped: it is what was geocoded, or a PO box.
        branches.loc[i, ["latitude", "longitude", "location_source"]] = [
            result.latitude,
            result.longitude,
            result.method or "place",
        ]
    if manual is not None and not manual.empty:
        by_key = manual.set_index(BRANCH_KEY)
        for i, key in zip(branches.index, zip(*(branches[k] for k in BRANCH_KEY))):
            if key in by_key.index:
                lat, lon = by_key.loc[key, ["latitude", "longitude"]]
                branches.loc[i, ["latitude", "longitude", "location_source"]] = [
                    lat,
                    lon,
                    "manual",
                ]
    branches["has_location"] = branches["location_source"] != "none"
    columns = [
        "district",
        "district_slug",
        "branch",
        "branch_slug",
        "address",
        "latitude",
        "longitude",
        "has_location",
        "location_source",
        "n_activities",
        "categories",
        "branch_url",
    ]
    return branches[columns].sort_values(["district", "branch"], ignore_index=True)


def build_tables(
    raw: pd.DataFrame,
    geocodes: dict[str, GeocodeResult] | None = None,
    manual: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    """{table name: DataFrame} for the app."""
    activities = build_activities(raw)
    return {
        "activities": activities.sort_values(
            ["district", "branch", "category", "activity"], ignore_index=True
        ),
        "branches": build_branches(activities, geocodes, manual),
    }


def run() -> None:
    raw = read_raw()
    if raw.empty:
        print(
            f"[transform] No data files under {config.RAW_DIR}. Run `make scrape` first."
        )
        return

    geocodes = load_cache()
    print(f"[transform] Read {len(raw):,} raw rows, {len(geocodes)} cached geocodes")
    try:
        manual = overrides.load_overrides()
    except overrides.OverrideError as exc:
        raise SystemExit(f"[transform] {exc}") from None
    tables = build_tables(raw, geocodes, manual)
    for key in overrides.unknown_keys(manual, tables["branches"]):
        print(f"  [warn] {config.OVERRIDES.name}: no scraped branch {key}, ignored")
    for name, df in tables.items():
        storage.save(name, df)
    counts = tables["branches"]["location_source"].value_counts().to_dict()
    print(f"[transform] Branch locations: {counts}")


if __name__ == "__main__":
    run()
