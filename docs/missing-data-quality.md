# Branch locations: where they come from

How every branch gets a point on the map, and what is still imperfect. Read this before
changing geocoding, addresses or coordinates, in `backend/geocode.py`,
`backend/transform.py`, `backend/overrides.py`, the scraper or the map.

## Contents

- [Summary](#summary)
- [Why this is needed](#why-this-is-needed)
- [Where a location comes from](#where-a-location-comes-from)
- [How the Kartverket lookup works](#how-the-kartverket-lookup-works)
- [Coordinates entered by hand](#coordinates-entered-by-hand)
- [The cache](#the-cache)
- [Decisions](#decisions)
- [Known limits and ideas](#known-limits-and-ideas)

## Summary

Full scrape of November 2026, 347 branches. All of them are on the map.

| `location_source` | Branches | What it means |
|---|---|---|
| `address` | 146 | The branch's street address, found in Kartverket's address register: the building |
| `site` | 84 | The coordinates on the branch's own rodekors.no page |
| `place` | 113 | A town, village or municipality matching the branch: its centre |
| `manual` | 4 | Entered by hand in `data/overrides.csv` |
| `none` | 0 | Not on the map (still listed in the tables) |

## Why this is needed

- **Most branch pages have an address but no coordinates.** 335 of 347 have an address;
  only 88 have map coordinates.
- **Addresses are messy.** Common problems:
  - PO boxes ("Boks 195, 4558 VANSE")
  - abbreviations ("Heimdalsgt. 3")
  - a contact person ("c/o …", "v/ …")
  - old postcodes from before municipalities merged
- **Some site coordinates are fake.** Four branches (Karasjok, Nordkapp, Bø in Nordland,
  Siljan) all pointed to one spot in central Oslo, a stand-in the site uses. Site
  coordinates shared by branches in *different* districts are therefore ignored
  (`transform.placeholder_coordinates`), and those branches are looked up like the rest.

## Where a location comes from

The first source that works wins:

| Order | Source | Precision | `location_source` |
|---|---|---|---|
| 1 | Hand-entered coordinates (`data/overrides.csv`) | as entered | `manual` |
| 2 | Coordinates on the branch page (unless they are a placeholder) | exact | `site` |
| 3 | Kartverket: the street address | building | `address` |
| 4 | Kartverket: a place for the branch | town or municipality centre | `place` |
| — | Nothing found | not on the map | `none` |

`make transform` applies this order, reading only committed files and never the network.
Each branch's scraped `address` is kept as it is.

## How the Kartverket lookup works

`make geocode` (`backend/geocode.py`) looks up every branch without usable site
coordinates. It uses two free Kartverket APIs that need no key, waits 0.5 s between
requests, and sends the scraper's `User-Agent`.

**Search area.** Each branch is searched within its county. Red Cross districts still use
the pre-2024 counties, so `COUNTY_NUMBERS` maps them to today's numbers, e.g. Oppland →
34 Innlandet. Four districts reach into a second county:

| District | Also searches | For |
|---|---|---|
| Rogaland | Agder | Flekkefjord |
| Oppland | Akershus | Jevnaker, Lunner |
| Trøndelag | Møre og Romsdal | Surnadal |
| Troms | Svalbard | Longyearbyen |

**The steps, best first:**

1. **Street address** ([adresser API](https://api.kartverket.no/adresser/v1/)).
   - `parse_address` takes the street and house number, and the postcode and town. It
     skips PO boxes, "c/o" and "v/" names, and text in brackets.
   - The street is searched as a stem with a wildcard, so abbreviations still match
     ("Heimdalsgt." → `Heimdals*`). It is searched in the post town first, then by
     postcode.
   - A hit needs the same house number, and a street name that starts with the stem. An
     exact street name beats the rest. If different streets remain, the address step gives
     up rather than guess.
2. **The branch name as a settlement** ([stedsnavn API](https://api.kartverket.no/stedsnavn/v1/)).
   - "Settlement" means these place types, best first: By, Tettsted, Bydel,
     Tettbebyggelse, Kommune, Bygdelag, and former municipalities (listed as
     "Annen administrativ inndeling"). Churches, farms, fjords etc. are ignored.
   - Branch names are cleaned first: "Røde Kors", "Raude Kross", "Hjelpekorps" and
     "Omsorg" are removed.
   - A branch with two names is placed at the first one that matches ("Øyer Tretten" →
     Øyer). The popup still shows the full name. Words like Nedre or Vestre are never
     searched on their own.
   - A hamlet (Bygdelag) loses to a municipality with exactly the same name: "Bø" in
     Nordland is Bø kommune, not the hamlet Bø in Steigen.
3. **The post town as a settlement.** This covers PO boxes: Lista → Vanse. It comes
   after the branch name, so Arna og Åsane (post town Bergen) stays at Arna.
4. **The branch name as a municipality** ("Flatanger" → Flatanger kommune).
   - The exact name wins, so Heim doesn't become Trondheim.
   - A near match counts only when it is the only one, so "*Eiker kommune" (both Nedre and
     Øvre Eiker) is rejected.
5. **Nothing found.** The branch goes to `data/overrides.csv`.

## Coordinates entered by hand

1. `make overrides` adds every branch still without a location to `data/overrides.csv`,
   with empty `latitude` and `longitude`. It also removes empty rows for branches that
   have been found since. It never changes rows you filled in.
2. Fill in decimal degrees with a dot, latitude first (`60.3939, 11.5406`). `note` is free
   text.
3. `make transform` applies the rows. It stops and names the line if:
   - only one coordinate is filled in
   - a value isn't a number (a comma decimal, `60,39`)
   - the point is outside Norway or Svalbard (lat 57–81, lon 4–32; catches swapped values)
   - a branch appears twice

   A row for a branch that is no longer on the site only gives a warning.

Today's rows:

| Branch | Why it needed a hand-entered location |
|---|---|
| Odal | No address on the site |
| Finse | Postcode only |
| Vossestrand | The street isn't in the address register |
| Hedalen | A PO box, and "Hedalen" is a valley, not a settlement |

## The cache

- **What it holds.** `data/geocode_cache.csv` is committed and holds every lookup, misses
  included, so `make transform` is fast and works offline.
  - Key: `"<place>, <county> | <address>"`. A branch whose address changes is looked up
    again.
  - Columns:
    - `status`: `found` or `no_match`
    - `method`: `address` or `place`
    - `matched_name`, `place_type`, `municipality`: what was matched
- **Misses aren't looked up again** on their own. After changing the matcher, run
  `make geocode-retry`.
- **Unused rows.** `uv run python -m backend.geocode --prune` deletes rows no branch uses
  any more, e.g. after a change to how cache keys are built.
- **Other commands.** `uv run python -m backend.geocode --dry-run` lists the lookups
  without any requests. A failed request stops the run but keeps what was found; run it
  again to continue.
- **Tests never call Kartverket.** They use a fake session.

## Decisions

- **Scrape coordinates when the page has them.** They cost no extra request, and are the
  most accurate source, unless they are a placeholder.
- **Fix data in `transform` and `geocode`, not in the scraper.** A change to the matching
  must not need a new 2–3 hour scrape.
- **Kartverket, not Google** (2026-11-20).
  - Kartverket is free, open data, so the results can be cached and committed. The
    "© Kartverket" credit is already on the map.
  - Google costs money, and its terms restrict showing results on a non-Google map and
    sharing them.
- **The street address comes first** (2026-11-21), so the marker sits on the building
  rather than at a town centre.

## Known limits and ideas

- **Not every street address is in the register.** Some streets aren't found under the
  scraped post town (e.g. Sykehjemsvn. 5, Stathelle; Kleiva 2, Hasvåg). Those branches
  fall back to the town or municipality centre.
- **Approximate markers look the same as exact ones.** Idea: show `place` locations with
  a different marker and "approximate location" in the popup.
- **Reverse geocoding.** The 84 branches with site coordinates could get a clean address
  from Kartverket's `punktsok`. Check its terms first.
- **Addresses in activity descriptions** (e.g. "Hans Thornes vei 26") are not used. A
  description often lists several addresses, so picking the branch's own one easily goes
  wrong.
- **Kartverket's limits.** Kartverket publishes no rate limit for these APIs. We stay at
  2 requests per second or fewer. Breaking changes are announced 3 months ahead on
  <https://status.kartverket.no>.
- **Test fixtures.** Rerun `make fixtures` from time to time so the saved test pages
  match the live site.
