"""Append-only, date-partitioned snapshot storage.

Layout:  <root>/<YYYY-MM-DD>/<TICKER>.csv

Append-only is a deliberate property, not a missing feature: market
snapshots are facts about a moment, and a pipeline that can silently
rewrite yesterday's facts cannot be trusted as a research input. Saving the
same (date, ticker) twice raises unless `overwrite=True` is said out loud.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from optpipe.snapshot import COLUMNS


def save_snapshot(frame: pd.DataFrame, root: str | Path = "data/snapshots",
                  overwrite: bool = False) -> Path:
    """Persist one ticker's snapshot. Refuses silent overwrites."""
    if frame.empty:
        raise ValueError("refusing to store an empty snapshot")
    tickers = frame["ticker"].unique()
    dates = frame["snapshot_date"].unique()
    if len(tickers) != 1 or len(dates) != 1:
        raise ValueError("one snapshot file = one ticker on one date")

    date_str = pd.Timestamp(dates[0]).strftime("%Y-%m-%d")
    path = Path(root) / date_str / f"{tickers[0]}.csv"
    if path.exists() and not overwrite:
        raise FileExistsError(
            f"{path} already exists — snapshots are append-only "
            "(pass overwrite=True to replace deliberately)"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    return path


def load_snapshot(ticker: str, date: str, root: str | Path = "data/snapshots") -> pd.DataFrame:
    """Load one ticker's snapshot for one date."""
    path = Path(root) / date / f"{ticker}.csv"
    if not path.exists():
        raise FileNotFoundError(f"no snapshot at {path}")
    return _read(path)


def load_history(ticker: str, root: str | Path = "data/snapshots") -> pd.DataFrame:
    """All stored snapshots for a ticker, oldest first."""
    root = Path(root)
    paths = sorted(root.glob(f"*/{ticker}.csv"))
    if not paths:
        raise FileNotFoundError(f"no snapshots for {ticker!r} under {root}")
    return pd.concat([_read(p) for p in paths], ignore_index=True)


def list_snapshots(root: str | Path = "data/snapshots") -> pd.DataFrame:
    """Inventory: one row per stored (date, ticker) with contract counts."""
    root = Path(root)
    rows = []
    for path in sorted(root.glob("*/*.csv")):
        rows.append({
            "date": path.parent.name,
            "ticker": path.stem,
            "contracts": sum(1 for _ in open(path, encoding="utf-8")) - 1,
        })
    return pd.DataFrame(rows)


def _read(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, parse_dates=["snapshot_date", "expiry"])
    missing = set(COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"{path} is missing columns {sorted(missing)}")
    return frame
