"""Scrape every district → local branch → address + activities into one CSV per district."""

import argparse
import logging
import os
import tempfile
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Protocol
from urllib.parse import urljoin

import pandas as pd

from local_branch_overview.scraper.client import PoliteClient
from local_branch_overview.scraper.parse import (
    DISTRICTS_URL,
    SINGLE_BRANCH_PAGES,
    Activity,
    Branch,
    BranchDetails,
    District,
    branch_index_url,
    find_activities_link,
    parse_activity_cards,
    parse_activity_categories,
    parse_activity_list,
    parse_branch_page,
    parse_branches,
    parse_contact_page,
    parse_districts,
    split_by_group,
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
    "section",
    "activity",
    "description",
    "branch_url",
]


class Fetcher(Protocol):
    def get(self, url: str) -> str: ...


@dataclass
class Status:
    """What happened to one output file, for the summary at the end of a run."""

    slug: str
    state: str = ""  # written | skipped | empty
    branches: int = 0
    rows: int = 0
    failed: list[str] = field(default_factory=list)


def _check(ok: bool) -> str:
    return "✓" if ok else "✗"


def _describe(details: BranchDetails) -> str:
    return (
        f"{len(details.activities)} activities · "
        f"address {_check(bool(details.address))} · "
        f"map {_check(details.latitude is not None)}"
    )


def _rows(district: District, branch: Branch, details: BranchDetails) -> list[dict]:
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
    return [
        base
        | {
            "section": activity.section if activity else "",
            "activity": activity.name if activity else "",
            "description": activity.description if activity else "",
        }
        for activity in details.activities or [None]
    ]


def _linked_activities(
    client: Fetcher, branch: Branch, html: str, limit: int | None = None
) -> list[Activity]:
    """Activities on a subpage linked from the branch page, see `find_activities_link`.

    Either the subpage lists them itself (Bodø), or it links to category pages that do
    (Kristiansand); then `section` is the category name and `limit` caps the categories.
    A failed subpage is logged and skipped: the branch keeps its own page's data.
    """
    url = find_activities_link(html, branch.url)
    if url is None:
        return []
    log.info("        following activities link %s", url)
    try:
        page = client.get(url)
    except Exception:
        log.exception("  ✗ activities page failed, skipping %s", url)
        return []
    # Only expanders here: a hub lists its categories as `list-page__item`s too.
    activities = parse_branch_page(page).activities
    if activities:
        return activities
    for category in parse_activity_cards(page, url)[:limit]:
        try:
            page = client.get(category.url)
        except Exception:
            log.exception("  ✗ category page failed, skipping %s", category.url)
            continue
        # The list first: category pages may also hold expanders about volunteering.
        found = parse_activity_list(page) or parse_branch_page(page).activities
        activities += [replace(a, section=category.name) for a in found]
    return activities


def scrape_district(
    client: Fetcher,
    district: District,
    branches: list[Branch],
    limit_categories: int | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    """Rows for one district (one per activity) and the URLs of branches that failed."""
    rows: list[dict] = []
    failed: list[str] = []
    for i, branch in enumerate(branches, 1):
        log.info("  [%d/%d] %s …", i, len(branches), branch.name)
        try:
            html = client.get(branch.url)
            details = parse_branch_page(html)
        except Exception:
            log.exception("  ✗ failed, skipping %s", branch.url)
            failed.append(branch.url)
            continue
        if not details.activities:
            details = replace(
                details,
                activities=_linked_activities(client, branch, html, limit_categories),
            )
        log.info("        %s", _describe(details))
        rows += _rows(district, branch, details)
    return pd.DataFrame(rows, columns=COLUMNS), failed


def scrape_single_branch(
    client: Fetcher, district: District, limit: int | None = None
) -> tuple[pd.DataFrame, list[str]]:
    """A district without local branches (Oslo) as one branch, see `SINGLE_BRANCH_PAGES`.

    `limit` caps the number of activity category pages. If the contact or activities
    page fails, nothing is returned, so the next run tries the district again.
    """
    contact_path, activities_path = SINGLE_BRANCH_PAGES[district.slug]
    contact_url = urljoin(district.url, contact_path)
    index_url = urljoin(district.url, activities_path)
    url = contact_url
    try:
        log.info("  contact page …")
        contact = parse_contact_page(client.get(url))
        log.info(
            "        address %s · map %s",
            _check(bool(contact.address)),
            _check(contact.latitude is not None),
        )
        url = index_url
        categories = parse_activity_categories(client.get(url), index_url)
    except Exception:
        log.exception("  ✗ failed, skipping %s", url)
        return pd.DataFrame(columns=COLUMNS), [url]

    selected = categories[:limit]
    log.info(
        "  %d activity categories listed, scraping %d", len(categories), len(selected)
    )
    branch = Branch(name=district.name, slug=district.slug, url=district.url)
    activities: list[Activity] = []
    failed: list[str] = []
    for i, category in enumerate(selected, 1):
        log.info("  [%d/%d] %s …", i, len(selected), category.name)
        try:
            page = parse_branch_page(client.get(category.url))
        except Exception:
            log.exception("  ✗ failed, skipping %s", category.url)
            failed.append(category.url)
            continue
        log.info("        %d activities", len(page.activities))
        activities += [replace(a, section=category.name) for a in page.activities]
    if failed and not activities:  # nothing written, so the next run tries again
        return pd.DataFrame(columns=COLUMNS), failed
    rows = _rows(district, branch, replace(contact, activities=activities))
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


def _save(df: pd.DataFrame, path: Path, status: Status) -> None:
    if df.empty:  # no CSV, so the next run tries this district again
        status.state = "empty"
        log.warning("  ✗ %s: no branch data, nothing written", status.slug)
        return
    _write_atomic(df, path)
    status.state = "written"
    status.rows = len(df)
    status.branches = df["branch_slug"].nunique()
    log.info("  ✓ wrote %s (%d rows, %d branches)", path, status.rows, status.branches)


def _log_summary(statuses: list[Status], seconds: float) -> None:
    width = max([len(s.slug) for s in statuses] + [8])
    log.info("Summary (%.0f min):", seconds / 60)
    log.info(
        "  %-*s  %-8s %8s %5s %6s",
        width,
        "district",
        "status",
        "branches",
        "rows",
        "failed",
    )
    for s in statuses:
        log.info(
            "  %-*s  %-8s %8d %5d %6d",
            width,
            s.slug,
            s.state,
            s.branches,
            s.rows,
            len(s.failed),
        )
    written = [s for s in statuses if s.state == "written"]
    log.info(
        "  %d written, %d skipped, %d empty · %d rows total",
        len(written),
        sum(s.state == "skipped" for s in statuses),
        sum(s.state == "empty" for s in statuses),
        sum(s.rows for s in written),
    )


def scrape(
    client: Fetcher,
    out_dir: Path,
    *,
    only: set[str] | None = None,
    limit_branches: int | None = None,
    force: bool = False,
) -> list[str]:
    """Write `<out_dir>/<district-slug>.csv` per district. Returns the failed page URLs.

    Districts whose index groups its branches (Trøndelag: Nord/Sør) get one CSV per group.
    The index page is fetched even when resuming, so a half-done split district finishes.
    Districts in `SINGLE_BRANCH_PAGES` (Oslo) are scraped as one branch.
    """
    started = time.monotonic()
    districts = parse_districts(client.get(DISTRICTS_URL))
    if only:
        unknown = only - {d.slug for d in districts}
        if unknown:
            raise SystemExit(f"Unknown district(s): {', '.join(sorted(unknown))}")
        districts = [d for d in districts if d.slug in only]
    limit_text = (
        f"≤{limit_branches} branches each" if limit_branches else "all branches"
    )
    log.info("Scraping %d districts → %s (%s)", len(districts), out_dir, limit_text)

    statuses: list[Status] = []
    for n, district in enumerate(districts, 1):
        log.info("[%d/%d] %s", n, len(districts), district.name)
        if district.slug in SINGLE_BRANCH_PAGES:
            parts = [(district, None)]
        else:
            branches = parse_branches(client.get(branch_index_url(district)))
            if not branches:
                log.warning(
                    "  ✗ %s: no local branches listed, nothing written", district.slug
                )
                statuses.append(Status(district.slug, state="empty"))
                continue
            log.info("  %d local branches listed", len(branches))
            parts = split_by_group(district, branches)
        for part, members in parts:
            status = Status(part.slug)
            statuses.append(status)
            path = out_dir / f"{part.slug}.csv"
            if path.exists() and not force:
                status.state = "skipped"
                log.info("  %s: already scraped (%s), skipping", part.slug, path)
                continue
            if members is None:
                df, status.failed = scrape_single_branch(client, part, limit_branches)
            else:
                if len(parts) > 1:
                    log.info("  %s: %d branches", part.name, len(members))
                df, status.failed = scrape_district(
                    client, part, members[:limit_branches], limit_branches
                )
            _save(df, path, status)

    _log_summary(statuses, time.monotonic() - started)
    return [url for s in statuses for url in s.failed]


def rescrape_empty(
    client: Fetcher, out_dir: Path, *, only: set[str] | None = None
) -> list[str]:
    """Re-scrape branches whose rows in `<out_dir>/*.csv` have no activity, in place.

    Each such branch's rows are replaced by a fresh scrape. Other rows are left
    byte-for-byte as they were, and failed branches keep their old rows. Returns the
    failed URLs. Useful after the parser learns a new page layout.
    """
    failed: list[str] = []
    found = updated = 0
    for path in sorted(out_dir.glob("*.csv")):
        old = pd.read_csv(path, dtype=str, keep_default_na=False)
        slug = old["district_slug"].iloc[0] if len(old) else path.stem
        if slug in SINGLE_BRANCH_PAGES or (only and slug not in only):
            continue
        has_activity = old["activity"].ne("").groupby(old["branch_slug"]).any()
        empty = has_activity[~has_activity].index.tolist()
        if not empty:
            continue
        found += len(empty)
        log.info("%s: %d branch(es) without activities", path.name, len(empty))
        district = District(
            name=old["district"].iloc[0], slug=slug, url=DISTRICTS_URL + slug
        )
        parts: list[pd.DataFrame] = []
        for branch_slug, rows in old.groupby("branch_slug", sort=False):
            if branch_slug not in empty:
                parts.append(rows)
                continue
            first = rows.iloc[0]
            branch = Branch(
                name=first["branch"], slug=branch_slug, url=first["branch_url"]
            )
            df, branch_failed = scrape_district(client, district, [branch])
            failed += branch_failed
            if branch_failed or not df["activity"].ne("").any():
                parts.append(rows)  # nothing new: keep the old rows
                continue
            updated += 1
            parts.append(df)
        _write_atomic(pd.concat(parts)[COLUMNS], path)
    log.info("%d of %d empty branch(es) now have activities", updated, found)
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
        "--limit-branches",
        type=int,
        help="at most N branches per district "
        "(also N activity category pages for Oslo and nested activity pages)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-scrape districts that already have a CSV",
    )
    parser.add_argument(
        "--only-empty",
        action="store_true",
        help="re-scrape only branches without activities in existing CSVs, in place",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S"
    )
    only = set(args.district) if args.district else None
    if args.only_empty:
        failed = rescrape_empty(PoliteClient(), args.out, only=only)
    else:
        failed = scrape(
            PoliteClient(),
            args.out,
            only=only,
            limit_branches=args.limit_branches,
            force=args.force,
        )
    if failed:
        log.warning("%d page(s) failed:\n  %s", len(failed), "\n  ".join(failed))
        raise SystemExit(1)
    log.info("Done.")
