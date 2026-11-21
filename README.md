# Red Cross local branches in Norway

An interactive map of every Red Cross local branch (*lokalforening*) in Norway: where it
is and what it does.

## Contents

- [The quest](#the-quest)
- [How it works](#how-it-works)
- [Stack](#stack)
- [Quick start (Windows + WSL)](#quick-start-windows--wsl)
- [Make commands](#make-commands)
- [Refreshing the data](#refreshing-the-data)
- [Project layout](#project-layout)
- [Sources and credits](#sources-and-credits)
- [More docs](#more-docs)
- [License](#license)

## The quest

The Norwegian Red Cross has around 350 local branches. Each one has its own page on
[rodekors.no](https://www.rodekors.no/lokalforeninger/), but there is no single place to
see them all, or to find which branch near you offers a given activity, such as homework
help, visiting friends or first-aid groups.

This repo collects that public information into one dataset and shows it as a map you can
search and filter. The app runs locally with Streamlit; hosting (Cloudflare if possible)
is still being worked out.

## How it works

```
rodekors.no ──scrape──▶ data/raw/ ──geocode──▶ data/geocode_cache.csv ─┐
                                                                      ├─transform─▶ data/tables/ ──▶ Streamlit app
                      data/overrides.csv (coordinates entered by hand) ┘
```

1. **Scrape.** Read every district and branch page on rodekors.no: name, address, map
   coordinates and activities. The scraper is polite: it waits 5–15 seconds between
   requests, so a full run takes 2–3 hours.
2. **Geocode.** Most branch pages have an address but no coordinates. Kartverket's free
   APIs turn the street address into a point. When that fails, it uses the town or
   municipality instead.
3. **Fill the gaps by hand.** The few branches that still have no location get their
   coordinates in `data/overrides.csv`.
4. **Transform.** Combine it all into the small tables the app reads (`data/tables/`).
   They're committed, so the app works without scraping.

Today all 347 branches are on the map: 146 at their street address, 84 at the site's own
coordinates, 113 at a town or municipality centre, and 4 entered by hand. The details
are in [docs/missing-data-quality.md](docs/missing-data-quality.md).

## Stack

| Part | Tool |
|---|---|
| Language | Python 3.14 |
| Packages and virtualenv | [uv](https://docs.astral.sh/uv/) (never `pip install`) |
| Scraping | requests, Beautiful Soup |
| Data | pandas, CSV files in the repo |
| Geocoding | Kartverket address and place-name APIs (no key needed) |
| App | [Streamlit](https://streamlit.io/), folium / Leaflet, streamlit-folium |
| Map tiles | Kartverket topographic map |
| Quality | ruff (lint and format), pytest, pre-commit |
| CI and releases | GitHub Actions (`make ci`), release-please, Dependabot |

## Quick start (Windows + WSL)

On macOS or Linux, skip step 1.

1. **Install WSL with Ubuntu.** In PowerShell as administrator, run this, then restart and
   open "Ubuntu" from the Start menu:
   ```powershell
   wsl --install -d Ubuntu
   ```
2. **Install git, make and uv** (in the Ubuntu terminal):
   ```sh
   sudo apt update && sudo apt install -y git make curl
   curl -LsSf https://astral.sh/uv/install.sh | sh
   exec $SHELL   # reload the shell so `uv` is found
   ```
3. **Get the code and install.** uv downloads the right Python by itself.
   ```sh
   git clone https://github.com/Manteplante/local-branch-overview.git
   cd local-branch-overview
   make sync     # install all dependencies
   make hooks    # optional: run lint/format checks before each commit
   ```
4. **Run the app:**
   ```sh
   make run
   ```
   Open <http://localhost:8501> in your Windows browser (WSL forwards `localhost`).

Tip: keep the repo inside the WSL file system (e.g. `~/repositories/`), not under
`/mnt/c/`. It is much faster. In VS Code, use the "WSL" extension and run `code .` from
the repo folder.

## Make commands

Run `make help` for the full list.

| Command | What it does |
|---|---|
| `make sync` | Install all dependencies |
| `make run` | Start the app on http://localhost:8501 |
| `make ci` | Lock check, lint, format check and tests: exactly what GitHub Actions runs |
| `make test` / `make lint` / `make format` | Run one of those checks; `format` also fixes |
| `make scrape` | Scrape all districts to `data/raw/` (2–3 h; rerun to resume) |
| `make scrape-sample` | Quick test scrape: at most 2 branches per district (about 10 min) |
| `make geocode` | Look up coordinates for branches without them (free, cached) |
| `make geocode-retry` | Look up the cached misses again, after changing the matcher |
| `make overrides` | Add branches still without a location to `data/overrides.csv` |
| `make transform` | Build the app tables in `data/tables/` |
| `make report` | Print a summary of raw files, tables and pages |

## Refreshing the data

```sh
make scrape          # 2–3 h, resumable
make geocode         # a few minutes; only new branches or changed addresses are looked up
make overrides       # lists branches that still have no location
# fill in latitude/longitude for any new rows in data/overrides.csv
make transform
git add data/ && git status
```

The [cheat sheet](docs/cheat-sheet.md) covers this step by step, plus troubleshooting.

## Project layout

```
app.py                  Streamlit entry point (pages/ are added automatically)
pages/                  App pages: 00_home.py, 01_map.py, ...
backend/                Data pipeline and app helpers
  geocode.py            Kartverket lookups and the geocode cache
  overrides.py          Hand-entered coordinates
  transform.py          raw data -> app tables
  mapview.py, ui.py     Map and page helpers
src/local_branch_overview/scraper/   The rodekors.no scraper
data/                   raw/ and sample/ (local only), the cache, overrides and tables (committed)
tests/                  pytest, with saved HTML pages as fixtures (no network)
docs/                   Cheat sheet and the data-quality notes
```

## Sources and credits

- **Norwegian Red Cross (Norges Røde Kors)**: branch names, addresses, coordinates and
  activities are taken from the public pages at
  <https://www.rodekors.no/lokalforeninger/>. This is an independent project, not made
  by or affiliated with the Red Cross.
- **Kartverket** (the Norwegian Mapping Authority), open data, © Kartverket:
  - Address API: <https://api.kartverket.no/adresser/v1/>
  - Place-name API (stedsnavn): <https://api.kartverket.no/stedsnavn/v1/>
  - Topographic map tiles: <https://cache.kartverket.no/>
- **[Streamlit](https://streamlit.io/)** for the app, and **[folium](https://python-visualization.github.io/folium/)**
  / **[Leaflet](https://leafletjs.com/)** for the map.
- **Home page illustration**: AI-generated with OpenAI's image model from the prompt
  “Create an a PNG image 1920×1080 pixels of a fiord, cascades running down steep
  mountains, and a small town in the mouth of the river that meets the fiord, using the
  creative style of classic 90s disney movie”.

## More docs

- [docs/cheat-sheet.md](docs/cheat-sheet.md): everyday commands, the data refresh,
  troubleshooting and the git workflow.
- [docs/missing-data-quality.md](docs/missing-data-quality.md): how each branch gets its
  location, and what is still imperfect.
- [SKILLS.md](SKILLS.md): how tests, CI, hooks, dependencies and releases fit together.
- [CHANGELOG.md](CHANGELOG.md): released versions.

## License

[MIT](LICENSE).
