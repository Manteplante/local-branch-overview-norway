"""Raw scraper CSVs (data/raw/) -> app tables (data/tables/).

    make transform

`branches`    one row per local branch, for the map
`activities`  one row per activity, with a `category` for filtering
"""

from __future__ import annotations

import pandas as pd

from . import config, storage
from .categories import categorize

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


def build_branches(activities: pd.DataFrame) -> pd.DataFrame:
    """One row per branch, with its activity count and categories."""

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
    branches["has_location"] = (
        branches["latitude"].notna() & branches["longitude"].notna()
    )
    columns = [
        "district",
        "district_slug",
        "branch",
        "branch_slug",
        "address",
        "latitude",
        "longitude",
        "has_location",
        "n_activities",
        "categories",
        "branch_url",
    ]
    return branches[columns].sort_values(["district", "branch"], ignore_index=True)


def build_tables(raw: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """{table name: DataFrame} for the app."""
    activities = build_activities(raw)
    return {
        "activities": activities.sort_values(
            ["district", "branch", "category", "activity"], ignore_index=True
        ),
        "branches": build_branches(activities),
    }


def run() -> None:
    raw = read_raw()
    if raw.empty:
        print(
            f"[transform] No data files under {config.RAW_DIR}. Run `make scrape` first."
        )
        return

    print(f"[transform] Read {len(raw):,} raw rows")
    for name, df in build_tables(raw).items():
        storage.save(name, df)


if __name__ == "__main__":
    run()
