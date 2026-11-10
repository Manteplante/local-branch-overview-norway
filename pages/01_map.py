"""Interactive map of the local branches."""

import streamlit as st
from streamlit_folium import st_folium

from backend.filters import filter_branches
from backend.mapview import build_map
from backend.ui import load_tables, sidebar_filters

st.title("Map")

branches, _ = load_tables()
selection = filter_branches(
    branches, **sidebar_filters(branches, search_label="Search branch or address")
)

located = selection["has_location"].astype(bool)
st.caption(
    f"{located.sum()} branches shown · {(~located).sum()} without location "
    "(listed under Data, to be geocoded)"
)

# returned_objects=[]: panning and zooming don't rerun the page.
st_folium(
    build_map(selection), height=650, use_container_width=True, returned_objects=[]
)
