"""Shared fixture: a constructed tidy chain with hand-known feature answers."""

import numpy as np
import pandas as pd
import pytest

from optpipe.snapshot import COLUMNS


def build_chain(
    spot=100.0,
    snapshot_date="2026-07-02",
    expiries=(("2026-08-01", 30), ("2026-09-30", 90)),
    strikes=(80, 90, 95, 100, 105, 110, 120),
    iv_by_expiry=(0.20, 0.25),
    skew_slope=0.4,
    straddle_mid=4.0,
) -> pd.DataFrame:
    """Synthetic snapshot: linear-in-moneyness smile, known ATM IVs.

    iv(strike) = base_iv + skew_slope * (1 - strike/spot)
    so at 95/105 the put-minus-call spread is skew_slope * 0.10.
    """
    rows = []
    for (expiry, dte), base_iv in zip(expiries, iv_by_expiry):
        for strike in strikes:
            moneyness = strike / spot
            iv = base_iv + skew_slope * (1.0 - moneyness)
            for option_type in ("call", "put"):
                mid = straddle_mid / 2.0 if strike == spot else max(
                    0.5, abs(spot - strike) * 0.5)
                rows.append({
                    "ticker": "TEST", "snapshot_date": pd.Timestamp(snapshot_date),
                    "spot": spot, "expiry": pd.Timestamp(expiry), "dte": dte,
                    "option_type": option_type, "strike": float(strike),
                    "bid": mid - 0.05, "ask": mid + 0.05, "mid": mid,
                    "last": mid, "iv": iv, "volume": 100, "open_interest": 1000,
                    "moneyness": moneyness,
                })
    return pd.DataFrame(rows)[COLUMNS]


@pytest.fixture
def chain() -> pd.DataFrame:
    return build_chain()
