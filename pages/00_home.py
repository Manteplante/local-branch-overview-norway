"""Landing page: what this is, where the data comes from, how good it is, and thanks.

Text first, the illustration below it.
"""

from datetime import datetime

import streamlit as st
from streamlit.errors import StreamlitPageNotFoundError

from backend import config, storage
from backend.categories import OTHER
from backend.ui import front_image, load_tables, location_counts

REPO = "https://github.com/Manteplante/local-branch-overview"
QUALITY_NOTES = f"{REPO}/blob/main/docs/missing-data-quality.md"
RODEKORS = "https://www.rodekors.no/lokalforeninger/"
IMAGE_PROMPT = (  # verbatim, as given to OpenAI's image model
    "Create an a PNG image 1920×1080 pixels of a fiord, cascades running down steep "
    "mountains, and a small town in the mouth of the river that meets the fiord, using "
    "the creative style of classic 90s disney movie"
)

st.markdown(
    """
    <style>
    .lbo-lead { font-size: 1.2rem; line-height: 1.55; color: #3E4C59; max-width: 46rem;
                margin: -0.4rem 0 1rem; }
    [data-testid="stImage"] img { border-radius: 14px; }
    [data-testid="stMetricValue"] { font-weight: 600; }
    </style>
    """,
    unsafe_allow_html=True,
)

branches, activities = load_tables()
named = activities[activities["activity"].fillna("") != ""]
counts = location_counts(branches)
other = int((named["category"] == OTHER).sum())
located = len(branches) - counts["none"]

st.title(config.APP_NAME)
st.markdown(
    "<p class='lbo-lead'>Every Red Cross local branch in Norway on one map. Find a "
    "branch near you and <b>see what it does</b>: open the map, hover over or click a "
    "branch, and its activities appear, from first aid and visiting friends to "
    "homework help. Filter by district, category or a specific activity.</p>",
    unsafe_allow_html=True,
)
try:
    st.page_link("pages/01_map.py", label="Open the map", icon=":material/map:")
except (
    StreamlitPageNotFoundError
):  # the page run on its own, outside app.py's navigation
    st.markdown("[Open the map](map)")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Districts", f"{branches['district'].nunique():,}")
c2.metric("Local branches", f"{len(branches):,}")
c3.metric("Activities", f"{len(named):,}")
c4.metric("On the map", f"{located / max(len(branches), 1):.0%}")

table = storage.path("branches")
stamp = datetime.fromtimestamp(table.stat().st_mtime) if table else None
built = f"{stamp.day} {stamp:%B %Y}" if stamp else "unknown"

source, quality, thanks = st.columns(3)

with source.container(border=True):
    st.subheader(":material/travel_explore: Where the data comes from", divider="red")
    st.markdown(
        f"Branch names, addresses, map coordinates and activities were **scraped from "
        f"the public pages on [rodekors.no]({RODEKORS})**, one district and branch at a "
        f"time, with 5–15 seconds between requests so the site isn't burdened.\n\n"
        f"Data built **{built}**.\n\n"
        "This is an independent project, not made by or affiliated with the "
        "Norwegian Red Cross."
    )

with quality.container(border=True):
    st.subheader(":material/fact_check: Good to know about the data", divider="red")
    exact = counts["address"] + counts["site"] + counts["manual"]
    st.markdown(
        f"- **Most branch pages have an address but no map coordinates.** {exact:,} "
        f"branches are placed exactly: {counts['address']:,} at their street address, "
        f"{counts['site']:,} at the site's own coordinates and {counts['manual']:,} "
        "entered by hand.\n"
        f"- **{counts['place']:,} are approximate**: placed at the centre of their town "
        "or municipality. They are hollow rings on the map.\n"
        "- **Activities are shown as published** on rodekors.no and may be out of "
        "date. Categories are assigned automatically from the activity names.\n"
        f"- **{other:,} activities ({other / max(len(named), 1):.0%}) are in "
        '"Annet" (other).** Many branches run local variants with their own names, '
        "such as a second-hand shop or a walking group, that don't fit the main "
        "categories. Use *Specific activity* on the map to find them by name.\n\n"
        f"[Read the full data-quality notes]({QUALITY_NOTES})"
    )

with thanks.container(border=True):
    st.subheader(":material/favorite: Thank you, Kartverket", divider="red")
    st.markdown(
        "The **map tiles** (topographic map) and the **geocoding** that turns branch "
        "addresses and place names into points come from "
        "[Kartverket](https://www.kartverket.no/), the Norwegian Mapping Authority, as "
        "open data. © Kartverket.\n\n"
        "- [Address API](https://api.kartverket.no/adresser/v1/)\n"
        "- [Place-name API (stedsnavn)](https://api.kartverket.no/stedsnavn/v1/)\n"
        "- [Topographic map tiles](https://cache.kartverket.no/)\n\n"
        "Built with [Streamlit](https://streamlit.io/) and "
        "[folium](https://python-visualization.github.io/folium/) / "
        "[Leaflet](https://leafletjs.com/)."
    )

image = front_image()
if image:
    st.image(image, width="stretch")
    st.caption(f"Illustration: AI-generated with OpenAI. Prompt: “{IMAGE_PROMPT}”")

st.caption(f"Open source on [GitHub]({REPO}) · MIT licence")
