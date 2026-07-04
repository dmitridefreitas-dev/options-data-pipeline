"""Derived features from tidy snapshots.

Per-snapshot (cross-sectional) features:
    atm_iv          IV at the strike nearest spot, call/put averaged
    term_structure  ATM IV per expiry with days-to-expiry
    term_slope      far-minus-near ATM IV (default ~90d minus ~30d)
    skew            OTM-put IV minus OTM-call IV at symmetric moneyness
    expected_move   ATM straddle mid / spot, per expiry

Across-history feature (needs accumulated snapshots):
    iv_rank         where today's ATM IV sits in its own trailing range

All functions are pure frame-in / number-out, so every one is tested
offline against constructed chains with hand-known answers.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _one_expiry(chain: pd.DataFrame, expiry) -> pd.DataFrame:
    sub = chain[chain["expiry"] == pd.Timestamp(expiry)]
    if sub.empty:
        raise ValueError(f"no contracts for expiry {expiry}")
    return sub


def atm_iv(chain: pd.DataFrame, expiry) -> float:
    """IV at the strike nearest spot, averaging call and put when both quote."""
    sub = _one_expiry(chain, expiry).dropna(subset=["iv"])
    if sub.empty:
        return float("nan")
    spot = sub["spot"].iloc[0]
    nearest = (sub["strike"] - spot).abs().min()
    at_the_money = sub[(sub["strike"] - spot).abs() == nearest]
    return float(at_the_money["iv"].mean())


def term_structure(chain: pd.DataFrame) -> pd.DataFrame:
    """ATM IV and DTE for every expiry in the snapshot, nearest first."""
    rows = []
    for expiry in sorted(chain["expiry"].unique()):
        sub = chain[chain["expiry"] == expiry]
        rows.append({
            "expiry": pd.Timestamp(expiry),
            "dte": int(sub["dte"].iloc[0]),
            "atm_iv": atm_iv(chain, expiry),
        })
    return pd.DataFrame(rows)


def term_slope(chain: pd.DataFrame, near_dte: int = 30, far_dte: int = 90) -> float:
    """ATM IV at the expiry nearest `far_dte` minus the one nearest `near_dte`.

    Positive = upward-sloping (normal); negative = inverted, the classic
    stress signature where near-dated protection is bid over far-dated.
    """
    ts = term_structure(chain).dropna(subset=["atm_iv"])
    if len(ts) < 2:
        return float("nan")
    near = ts.iloc[(ts["dte"] - near_dte).abs().argmin()]
    far = ts.iloc[(ts["dte"] - far_dte).abs().argmin()]
    if near["expiry"] == far["expiry"]:
        return float("nan")
    return float(far["atm_iv"] - near["atm_iv"])


def skew(chain: pd.DataFrame, expiry, otm: float = 0.05) -> float:
    """OTM-put IV minus OTM-call IV at symmetric moneyness (default 95/105).

    Positive is the equity-index norm: downside protection costs more vol
    than upside participation.
    """
    sub = _one_expiry(chain, expiry).dropna(subset=["iv"])
    puts = sub[sub["option_type"] == "put"]
    calls = sub[sub["option_type"] == "call"]
    if puts.empty or calls.empty:
        return float("nan")
    put_leg = puts.iloc[(puts["moneyness"] - (1.0 - otm)).abs().argmin()]
    call_leg = calls.iloc[(calls["moneyness"] - (1.0 + otm)).abs().argmin()]
    return float(put_leg["iv"] - call_leg["iv"])


def expected_move(chain: pd.DataFrame, expiry) -> float:
    """ATM straddle mid over spot: the market's priced move through expiry."""
    sub = _one_expiry(chain, expiry).dropna(subset=["mid"])
    spot = sub["spot"].iloc[0] if len(sub) else float("nan")
    legs = []
    for option_type in ("call", "put"):
        side = sub[sub["option_type"] == option_type]
        if side.empty:
            return float("nan")
        legs.append(side.iloc[(side["strike"] - spot).abs().argmin()])
    same_strike = legs[0]["strike"] == legs[1]["strike"]
    if not same_strike:
        return float("nan")
    return float((legs[0]["mid"] + legs[1]["mid"]) / spot)


def snapshot_features(chain: pd.DataFrame) -> dict[str, float]:
    """The one-row summary a downstream signal would consume."""
    ts = term_structure(chain).dropna(subset=["atm_iv"])
    if ts.empty:
        raise ValueError("snapshot has no usable IVs")
    near = ts.iloc[(ts["dte"] - 30).abs().argmin()]
    return {
        "spot": float(chain["spot"].iloc[0]),
        "atm_iv_30d": float(near["atm_iv"]),
        "term_slope": term_slope(chain),
        "skew_30d": skew(chain, near["expiry"]),
        "expected_move_30d": expected_move(chain, near["expiry"]),
    }


def iv_rank(current_iv: float, historical_ivs) -> float:
    """Where current IV sits in its own history: 0 = at the low, 1 = at the high.

    The options trader's normalisation: 25% IV is cheap for one name and
    rich for another; rank makes them comparable. Needs history — which is
    exactly why the pipeline stores every snapshot it takes.
    """
    history = np.asarray(historical_ivs, dtype=float)
    history = history[~np.isnan(history)]
    if len(history) < 2:
        return float("nan")
    low, high = history.min(), history.max()
    if high == low:
        return 0.5
    return float(np.clip((current_iv - low) / (high - low), 0.0, 1.0))
