"""Snapshot every district page plus its first N branch pages into tests/fixtures/sample/.

Uses the same polite client as the scraper (~52 requests, ~10-15 min). Pages already
saved are kept unless --force. Run it when the site
changes and the sample tests need fresh pages: `make fixtures`.
"""

import argparse
import logging
import re
from pathlib import Path

from local_branch_overview.scraper.client import PoliteClient
from local_branch_overview.scraper.parse import (
    DISTRICTS_URL,
    branch_index_url,
    parse_branches,
    parse_districts,
)

log = logging.getLogger(__name__)
OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "sample"
_MAIN = re.compile(r'<main id="main-content-area">.*?</main>', re.DOTALL)
_BLANK_LINES = re.compile(r"\n\s*\n+")


def trim(html: str) -> str:
    """Keep only the <main> content, which is all the parser reads."""
    match = _MAIN.search(html)
    body = match.group(0) if match else html
    body = _BLANK_LINES.sub("\n", body.replace("\r", ""))
    return f"<!doctype html><html><body>\n{body}\n</body></html>\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--branches", type=int, default=2, help="branches per district")
    parser.add_argument(
        "--force", action="store_true", help="re-fetch pages already saved"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    client = PoliteClient()
    (OUT / "districts").mkdir(parents=True, exist_ok=True)
    (OUT / "branches").mkdir(parents=True, exist_ok=True)

    def fetch(url: str, path: Path) -> str:
        """Saved page if there is one (unless --force), else fetch, trim and save it."""
        if path.exists() and not args.force:
            return path.read_text(encoding="utf-8")
        html = trim(client.get(url))
        path.write_text(html, encoding="utf-8")
        return html

    districts = parse_districts(client.get(DISTRICTS_URL))
    for n, district in enumerate(districts, 1):
        log.info("[%d/%d] %s", n, len(districts), district.slug)
        index = OUT / "districts" / f"{district.slug}.html"
        html = fetch(branch_index_url(district), index)
        for branch in parse_branches(html)[: args.branches]:
            fetch(branch.url, OUT / "branches" / f"{district.slug}__{branch.slug}.html")


if __name__ == "__main__":
    main()
