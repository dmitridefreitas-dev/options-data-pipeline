"""Fetch an option chain and normalise it into one tidy frame.

One row per contract, one schema forever:

    ticker, snapshot_date, spot, expiry, dte, option_type, strike,
    bid, ask, mid, last, iv, volume, open_interest, moneyness

`tidy_chain` is a pure function of raw frames (testable offline with canned
data); `fetch_chain` is the thin network wrapper around yfinance.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

COLUMNS = [
    "ticker", "snapshot_date", "spot", "expiry", "dte", "option_type", "strike",
    "bid", "ask", "mid", "last", "iv", "volume", "open_interest", "moneyness",
]


def tidy_chain(
    calls: pd.DataFrame,
    puts: pd.DataFrame,
    ticker: str,
    spot: float,
    expiry: str,
    snapshot_date: str | pd.Timestamp,
) -> pd.DataFrame:
    """Normalise one expiry's raw yfinance calls/puts into the tidy schema.

    Mid is (bid+ask)/2 only when both sides are live; a one-sided or empty
    quote yields NaN rather than a fake price. Contracts with no usable
    price at all (no quote, no last) are dropped.
    """
    snapshot_date = pd.Timestamp(snapshot_date).normalize()
    expiry_ts = pd.Timestamp(expiry)
    frames = []
    for raw, option_type in [(calls, "call"), (puts, "put")]:
        if raw is None or len(raw) == 0:
            continue
        f = pd.DataFrame({
            "strike": raw["strike"].astype(float),
            "bid": raw.get("bid", np.nan),
            "ask": raw.get("ask", np.nan),
            "last": raw.get("lastPrice", np.nan),
            "iv": raw.get("impliedVolatility", np.nan),
            "volume": raw.get("volume", np.nan),
            "open_interest": raw.get("openInterest", np.nan),
        })
        f["option_type"] = option_type
        frames.append(f)
    if not frames:
        return pd.DataFrame(columns=COLUMNS)

    out = pd.concat(frames, ignore_index=True)
    both_sides = (out["bid"] > 0) & (out["ask"] > 0)
    out["mid"] = np.where(both_sides, (out["bid"] + out["ask"]) / 2.0, np.nan)

    priceless = out["mid"].isna() & (out["last"].isna() | (out["last"] <= 0))
    out = out[~priceless].copy()

    out["ticker"] = ticker
    out["snapshot_date"] = snapshot_date
    out["spot"] = float(spot)
    out["expiry"] = expiry_ts
    out["dte"] = int((expiry_ts - snapshot_date).days)
    out["moneyness"] = out["strike"] / float(spot)
    return out[COLUMNS].sort_values(["option_type", "strike"]).reset_index(drop=True)


DEFAULT_TARGET_DTES = (7, 14, 21, 30, 45, 60, 90, 120)


def fetch_chain(
    ticker: str,
    target_dtes: tuple[int, ...] = DEFAULT_TARGET_DTES,
    snapshot_date: str | pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Fetch the expiries nearest each target DTE into one tidy frame.

    Liquid ETFs now list *daily* expirations, so "the first N expiries" can
    span two weeks and miss the term structure entirely. Selecting by
    target days-to-expiry keeps snapshots compact while spanning the curve.
    """
    import yfinance as yf

    tk = yf.Ticker(ticker)
    expiries = tk.options
    if not expiries:
        raise RuntimeError(f"no option expiries returned for {ticker!r}")

    history = tk.history(period="5d")
    if history.empty:
        raise RuntimeError(f"no spot history returned for {ticker!r}")
    spot = float(history["Close"].iloc[-1])
    if snapshot_date is None:
        snapshot_date = history.index[-1].tz_localize(None).normalize()
    snapshot_ts = pd.Timestamp(snapshot_date).normalize()

    dtes = pd.Series({e: (pd.Timestamp(e) - snapshot_ts).days for e in expiries})
    chosen = sorted({(dtes - target).abs().idxmin() for target in target_dtes})

    pieces = []
    for expiry in chosen:
        chain = tk.option_chain(expiry)
        pieces.append(tidy_chain(chain.calls, chain.puts, ticker, spot,
                                 expiry, snapshot_date))
    return pd.concat(pieces, ignore_index=True)
