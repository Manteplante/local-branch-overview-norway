"""Interactive map of the local branches."""

import streamlit as st
from streamlit_folium import st_folium

from backend.filters import filter_branches
from backend.mapview import build_map
from backend.ui import load_tables, sidebar_filters

st.title("Map")

branches, activities = load_tables()
filters = sidebar_filters(branches, search_label="Search branch or address")
selection = filter_branches(branches, **filters)

located = selection["has_location"].astype(bool)
st.caption(
    f"{located.sum()} branches shown · {(~located).sum()} without a location · "
    "hover over a marker to see its activities, click to keep them open"
)

# returned_objects=[]: panning and zooming don't rerun the page.
st_folium(
    build_map(selection, activities, highlight=filters["categories"]),
    height=650,
    use_container_width=True,
    returned_objects=[],
)
