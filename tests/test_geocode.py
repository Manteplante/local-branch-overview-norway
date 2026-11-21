"""Kartverket geocoding with a fake session: no test touches the network."""

from pathlib import Path

import pytest
import requests

from backend import config, geocode
from backend.geocode import (
    COUNTY_NUMBERS,
    GeocodeError,
    GeocodeResult,
    KartverketGeocoder,
    Target,
    branch_query,
    branch_target,
    geocode_missing,
    load_cache,
    name_parts,
    save_cache,
)


def place(name: str, kind: str, lat: float = 61.0, lng: float = 9.1) -> dict:
    return {
        "skrivemåte": name,
        "navneobjekttype": kind,
        "kommuner": [{"kommunenavn": f"{name} kommune"}],
        "representasjonspunkt": {"nord": lat, "øst": lng, "koordsys": 4258},
    }


def names(*places: dict) -> dict:
    return {"metadata": {"totaltAntallTreff": len(places)}, "navn": list(places)}


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Server Error")

    def json(self) -> dict:
        return self.payload


class FakeSession(requests.Session):
    """Answers with queued payloads and records the params of each call."""

    def __init__(self, *responses: dict | FakeResponse | Exception) -> None:
        super().__init__()
        self.responses = list(responses)
        self.calls: list[dict] = []

    def get(self, url, params=None, **kwargs):  # type: ignore[override]
        self.calls.append(params)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item if isinstance(item, FakeResponse) else FakeResponse(item)


def geocoder(*responses: dict | FakeResponse | Exception) -> KartverketGeocoder:
    return KartverketGeocoder(session=FakeSession(*responses), sleep=lambda _: None)


BAGN = Target("Bagn, Oppland", "Bagn", ("34",))


# ── matching ──────────────────────────────────────────────────────────────────


def test_picks_highest_ranked_settlement() -> None:
    g = geocoder(
        names(
            place("Bagn", "Navnegard", 1, 1),
            place("Bagn", "Tettsted", 60.82, 9.55),
            place("Bagn", "Kommune", 2, 2),
        )
    )

    result = g.geocode(BAGN)

    assert result.found
    assert (result.latitude, result.longitude) == (60.82, 9.55)
    assert (result.matched_name, result.place_type) == ("Bagn", "Tettsted")
    assert result.municipality == "Bagn kommune"
    assert g.session.calls == [
        {"sok": "Bagn", "utkoordsys": "4258", "treffPerSide": "10", "fnr": ["34"]}
    ]


def test_ties_keep_api_order() -> None:
    g = geocoder(names(place("Bø", "Tettsted", 1, 1), place("Bø", "Tettsted", 2, 2)))
    assert g.geocode(Target("Bø", "Bø", ("40",))).latitude == 1


def test_falls_back_to_the_single_municipality() -> None:
    g = geocoder(
        names(place("Flatanger", "Kirke")),  # churches don't count
        names(place("Flatanger kommune", "Kommune", 64.5, 10.8)),
    )

    result = g.geocode(Target("Flatanger, Trøndelag", "Flatanger", ("50",)))

    assert result.place_type == "Kommune" and result.latitude == 64.5
    assert g.session.calls[1]["sok"] == "*Flatanger kommune"


def test_rejects_ambiguous_municipality() -> None:
    g = geocoder(
        names(),
        names(place("Nord-Aurdal kommune", "Kommune"), place("Sør-Aurdal kommune", "Kommune")),
    )  # fmt: skip
    assert g.geocode(Target("Aurdal", "Aurdal", ("34",))).status == "no_match"


def test_exact_municipality_beats_suffix_matches() -> None:
    g = geocoder(
        names(place("Heim", "Gard")),
        names(place("Trondheim kommune", "Kommune", 63.4, 10.4),
              place("Heim kommune", "Kommune", 63.3, 9.1)),
    )  # fmt: skip
    result = g.geocode(Target("Heim, Trøndelag", "Heim", ("50",)))
    assert (result.matched_name, result.latitude) == ("Heim kommune", 63.3)


def test_former_municipality_is_accepted() -> None:
    former = "Annen administrativ inndeling"
    g = geocoder(
        names(place("Skedsmo", "Kirke")),
        names(place("Skedsmo kommune", former, 59.96, 11.04)),
    )

    result = g.geocode(Target("Skedsmo, Akershus", "Skedsmo", ("32",)))

    assert (result.matched_name, result.place_type) == ("Skedsmo kommune", former)


def test_current_municipality_beats_former_one() -> None:
    g = geocoder(
        names(),
        names(place("Os kommune", "Annen administrativ inndeling", 1, 1),
              place("Os kommune", "Kommune", 2, 2)),
    )  # fmt: skip
    assert g.geocode(Target("Os", "Os", ("34",))).latitude == 2


def test_ambiguous_former_and_current_municipality_rejected() -> None:
    g = geocoder(
        names(),
        names(place("Nedre Eiker kommune", "Annen administrativ inndeling"),
              place("Øvre Eiker kommune", "Kommune")),
    )  # fmt: skip
    assert g._find(Target("Eiker", "Eiker", ("33",))) is None


@pytest.mark.parametrize(
    ("name", "parts"),
    [
        ("Øyer Tretten", ["Øyer", "Tretten"]),
        ("Høre/Vestre Slidre", ["Høre", "Vestre Slidre", "Slidre"]),
        ("Soknedal-Budal", ["Soknedal", "Budal"]),
        ("Furnes og Brumunddal", ["Furnes", "Brumunddal"]),
        ("Nedre Eiker", ["Eiker"]),  # qualifier words are never searched alone
        ("Bagn", []),
    ],
)
def test_name_parts(name: str, parts: list[str]) -> None:
    assert name_parts(name) == parts


def test_two_name_branch_takes_first_part_that_matches() -> None:
    g = geocoder(
        names(), names(),  # "Furnes og Brumunddal" as a whole
        names(), names(),  # "Furnes"
        names(place("Brumunddal", "By", 60.88, 10.94)),
    )  # fmt: skip

    result = g.geocode(
        Target("Furnes og Brumunddal, Hedmark", "Furnes og Brumunddal", ("34",))
    )

    assert result.matched_name == "Brumunddal"
    assert [c["sok"] for c in g.session.calls] == [
        "Furnes og Brumunddal",
        "*Furnes og Brumunddal kommune",
        "Furnes",
        "Furnes kommune",  # a part only takes the exact municipality, no wildcard
        "Brumunddal",
    ]


def test_part_never_drifts_to_a_neighbouring_municipality() -> None:
    g = geocoder(
        names(), names(),  # "Nedre Eiker" as a whole
        names(),  # "Eiker"
        names(place("Øvre Eiker kommune", "Kommune")),  # "Eiker kommune": not exact
    )  # fmt: skip
    assert g.geocode(Target("Nedre Eiker", "Nedre Eiker", ("33",))).status == "no_match"


def test_og_names_fall_back_to_first_part() -> None:
    g = geocoder(names(), names(), names(place("Arna", "Bydel", 60.42, 5.47)))

    result = g.geocode(Target("Arna og Åsane, Hordaland", "Arna og Åsane", ("46",)))

    assert result.matched_name == "Arna" and result.found
    assert [c["sok"] for c in g.session.calls] == [
        "Arna og Åsane",
        "*Arna og Åsane kommune",
        "Arna",
    ]


def test_no_match() -> None:
    g = geocoder(names(), names())

    result = g.geocode(Target("Nowhere", "Nowhere", ()))

    assert result == GeocodeResult(
        query="Nowhere", status="no_match", fetched_at=result.fetched_at
    )
    assert "fnr" not in g.session.calls[0]  # unknown county: search all of Norway


@pytest.mark.parametrize(
    "response",
    [
        FakeResponse({}, status_code=503),
        FakeResponse({"unexpected": "shape"}),
        requests.ConnectionError("down"),
    ],
)
def test_request_errors_raise(response: FakeResponse | Exception) -> None:
    with pytest.raises(GeocodeError, match="Bagn"):
        geocoder(response).geocode(BAGN)


# ── run ───────────────────────────────────────────────────────────────────────


def test_geocode_missing_skips_cached_and_duplicates() -> None:
    g = geocoder(names(place("Bagn", "Tettsted")), names(), names())
    cached = GeocodeResult(
        query="Bryne, Rogaland", status="found", latitude=1, longitude=1
    )
    cache = {"Bryne, Rogaland": cached}
    targets = [
        BAGN,
        BAGN,
        Target("Bryne, Rogaland", "Bryne", ("11", "42")),
        Target("X", "X", ()),
    ]

    summary = geocode_missing(targets, g, cache, log=str)

    assert (summary.found, summary.no_match, summary.cached) == (1, 1, 1)
    assert cache["X"].status == "no_match"  # misses are cached: never asked again
    assert len(g.session.calls) == 3
    assert g.session.responses == []  # fmt: skip


def test_cache_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "cache.csv"
    cache = {
        "b": GeocodeResult(query="b", status="no_match", fetched_at="t"),
        "a": GeocodeResult(
            query="a", status="found", latitude=1.5, longitude=2.5,
            matched_name="A", place_type="By", municipality="A kommune",
        ),
    }  # fmt: skip

    save_cache(cache, path)

    assert load_cache(path) == cache
    assert path.read_text().splitlines()[1].startswith("a,")  # sorted by query
    assert load_cache(tmp_path / "missing.csv") == {}


@pytest.mark.parametrize(
    ("branch", "district", "target"),
    [
        (
            "Bagn Røde Kors",
            "Oppland Røde Kors",
            Target("Bagn, Oppland", "Bagn", ("34", "32")),
        ),
        (
            "Flatanger",
            "Røde Kors i Trøndelag – Nord",
            Target("Flatanger, Trøndelag", "Flatanger", ("50", "15")),
        ),
        ("Oslo Røde Kors", "Oslo Røde Kors", Target("Oslo", "Oslo", ("03",))),
        (
            "Bryne Røde Kors",
            "Rogaland Røde Kors med Flekkefjord by",
            Target("Bryne, Rogaland", "Bryne", ("11", "42")),
        ),
        (
            "Brumunddal Røde Kors Hjelpekorps",
            "Hedmark Røde Kors",
            Target("Brumunddal, Hedmark", "Brumunddal", ("34",)),
        ),
        (
            "Arna og Åsane Røde Kors",
            "Hordaland Røde Kors",
            Target("Arna og Åsane, Hordaland", "Arna og Åsane", ("46",)),
        ),
        ("Foo Røde Kors", "Atlantis Røde Kors", Target("Foo, Atlantis", "Foo", ())),
        (
            "Olden Raude Kross",
            "Sogn og Fjordane Røde Kors",
            Target("Olden, Sogn og Fjordane", "Olden", ("46",)),
        ),
        (
            "Saltdal Omsorg",
            "Nordland Røde Kors",
            Target("Saltdal, Nordland", "Saltdal", ("18",)),
        ),
        (
            "Jevnaker Røde Kors",
            "Oppland Røde Kors",
            Target("Jevnaker, Oppland", "Jevnaker", ("34", "32")),
        ),
    ],
)
def test_branch_target(branch: str, district: str, target: Target) -> None:
    assert branch_target(branch, district) == target
    assert branch_query(branch, district) == target.query


# Every district on rodekors.no (data/sample, 2026-11) maps to a county number.
SITE_DISTRICTS = [
    "Agder Røde Kors", "Akershus Røde Kors", "Buskerud Røde Kors", "Finnmark Røde Kors",
    "Hedmark Røde Kors", "Hordaland Røde Kors", "Møre og Romsdal Røde Kors",
    "Nordland Røde Kors", "Oppland Røde Kors", "Oslo Røde Kors",
    "Rogaland Røde Kors med Flekkefjord by", "Røde Kors i Trøndelag – Nord",
    "Røde Kors i Trøndelag – Sør", "Sogn og Fjordane Røde Kors", "Telemark Røde Kors",
    "Troms Røde Kors", "Vestfold Røde Kors", "Østfold Røde Kors",
]  # fmt: skip


@pytest.mark.parametrize("district", SITE_DISTRICTS)
def test_every_site_district_has_a_county(district: str) -> None:
    numbers = branch_target("X", district).county_numbers
    assert numbers and numbers in COUNTY_NUMBERS.values()


def test_dry_run_makes_no_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(geocode, "missing_targets", lambda: [BAGN])
    monkeypatch.setattr(config, "GEOCODE_CACHE", tmp_path / "cache.csv")

    def no_network(*args, **kwargs):
        raise AssertionError("dry run must not call Kartverket")

    monkeypatch.setattr(geocode, "KartverketGeocoder", no_network)

    geocode.main(["--dry-run"])
    assert not (tmp_path / "cache.csv").exists()


def test_main_saves_results_before_stopping_on_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    second = Target("Bryne, Rogaland", "Bryne", ("11", "42"))
    monkeypatch.setattr(geocode, "missing_targets", lambda: [BAGN, second])
    monkeypatch.setattr(config, "GEOCODE_CACHE", tmp_path / "cache.csv")
    session = FakeSession(names(place("Bagn", "Tettsted")), requests.Timeout("slow"))
    monkeypatch.setattr(
        geocode,
        "KartverketGeocoder",
        lambda: KartverketGeocoder(session=session, sleep=lambda _: None),
    )

    with pytest.raises(SystemExit, match="rerun to resume"):
        geocode.main([])
    assert set(load_cache(tmp_path / "cache.csv")) == {"Bagn, Oppland"}


def test_retry_misses_requeries_only_no_match_rows() -> None:
    found = GeocodeResult(
        query="Bagn, Oppland", status="found", latitude=1, longitude=1
    )
    miss = GeocodeResult(query="Voss, Hordaland", status="no_match")
    cache = {found.query: found, miss.query: miss}
    voss = Target("Voss, Hordaland", "Voss", ("46",))
    g = geocoder(names(place("Voss", "Annen administrativ inndeling", 60.63, 6.42)))

    assert geocode_missing([BAGN, voss], g, cache, log=str).cached == 2  # default: skip
    summary = geocode_missing([BAGN, voss], g, cache, retry_misses=True, log=str)

    assert (summary.found, summary.cached) == (1, 1)
    assert cache["Voss, Hordaland"].found and cache["Bagn, Oppland"] is found
