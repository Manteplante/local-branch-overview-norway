"""The folium map: Kartverket topo tiles, clustered markers, escaped popups."""

from __future__ import annotations

from html import escape

import folium
import pandas as pd
from folium.plugins import MarkerCluster

KARTVERKET_TOPO = (
    "https://cache.kartverket.no/v1/wmts/1.0.0/topo/default/webmercator/{z}/{y}/{x}.png"
)
KARTVERKET_ATTRIBUTION = '&copy; <a href="https://www.kartverket.no/">Kartverket</a>'
NORWAY_CENTER = (64.5, 13.0)
MARKER_COLOR = "#C8102E"


def popup_html(row: pd.Series) -> str:
    """Popup for one branch. Every scraped value is HTML-escaped."""
    categories = [c for c in str(row.get("categories") or "").split("; ") if c]
    items = "".join(f"<li>{escape(c)}</li>" for c in categories)
    activities = (
        f"<ul style='margin:4px 0 0 16px;padding:0'>{items}</ul>" if items else ""
    )
    url = escape(str(row.get("branch_url") or ""), quote=True)
    link = (
        f"<a href='{url}' target='_blank' rel='noopener'>Read more on rodekors.no</a>"
    )
    return (
        f"<div style='min-width:220px'>"
        f"<strong>{escape(str(row['branch']))}</strong><br>"
        f"<span>{escape(str(row.get('address') or ''))}</span><br>"
        f"<small>{int(row.get('n_activities') or 0)} activities</small>"
        f"{activities}<div style='margin-top:6px'>{link}</div></div>"
    )


def build_map(branches: pd.DataFrame) -> folium.Map:
    """A map of the branches that have coordinates."""
    located = branches[branches["has_location"].astype(bool)]
    fmap = folium.Map(
        location=NORWAY_CENTER,
        zoom_start=5,
        tiles=KARTVERKET_TOPO,
        attr=KARTVERKET_ATTRIBUTION,
        control_scale=True,
    )
    cluster = MarkerCluster().add_to(fmap)
    for _, row in located.iterrows():
        folium.CircleMarker(
            location=(row["latitude"], row["longitude"]),
            radius=7,
            color=MARKER_COLOR,
            fill=True,
            fill_opacity=0.85,
            tooltip=escape(str(row["branch"])),
            popup=folium.Popup(popup_html(row), max_width=320),
        ).add_to(cluster)
    if len(located) > 1:
        fmap.fit_bounds(
            [
                [located["latitude"].min(), located["longitude"].min()],
                [located["latitude"].max(), located["longitude"].max()],
            ]
        )
    return fmap
