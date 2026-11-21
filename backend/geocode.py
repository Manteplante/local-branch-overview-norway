"""Kartverket geocoding for branches the site gives no coordinates for.

    make geocode                                  # look up what isn't cached yet
    make geocode-retry                            # ... and the cached misses again
    uv run python -m backend.geocode --dry-run    # list the queries, no calls
    uv run python -m backend.geocode --prune      # also drop rows no branch uses

Uses Kartverket's free, keyless APIs (open data, "© Kartverket"), best first:
the branch's street address (adresser), else a place (stedsnavn): the branch name as a
settlement, the post town, the branch name as a municipality.
Results go to a committed cache (`config.GEOCODE_CACHE`); `make transform` reads only
the cache and never calls the network. See docs/missing-data-quality.md.
"""

from __future__ import annotations

import argparse
import os
import re
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, fields
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import requests

from local_branch_overview.scraper.client import USER_AGENT

from . import config

API_URL = "https://api.kartverket.no/stedsnavn/v1/navn"
ADDRESS_URL = "https://api.kartverket.no/adresser/v1/sok"
MIN_DELAY_SECONDS = 0.5  # no published rate limit; stay polite

FORMER_MUNICIPALITY = "Annen administrativ inndeling"  # Skedsmo, Voss, Os, ...

# Place types that stand for a settlement, best first. Churches, farms, fjords etc. are
# skipped: "Flatanger" alone only matches the church, "Heim" a farm.
PLACE_TYPES = [
    "By",
    "Tettsted",
    "Bydel",
    "Tettbebyggelse",
    "Kommune",
    "Bygdelag (bygd)",
    FORMER_MUNICIPALITY,
]
_TYPE_RANK = {t: i for i, t in enumerate(PLACE_TYPES)}

# Red Cross districts still use the pre-2024 county names; search the current county.
# Some districts reach past their old county: Rogaland covers Flekkefjord (Agder),
# Oppland Jevnaker and Lunner (now Akershus), Trøndelag Surnadal (Møre og Romsdal),
# Troms Longyearbyen (Svalbard).
COUNTY_NUMBERS: dict[str, tuple[str, ...]] = {
    "Agder": ("42",),
    "Akershus": ("32",),
    "Buskerud": ("33",),
    "Finnmark": ("56",),
    "Hedmark": ("34",),
    "Hordaland": ("46",),
    "Møre og Romsdal": ("15",),
    "Nordland": ("18",),
    "Oppland": ("34", "32"),
    "Oslo": ("03",),
    "Rogaland": ("11", "42"),
    "Sogn og Fjordane": ("46",),
    "Telemark": ("40",),
    "Troms": ("55", "21"),
    "Trøndelag": ("50", "15"),
    "Vestfold": ("39",),
    "Østfold": ("31",),
}


class GeocodeError(RuntimeError):
    """A failed request: stops the run; results fetched so far are kept."""


@dataclass(frozen=True)
class GeocodeResult:
    query: str
    status: str  # found | no_match
    method: str = ""  # address (house-level) | place (town / municipality centre)
    latitude: float | None = None
    longitude: float | None = None
    matched_name: str = ""
    place_type: str = ""  # By | Tettsted | Bydel | Tettbebyggelse | Kommune | ...
    municipality: str = ""
    fetched_at: str = ""

    @property
    def found(self) -> bool:
        return self.status == "found" and self.latitude is not None


@dataclass(frozen=True)
class Target:
    query: str  # cache key, e.g. "Bagn, Oppland"
    place: str  # "Bagn"
    county_numbers: tuple[str, ...] = ()  # ("34",); empty searches all of Norway
    address: str = ""  # as scraped: "Frøyas gate 6, 2270 FLISA"


@dataclass(frozen=True)
class Address:
    """The parts of a scraped address we can search on."""

    street: str = ""  # "Heimdalsgt." -- empty for a PO box
    number: str = ""  # "3"
    letter: str = ""  # "A"
    postcode: str = ""  # "2821"
    town: str = ""  # "GJØVIK"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _has_point(name: dict) -> bool:
    return bool(name.get("representasjonspunkt"))


def _best_settlement(names: list[dict]) -> dict | None:
    """The highest-ranked settlement; ties keep the API's order."""
    candidates = [
        n for n in names if n.get("navneobjekttype") in _TYPE_RANK and _has_point(n)
    ]
    return min(candidates, key=lambda n: _TYPE_RANK[n["navneobjekttype"]], default=None)


def _municipality(
    names: list[dict], place: str, *, exact_only: bool = False
) -> dict | None:
    """ "<place> kommune" exactly, else (unless `exact_only`) the only one ending in it.

    Current municipalities come before former ones. The exact name wins because
    "*Heim kommune" also matches Trondheim kommune; "*Eiker kommune" matches both Nedre
    and Øvre Eiker, so it is rejected.
    """
    municipalities = [
        n
        for kind in ("Kommune", FORMER_MUNICIPALITY)
        for n in names
        if n.get("navneobjekttype") == kind and _has_point(n)
    ]
    exact = f"{place} kommune".casefold()
    for n in municipalities:
        if n.get("skrivemåte", "").casefold() == exact:
            return n
    if exact_only:
        return None
    return municipalities[0] if len(municipalities) == 1 else None


# Words that only qualify a name: "Nedre Eiker" must not be searched as "Nedre".
_QUALIFIERS = {
    w.casefold()
    for w in [
        "Nedre",
        "Øvre",
        "Vestre",
        "Austre",
        "Østre",
        "Nord",
        "Sør",
        "Indre",
        "Ytre",
        "Midtre",
        "Store",
        "Lille",
    ]
}


def name_parts(place: str) -> list[str]:
    """The single places in a two-name branch, phrases before single words.

    "Høre/Vestre Slidre" -> ["Høre", "Vestre Slidre", "Slidre"];
    "Øyer Tretten" -> ["Øyer", "Tretten"]. The whole name itself is not included.
    """
    phrases = [p.strip() for p in re.split(r"\s+og\s+|/|-", place) if p.strip()]
    words = [w for p in phrases if " " in p for w in p.split()]
    parts = [
        p
        for p in phrases + words
        if p != place and p.casefold() not in _QUALIFIERS and p.casefold() != "og"
    ]
    return list(dict.fromkeys(parts))


# ── addresses ─────────────────────────────────────────────────────────────────

_POSTCODE = re.compile(r"(\d{4})\s+(.+)")
# Parts that are a PO box, a person or a label, never a street.
_NOT_STREET = re.compile(
    r"^(?:c/o|v/|boks\b|postboks\b|pb\b|besøksadresse)", re.IGNORECASE
)
# Trailing noise inside a street part: "Sagvn. 16 Postboks 149", "… 26 v/Elisabeth".
_STREET_TAIL = re.compile(r"\s+(?:v/|c/o|postboks\b|boks\b|pb\b).*$", re.IGNORECASE)
_STREET = re.compile(
    r"(?P<name>[^\d]*[^\d\s.])\.?\s*(?P<number>\d+)\s*(?P<letter>[A-Za-z])?\b"
)
# "Heimdalsgt." -> "Heimdals", "Torgeir Vraasplass" -> "Torgeir Vraas"
_STREET_SUFFIX = re.compile(
    r"\s*(?:veien|vegen|vei|veg|vn|v|gata|gaten|gate|gt|g|plass|pl)$", re.IGNORECASE
)


def parse_address(text: str) -> Address:
    """ "Heimdalsgt. 3, 2821 GJØVIK" -> Address("Heimdalsgt", "3", "", "2821", "GJØVIK").

    The post code part is the last "NNNN Town"; the street is the first other part with
    a house number that isn't a PO box, a "c/o" or the branch's own name.
    """
    parts = [" ".join(p.split()) for p in text.split(",")]
    parts = [p for p in parts if p]
    postcode = town = ""
    for i in range(len(parts) - 1, -1, -1):
        m = _POSTCODE.fullmatch(parts[i])
        if m:
            postcode, town = m.groups()
            del parts[i]
            break
    for part in parts:
        if _NOT_STREET.match(part) or "røde kors" in part.casefold():
            continue
        part = _STREET_TAIL.sub("", re.sub(r"\s*\(.*?\)", "", part))
        m = _STREET.match(part)
        if m:
            return Address(
                street=m["name"].strip(),
                number=str(int(m["number"])),
                letter=(m["letter"] or "").upper(),
                postcode=postcode,
                town=town,
            )
    return Address(postcode=postcode, town=town)


def street_pattern(street: str) -> str:
    """A wildcard that survives abbreviations: "Heimdalsgt" -> "Heimdals*"."""
    stem = _STREET_SUFFIX.sub("", street.rstrip(". "))
    return f"{stem if len(stem) >= 3 else street}*"


def town_names(town: str) -> list[str]:
    """ "SANDE I VESTFOLD" -> ["Sande I Vestfold", "Sande"]; "MO I RANA" keeps both."""
    full = town.strip().title()
    short = re.sub(r"\s+(?:i|på)\s+.*$", "", full, flags=re.IGNORECASE)
    return list(dict.fromkeys(n for n in (full, short) if n))


def _squash(name: str) -> str:
    return "".join(str(name).split()).casefold()


def _best_address(hits: list[dict], address: Address) -> dict | None:
    """The hit with the right house number on the right street.

    The wildcard search is loose ("Biri* 32" also returns Honnevegen 32), so a street
    must start with our stem; an exact street name beats the rest; and what is left
    must be one street.
    """
    stem = _squash(street_pattern(address.street).rstrip("*"))
    same = [
        h
        for h in hits
        if str(h.get("nummer")) == address.number
        and h.get("representasjonspunkt")
        and _squash(h.get("adressenavn", "")).startswith(stem)
    ]
    exact = [h for h in same if _squash(h["adressenavn"]) == _squash(address.street)]
    same = exact or same
    if address.letter:
        same = [
            h for h in same if (h.get("bokstav") or "").upper() == address.letter
        ] or same
    if not same or len({h.get("adressenavn") for h in same}) != 1:
        return None
    return min(same, key=lambda h: bool(h.get("bokstav")))  # "18" before "18A"


class KartverketGeocoder:
    """One branch target → one `GeocodeResult`, searched within its county."""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        timeout: float = 10,
    ) -> None:
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.sleep = sleep
        self.timeout = timeout

    def _get(self, url: str, params: dict, key: str) -> list[dict]:
        self.sleep(MIN_DELAY_SECONDS)
        params = {"utkoordsys": "4258", "treffPerSide": "10", **params}
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            items = response.json()[key]
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            raise GeocodeError(f"{params.get('sok')!r}: {exc}") from None
        return items if isinstance(items, list) else []

    def _search(self, text: str, county_numbers: tuple[str, ...]) -> list[dict]:
        params: dict = {"sok": text}
        if county_numbers:
            params["fnr"] = list(county_numbers)  # sent as fnr=11&fnr=42
        return self._get(API_URL, params, "navn")

    def _address(self, address: Address) -> dict | None:
        """The street address, searched in its post town, then by its post code
        (post codes change when municipalities merge; town names rarely do)."""
        if not address.street or not (address.town or address.postcode):
            return None
        sok = f"{street_pattern(address.street)} {address.number}"
        filters = [{"poststed": address.town}, {"postnummer": address.postcode}]
        for where in [f for f in filters if all(f.values())]:
            hit = _best_address(
                self._get(ADDRESS_URL, {"sok": sok, **where}, "adresser"), address
            )
            if hit:
                return hit
        return None

    def _settlement(self, name: str, county_numbers: tuple[str, ...]) -> dict | None:
        return _best_settlement(self._search(name, county_numbers))

    def _place(self, target: Target, address: Address) -> dict | None:
        """A place for the branch, best first:

        1. the branch name as a settlement, else one of its parts ("Øyer Tretten" ->
           Øyer; the popup shows the full name)
        2. the post town as a settlement (PO boxes: Lista -> Vanse); after the name, so
           "Arna og Åsane" (post town Bergen) stays at Arna
        3. the branch name as a municipality; a part only as its exact "<part> kommune",
           never the wildcard rule, so "Eiker" can't drift to Øvre Eiker
        """
        counties = target.county_numbers
        names = [target.place, *name_parts(target.place)]
        seen = {n.casefold() for n in names}
        towns = [t for t in town_names(address.town) if t.casefold() not in seen]
        for name in names + towns:
            if hit := self._settlement(name, counties):
                return hit
        if hit := _municipality(
            self._search(f"*{target.place} kommune", counties), target.place
        ):
            return hit
        for part in name_parts(target.place):
            found = self._search(f"{part} kommune", counties)
            if hit := _municipality(found, part, exact_only=True):
                return hit
        return None

    def _find(self, target: Target) -> dict | None:  # used by tests: place lookup only
        return self._place(target, parse_address(target.address))

    def geocode(self, target: Target) -> GeocodeResult:
        address = parse_address(target.address)
        if street := self._address(address):
            point = street["representasjonspunkt"]
            return GeocodeResult(
                query=target.query,
                status="found",
                method="address",
                latitude=float(point["lat"]),
                longitude=float(point["lon"]),
                matched_name=(
                    f"{street.get('adressetekst', '')}, "
                    f"{street.get('postnummer', '')} {street.get('poststed', '')}"
                ),
                place_type="Adresse",
                municipality=str(street.get("kommunenavn", "")).title(),
                fetched_at=_now(),
            )
        hit = self._place(target, address)
        if hit is not None:
            point = hit["representasjonspunkt"]
            municipalities = hit.get("kommuner") or [{}]
            return GeocodeResult(
                query=target.query,
                status="found",
                method="place",
                latitude=float(point["nord"]),
                longitude=float(point["øst"]),
                matched_name=hit.get("skrivemåte", ""),
                place_type=hit.get("navneobjekttype", ""),
                municipality=municipalities[0].get("kommunenavn", ""),
                fetched_at=_now(),
            )
        return GeocodeResult(query=target.query, status="no_match", fetched_at=_now())


# ── targets ───────────────────────────────────────────────────────────────────

# "Raude Kross" is the Nynorsk spelling; "Saltdal Omsorg" is the Saltdal branch.
_RED_CROSS = re.compile(
    r"\b(Røde Kors|Raude Kross|Hjelpekorps|Omsorg)\b( i)?", re.IGNORECASE
)
# "Trøndelag – Nord" -> "Trøndelag", "Rogaland med Flekkefjord by" -> "Rogaland"
_DISTRICT_SUFFIX = re.compile(r"\s+(–|med)\s+.*$")


def _strip(name: str) -> str:
    return " ".join(_RED_CROSS.sub(" ", name).split())


def branch_target(branch: str, district: str, address: str = "") -> Target:
    """ "Bagn Røde Kors" + "Oppland Røde Kors" -> Target("Bagn, Oppland", "Bagn", ("34",)).

    The cache key ends in " | <address>" when there is one, so a branch whose address
    changes on the site is looked up again.
    """
    place = _strip(branch)
    county = _strip(_DISTRICT_SUFFIX.sub("", district))
    address = " ".join(str(address or "").split())
    query = ", ".join([place] + ([county] if county and county != place else []))
    if address:
        query = f"{query} | {address}"
    return Target(
        query=query,
        place=place,
        county_numbers=COUNTY_NUMBERS.get(county, ()),
        address=address,
    )


def branch_query(branch: str, district: str, address: str = "") -> str:
    """The cache key for a branch: "Bagn, Oppland | Bagnsvegen 1, 2930 BAGN"."""
    return branch_target(branch, district, address).query


# ── cache ─────────────────────────────────────────────────────────────────────

CACHE_COLUMNS = [f.name for f in fields(GeocodeResult)]


def load_cache(path: Path | None = None) -> dict[str, GeocodeResult]:
    path = path or config.GEOCODE_CACHE
    if not path.exists():
        return {}
    df = pd.read_csv(path, keep_default_na=False, dtype=str)
    cache = {}
    for row in df.to_dict("records"):
        values = {c: row.get(c, "") for c in CACHE_COLUMNS}
        for c in ("latitude", "longitude"):
            values[c] = float(values[c]) if values[c] else None
        cache[values["query"]] = GeocodeResult(**values)
    return cache


def save_cache(cache: dict[str, GeocodeResult], path: Path | None = None) -> None:
    """Sorted by query so diffs stay readable; written atomically."""
    path = path or config.GEOCODE_CACHE
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [asdict(cache[q]) for q in sorted(cache)]
    df = pd.DataFrame(rows, columns=CACHE_COLUMNS)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".csv.tmp")
    os.close(fd)
    try:
        df.to_csv(tmp, index=False, encoding="utf-8")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


# ── run ───────────────────────────────────────────────────────────────────────


@dataclass
class Summary:
    found: int = 0
    no_match: int = 0
    cached: int = 0


def _uncached(
    targets: list[Target],
    cache: dict[str, GeocodeResult],
    *,
    retry_misses: bool = False,
) -> list[Target]:
    """Targets to look up: not cached, or (with `retry_misses`) cached as no match."""
    unique = {t.query: t for t in targets}
    return [
        t
        for q, t in unique.items()
        if q not in cache or (retry_misses and not cache[q].found)
    ]


def geocode_missing(
    targets: list[Target],
    geocoder: KartverketGeocoder,
    cache: dict[str, GeocodeResult],
    *,
    retry_misses: bool = False,
    log: Callable[[str], None] = print,
) -> Summary:
    """Look up the targets that aren't cached yet; results are added to `cache`."""
    todo = _uncached(targets, cache, retry_misses=retry_misses)
    summary = Summary(cached=len({t.query for t in targets}) - len(todo))
    for i, target in enumerate(todo, 1):
        result = geocoder.geocode(target)
        cache[target.query] = result
        if result.found:
            summary.found += 1
            log(
                f"  [{i}/{len(todo)}] ✓ {target.query} → {result.matched_name} "
                f"({result.place_type}, {result.municipality})"
            )
        else:
            summary.no_match += 1
            log(f"  [{i}/{len(todo)}] ✗ {target.query}: no match")
    return summary


def missing_targets() -> list[Target]:
    """Targets for every branch the scraped data has no coordinates for."""
    from . import transform  # transform imports this module

    raw = transform.read_raw()
    if raw.empty:
        return []
    branches = transform.build_branches(transform.build_activities(raw))
    missing = branches[~branches["has_location"]]
    return [
        branch_target(b, d, a)
        for b, d, a in zip(missing.branch, missing.district, missing.address)
    ]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="list queries, no calls")
    parser.add_argument(
        "--prune",
        action="store_true",
        help="delete cache rows that no branch without coordinates uses any more",
    )
    parser.add_argument(
        "--retry-misses",
        action="store_true",
        help="look up cached 'no match' branches again (found ones are kept)",
    )
    args = parser.parse_args(argv)

    targets = missing_targets()
    cache = load_cache()
    todo = _uncached(targets, cache, retry_misses=args.retry_misses)
    unused = sorted(set(cache) - {t.query for t in targets})
    print(
        f"[geocode] {len(targets)} branches without coordinates in {config.RAW_DIR}, "
        f"{len(todo)} to look up, {len(unused)} unused cache rows"
        + ("" if args.prune or not unused else " (--prune deletes them)")
    )
    if args.dry_run:
        for target in todo:
            print(
                f"  {target.query}  (county {', '.join(target.county_numbers) or 'any'})"
            )
        return
    if args.prune and unused:
        for query in unused:
            del cache[query]
        save_cache(cache)
        print(f"[geocode] Pruned {len(unused)} unused rows")
    if not todo:
        print("[geocode] Nothing to do.")
        return

    try:
        summary = geocode_missing(
            targets, KartverketGeocoder(), cache, retry_misses=args.retry_misses
        )
    except GeocodeError as exc:
        raise SystemExit(
            f"[geocode] Stopped: {exc}. Results so far are saved; rerun to resume."
        ) from None
    finally:
        save_cache(cache)
    print(
        f"[geocode] {summary.found} found, {summary.no_match} no match, "
        f"{summary.cached} already cached · cache: {config.GEOCODE_CACHE}"
    )


if __name__ == "__main__":
    main()
