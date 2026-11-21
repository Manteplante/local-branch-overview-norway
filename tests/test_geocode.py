"""Kartverket geocoding with a fake session: no test touches the network."""

from pathlib import Path

import pytest
import requests

from backend import config, geocode
from backend.geocode import (
    COUNTY_NUMBERS,
    Address,
    GeocodeError,
    GeocodeResult,
    KartverketGeocoder,
    Target,
    branch_query,
    branch_target,
    geocode_missing,
    load_cache,
    name_parts,
    parse_address,
    save_cache,
    street_pattern,
    town_names,
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
        names(),  # "Furnes og Brumunddal" as a settlement
        names(),  # "Furnes"
        names(place("Brumunddal", "By", 60.88, 10.94)),
    )

    result = g.geocode(
        Target("Furnes og Brumunddal, Hedmark", "Furnes og Brumunddal", ("34",))
    )

    assert result.matched_name == "Brumunddal" and result.method == "place"
    # every name is tried as a settlement before any municipality search
    assert [c["sok"] for c in g.session.calls] == [
        "Furnes og Brumunddal",
        "Furnes",
        "Brumunddal",
    ]


def test_part_never_drifts_to_a_neighbouring_municipality() -> None:
    g = geocoder(
        names(),  # "Nedre Eiker" as a settlement
        names(),  # "Eiker" as a settlement
        names(),  # "*Nedre Eiker kommune"
        names(place("Øvre Eiker kommune", "Kommune")),  # "Eiker kommune": not exact
    )  # fmt: skip
    assert g.geocode(Target("Nedre Eiker", "Nedre Eiker", ("33",))).status == "no_match"


def test_og_names_fall_back_to_first_part() -> None:
    g = geocoder(names(), names(place("Arna", "Bydel", 60.42, 5.47)))

    result = g.geocode(Target("Arna og Åsane, Hordaland", "Arna og Åsane", ("46",)))

    assert result.matched_name == "Arna" and result.found
    assert [c["sok"] for c in g.session.calls] == ["Arna og Åsane", "Arna"]


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


# ── addresses ─────────────────────────────────────────────────────────────────


def address_hit(
    street: str, number: int, letter: str = "", lat: float = 60.8, lon: float = 10.7
) -> dict:
    text = f"{street} {number}{letter}"
    return {
        "adressetekst": text, "adressenavn": street, "nummer": number, "bokstav": letter,
        "postnummer": "2821", "poststed": "GJØVIK", "kommunenavn": "GJØVIK",
        "representasjonspunkt": {"epsg": "EPSG:4258", "lat": lat, "lon": lon},
    }  # fmt: skip


def addresses(*hits: dict) -> dict:
    return {"metadata": {"totaltAntallTreff": len(hits)}, "adresser": list(hits)}


# Real strings from the 2026-11 scrape.
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Frøyas gate 6, 2270 FLISA", Address("Frøyas gate", "6", "", "2270", "FLISA")),
        (
            "Heimdalsgt. 3, 2821 GJØVIK",
            Address("Heimdalsgt", "3", "", "2821", "GJØVIK"),
        ),
        ("Industrivn.039, 2680 VÅGÅ", Address("Industrivn", "39", "", "2680", "VÅGÅ")),
        (
            "Tvildesveien 18 A, 5705 VOSS",
            Address("Tvildesveien", "18", "A", "5705", "VOSS"),
        ),
        (
            "Sagvn. 16 Postboks 149, 3321 VESTFOSSEN",
            Address("Sagvn", "16", "", "3321", "VESTFOSSEN"),
        ),
        (
            "Noroddveien 26 v/Elisabeth Edvardsen, 4816 KOLBJØRNSVIK",
            Address("Noroddveien", "26", "", "4816", "KOLBJØRNSVIK"),
        ),
        (
            "c/o Ingrid Norbye-Antonsen, Dalavegen 44 A, 6885 ÅRDALSTANGEN",
            Address("Dalavegen", "44", "A", "6885", "ÅRDALSTANGEN"),
        ),
        (
            "Trollhaugen, Mellombygdveien 11, 9321 MOEN",
            Address("Mellombygdveien", "11", "", "9321", "MOEN"),
        ),
        (
            "Torgeir Vraasplass 4, 3044       DRAMMEN",
            Address("Torgeir Vraasplass", "4", "", "3044", "DRAMMEN"),
        ),
        ("Boks 195, 4558 VANSE", Address(postcode="4558", town="VANSE")),
        ("Besøksadresse:, 5879 BERGEN", Address(postcode="5879", town="BERGEN")),
        (
            "Øygarden Røde Kors v/ Roar Elde, 5337 RONG",
            Address(postcode="5337", town="RONG"),
        ),
        ("", Address()),
    ],
)
def test_parse_address(text: str, expected: Address) -> None:
    assert parse_address(text) == expected


@pytest.mark.parametrize(
    ("street", "pattern"),
    [
        ("Heimdalsgt", "Heimdals*"),
        ("Sentrumsvn", "Sentrums*"),
        ("Tvildesveien", "Tvildes*"),
        ("Torgeir Vraasplass", "Torgeir Vraas*"),
        ("Frøyas gate", "Frøyas*"),
        ("Kolskogheiane", "Kolskogheiane*"),
        ("Veg", "Veg*"),  # too short to cut
    ],
)
def test_street_pattern(street: str, pattern: str) -> None:
    assert street_pattern(street) == pattern


def test_town_names() -> None:
    assert town_names("SANDE I VESTFOLD") == ["Sande I Vestfold", "Sande"]
    assert town_names("FLISA") == ["Flisa"]
    assert town_names("") == []


GJOVIK = Target("Gjøvik, Oppland | x", "Gjøvik", ("34",), "Heimdalsgt. 3, 2821 GJØVIK")


def test_street_address_wins_and_is_searched_by_post_town() -> None:
    g = geocoder(addresses(address_hit("Heimdals gate", 3, lat=60.79, lon=10.69)))

    result = g.geocode(GJOVIK)

    assert (result.method, result.place_type) == ("address", "Adresse")
    assert (result.latitude, result.longitude) == (60.79, 10.69)
    assert result.matched_name == "Heimdals gate 3, 2821 GJØVIK"
    assert result.municipality == "Gjøvik"
    assert g.session.calls == [
        {
            "utkoordsys": "4258",
            "treffPerSide": "10",
            "sok": "Heimdals* 3",
            "poststed": "GJØVIK",
        }
    ]


def test_address_falls_back_to_post_code() -> None:
    g = geocoder(addresses(), addresses(address_hit("Heimdals gate", 3)))
    assert g.geocode(GJOVIK).method == "address"
    assert g.session.calls[1]["postnummer"] == "2821"


def test_address_needs_the_house_number_and_prefers_no_letter() -> None:
    hits = addresses(
        address_hit("Heimdals gate", 13, lat=1),  # wildcard noise: wrong number
        address_hit("Heimdals gate", 3, "B", lat=2),
        address_hit("Heimdals gate", 3, lat=3),
    )
    assert geocoder(hits).geocode(GJOVIK).latitude == 3


def test_address_letter_is_matched_when_given() -> None:
    target = Target("Voss", "Voss", ("46",), "Tvildesveien 18 A, 5705 VOSS")
    hits = addresses(
        address_hit("Tvildesvegen", 18, lat=1),
        address_hit("Tvildesvegen", 18, "A", lat=2),
    )
    assert geocoder(hits).geocode(target).latitude == 2


def test_address_on_two_different_streets_is_rejected() -> None:
    hits = addresses(address_hit("Heimdals gate", 3), address_hit("Heimdalsvegen", 3))
    g = geocoder(hits, addresses(), names(place("Gjøvik", "By", 60.8, 10.7)))

    result = g.geocode(GJOVIK)

    assert (result.method, result.matched_name) == ("place", "Gjøvik")


def test_po_box_uses_the_post_town() -> None:
    target = Target(
        "Lista, Agder | Boks 195, 4558 VANSE", "Lista", ("42",), "Boks 195, 4558 VANSE"
    )
    g = geocoder(names(), names(place("Vanse", "Tettsted", 58.10, 6.69)))

    result = g.geocode(target)

    assert (result.method, result.matched_name) == ("place", "Vanse")
    assert [c["sok"] for c in g.session.calls] == [
        "Lista",
        "Vanse",
    ]  # no address search


def test_branch_settlement_beats_post_town() -> None:
    target = Target(
        "Arna og Åsane", "Arna og Åsane", ("46",), "Besøksadresse:, 5879 BERGEN"
    )
    g = geocoder(names(), names(place("Arna", "Bydel", 60.42, 5.47)))
    assert g.geocode(target).matched_name == "Arna"  # not Bergen centre


def test_post_town_beats_municipality() -> None:
    target = Target("Gauldal", "Gauldal", ("50",), "Bjørgen, 7387 SINGSÅS")
    g = geocoder(names(), names(place("Singsås", "Tettsted", 62.9, 10.7)))
    assert g.geocode(target).matched_name == "Singsås"
    assert len(g.session.calls) == 2  # never got to "*Gauldal kommune"


def test_cache_key_includes_address() -> None:
    t = branch_target(
        "Solør Røde Kors", "Hedmark Røde Kors", "Frøyas  gate 6, 2270 FLISA"
    )
    assert t.query == "Solør, Hedmark | Frøyas gate 6, 2270 FLISA"
    assert t.address == "Frøyas gate 6, 2270 FLISA"
    assert (
        branch_target("Solør Røde Kors", "Hedmark Røde Kors").query == "Solør, Hedmark"
    )


def test_prune_drops_unused_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "cache.csv"
    used = GeocodeResult(query="Bagn, Oppland", status="found", latitude=1, longitude=1)
    old = GeocodeResult(query="Old key", status="no_match")
    save_cache({used.query: used, old.query: old}, path)
    monkeypatch.setattr(config, "GEOCODE_CACHE", path)
    monkeypatch.setattr(geocode, "missing_targets", lambda: [BAGN])

    geocode.main([])  # without --prune: kept
    assert set(load_cache(path)) == {"Bagn, Oppland", "Old key"}
    geocode.main(["--prune"])
    assert set(load_cache(path)) == {"Bagn, Oppland"}


def test_address_ignores_other_streets_from_the_loose_wildcard() -> None:
    target = Target("Redalen", "Redalen", ("34", "32"), "Birivegen 32, 2836 BIRI")
    hits = addresses(
        address_hit("Honnevegen", 32, lat=1),
        address_hit("Birivegen", 32, lat=2),
        address_hit("Klomsteinrovegen", 32, lat=3),
    )
    assert geocoder(hits).geocode(target).latitude == 2


def test_exact_street_name_beats_other_streets_with_the_stem() -> None:
    target = Target("Brumunddal", "Brumunddal", ("34",), "Brugata 3 a, 2380 BRUMUNDDAL")
    hits = addresses(
        address_hit("Brustadvegen", 3, "A", lat=1),
        address_hit("Brugata", 3, "A", lat=2),
    )
    assert geocoder(hits).geocode(target).latitude == 2
