"""Interactive map of the local branches."""

import streamlit as st
from streamlit_folium import st_folium

from backend.filters import filter_branches
from backend.mapview import MARKER_COLOR, build_map
from backend.ui import load_tables, location_counts, sidebar_filters

st.markdown(
    f"""
    <style>
    [data-testid="stMetricValue"] {{ font-weight: 600; }}
    .lbo-legend {{ display: flex; flex-wrap: wrap; gap: 6px 22px; align-items: center;
                  color: #52606D; font-size: 0.9rem; margin-top: -0.4rem; }}
    .lbo-legend span {{ display: inline-flex; align-items: center; gap: 7px; }}
    .lbo-dot {{ width: 13px; height: 13px; border-radius: 50%; display: inline-block;
               box-sizing: border-box; }}
    .lbo-exact {{ background: {MARKER_COLOR}; border: 1.5px solid #fff;
                 box-shadow: 0 0 0 1px {MARKER_COLOR}; }}
    .lbo-approx {{ background: #fff; border: 2.5px solid {MARKER_COLOR}; }}
    .lbo-cluster {{ background: #F1D302; border: 3px solid rgba(241, 211, 2, .35);
                   background-clip: padding-box; width: 17px; height: 17px; }}
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Map")
st.caption(
    "Hover over a marker to see the branch's activities · click to keep them open · "
    "filter by district, activity category or a specific activity in the sidebar"
)

branches, activities = load_tables()
filters = sidebar_filters(
    branches, search_label="Search branch or address", activities=activities
)
selection = filter_branches(branches, activities=activities, **filters)
counts = location_counts(selection)
shown = len(selection) - counts["none"]

c1, c2, c3 = st.columns(3)
c1.metric("Branches shown", f"{shown:,}")
c2.metric(
    "Exact location", f"{counts['address'] + counts['site'] + counts['manual']:,}"
)
c3.metric("Approximate (town centre)", f"{counts['place']:,}")
if counts["none"]:
    st.caption(
        f"{counts['none']:,} matching branches have no location and aren't shown."
    )

# returned_objects=[]: panning and zooming don't rerun the page.
st_folium(
    build_map(
        selection,
        activities,
        highlight=filters["categories"],
        highlight_activities=filters["activity_names"],
    ),
    height=720,
    use_container_width=True,
    returned_objects=[],
)

st.markdown(
    "<div class='lbo-legend'>"
    "<span><i class='lbo-dot lbo-exact'></i>Exact location</span>"
    "<span><i class='lbo-dot lbo-approx'></i>Approximate: town or municipality centre</span>"
    "<span><i class='lbo-dot lbo-cluster'></i>Several branches: zoom in or click</span>"
    "</div>",
    unsafe_allow_html=True,
)
