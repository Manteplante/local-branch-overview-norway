"""Pure HTML parsers for rodekors.no local-branch pages. No network access here."""

import json
import re
from dataclasses import dataclass
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

BASE_URL = "https://www.rodekors.no"
DISTRICTS_URL = f"{BASE_URL}/lokalforeninger/"
# Branches title the section differently ("Tilbud og aktiviteter", "Aktiviteter", ...).
ACTIVITIES_HEADING = re.compile(r"aktivitet|tilbud", re.IGNORECASE)

_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class District:
    name: str
    slug: str
    url: str


@dataclass(frozen=True)
class Branch:
    name: str
    slug: str
    url: str


@dataclass(frozen=True)
class Activity:
    name: str
    description: str


@dataclass(frozen=True)
class BranchDetails:
    address: str
    latitude: float | None
    longitude: float | None
    activities: list[Activity]


def _clean(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def _slug(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1]


def parse_districts(html: str) -> list[District]:
    """Districts listed on /lokalforeninger/ (one `h2 > a` per district)."""
    soup = BeautifulSoup(html, "html.parser")
    districts = []
    for link in soup.select('h2 > a[href^="/lokalforeninger/"]'):
        url = urljoin(BASE_URL, link["href"])
        districts.append(
            District(name=_clean(link.get_text()), slug=_slug(url), url=url)
        )
    return districts


def parse_branches(html: str) -> list[Branch]:
    """Local branches listed on a district page."""
    soup = BeautifulSoup(html, "html.parser")
    branches = []
    for link in soup.select("h3.article-teaser__heading > a[href]"):
        url = urljoin(BASE_URL, link["href"])
        branches.append(Branch(name=_clean(link.get_text()), slug=_slug(url), url=url))
    return branches


def _address(soup: BeautifulSoup) -> str:
    dt = soup.find("dt", string=lambda s: s is not None and s.strip() == "Adresse")
    dd = dt.find_next_sibling("dd") if dt else None
    address = _clean(dd.get_text()) if dd else ""
    return "" if address == "-" else address


def _coordinates(soup: BeautifulSoup) -> tuple[float | None, float | None]:
    """The branch map's marker: data-marker='["lat", "lng", "address", zoom]'."""
    marker = soup.find(attrs={"data-marker": True})
    if marker is None:
        return None, None
    try:
        lat, lng = json.loads(marker["data-marker"])[:2]
        return float(lat), float(lng)
    except (ValueError, TypeError):
        return None, None


def _activities(soup: BeautifulSoup) -> list[Activity]:
    heading = soup.find(
        "h2",
        class_="expander__title",
        string=ACTIVITIES_HEADING,
    )
    expander = heading.find_next("div", class_="expander") if heading else None
    if not isinstance(expander, Tag):
        return []

    activities = []
    for item in expander.find_all("div", class_="expander__item", recursive=False):
        head = item.select_one(":scope > .expander__inner > .expander__head")
        body = item.select_one(":scope > .expander__inner > .expander__body")
        if head is None:
            continue
        description = ""
        if body is not None:
            for figure in body.find_all("figure"):
                figure.decompose()
            description = _clean(body.get_text(" "))
        activities.append(
            Activity(name=_clean(head.get_text()), description=description)
        )
    return activities


def parse_branch_page(html: str) -> BranchDetails:
    """Address, map coordinates and activities of one local branch."""
    soup = BeautifulSoup(html, "html.parser")
    latitude, longitude = _coordinates(soup)
    return BranchDetails(
        address=_address(soup),
        latitude=latitude,
        longitude=longitude,
        activities=_activities(soup),
    )
