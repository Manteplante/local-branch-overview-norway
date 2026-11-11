"""Configuration — the only module that reads the environment.

Every value has a working default, so no setup is needed. Override one with an environment
variable, e.g. `TABLES_DIR=/tmp/tables make run`.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # the repo root, not backend/


def _text(name: str, default: str = "") -> str:
    return (os.getenv(name) or "").strip() or default


def _dir(name: str, default: str) -> Path:
    raw = Path(_text(name, default)).expanduser()
    return raw if raw.is_absolute() else (ROOT / raw).resolve()


APP_NAME = _text("APP_NAME", "Røde Kors lokalforeninger")
APP_ICON = _text("APP_ICON", "🗺️")

RAW_DIR = _dir("RAW_DIR", "data/raw")  # what the scraper writes (gitignored)
TABLES_DIR = _dir("TABLES_DIR", "data/tables")  # what the app reads (committed)
ASSETS_DIR = _dir("ASSETS_DIR", "assets")

# What the pipeline *writes*: csv, parquet, or xlsx. Reading accepts all three.
#   csv      readable anywhere, diffs well in PRs  (the default: our tables are small)
#   parquet  smallest and fastest, keeps dtypes    (needs pyarrow)
#   xlsx     only when a human needs to open it in Excel (needs openpyxl)
FILE_FORMAT = _text("FILE_FORMAT", "csv").strip(".").lower()

# Geocoding (`make geocode`, see docs/missing-data-quality.md). Billable: it only calls
# Google when the key is set *and* GOOGLE_GEOCODING_CONFIRM=1.
GOOGLE_API_TOKEN = _text("GOOGLE_API_TOKEN")
GOOGLE_GEOCODING_CONFIRM = _text("GOOGLE_GEOCODING_CONFIRM") == "1"
MAX_GEOCODE_REQUESTS = int(_text("MAX_GEOCODE_REQUESTS", "100"))
GEOCODE_CACHE = _dir("GEOCODE_CACHE", "data/geocode_cache.csv")  # committed
