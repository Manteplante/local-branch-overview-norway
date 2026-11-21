"""Kartverket place-name geocoding for branches the site gives no coordinates for.

    make geocode                                  # look up what isn't cached yet
    make geocode-retry                            # ... and the cached misses again
    uv run python -m backend.geocode --dry-run    # list the queries, no calls

Uses Kartverket's free, keyless place-name API (stedsnavn, open data, "© Kartverket").
A match is the centre of a town, village or municipality, not a street address.
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

    def _search(self, text: str, county_numbers: tuple[str, ...]) -> list[dict]:
        self.sleep(MIN_DELAY_SECONDS)
        params: dict = {"sok": text, "utkoordsys": "4258", "treffPerSide": "10"}
        if county_numbers:
            params["fnr"] = list(county_numbers)  # sent as fnr=11&fnr=42
        try:
            response = self.session.get(API_URL, params=params, timeout=self.timeout)
            response.raise_for_status()
            names = response.json()["navn"]
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            raise GeocodeError(f"{text!r}: {exc}") from None
        return names if isinstance(names, list) else []

    def _lookup(
        self, place: str, county_numbers: tuple[str, ...], *, strict: bool = False
    ) -> dict | None:
        """The place as a settlement, else as the municipality named after it.

        `strict` (for one part of a two-name branch) only accepts the exact
        "<place> kommune", never the wildcard "only one match" rule, so a part like
        "Eiker" can't drift to a neighbour.
        """
        hit = _best_settlement(self._search(place, county_numbers))
        if hit or strict:
            return hit or _municipality(
                self._search(f"{place} kommune", county_numbers), place, exact_only=True
            )
        return _municipality(self._search(f"*{place} kommune", county_numbers), place)

    def _find(self, target: Target) -> dict | None:
        """The whole name, else the first of its parts that matches: a two-name branch
        like "Øyer Tretten" is placed at one of them; the popup shows the full name."""
        hit = self._lookup(target.place, target.county_numbers)
        for part in name_parts(target.place):
            if hit:
                break
            hit = self._lookup(part, target.county_numbers, strict=True)
        return hit

    def geocode(self, target: Target) -> GeocodeResult:
        hit = self._find(target)
        if hit is not None:
            point = hit["representasjonspunkt"]
            municipalities = hit.get("kommuner") or [{}]
            return GeocodeResult(
                query=target.query,
                status="found",
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


def branch_target(branch: str, district: str) -> Target:
    """ "Bagn Røde Kors" + "Oppland Røde Kors" -> Target("Bagn, Oppland", "Bagn", ("34",))."""
    place = _strip(branch)
    county = _strip(_DISTRICT_SUFFIX.sub("", district))
    query = ", ".join([place] + ([county] if county and county != place else []))
    return Target(
        query=query, place=place, county_numbers=COUNTY_NUMBERS.get(county, ())
    )


def branch_query(branch: str, district: str) -> str:
    """The cache key for a branch: "Bagn, Oppland"."""
    return branch_target(branch, district).query


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
    return [branch_target(b, d) for b, d in zip(missing.branch, missing.district)]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="list queries, no calls")
    parser.add_argument(
        "--retry-misses",
        action="store_true",
        help="look up cached 'no match' branches again (found ones are kept)",
    )
    args = parser.parse_args(argv)

    targets = missing_targets()
    cache = load_cache()
    todo = _uncached(targets, cache, retry_misses=args.retry_misses)
    print(
        f"[geocode] {len(targets)} branches without coordinates in {config.RAW_DIR}, "
        f"{len(todo)} to look up"
    )
    if args.dry_run:
        for target in todo:
            print(
                f"  {target.query}  (county {', '.join(target.county_numbers) or 'any'})"
            )
        return
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
