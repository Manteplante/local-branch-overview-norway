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


def sidebar_filters(branches: pd.DataFrame, *, search_label: str) -> dict:
    """District, category and search filters in the sidebar, as filter_* keyword args."""
    with st.sidebar:
        st.header("Filters")
        districts = st.multiselect(
            "District", sorted(branches["district"].dropna().unique()), key="districts"
        )
        categories = st.multiselect("Activity", CATEGORIES, key="categories")
        search = st.text_input(search_label, key="search")
    return {"districts": districts, "categories": categories, "search": search}
