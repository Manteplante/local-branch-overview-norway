"""Which activities are offered where."""

import streamlit as st

from backend.filters import filter_activities
from backend.ui import load_tables, sidebar_filters

st.title("Activities")

branches, activities = load_tables()
selection = filter_activities(
    activities,
    **sidebar_filters(branches, search_label="Search activity or description"),
)

if selection.empty:
    st.info("No activities match the filters.")
    st.stop()

st.subheader("Branches offering each kind of activity")
counts = (
    selection.drop_duplicates(["branch_slug", "district_slug", "category"])
    .groupby("category")
    .size()
    .sort_values(ascending=False)
    .rename("branches")
)
st.bar_chart(counts, horizontal=True, color="#C8102E")

st.subheader(f"{len(selection)} activities")
st.dataframe(
    selection[
        ["district", "branch", "category", "activity", "description", "branch_url"]
    ],
    hide_index=True,
    width="stretch",
    column_config={
        "branch_url": st.column_config.LinkColumn("Page", display_text="rodekors.no"),
        "description": st.column_config.TextColumn("Description", width="large"),
    },
)
