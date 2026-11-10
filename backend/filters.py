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
) -> pd.DataFrame:
    """Branches in any of `districts`, offering any of `categories`, matching `search`
    (branch name, address or categories). Empty or None means "no filter"."""
    df = branches
    if districts:
        df = df[df["district"].isin(districts)]
    if categories:
        offered = df["categories"].fillna("").str.split("; ")
        df = df[offered.map(lambda cats: bool(set(cats) & set(categories)))]
    if search.strip():
        df = df[_matches(df, ["branch", "address", "categories"], search)]
    return df


def filter_activities(
    activities: pd.DataFrame,
    *,
    districts: list[str] | None = None,
    categories: list[str] | None = None,
    search: str = "",
) -> pd.DataFrame:
    """Activities in `districts` and `categories`, matching `search` (branch, activity name
    or description). Rows without an activity are dropped."""
    df = activities[activities["activity"].fillna("") != ""]
    if districts:
        df = df[df["district"].isin(districts)]
    if categories:
        df = df[df["category"].isin(categories)]
    if search.strip():
        df = df[_matches(df, ["branch", "activity", "description"], search)]
    return df
