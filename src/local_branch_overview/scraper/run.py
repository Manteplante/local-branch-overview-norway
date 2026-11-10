"""Scrape every district → local branch → address + activities into one CSV per district."""

import argparse
import logging
import os
import tempfile
from pathlib import Path
from typing import Protocol

import pandas as pd

from local_branch_overview.scraper.client import PoliteClient
from local_branch_overview.scraper.parse import (
    DISTRICTS_URL,
    District,
    parse_branch_page,
    parse_branches,
    parse_districts,
)

log = logging.getLogger(__name__)

COLUMNS = [
    "district",
    "district_slug",
    "branch",
    "branch_slug",
    "address",
    "latitude",
    "longitude",
    "activity",
    "description",
    "branch_url",
]


class Fetcher(Protocol):
    def get(self, url: str) -> str: ...


def scrape_district(
    client: Fetcher, district: District, limit_branches: int | None = None
) -> tuple[pd.DataFrame, list[str]]:
    """Rows for one district (one per activity) and the URLs of branches that failed."""
    branches = parse_branches(client.get(district.url))[:limit_branches]
    rows: list[dict] = []
    failed: list[str] = []
    for i, branch in enumerate(branches, 1):
        log.info("%s %d/%d %s", district.slug, i, len(branches), branch.slug)
        try:
            details = parse_branch_page(client.get(branch.url))
        except Exception:
            log.exception("Skipping %s", branch.url)
            failed.append(branch.url)
            continue
        base = {
            "district": district.name,
            "district_slug": district.slug,
            "branch": branch.name,
            "branch_slug": branch.slug,
            "address": details.address,
            "latitude": details.latitude,
            "longitude": details.longitude,
            "branch_url": branch.url,
        }
        for activity in details.activities or [None]:
            rows.append(
                base
                | {
                    "activity": activity.name if activity else "",
                    "description": activity.description if activity else "",
                }
            )
    return pd.DataFrame(rows, columns=COLUMNS), failed


def _write_atomic(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".csv.tmp")
    os.close(fd)
    try:
        df.to_csv(tmp, index=False, encoding="utf-8")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def scrape(
    client: Fetcher,
    out_dir: Path,
    *,
    only: set[str] | None = None,
    limit_branches: int | None = None,
    force: bool = False,
) -> list[str]:
    """Write `<out_dir>/<district-slug>.csv` per district. Returns the failed branch URLs."""
    districts = parse_districts(client.get(DISTRICTS_URL))
    if only:
        unknown = only - {d.slug for d in districts}
        if unknown:
            raise SystemExit(f"Unknown district(s): {', '.join(sorted(unknown))}")
        districts = [d for d in districts if d.slug in only]

    failed: list[str] = []
    for n, district in enumerate(districts, 1):
        path = out_dir / f"{district.slug}.csv"
        if path.exists() and not force:
            log.info(
                "[%d/%d] %s: already scraped, skipping",
                n,
                len(districts),
                district.slug,
            )
            continue
        log.info("[%d/%d] %s", n, len(districts), district.name)
        df, district_failed = scrape_district(client, district, limit_branches)
        _write_atomic(df, path)
        failed += district_failed
        log.info("Wrote %s (%d rows)", path, len(df))
    return failed


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", type=Path, default=Path("data/raw"), help="output folder"
    )
    parser.add_argument(
        "--district",
        action="append",
        help="only this district slug, e.g. agder (repeatable)",
    )
    parser.add_argument(
        "--limit-branches", type=int, help="at most N branches per district"
    )
    parser.add_argument(
        "--force", action="store_true", help="re-scrape districts with a CSV"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    failed = scrape(
        PoliteClient(),
        args.out,
        only=set(args.district) if args.district else None,
        limit_branches=args.limit_branches,
        force=args.force,
    )
    if failed:
        log.warning("%d branch page(s) failed:\n  %s", len(failed), "\n  ".join(failed))
        raise SystemExit(1)
    log.info("Done.")
