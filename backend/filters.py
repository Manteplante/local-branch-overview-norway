"""Filtering shared by the pages. Pure functions over the app tables."""

from __future__ import annotations

import pandas as pd


def _matches(df: pd.DataFrame, columns: list[str], search: str) -> pd.Series:
    needle = search.strip().lower()
    mask = pd.Series(False, index=df.index)
    for column in columns:
        mask |= df[column].fillna("").str.lower().str.contains(needle, regex=False)
    return mask


def filter_branches(
    branches: pd.DataFrame,
    *,
    districts: list[str] | None = None,
    categories: list[str] | None = None,
    search: str = "",
    activity_names: list[str] | None = None,
    activities: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Branches in any of `districts`, offering any of `categories`, matching `search`
    (branch name, address or categories), and offering any of `activity_names` (looked
    up in `activities`). Empty or None means "no filter"."""
    df = branches
    if activity_names and activities is not None:
        offering = activities[activities["activity"].isin(activity_names)]
        keys = set(zip(offering["district_slug"], offering["branch_slug"]))
        df = df[[k in keys for k in zip(df["district_slug"], df["branch_slug"])]]
    if districts:
        df = df[df["district"].isin(districts)]
    if categories:
        offered = df["categories"].fillna("").str.split("; ")
        df = df[offered.map(lambda cats: bool(set(cats) & set(categories)))]
    if search.strip():
        df = df[_matches(df, ["branch", "address", "categories"], search)]
    return df
