"""The folium map: Kartverket topo tiles, clustered markers and an activity panel.

Markers and the panel are drawn by a small script inside the map (see `_SCRIPT`), so
hovering is instant and needs no Streamlit rerun:

- markers sit on a canvas with a wide hit tolerance, so they are easy to hover and tap;
- hovering a marker shows the branch and its activities in a panel at the top left;
  clicking pins it there (× or a click on empty map unpins);
- clusters break up into single markers from about city zoom.

Branch data is embedded as JSON with `<`, `>` and `&` escaped, and the script only ever
sets `textContent`, so scraped text can't inject HTML or script.
"""

from __future__ import annotations

import json
from collections.abc import Iterable

import folium
import pandas as pd
from branca.element import MacroElement, Template
from folium.plugins import MarkerCluster

KARTVERKET_TOPO = (
    "https://cache.kartverket.no/v1/wmts/1.0.0/topo/default/webmercator/{z}/{y}/{x}.png"
)
KARTVERKET_ATTRIBUTION = '&copy; <a href="https://www.kartverket.no/">Kartverket</a>'
NORWAY_CENTER = (64.5, 13.0)
MARKER_COLOR = "#C8102E"
EXCERPT_CHARS = 160
SVALBARD_LAT = 74.0  # north of mainland Norway (71.2°)
CLUSTER_OPTIONS = {
    "disableClusteringAtZoom": 10,  # single, hoverable markers from about city zoom
    "maxClusterRadius": 45,
    "showCoverageOnHover": False,
    "spiderfyOnMaxZoom": False,
}
BRANCH_KEY = ["district_slug", "branch_slug"]


def excerpt(text: str, limit: int = EXCERPT_CHARS) -> str:
    """The first `limit` characters, cut at a word boundary, with "…" if shortened."""
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" ,.;:-–")
    return f"{cut}…"


def _activity_groups(rows: pd.DataFrame, highlight: set[str]) -> list[dict]:
    named = rows[rows["activity"].fillna("") != ""]
    groups = []
    for category, group in named.groupby("category", sort=False):
        items = [
            {"name": str(a), "text": excerpt(d)}
            for a, d in sorted(
                zip(group["activity"], group["description"].fillna("")),
                key=lambda pair: str(pair[0]).casefold(),
            )
        ]
        groups.append(
            {
                "category": str(category),
                "highlight": category in highlight,
                "items": items,
            }
        )
    # Categories picked in the sidebar first, then alphabetical.
    return sorted(groups, key=lambda g: (not g["highlight"], g["category"].casefold()))


def branch_payloads(
    branches: pd.DataFrame,
    activities: pd.DataFrame | None = None,
    highlight: Iterable[str] = (),
) -> list[dict]:
    """One dict per branch *with a location*, as the map script expects it."""
    located = branches[branches["has_location"].astype(bool)]
    highlight = set(highlight)
    by_branch = (
        dict(iter(activities.groupby(BRANCH_KEY, sort=False)))
        if activities is not None and not activities.empty
        else {}
    )
    empty = pd.DataFrame(columns=["category", "activity", "description"])
    payloads = []
    for _, row in located.iterrows():
        rows = by_branch.get((row["district_slug"], row["branch_slug"]), empty)
        payloads.append(
            {
                "lat": float(row["latitude"]),
                "lon": float(row["longitude"]),
                "name": str(row["branch"]),
                "district": str(row.get("district") or ""),
                "address": str(row.get("address") or ""),
                "url": str(row.get("branch_url") or ""),
                "approximate": row.get("location_source") == "place",
                "groups": _activity_groups(rows, highlight),
            }
        )
    return payloads


def _script_json(value) -> str:
    """JSON that is safe inside a <script> element."""
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    for char, code in (
        ("<", "\\u003c"),
        (">", "\\u003e"),
        ("&", "\\u0026"),
        (" ", "\\u2028"),
        (" ", "\\u2029"),
    ):
        text = text.replace(char, code)
    return text


_STYLE = """
.lbo-panel {
  background: #fff; color: #1F2933; width: min(320px, 75vw); overflow-y: auto;
  padding: 10px 12px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,.25);
  font: 13px/1.4 system-ui, -apple-system, "Segoe UI", sans-serif;
}
.lbo-hint { color: #52606D; }
.lbo-head { display: flex; align-items: flex-start; gap: 8px; }
.lbo-head h3 { margin: 0; font-size: 15px; line-height: 1.3; flex: 1; color: #C8102E; }
.lbo-close {
  border: 0; background: none; font-size: 18px; line-height: 1; cursor: pointer;
  color: #52606D; padding: 0 2px;
}
.lbo-meta { color: #52606D; margin-top: 2px; }
.lbo-approx {
  margin-top: 4px; font-size: 12px; color: #7B4B00; background: #FFF4E0;
  border-radius: 4px; padding: 1px 6px; display: inline-block;
}
.lbo-count { margin: 8px 0 4px; font-weight: 600; }
.lbo-cat {
  margin: 8px 0 2px; font-size: 12px; font-weight: 700; text-transform: uppercase;
  letter-spacing: .03em; color: #52606D;
}
.lbo-cat.lbo-hl { color: #C8102E; }
.lbo-panel ul { margin: 0; padding-left: 16px; }
.lbo-panel li { margin: 2px 0 6px; }
.lbo-panel li span { display: block; color: #3E4C59; }
.lbo-link { display: inline-block; margin-top: 8px; color: #C8102E; font-weight: 600; }
"""

_SCRIPT = """
(function () {
  var map = {{ this.map_name }};
  var cluster = {{ this.cluster_name }};
  var branches = {{ this.data }};
  var COLOR = {{ this.color }};
  var BASE = {radius: 8, color: "#ffffff", weight: 1.5, fillColor: COLOR, fillOpacity: 0.9};
  var renderer = L.canvas({tolerance: 8});
  var pinned = null, hovered = null;

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = text;
    return e;
  }

  var Panel = L.Control.extend({
    options: {position: "topleft"},
    onAdd: function () {
      var box = L.DomUtil.create("div", "lbo-panel");
      L.DomEvent.disableClickPropagation(box);
      L.DomEvent.disableScrollPropagation(box);
      return box;
    }
  });
  var box = new Panel().addTo(map).getContainer();
  function fit() { box.style.maxHeight = Math.max(map.getSize().y - 160, 120) + "px"; }
  map.on("resize", fit); fit();

  function hint() {
    box.replaceChildren(el("div", "lbo-hint",
      "Hover over a branch to see its activities \\u00b7 click to keep it open"));
  }

  function show(b) {
    box.replaceChildren();
    var head = el("div", "lbo-head");
    head.appendChild(el("h3", null, b.name));
    if (pinned && pinned.branch === b) {
      var close = el("button", "lbo-close", "\\u00d7");
      close.title = "Close";
      close.onclick = unpin;
      head.appendChild(close);
    }
    box.appendChild(head);
    var meta = [b.district, b.address].filter(Boolean).join(" \\u00b7 ");
    if (meta) box.appendChild(el("div", "lbo-meta", meta));
    if (b.approximate) {
      box.appendChild(el("div", "lbo-approx", "Approximate location (town centre)"));
    }
    var n = b.groups.reduce(function (s, g) { return s + g.items.length; }, 0);
    box.appendChild(el("div", "lbo-count",
      n ? n + (n === 1 ? " activity" : " activities") : "No activities listed"));
    b.groups.forEach(function (g) {
      box.appendChild(el("div", "lbo-cat" + (g.highlight ? " lbo-hl" : ""), g.category));
      var ul = el("ul");
      g.items.forEach(function (a) {
        var li = el("li");
        li.appendChild(el("strong", null, a.name));
        if (a.text) li.appendChild(el("span", null, a.text));
        ul.appendChild(li);
      });
      box.appendChild(ul);
    });
    if (b.url.indexOf("https://www.rodekors.no/") === 0) {
      var link = el("a", "lbo-link", "Read more on rodekors.no \\u2197");
      link.href = b.url; link.target = "_blank"; link.rel = "noopener";
      box.appendChild(link);
    }
    box.scrollTop = 0;
  }

  function paint(m) {
    var on = m === pinned || m === hovered;
    m.setStyle(on ? {color: m === pinned ? "#1F2933" : "#7A0019", weight: 3} : BASE);
    m.setRadius(on ? 11 : BASE.radius);
    if (on) m.bringToFront();
  }

  function unpin() {
    var old = pinned;
    pinned = null;
    if (old) paint(old);
    hint();
  }

  branches.forEach(function (b) {
    var m = L.circleMarker([b.lat, b.lon], L.extend({renderer: renderer}, BASE));
    m.branch = b;
    m.on("mouseover", function () { hovered = m; paint(m); show(b); });
    m.on("mouseout", function () {
      hovered = null; paint(m);
      if (pinned) show(pinned.branch); else hint();
    });
    m.on("click", function (e) {
      L.DomEvent.stopPropagation(e);
      var old = pinned;
      pinned = m;
      if (old && old !== m) paint(old);
      paint(m); show(b);
    });
    cluster.addLayer(m);
  });
  map.on("click", unpin);
  hint();
})();
"""


class _BranchLayer(MacroElement):
    """Markers + panel, rendered after the cluster it fills."""

    _template = Template(
        "{% macro header(this, kwargs) %}<style>"
        + _STYLE
        + "</style>{% endmacro %}"
        + "{% macro script(this, kwargs) %}"
        + _SCRIPT
        + "{% endmacro %}"
    )

    def __init__(self, fmap: folium.Map, cluster: MarkerCluster, payloads: list[dict]):
        super().__init__()
        self._name = "BranchLayer"
        self.map_name = fmap.get_name()
        self.cluster_name = cluster.get_name()
        self.data = _script_json(payloads)
        self.color = json.dumps(MARKER_COLOR)


def build_map(
    branches: pd.DataFrame,
    activities: pd.DataFrame | None = None,
    highlight: Iterable[str] = (),
) -> folium.Map:
    """A map of the branches that have coordinates, with the activity panel."""
    payloads = branch_payloads(branches, activities, highlight)
    fmap = folium.Map(
        location=NORWAY_CENTER,
        zoom_start=5,
        tiles=KARTVERKET_TOPO,
        attr=KARTVERKET_ATTRIBUTION,
        control_scale=True,
    )
    cluster = MarkerCluster(**CLUSTER_OPTIONS).add_to(fmap)
    _BranchLayer(fmap, cluster, payloads).add_to(fmap)
    # Open on the mainland: Longyearbyen (Svalbard) would shrink Norway to a sliver.
    # Its marker is still there when you pan north.
    mainland = [p for p in payloads if p["lat"] < SVALBARD_LAT] or payloads
    if len(mainland) > 1:
        lats = [p["lat"] for p in mainland]
        lons = [p["lon"] for p in mainland]
        fmap.fit_bounds([[min(lats), min(lons)], [max(lats), max(lons)]])
    return fmap
