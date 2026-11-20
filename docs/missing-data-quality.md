# Missing addresses and coordinates

Status: **Kartverket place-name geocoding is built** (`make geocode`, `backend/geocode.py`). The other
steps below are still a plan. Read this before touching geocoding, addresses or
coordinates in `backend/transform.py`, the scraper or the map.

## The problem

Around November 2026, rodekors.no stopped publishing branch addresses. Found during
`make scrape-sample` on 2026-11-11:

- The `Adresse` field on branch pages is now empty, and the address inside the map marker
  (`data-marker='["lat", "lng", "", zoom]'`) is blank.
- The saved test pages (`tests/fixtures/`) are older and still have addresses, so the tests
  did not catch the change.
- Sample run (35 branches): **1 branch has an address** (Oslo, read from its contact page)
  and **13 have coordinates** (from the map marker). The other 22 have none.
- `backend/transform.py` keeps only branches with coordinates, so those 22 are left off the
  map.

## Decisions

- **Keep scraping the coordinates.** They come from the branch page we already fetch, so no
  extra request is needed, and they are the most accurate source we have. Scrape time comes
  from the polite delays in `PoliteClient`, not from parsing.
- **Fill in missing data in `backend/transform.py`, not in the scraper.** Changes to the
  geocoding logic must not need a 2–3 h re-scrape.

- **Geocode with Kartverket place names, and commit the results** (2026-11-20; replaces
  the Google geocoder from 2026-11-11). Free and needs no key. It is open data, so caching
  and committing the results is fine. The required "© Kartverket" attribution is already on
  the map (`backend/mapview.py`). Google was dropped because it is billable and its terms
  restrict showing results on a non-Google map and redistributing them.

## How it works now

- `make geocode` builds the branch list from `RAW_DIR` and takes the branches without
  site coordinates. Each one becomes a `Target` (`branch_target`): the place (branch name
  without "Røde Kors"), the cache key `"<place>, <county>"`, and the current county
  number(s). Red Cross districts use pre-2024 county names, so `COUNTY_NUMBERS` maps them,
  e.g. Oppland → 34 Innlandet. Rogaland → `11,42` because it includes Flekkefjord.
- It searches `https://api.kartverket.no/stedsnavn/v1/navn` within that county, waiting
  0.5 s between requests and sending the scraper's `User-Agent`:
  1. `<place>`: the best settlement by type, `By > Tettsted > Bydel > Tettbebyggelse >
     Kommune > Bygdelag (bygd)`. Churches, farms, fjords etc. are ignored.
  2. Else `*<place> kommune`: the exact `<place> kommune` if listed (Heim, not
     Trondheim), otherwise only when exactly one municipality matches
     (Flatanger, Gauldal → Midtre Gauldal).
  3. Else, for "X og Y" names, steps 1–2 with "X" (Arna og Åsane → Arna, Bø og Sauherad → Bø).
  4. Else a miss.
  On `data/sample` (2026-11-20) this matched all 22 branches without site coordinates.
- A match is the centre of a town or municipality, **not an address**, so `address` stays
  as scraped.
- Results, misses included, go to the committed cache `data/geocode_cache.csv`. Columns:
  `matched_name`, `place_type`, `municipality`. `make transform` reads only the cache, never
  the network, and sets `location_source` to `site` / `kartverket` / `none`. Site
  coordinates always win.
- `--dry-run` lists the queries without calling anything. A request error stops the run
  after saving what was found; rerun to resume. Tests use a fake session.

## Plan: from most to least precise

| Step | Applies to | Method | Precision | `location_source` |
|---|---|---|---|---|
| 1 | Has site coordinates | Keep them. Address via reverse geocoding: Kartverket `https://ws.geonorge.no/adresser/v1/punktsok` | exact | `site` (+ `reverse` for address) |
| 2 | No coordinates | **Built**: Kartverket place-name geocoding via `make geocode` (`https://api.kartverket.no/stedsnavn/v1/navn`) | place or village centre | `kartverket` |
| 3 | Still missing | Fill in by hand in a committed `data/overrides.csv` (`branch_slug, address, latitude, longitude`). Overrides beat every other source | exact | `manual` |
| — | Nothing found | Keep the branch in the activity tables; leave it off the map | — | `none` |

Supporting pieces:

- **`location_source` column** in the `branches` table. The app shows approximate locations
  (`placename`) with a different marker, e.g. a hollow circle and "approximate location" in
  the tooltip.
- **Committed geocode cache** `data/geocode_cache.csv` (query → result). `make transform`
  stays fast and repeatable and works offline. The API is only called for new branches.
- **Tests:** mock the HTTP calls. Never hit Kartverket in `make test`.

## Not doing (for now)

- **Finding addresses in activity descriptions** (e.g. Arendal's "Hans Thornes vei 26"). A
  description often lists several addresses (Oslo's homework help lists three), so picking
  the branch's own one goes wrong easily. Reconsider only if steps 1–3 leave many gaps.

## Open questions

- Kartverket publishes no rate limit for stedsnavn (no key or login is needed). We stay at
  ≤ 2 requests/s. Breaking API changes are announced 3 months ahead on
  https://status.kartverket.no. Before relying on `punktsok` (step 1), check its terms.
- Regional names are handled by the "X og Y" fallback above. A branch that still misses
  goes to `data/overrides.csv` (step 3).
- Rerun `make fixtures` so the tests use pages without addresses.
