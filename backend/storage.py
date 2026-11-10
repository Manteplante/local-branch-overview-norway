"""Tables in, tables out — read by name from data/tables/.

    load("branches")        -> DataFrame, empty if it isn't there (csv, parquet or xlsx)
    save("branches", df)    -> writes data/tables/branches.<FILE_FORMAT>
    tables()                -> ["activities", "branches"]

The pipeline and the app use these same calls. Reads never raise: a missing or broken file
comes back as an empty DataFrame, so the app shows an empty state instead of a stack trace.
Writes do raise.
"""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd

from . import config


def _cache(ttl: int, max_entries: int):
    """`st.cache_data` when a Streamlit runtime is live, otherwise a no-op.

    These modules are also used from plain scripts (`make transform`), where
    `st.cache_data` would only warn.
    """
    try:
        import streamlit as st
        import streamlit.runtime
    except ImportError:
        return lambda func: func
    if streamlit.runtime.exists():
        return st.cache_data(ttl=ttl, max_entries=max_entries)
    return lambda func: func


# ── File formats ──────────────────────────────────────────────────────────────

DATA_SUFFIXES = (".csv", ".parquet", ".xlsx", ".xls")
# What a missing, unreadable or malformed file raises (pyarrow/openpyxl errors are
# ValueErrors; ImportError when the optional reader is not installed).
READ_ERRORS = (OSError, ValueError, ImportError)


def data_suffix() -> str:
    """The extension the pipeline writes, e.g. ".csv"."""
    suffix = f".{config.FILE_FORMAT}"
    if suffix not in DATA_SUFFIXES:
        raise ValueError(
            f"FILE_FORMAT={config.FILE_FORMAT!r} is not supported. "
            f"Use one of: {', '.join(s.lstrip('.') for s in DATA_SUFFIXES)}."
        )
    return suffix


def _read_frame(handle, suffix: str, **kwargs) -> pd.DataFrame:
    if suffix == ".parquet":
        return pd.read_parquet(handle, **kwargs)
    if suffix in (".xlsx", ".xls"):
        return pd.read_excel(handle, **kwargs)
    return pd.read_csv(handle, **kwargs)


def _frame_bytes(df: pd.DataFrame, suffix: str) -> bytes:
    buffer = io.BytesIO()
    if suffix == ".parquet":
        df.to_parquet(buffer, index=False)
    elif suffix in (".xlsx", ".xls"):
        df.to_excel(buffer, index=False)
    else:
        buffer.write(df.to_csv(index=False).encode("utf-8"))
    return buffer.getvalue()


def read_file(path: Path, **kwargs) -> pd.DataFrame:
    """Read one local file, format taken from its extension."""
    with path.open("rb") as handle:
        return _read_frame(handle, path.suffix.lower(), **kwargs)


def write_frame(path: Path, df: pd.DataFrame) -> Path:
    """Write a DataFrame to an explicit path, format taken from its extension."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_frame_bytes(df, path.suffix.lower()))
    return path


# ── Reading ───────────────────────────────────────────────────────────────────


def path(name: str) -> Path | None:
    """The file for a table name, or None. FILE_FORMAT is tried first, so a freshly written
    file wins over an older one left behind in another format."""
    preferred = data_suffix()
    for suffix in (preferred, *(s for s in DATA_SUFFIXES if s != preferred)):
        candidate = config.TABLES_DIR / f"{name}{suffix}"
        if candidate.is_file():
            return candidate
    return None


@_cache(ttl=600, max_entries=8)
def load(name: str, **read_kwargs) -> pd.DataFrame:
    """Read one table by name, in whatever format it was saved. Empty if missing."""
    file = path(name)
    if file is None:
        return pd.DataFrame()
    try:
        return read_file(file, **read_kwargs)
    except READ_ERRORS as exc:
        print(f"[storage] could not read {file.name}: {exc}")
        return pd.DataFrame()


def tables() -> list[str]:
    """Names of every available table, without the extension."""
    if not config.TABLES_DIR.is_dir():
        return []
    return sorted(
        {
            p.stem
            for p in config.TABLES_DIR.iterdir()
            if p.suffix.lower() in DATA_SUFFIXES
        }
    )


def describe() -> str:
    """Where tables are read from, for status messages."""
    return str(config.TABLES_DIR)


# ── Writing ───────────────────────────────────────────────────────────────────


def save(name: str, df: pd.DataFrame) -> Path:
    """Write a table to TABLES_DIR in FILE_FORMAT."""
    path = write_frame(config.TABLES_DIR / f"{name}{data_suffix()}", df)
    print(f"[storage] {path.name}: {len(df):,} rows")
    return path
