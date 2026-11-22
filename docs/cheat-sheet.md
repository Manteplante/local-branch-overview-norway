# Cheat sheet

Quick answers for working on this repo. To set it up, start with the
[README](../README.md#quick-start-windows--wsl).

## Contents

- [Everyday commands](#everyday-commands)
- [Refresh all the data](#refresh-all-the-data)
- [Add coordinates by hand](#add-coordinates-by-hand)
- [Geocoding options](#geocoding-options)
- [Git workflow](#git-workflow)
- [Troubleshooting](#troubleshooting)

## Everyday commands

| I want to… | Run |
|---|---|
| Install or update dependencies | `make sync` |
| Start the app | `make run`, then open <http://localhost:8501> |
| Check everything before a PR | `make ci` |
| Fix formatting and simple lint errors | `make format` |
| Run only the tests | `make test` |
| Add a package | `uv add <pkg>` (or `uv add --dev <pkg>`), never `pip install` |
| See all make targets | `make help` |

## Refresh all the data

```sh
make scrape        # 1. all districts -> data/raw/   (2–3 h; rerun to resume)
make geocode       # 2. coordinates for branches without them (a few minutes)
make overrides     # 3. list branches still without a location in data/overrides.csv
                   #    -> fill in any empty rows (next section)
make transform     # 4. build data/tables/ for the app
make run           # 5. look at the map
```

Then commit `data/geocode_cache.csv`, `data/overrides.csv` and `data/tables/`.
`data/raw/` stays on your machine.

Changed the parser so it finds more activities? `make scrape-empty` re-scrapes only the
branches that have none in `data/raw/` (about 15–20 min), then run `make transform`.

Just testing? `make scrape-sample` scrapes at most 2 branches per district (about 10 min)
into `data/sample/`. To use it, prefix other commands with `RAW_DIR=data/sample`.

## Add coordinates by hand

1. Run `make overrides`. Branches without a location get a row with empty `latitude` and
   `longitude` in `data/overrides.csv`.
2. Find the place on [Google Maps](https://maps.google.com) or
   [norgeskart.no](https://norgeskart.no), right-click it and copy the coordinates.
3. Paste them into the row, **latitude first, with a dot**:
   ```
   hedmark,odal,Odal Røde Kors,60.3939,11.5406,Skarnes
   ```
   `note` is optional, e.g. which place you chose.
4. Run `make transform`. The row now beats every other source (`location_source = manual`).

`make transform` stops and names the line if a row has only one coordinate, a comma
decimal (`60,39`), a point outside Norway (often latitude and longitude swapped), or the
same branch twice.

## Geocoding options

These flags are passed to the script directly. `make` can't forward them.

| Run | When |
|---|---|
| `uv run python -m backend.geocode --dry-run` | See what would be looked up, without any requests |
| `make geocode-retry` | You changed the matcher and want the cached misses tried again |
| `uv run python -m backend.geocode --prune` | Delete cache rows no branch uses any more (after a big change) |

To redo a few branches, delete their rows from `data/geocode_cache.csv` and run
`make geocode`. How the lookup works is explained in
[missing-data-quality.md](missing-data-quality.md).

## Git workflow

- `main` is protected. Work on a feature branch and merge it with a pull request:
  ```sh
  git switch main && git pull
  git switch -c <you>/<topic>
  # ... work, then:
  make ci
  git add -A && git commit -m "feat: ..." && git push -u origin HEAD
  ```
- Commit prefixes decide the release: `feat:` (minor), `fix:` (patch), `feat!:` (major).
  `docs:`, `test:`, `ci:` and `chore:` don't make a release.
- Push rejected with **GH007 (private email)**? Commit with your GitHub noreply address:
  `git config --global user.email "<id>+<user>@users.noreply.github.com"`, then
  `git commit --amend --reset-author --no-edit`.

## Troubleshooting

| Problem | Fix |
|---|---|
| `uv: command not found` | Run `exec $SHELL` after installing uv, or open a new terminal |
| `make ci` fails on format | `make format`, then check `git diff` |
| `make ci` fails on lock check | `uv lock`, then commit `uv.lock` |
| The app shows old data | `make transform`, then reload the page |
| A branch sits in the wrong place | Check its row in `data/geocode_cache.csv` (what it matched). Fix it in `data/overrides.csv` |
| `make transform` stops with an overrides error | Fix the line it names in `data/overrides.csv` |
| The scrape stopped halfway | Run `make scrape` again; finished districts are skipped |
| WSL is slow | Keep the repo in `~/…`, not under `/mnt/c/…` |
