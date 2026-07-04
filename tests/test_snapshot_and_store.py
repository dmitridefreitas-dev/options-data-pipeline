"""Tidying raw chain frames, and the append-only storage contract."""

import numpy as np
import pandas as pd
import pytest

from optpipe.snapshot import COLUMNS, tidy_chain
from optpipe.store import list_snapshots, load_history, load_snapshot, save_snapshot
from tests.conftest import build_chain


def raw_side(strikes, bids, asks, ivs):
    return pd.DataFrame({
        "strike": strikes, "bid": bids, "ask": asks,
        "lastPrice": [max(b, 0.01) for b in bids],
        "impliedVolatility": ivs,
        "volume": [10] * len(strikes), "openInterest": [100] * len(strikes),
    })


class TestTidyChain:
    def test_schema_and_mid(self):
        calls = raw_side([100.0, 110.0], [5.0, 1.0], [5.2, 1.2], [0.2, 0.22])
        puts = raw_side([100.0, 90.0], [4.8, 0.9], [5.0, 1.1], [0.21, 0.24])
        tidy = tidy_chain(calls, puts, "SPY", spot=100.0,
                          expiry="2026-08-21", snapshot_date="2026-07-02")

        assert list(tidy.columns) == COLUMNS
        assert len(tidy) == 4
        atm_call = tidy[(tidy.option_type == "call") & (tidy.strike == 100.0)].iloc[0]
        assert atm_call.mid == pytest.approx(5.1)
        assert atm_call.dte == 50
        assert atm_call.moneyness == pytest.approx(1.0)

    def test_one_sided_quote_has_no_mid(self):
        calls = raw_side([100.0], [0.0], [5.2], [0.2])  # bid dead
        tidy = tidy_chain(calls, None, "SPY", 100.0, "2026-08-21", "2026-07-02")
        assert np.isnan(tidy.iloc[0].mid)
        assert tidy.iloc[0]["last"] > 0  # kept because last trade exists

    def test_priceless_contracts_dropped(self):
        calls = raw_side([100.0, 200.0], [5.0, 0.0], [5.2, 0.0], [0.2, 0.3])
        calls.loc[1, "lastPrice"] = 0.0
        tidy = tidy_chain(calls, None, "SPY", 100.0, "2026-08-21", "2026-07-02")
        assert tidy.strike.tolist() == [100.0]


class TestStore:
    def test_round_trip(self, tmp_path, chain):
        save_snapshot(chain, root=tmp_path)
        loaded = load_snapshot("TEST", "2026-07-02", root=tmp_path)
        assert len(loaded) == len(chain)
        assert list(loaded.columns) == COLUMNS

    def test_append_only(self, tmp_path, chain):
        save_snapshot(chain, root=tmp_path)
        with pytest.raises(FileExistsError, match="append-only"):
            save_snapshot(chain, root=tmp_path)
        save_snapshot(chain, root=tmp_path, overwrite=True)  # explicit is allowed

    def test_history_concatenates_dates(self, tmp_path):
        day1 = build_chain(snapshot_date="2026-07-01")
        day2 = build_chain(snapshot_date="2026-07-02")
        save_snapshot(day1, root=tmp_path)
        save_snapshot(day2, root=tmp_path)

        history = load_history("TEST", root=tmp_path)
        assert history["snapshot_date"].nunique() == 2

        inventory = list_snapshots(root=tmp_path)
        assert inventory["date"].tolist() == ["2026-07-01", "2026-07-02"]

    def test_mixed_tickers_rejected(self, tmp_path, chain):
        mixed = chain.copy()
        mixed.loc[mixed.index[:3], "ticker"] = "OTHER"
        with pytest.raises(ValueError, match="one ticker"):
            save_snapshot(mixed, root=tmp_path)

    def test_empty_rejected(self, tmp_path, chain):
        with pytest.raises(ValueError, match="empty"):
            save_snapshot(chain.iloc[0:0], root=tmp_path)
