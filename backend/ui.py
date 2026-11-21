"""Small Streamlit helpers shared by the pages."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from . import storage
from .categories import CATEGORIES


def load_tables() -> tuple[pd.DataFrame, pd.DataFrame]:
    """(branches, activities). Stops the page with a hint when there is no data yet."""
    branches, activities = storage.load("branches"), storage.load("activities")
    if branches.empty:
        st.info(
            "No data yet. Run `make scrape` and then `make transform` to build "
            f"the tables in `{storage.describe()}`."
        )
        st.stop()
    return branches, activities


def activity_choices(activities: pd.DataFrame) -> dict[str, int]:
    """{activity name: number of branches offering it}, most common first."""
    named = activities[activities["activity"].fillna("") != ""]
    counts = (
        named.drop_duplicates(["district_slug", "branch_slug", "activity"])
        .groupby("activity")
        .size()
    )
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], str(kv[0]).casefold()))
    return {str(name): int(n) for name, n in ordered}


def sidebar_filters(
    branches: pd.DataFrame,
    *,
    search_label: str,
    activities: pd.DataFrame | None = None,
) -> dict:
    """District, category, search and (with `activities`) specific-activity filters in
    the sidebar, as filter_branches keyword args."""
    with st.sidebar:
        st.header("Filters")
        districts = st.multiselect(
            "District", sorted(branches["district"].dropna().unique()), key="districts"
        )
        categories = st.multiselect("Activity category", CATEGORIES, key="categories")
        filters = {"districts": districts, "categories": categories}
        if activities is not None:
            choices = activity_choices(activities)
            filters["activity_names"] = st.multiselect(
                "Specific activity",
                list(choices),
                key="activity_names",
                format_func=lambda name: f"{name} ({choices[name]})",
                placeholder="Type to search, e.g. Bruktbutikk",
                help="Activities as each branch names them, with the number of "
                "branches offering them. Many local ones are in the category Annet.",
            )
        filters["search"] = st.text_input(search_label, key="search")
    return filters


LOCATION_SOURCES = ["address", "site", "place", "manual", "none"]


def location_counts(branches: pd.DataFrame) -> dict[str, int]:
    """How many branches got their location from each source, in `LOCATION_SOURCES`
    order (all keys present, zero when unused)."""
    counts = branches.get("location_source", pd.Series(dtype=str)).value_counts()
    return {source: int(counts.get(source, 0)) for source in LOCATION_SOURCES}


def front_image() -> str | None:
    """The home page illustration: the web-sized JPEG, else the original PNG."""
    from . import config

    for name in ("frontpage.jpg", "frontpage.png"):
        path = config.ASSETS_DIR / name
        if path.is_file():
            return str(path)
    return None
