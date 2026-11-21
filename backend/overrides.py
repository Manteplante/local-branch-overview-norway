"""Hand-entered branch locations for what neither the site nor Kartverket could place.

    make overrides      # add every branch still without a location to the file
    # ...fill in latitude/longitude in data/overrides.csv, then:
    make transform      # filled rows win over every other source (location_source=manual)

`config.OVERRIDES` (data/overrides.csv, committed) has one row per branch, keyed by
`district_slug, branch_slug`. `branch` and `note` are only for the people editing it.
Coordinates are decimal degrees with a dot, e.g. 58.4316 (what Google Maps and
norgeskart.no copy). See docs/missing-data-quality.md.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pandas as pd

from . import config

COLUMNS = ["district_slug", "branch_slug", "branch", "latitude", "longitude", "note"]
KEY = ["district_slug", "branch_slug"]
# Mainland Norway and Svalbard, generously: catches swapped or mistyped values.
LAT_RANGE = (57.0, 81.0)
LON_RANGE = (4.0, 32.0)


class OverrideError(ValueError):
    """A row in the overrides file that can't be used; names the line to fix."""


def _read(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=COLUMNS)
    try:
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
    except pd.errors.ParserError as exc:
        raise OverrideError(
            f"{path.name}: {exc}. A comma inside a number? Use a dot: 58.4316"
        ) from None
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        raise OverrideError(f"{path.name}: missing columns {missing}")
    return df[COLUMNS].map(str.strip)


def _coordinate(
    value: str, name: str, bounds: tuple[float, float], where: str
) -> float:
    try:
        number = float(value)
    except ValueError:
        raise OverrideError(
            f"{where}: {name} {value!r} is not a number (use a dot: 58.4316)"
        ) from None
    low, high = bounds
    if not low <= number <= high:
        raise OverrideError(
            f"{where}: {name} {number} is outside Norway ({low}–{high}); swapped?"
        )
    return number


def load_overrides(path: Path | None = None) -> pd.DataFrame:
    """The filled-in rows (`KEY` + latitude, longitude as floats), validated.

    Rows with both coordinates empty are skipped; anything else that's wrong raises
    `OverrideError` rather than putting a marker in the wrong place.
    """
    path = path or config.OVERRIDES
    df = _read(path)
    duplicated = df[df.duplicated(KEY, keep=False)]
    if not duplicated.empty:
        keys = sorted(set(zip(duplicated.district_slug, duplicated.branch_slug)))
        raise OverrideError(f"{path.name}: listed more than once: {keys}")

    rows = []
    for i, row in df.iterrows():
        where = f"{path.name} line {int(str(i)) + 2} ({row.branch or row.branch_slug})"
        lat, lon = row.latitude, row.longitude
        if not lat and not lon:
            continue
        if not lat or not lon:
            raise OverrideError(f"{where}: fill in both latitude and longitude")
        rows.append(
            {
                "district_slug": row.district_slug,
                "branch_slug": row.branch_slug,
                "latitude": _coordinate(lat, "latitude", LAT_RANGE, where),
                "longitude": _coordinate(lon, "longitude", LON_RANGE, where),
            }
        )
    return pd.DataFrame(rows, columns=KEY + ["latitude", "longitude"])


def unknown_keys(overrides: pd.DataFrame, branches: pd.DataFrame) -> list[tuple]:
    """Override keys that match no scraped branch (it may have left the site)."""
    known = set(zip(branches.district_slug, branches.branch_slug))
    return [
        k for k in zip(overrides.district_slug, overrides.branch_slug) if k not in known
    ]


def seed(branches: pd.DataFrame, path: Path | None = None) -> int:
    """Add a row with empty coordinates for each branch still without a location.

    Existing rows are never changed or reordered. Returns how many rows were added.
    """
    path = path or config.OVERRIDES
    existing = _read(path)
    listed = set(zip(existing.district_slug, existing.branch_slug))
    missing = branches[branches["location_source"] == "none"]
    new = (
        missing[
            [k not in listed for k in zip(missing.district_slug, missing.branch_slug)]
        ]
        .assign(latitude="", longitude="", note="")[COLUMNS]
        .sort_values(KEY)
    )
    if new.empty and path.exists():
        return 0
    _write(pd.concat([existing, new], ignore_index=True), path)
    return len(new)


def _write(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".csv.tmp")
    os.close(fd)
    try:
        df.to_csv(tmp, index=False, encoding="utf-8")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def main() -> None:
    from . import transform  # transform imports this module
    from .geocode import load_cache

    raw = transform.read_raw()
    if raw.empty:
        print(
            f"[overrides] No data files under {config.RAW_DIR}. Run `make scrape` first."
        )
        return
    # Without overrides: "still without a location" after site + Kartverket.
    branches = transform.build_branches(transform.build_activities(raw), load_cache())
    added = seed(branches)
    rows = _read(config.OVERRIDES)
    empty = int(((rows.latitude == "") & (rows.longitude == "")).sum())
    print(
        f"[overrides] Added {added} branches to {config.OVERRIDES} · "
        f"{empty} of {len(rows)} rows still need latitude/longitude"
    )


if __name__ == "__main__":
    main()
