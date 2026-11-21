# Missing addresses and coordinates

Status: **Kartverket geocoding by street address, then by place** (`make geocode`,
`backend/geocode.py`) and **hand-entered locations** (`make overrides`,
`backend/overrides.py`) are built. Reverse geocoding (step 1 below) is still a plan. Read
this before touching geocoding, addresses or coordinates in `backend/transform.py`, the
scraper or the map.

## The problem

Most branch pages on rodekors.no have an address but no map coordinates.

- The full scrape (2026-11-20): 347 branches, **335 with an address**, **88 with
  coordinates** (from the map marker). 252 of the 259 branches without coordinates have
  an address.
- Addresses are often a PO box ("Boks 195, 4558 VANSE"), use abbreviations
  ("Heimdalsgt. 3", "Sentrumsvn. 72"), name a person ("c/o …", "v/ …"), or carry a postcode
  that changed when municipalities merged.
- **Some site coordinates are a placeholder**: a shared point in central Oslo (59.9155,
  10.7578) for Karasjok, Nordkapp, Bø (Nordland) and Siljan in 2026-11. Site coordinates
  shared by branches in *different* districts are therefore treated as missing
  (`transform.placeholder_coordinates`), and those branches are geocoded like the rest.
- An earlier note here said the site had stopped publishing addresses. That was based on
  the 35-branch sample of 2026-11-11 and does not hold for the full scrape.

## Decisions

- **Keep scraping the coordinates.** They come from the branch page we already fetch, so no
  extra request is needed, and they are the most accurate source we have. Scrape time comes
  from the polite delays in `PoliteClient`, not from parsing.
- **Fill in missing data in `backend/transform.py`, not in the scraper.** Changes to the
  geocoding logic must not need a 2–3 h re-scrape.
- **Geocode with Kartverket, and commit the results** (2026-11-20; replaces the Google
  geocoder from 2026-11-11). Free and needs no key. It is open data, so caching and
  committing the results is fine. The required "© Kartverket" attribution is already on
  the map (`backend/mapview.py`). Google was dropped because it is billable and its terms
  restrict showing results on a non-Google map and redistributing them.
- **The street address comes first** (2026-11-21). It puts the marker on the building
  rather than at a town centre.

## How it works now

- `make geocode` builds the branch list from `RAW_DIR` and takes the branches without
  site coordinates. Each one becomes a `Target` (`branch_target`):
  - the place: the branch name without "Røde Kors", "Raude Kross", "Hjelpekorps" or
    "Omsorg"
  - the scraped address
  - the cache key `"<place>, <county> | <address>"`, so a changed address is looked up again
  - the current county number(s). Red Cross districts use the pre-2024 county names, so
    `COUNTY_NUMBERS` maps them, e.g. Oppland → 34 Innlandet. Some districts reach past
    their old county and search two:
    - Rogaland `11, 42`: Flekkefjord
    - Oppland `34, 32`: Jevnaker and Lunner, now in Akershus
    - Trøndelag `50, 15`: Surnadal
    - Troms `55, 21`: Longyearbyen
- It waits 0.5 s between requests and sends the scraper's `User-Agent`. It tries, best
  first:
  1. **Street address** (`https://api.kartverket.no/adresser/v1/sok`), `method = address`:
     - `parse_address` takes the last `NNNN Town` part as the post code and town. The street
       is the first other part with a house number.
     - It skips `c/o`, `v/`, `Boks`, `Postboks`, `pb`, `Besøksadresse` and the branch's own
       name, and drops trailing "Postboks …", "v/ …" and "( … )".
     - The street is searched as a wildcard stem (`street_pattern`: "Heimdalsgt." →
       `Heimdals*`) plus the number, first in the post town, then by post code.
     - A hit needs the same house number (the letter too, if given; otherwise no letter is
       preferred), and every such hit must be on one street.
  2. **The branch name as a settlement** (`https://api.kartverket.no/stedsnavn/v1/navn`,
     within the county), else one of its parts. The best type wins:
     `By > Tettsted > Bydel > Tettbebyggelse > Kommune > Bygdelag (bygd) >
     Annen administrativ inndeling`. Churches, farms, fjords etc. are ignored. The last type
     is how Kartverket lists **former municipalities** (Voss, Os, Gaular, "Skedsmo kommune").
     - A hamlet (`Bygdelag (bygd)`) loses to a municipality with exactly the same name:
       "Bø" in Nordland is Bø kommune in Vesterålen, not the Bø hamlet in Steigen.
     - Two-name branches are placed at the first part that matches; the popup shows the
       full name ("Øyer Tretten" → Øyer, "Soknedal-Budal" → Soknedal).
     - Parts are split on ` og `, `/`, `-` and spaces, phrases before single words
       (`name_parts`). Qualifier words (Nedre, Øvre, Vestre, …) are never searched alone.
  3. **The post town as a settlement**, e.g. for PO boxes: Lista → Vanse. "SANDE I
     VESTFOLD" is tried as written, then as "Sande". This comes after the branch name, so
     "Arna og Åsane" (post town Bergen) stays at Arna.
  4. **The branch name as a municipality**: `*<place> kommune`.
     - The exact `<place> kommune` wins (Heim, not Trondheim), a current municipality before
       a former one.
     - Otherwise only a single match counts (Gauldal → Midtre Gauldal). "*Eiker kommune"
       (Nedre + Øvre) is rejected.
     - A part only takes its exact `<part> kommune`, so "Eiker" can't drift to Øvre Eiker.
  5. Else a miss, for `data/overrides.csv`.
- Full scrape (2026-11-21): out of 347 branches, 84 have usable site coordinates, **146 are
  placed at their street address**, 113 at a place, and 4 have none from geocoding. Those 4 are
  filled in by hand in `data/overrides.csv` (`manual`), so all 347 are on the map:
  - Odal: no address
  - Finse: post code only
  - Vossestrand: "Draugsvollsvegen 40" is not in the address register
  - Hedalen: a PO box, and Hedalen is a valley, not a settlement
- Steps 2–4 are `method = place`: the centre of a town or municipality. `address` stays
  as scraped either way.
- Results, misses included, go to the committed cache `data/geocode_cache.csv`. Columns:
  `method`, `matched_name`, `place_type`, `municipality`. `make transform` reads only the
  cache, never the network, and sets `location_source` to `site` / `address` / `place` /
  `manual` / `none`. Site coordinates always win; hand-entered ones beat everything.
- `--dry-run` lists the queries without calling anything. A request error stops the run
  after saving what was found; rerun to resume. Tests use a fake session.
- Misses are cached and not asked again. After changing the matcher, run
  `make geocode-retry` (`--retry-misses`), which looks up only the cached misses.
  When cache keys change, `make geocode -- --prune` (`--prune`) deletes the rows no
  branch uses any more.

## Hand-entered locations

For what neither the site nor Kartverket can place:

1. `make overrides` adds every branch still without a location to the committed
   `data/overrides.csv`, with empty `latitude` and `longitude`. It drops empty rows for
   branches that have a location by now, never changes filled rows, and keeps the order,
   so rerun it after each new scrape or geocoding change.
2. Fill in `latitude, longitude` in decimal degrees **with a dot** (`58.4316, 8.7210`, as
   Google Maps or norgeskart.no copy a point). `note` is free text, e.g. which place you
   picked. Leave a row empty to skip it.
3. `make transform` applies the filled rows as `location_source = manual`, which beats
   `site`, `address` and `place`.
   - It stops with the CSV line number if a row has only one coordinate, a value that is not
     a number (a comma decimal), a point outside Norway/Svalbard (lat 57–81, lon 4–32,
     catches swapped values), or a duplicate branch.
   - A row whose branch is no longer scraped only gives a warning.

The key is `district_slug, branch_slug`. `branch` is there only so the file is readable.

## Plan: from most to least precise

| Step | Applies to | Method | Precision | `location_source` |
|---|---|---|---|---|
| 1 | Has site coordinates | Keep them. Address via reverse geocoding: Kartverket `https://ws.geonorge.no/adresser/v1/punktsok` | exact | `site` (+ `reverse` for address) |
| 2 | No coordinates | **Built**: Kartverket via `make geocode`: street address (`adresser/v1/sok`), else place name (`stedsnavn/v1/navn`) | building, or town / municipality centre | `address` / `place` |
| 3 | Still missing | **Built**: by hand in the committed `data/overrides.csv` via `make overrides` (see above). Overrides beat every other source | as entered | `manual` |
| — | Nothing found | Keep the branch in the activity tables; leave it off the map | — | `none` |

Supporting pieces:

- **`location_source` column** in the `branches` table. The app shows approximate locations
  (`place`) with a different marker, e.g. a hollow circle and "approximate location" in
  the tooltip.
- **Committed geocode cache** `data/geocode_cache.csv` (query → result). `make transform`
  stays fast and repeatable and works offline. The API is only called for new branches.
- **Tests:** mock the HTTP calls. Never hit Kartverket in `make test`.

## Not doing (for now)

- **Finding addresses in activity descriptions** (e.g. Arendal's "Hans Thornes vei 26"). A
  description often lists several addresses (Oslo's homework help lists three), so picking
  the branch's own one goes wrong easily. Reconsider only if steps 1–3 leave many gaps.

## Open questions

- Kartverket publishes no rate limit for stedsnavn or adresser (no key or login is needed). We stay at
  ≤ 2 requests/s. Breaking API changes are announced 3 months ahead on
  https://status.kartverket.no. Before relying on `punktsok` (step 1), check its terms.
- The branches that still miss (listed above) are seeded in `data/overrides.csv`, with
  their coordinates still to fill in.
- Rerun `make fixtures` so the tests use pages without addresses.
