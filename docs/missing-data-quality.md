# Missing addresses and coordinates

Status: **plan, not built yet.** Read this before touching geocoding, addresses or coordinates
in `backend/transform.py`, the scraper or the map.

## The problem

Around November 2026, rodekors.no stopped publishing branch addresses. Found during
`make scrape-sample` on 2026-11-11:

- The `Adresse` field on branch pages is now empty, and the address inside the map marker
  (`data-marker='["lat", "lng", "", zoom]'`) is blank.
- The saved test pages (`tests/fixtures/`) are older and still have addresses, so the tests
  did not catch the change.
- Sample run (35 branches): **1 branch has an address** (Oslo, read from its contact page)
  and **14 have coordinates** (from the map marker). The other 21 have neither.
- `backend/transform.py` keeps only branches with coordinates, so those 21 are left off the
  map.

## Decisions

- **Keep scraping the coordinates.** They come from the branch page we already fetch, so no
  extra request is needed, and they are the most accurate source we have. Scrape time comes
  from the polite delays in `PoliteClient`, not from parsing.
- **Fill in missing data in `backend/transform.py`, not in the scraper.** Changes to the
  geocoding logic must not need a 2–3 h re-scrape.

## Plan: from most to least precise

| Step | Applies to | Method | Precision | `location_source` |
|---|---|---|---|---|
| 1 | Has site coordinates | Keep them. Address via reverse geocoding: Kartverket `https://ws.geonorge.no/adresser/v1/punktsok` | exact | `site` (+ `reverse` for address) |
| 2 | No coordinates | Place-name geocoding: strip " Røde Kors" from the branch name, look up in Kartverket `https://ws.geonorge.no/stedsnavn/v1/navn`, limited to the branch's county | place or village centre | `placename` |
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

- Rate limits and terms of use for the Kartverket APIs were not checked. Check before
  building, and send the same `User-Agent` as the scraper.
- Regional names like "Arna og Åsane" or "Bø og Sauherad" match no single place. Try the
  first part, then the municipality, then `manual`.
- Rerun `make fixtures` so the tests use pages without addresses.
