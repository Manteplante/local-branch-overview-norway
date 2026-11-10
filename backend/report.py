"""Print a markdown snapshot of the data the app is built from.

    make report

Raw files, tables (with their columns) and which tables each page reads, by inspection.
Read-only and never fails: it is a report, not a check. The assertions live in tests/.
"""

from __future__ import annotations

import re

from . import config, storage

PAGES = config.ROOT / "pages"
CALL = re.compile(r"""storage\.load\(\s*["']([^"']+)["']""")
MAX_COLUMNS = 8  # keep the table readable when a frame is very wide


def _rows(path) -> int:
    try:
        return len(storage.read_file(path))
    except storage.READ_ERRORS:
        return 0


def main() -> None:
    out: list[str] = ["### Raw files", ""]
    raw = sorted(
        p for p in config.RAW_DIR.glob("*") if p.suffix.lower() in storage.DATA_SUFFIXES
    )
    if raw:
        out += ["| File | Rows |", "| --- | --- |"]
        out += [f"| `{p.name}` | {_rows(p):,} |" for p in raw]
    else:
        out.append(f"_None in `{config.RAW_DIR}`. Run `make scrape`._")

    out += ["", "### Tables", ""]
    names = storage.tables()
    if names:
        out += ["| Table | Rows | Columns |", "| --- | --- | --- |"]
        for name in names:
            df = storage.load(name)
            cols = list(df.columns)
            shown = ", ".join(f"`{c}`" for c in cols[:MAX_COLUMNS])
            if len(cols) > MAX_COLUMNS:
                shown += f" _(+{len(cols) - MAX_COLUMNS} more)_"
            out.append(f"| `{name}` | {len(df):,} | {shown or '—'} |")
    else:
        out.append("_No tables yet. Run `make transform`._")

    out += ["", "### Pages", "", "| Page | Reads |", "| --- | --- |"]
    for path in sorted(PAGES.glob("[0-9]*.py")):
        text = path.read_text(encoding="utf-8")
        loads = dict.fromkeys(CALL.findall(text))
        if "load_tables(" in text:  # backend.ui.load_tables reads both tables
            loads |= dict.fromkeys(["branches", "activities"])
        shown = ", ".join(f"`{n}`" for n in loads) or "_nothing_"
        out.append(f"| `{path.name}` | {shown} |")

    out += ["", f"_Reading from `{storage.describe()}`._"]
    print("\n".join(out))


if __name__ == "__main__":
    main()
