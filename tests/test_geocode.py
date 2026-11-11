"""Google geocoding with a fake session: no test touches the network or the real key."""

from pathlib import Path

import pytest
import requests

from backend import config, geocode
from backend.geocode import (
    GeocodeError,
    GeocodeResult,
    GoogleGeocoder,
    QuotaExceeded,
    branch_query,
    geocode_missing,
    load_cache,
    save_cache,
)

KEY = "AIza-test-key-123"


def ok(lat: float = 61.0, lng: float = 9.1, address: str = "Bagn, Norge") -> dict:
    return {
        "status": "OK",
        "results": [
            {
                "formatted_address": address,
                "geometry": {
                    "location": {"lat": lat, "lng": lng},
                    "location_type": "APPROXIMATE",
                },
            }
        ],
    }


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} for url: ...&key={KEY}")

    def json(self) -> dict:
        return self.payload


class FakeSession(requests.Session):
    """Answers with queued payloads and records the params of each call."""

    def __init__(self, *responses: FakeResponse | Exception) -> None:
        super().__init__()
        self.responses = list(responses)
        self.calls: list[dict] = []

    def get(self, url, params=None, **kwargs):  # type: ignore[override]
        self.calls.append(params)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def geocoder(*responses: FakeResponse | Exception) -> GoogleGeocoder:
    return GoogleGeocoder(KEY, session=FakeSession(*responses), sleep=lambda _: None)


def test_ok_result_is_parsed_and_restricted_to_norway() -> None:
    g = geocoder(FakeResponse(ok()))

    result = g.geocode("Bagn, Oppland, Norway")

    assert result.found
    assert (result.latitude, result.longitude) == (61.0, 9.1)
    assert result.formatted_address == "Bagn, Norge"
    assert result.location_type == "APPROXIMATE"
    params = g.session.calls[0]
    assert params["components"] == "country:NO" and params["key"] == KEY


def test_zero_results_is_a_miss_not_an_error() -> None:
    result = geocoder(FakeResponse({"status": "ZERO_RESULTS", "results": []})).geocode(
        "Nowhere, Norway"
    )
    assert result.status == "ZERO_RESULTS" and not result.found


@pytest.mark.parametrize(
    "response",
    [
        FakeResponse({"status": "REQUEST_DENIED", "error_message": f"bad key {KEY}"}),
        FakeResponse({}, status_code=403),
        requests.ConnectionError(f"failed: https://maps.googleapis.com/?key={KEY}"),
    ],
)
def test_errors_never_contain_the_key(response) -> None:
    with pytest.raises(GeocodeError) as exc:
        geocoder(response).geocode("Bagn, Oppland, Norway")
    assert KEY not in str(exc.value)
    assert exc.value.__cause__ is None  # the original (with the key) is not chained


def test_missing_key_is_rejected() -> None:
    with pytest.raises(GeocodeError, match="GOOGLE_API_TOKEN"):
        GoogleGeocoder("")


def test_cap_stops_and_keeps_results() -> None:
    g = geocoder(FakeResponse(ok()), FakeResponse(ok()))
    cache: dict[str, GeocodeResult] = {}

    summary = geocode_missing(["a", "b", "c"], g, cache, max_requests=2, log=str)

    assert sorted(cache) == ["a", "b"]
    assert (summary.found, summary.left) == (2, 1)


def test_cached_queries_are_not_requested_again() -> None:
    g = geocoder(FakeResponse(ok()))
    cache = {"a": GeocodeResult(query="a", status="ZERO_RESULTS")}

    summary = geocode_missing(["a", "a", "b"], g, cache, max_requests=10, log=str)

    assert [c["address"] for c in g.session.calls] == ["b"]
    assert (summary.cached, summary.found) == (1, 1)


def test_quota_exceeded_stops_the_run() -> None:
    g = geocoder(FakeResponse(ok()), FakeResponse({"status": "OVER_QUERY_LIMIT"}))
    cache: dict[str, GeocodeResult] = {}

    summary = geocode_missing(["a", "b", "c"], g, cache, max_requests=10, log=str)

    assert list(cache) == ["a"] and summary.left == 2
    with pytest.raises(QuotaExceeded):
        geocoder(FakeResponse({"status": "OVER_DAILY_LIMIT"})).geocode("x")


def test_cache_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "cache.csv"
    cache = {
        "b": GeocodeResult(query="b", status="ZERO_RESULTS", fetched_at="t"),
        "a": GeocodeResult(query="a", status="OK", latitude=1.5, longitude=2.5),
    }

    save_cache(cache, path)

    assert load_cache(path) == cache
    assert path.read_text().splitlines()[1].startswith("a,")  # sorted by query
    assert load_cache(tmp_path / "missing.csv") == {}


@pytest.mark.parametrize(
    ("branch", "district", "query"),
    [
        ("Bagn Røde Kors", "Oppland Røde Kors", "Bagn, Oppland, Norway"),
        ("Flatanger", "Røde Kors i Trøndelag – Nord", "Flatanger, Trøndelag, Norway"),
        ("Oslo Røde Kors", "Oslo Røde Kors", "Oslo, Norway"),
        (
            "Bryne Røde Kors",
            "Rogaland Røde Kors med Flekkefjord by",
            "Bryne, Rogaland, Norway",
        ),
        (
            "Brumunddal Røde Kors Hjelpekorps",
            "Hedmark Røde Kors",
            "Brumunddal, Hedmark, Norway",
        ),
        (
            "Arna og Åsane Røde Kors",
            "Hordaland Røde Kors",
            "Arna og Åsane, Hordaland, Norway",
        ),
    ],
)
def test_branch_query(branch: str, district: str, query: str) -> None:
    assert branch_query(branch, district) == query


def test_main_refuses_without_confirm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(geocode, "missing_queries", lambda: ["Bagn, Oppland, Norway"])
    monkeypatch.setattr(config, "GEOCODE_CACHE", tmp_path / "cache.csv")
    monkeypatch.setattr(config, "GOOGLE_GEOCODING_CONFIRM", False)
    monkeypatch.setattr(config, "GOOGLE_API_TOKEN", KEY)

    with pytest.raises(SystemExit, match="GOOGLE_GEOCODING_CONFIRM=1"):
        geocode.main([])
    geocode.main(["--dry-run"])  # fine without the flag, makes no calls
    assert not (tmp_path / "cache.csv").exists()
