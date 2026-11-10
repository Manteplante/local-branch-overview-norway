"""The tables behind the app, for download, and what is still missing."""

import streamlit as st

from backend.ui import load_tables

st.title("Data")

branches, activities = load_tables()

missing = branches[~branches["has_location"].astype(bool)]
st.subheader(f"Without location ({len(missing)})")
st.caption(
    "These branches have no coordinates on rodekors.no, so they are not on the map yet."
)
st.dataframe(
    missing[["district", "branch", "address", "branch_url"]],
    hide_index=True,
    width="stretch",
    column_config={"branch_url": st.column_config.LinkColumn("Page")},
)

for name, df in (("branches", branches), ("activities", activities)):
    st.subheader(f"{name} ({len(df):,} rows)")
    st.dataframe(df, hide_index=True, width="stretch", height=300)
    st.download_button(
        f"Download {name}.csv",
        df.to_csv(index=False).encode("utf-8"),
        file_name=f"{name}.csv",
        mime="text/csv",
        key=f"download-{name}",
    )
