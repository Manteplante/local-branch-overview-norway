"""Pure HTML parsers for rodekors.no local-branch pages. No network access here."""

import json
import re
from dataclasses import dataclass
from urllib.parse import urljoin

from bs4 import BeautifulSoup

BASE_URL = "https://www.rodekors.no"
DISTRICTS_URL = f"{BASE_URL}/lokalforeninger/"
# Expander sections that hold info about the branch itself, not activities.
NON_ACTIVITY_SECTIONS = re.compile(
    r"nyttig informasjon|velkommen|^om oss$", re.IGNORECASE
)
# Districts whose branch list lives on a subpage instead of the district page.
BRANCH_INDEX_PATHS = {"trondelag": "finn-fram/"}
# Branch pages are exactly two levels deep: /lokalforeninger/<district>/<branch>/.
_BRANCH_HREF = re.compile(r"^/lokalforeninger/[^/]+/[^/]+/$")

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
    group: str = ""  # sub-region heading on the index page, e.g. "Nord" in Trøndelag


@dataclass(frozen=True)
class Activity:
    section: str
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


_ASCII = str.maketrans({"æ": "ae", "ø": "o", "å": "a"})


def _slugify(text: str) -> str:
    """ASCII slug in the site's own style: "Sør" -> "sor", "Møre og Romsdal" -> "more-og-romsdal"."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower().translate(_ASCII)).strip("-")


def _group(link) -> str:
    """Heading of the navigation group a link sits in ("NORD" -> "Nord"), else ""."""
    if "navigation-item__link" not in link.get("class", []):
        return ""
    heading = link.find_previous("h2", class_="navigation-block__top__header")
    text = _clean(heading.get_text()) if heading else ""
    return "" if text.lower() == "innhold" else text.capitalize()


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


def branch_index_url(district: District) -> str:
    """The page that lists a district's branches (usually the district page itself)."""
    return urljoin(district.url, BRANCH_INDEX_PATHS.get(district.slug, ""))


def parse_branches(html: str) -> list[Branch]:
    """Local branches listed on a district's branch index page.

    Districts use one of three layouts: teaser cards (`h3.article-teaser__heading`), a plain
    list of `h2 > a`, or a navigation menu (`a.navigation-item__link`, Trøndelag).
    """
    soup = BeautifulSoup(html, "html.parser")
    links = soup.select(
        "h3.article-teaser__heading > a[href], h2 > a[href], a.navigation-item__link[href]"
    )
    branches: dict[str, Branch] = {}
    for link in links:
        if not _BRANCH_HREF.match(link["href"]):
            continue
        url = urljoin(BASE_URL, link["href"])
        branches.setdefault(
            url,
            Branch(
                name=_clean(link.get_text()),
                slug=_slug(url),
                url=url,
                group=_group(link),
            ),
        )
    return list(branches.values())


def split_by_group(
    district: District, branches: list[Branch]
) -> list[tuple[District, list[Branch]]]:
    """One district per branch group, e.g. Trøndelag -> trondelag-nord and trondelag-sor.

    Districts without groups come back unchanged, as a single pair.
    """
    if not any(b.group for b in branches):
        return [(district, branches)]
    groups: dict[str, list[Branch]] = {}
    for branch in branches:
        groups.setdefault(branch.group, []).append(branch)
    return [
        (
            District(
                name=f"{district.name} – {group}" if group else district.name,
                slug=f"{district.slug}-{_slugify(group)}" if group else district.slug,
                url=district.url,
            ),
            members,
        )
        for group, members in groups.items()
    ]


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
    """Every expander item, tagged with its section heading (pages group them freely)."""
    activities = []
    for expander in soup.select("div.expander"):
        if expander.find_parent("div", class_="expander"):
            continue  # nested inside another activity's text
        heading = expander.find_previous("h2", class_="expander__title")
        section = _clean(heading.get_text()).rstrip(":") if heading else ""
        if NON_ACTIVITY_SECTIONS.search(section):
            continue
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
                Activity(
                    section=section,
                    name=_clean(head.get_text()),
                    description=description,
                )
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
