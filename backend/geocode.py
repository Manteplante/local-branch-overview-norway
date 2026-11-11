"""Google geocoding for branches the site gives no coordinates for.

    make geocode                                  # refuses: billable, needs the flag
    GOOGLE_GEOCODING_CONFIRM=1 make geocode       # look up what isn't cached yet
    uv run python -m backend.geocode --dry-run    # list the queries, no calls

Results go to a committed cache (`config.GEOCODE_CACHE`); `make transform` reads only
the cache and never calls the network. See docs/missing-data-quality.md.

Spend guards: the key alone does nothing (GOOGLE_GEOCODING_CONFIRM=1 is also needed),
MAX_GEOCODE_REQUESTS caps calls per run, and cached queries (misses too) cost 0.
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

API_URL = "https://maps.googleapis.com/maps/api/geocode/json"
MIN_DELAY_SECONDS = 0.2
PRICE_PER_1000_USD = 5.0  # after 10,000 free calls/month (2026)


class GeocodeError(RuntimeError):
    """A failed lookup. Its message never contains the API key."""


class QuotaExceeded(GeocodeError):
    """Google said OVER_QUERY_LIMIT / OVER_DAILY_LIMIT: stop the run, keep the results."""


@dataclass(frozen=True)
class GeocodeResult:
    query: str
    status: str  # OK | ZERO_RESULTS
    latitude: float | None = None
    longitude: float | None = None
    formatted_address: str = ""
    location_type: str = (
        ""  # ROOFTOP | RANGE_INTERPOLATED | GEOMETRIC_CENTER | APPROXIMATE
    )
    fetched_at: str = ""

    @property
    def found(self) -> bool:
        return self.status == "OK" and self.latitude is not None


class GoogleGeocoder:
    """One query → one `GeocodeResult`, restricted to Norway."""

    def __init__(
        self,
        api_key: str,
        *,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        timeout: float = 10,
    ) -> None:
        if not api_key:
            raise GeocodeError("GOOGLE_API_TOKEN is not set.")
        self._key = api_key
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.sleep = sleep
        self.timeout = timeout

    def _redact(self, text: str) -> str:
        return text.replace(self._key, "***")

    def geocode(self, query: str) -> GeocodeResult:
        self.sleep(MIN_DELAY_SECONDS)
        params = {
            "address": query,
            "region": "no",
            "components": "country:NO",
            "language": "no",
            "key": self._key,
        }
        try:
            response = self.session.get(API_URL, params=params, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            # requests puts the full URL, key included, in its messages.
            raise GeocodeError(self._redact(f"{query!r}: {exc}")) from None

        status = payload.get("status", "")
        now = datetime.now(UTC).isoformat(timespec="seconds")
        if status == "ZERO_RESULTS":
            return GeocodeResult(query=query, status=status, fetched_at=now)
        if status in {"OVER_QUERY_LIMIT", "OVER_DAILY_LIMIT"}:
            raise QuotaExceeded(f"{status}: {payload.get('error_message', '')}")
        if status != "OK" or not payload.get("results"):
            message = self._redact(payload.get("error_message", ""))
            raise GeocodeError(f"{query!r}: {status} {message}".strip())

        best = payload["results"][0]
        geometry = best["geometry"]
        return GeocodeResult(
            query=query,
            status=status,
            latitude=float(geometry["location"]["lat"]),
            longitude=float(geometry["location"]["lng"]),
            formatted_address=best.get("formatted_address", ""),
            location_type=geometry.get("location_type", ""),
            fetched_at=now,
        )


# ── queries ───────────────────────────────────────────────────────────────────

_RED_CROSS = re.compile(r"\b(Røde Kors|Hjelpekorps)\b( i)?", re.IGNORECASE)
# "Trøndelag – Nord" -> "Trøndelag", "Rogaland med Flekkefjord by" -> "Rogaland"
_DISTRICT_SUFFIX = re.compile(r"\s+(–|med)\s+.*$")


def _strip(name: str) -> str:
    return " ".join(_RED_CROSS.sub(" ", name).split())


def branch_query(branch: str, district: str) -> str:
    """ "Bagn Røde Kors" + "Oppland Røde Kors" -> "Bagn, Oppland, Norway"."""
    place = _strip(branch)
    county = _strip(_DISTRICT_SUFFIX.sub("", district))
    parts = [place] + ([county] if county and county != place else []) + ["Norway"]
    return ", ".join(parts)


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
    left: int = 0  # not looked up: request cap reached or quota exceeded


def geocode_missing(
    queries: list[str],
    geocoder: GoogleGeocoder,
    cache: dict[str, GeocodeResult],
    *,
    max_requests: int,
    log: Callable[[str], None] = print,
) -> Summary:
    """Look up the queries that aren't cached yet; results are added to `cache`."""
    summary = Summary()
    todo = [q for q in dict.fromkeys(queries) if q not in cache]
    summary.cached = len(set(queries)) - len(todo)
    for i, query in enumerate(todo, 1):
        if i > max_requests:
            summary.left = len(todo) - max_requests
            log(f"  request cap ({max_requests}) reached, {summary.left} left")
            break
        try:
            result = geocoder.geocode(query)
        except QuotaExceeded as exc:
            summary.left = len(todo) - i + 1
            log(f"  ✗ quota exceeded, stopping: {exc}")
            break
        cache[query] = result
        if result.found:
            summary.found += 1
            log(
                f"  [{i}/{len(todo)}] ✓ {query} → {result.formatted_address} "
                f"({result.location_type})"
            )
        else:
            summary.no_match += 1
            log(f"  [{i}/{len(todo)}] ✗ {query}: no match")
    return summary


def missing_queries() -> list[str]:
    """Queries for every branch the scraped data has no coordinates for."""
    from . import transform  # transform imports this module

    raw = transform.read_raw()
    if raw.empty:
        return []
    branches = transform.build_branches(transform.build_activities(raw))
    missing = branches[~branches["has_location"]]
    return [branch_query(b, d) for b, d in zip(missing.branch, missing.district)]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="list queries, no calls")
    args = parser.parse_args(argv)

    queries = missing_queries()
    cache = load_cache()
    todo = [q for q in dict.fromkeys(queries) if q not in cache]
    print(
        f"[geocode] {len(queries)} branches without coordinates in {config.RAW_DIR}, "
        f"{len(todo)} not cached yet"
    )
    if args.dry_run:
        for query in todo:
            print(f"  {query}")
        calls = min(len(todo), config.MAX_GEOCODE_REQUESTS)
        print(
            f"[geocode] dry run: would make {calls} calls "
            f"(≈ ${calls * PRICE_PER_1000_USD / 1000:.2f} past the free tier)"
        )
        return
    if not todo:
        print("[geocode] Nothing to do.")
        return
    if not config.GOOGLE_GEOCODING_CONFIRM:
        raise SystemExit(
            "[geocode] Billable: set GOOGLE_GEOCODING_CONFIRM=1 to call Google "
            "(try --dry-run first)."
        )

    geocoder = GoogleGeocoder(config.GOOGLE_API_TOKEN)
    try:
        summary = geocode_missing(
            queries, geocoder, cache, max_requests=config.MAX_GEOCODE_REQUESTS
        )
    finally:
        save_cache(cache)  # keep what we paid for, even if a call raised
    print(
        f"[geocode] {summary.found} found, {summary.no_match} no match, "
        f"{summary.cached} already cached, {summary.left} left · "
        f"cache: {config.GEOCODE_CACHE}"
    )


if __name__ == "__main__":
    main()
