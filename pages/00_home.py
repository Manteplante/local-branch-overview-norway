"""Landing page: what this is, and the numbers at a glance."""

from datetime import datetime

import streamlit as st

from backend import config, storage
from backend.ui import load_tables

banner = config.ASSETS_DIR / "frontpage.png"
if banner.is_file():
    st.image(str(banner), width="stretch")

st.title(config.APP_NAME)
st.markdown(
    "An overview of the Red Cross local branches in Norway: where they are and which "
    "activities they offer, collected from the public pages on "
    "[rodekors.no/lokalforeninger](https://www.rodekors.no/lokalforeninger/). "
    "Use the **Map** to explore, **Activities** to compare, and **Data** to download."
)

branches, activities = load_tables()
named = activities[activities["activity"].fillna("") != ""]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Districts", branches["district"].nunique())
c2.metric("Local branches", len(branches))
c3.metric("Activities", len(named))
c4.metric("On the map", f"{branches['has_location'].astype(bool).mean():.0%}")

table = storage.path("branches")
if table is not None:
    built = datetime.fromtimestamp(table.stat().st_mtime)
    st.caption(
        f"Data built {built:%Y-%m-%d}. Branches without coordinates are listed under Data."
    )
