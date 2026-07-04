"""Feature functions against the constructed chain's hand-known answers."""

import numpy as np
import pytest

from optpipe import features
from tests.conftest import build_chain


class TestAtmIV:
    def test_picks_strike_nearest_spot(self, chain):
        # At strike 100 == spot, iv = base_iv exactly (smile term vanishes).
        assert features.atm_iv(chain, "2026-08-01") == pytest.approx(0.20)
        assert features.atm_iv(chain, "2026-09-30") == pytest.approx(0.25)

    def test_unknown_expiry_raises(self, chain):
        with pytest.raises(ValueError, match="no contracts"):
            features.atm_iv(chain, "2030-01-01")


class TestTermStructure:
    def test_orders_by_expiry_with_correct_ivs(self, chain):
        ts = features.term_structure(chain)
        assert ts["dte"].tolist() == [30, 90]
        assert ts["atm_iv"].tolist() == pytest.approx([0.20, 0.25])

    def test_slope_is_far_minus_near(self, chain):
        assert features.term_slope(chain) == pytest.approx(0.05)

    def test_inverted_term_structure_is_negative(self):
        inverted = build_chain(iv_by_expiry=(0.40, 0.22))  # stress shape
        assert features.term_slope(inverted) == pytest.approx(-0.18)

    def test_single_expiry_has_no_slope(self):
        single = build_chain(expiries=(("2026-08-01", 30),), iv_by_expiry=(0.2,))
        assert np.isnan(features.term_slope(single))


class TestSkew:
    def test_matches_constructed_smile(self, chain):
        # iv(95 put) - iv(105 call) = skew_slope * (0.05 + 0.05) = 0.04
        assert features.skew(chain, "2026-08-01", otm=0.05) == pytest.approx(0.04)

    def test_flat_smile_has_zero_skew(self):
        flat = build_chain(skew_slope=0.0)
        assert features.skew(flat, "2026-08-01") == pytest.approx(0.0)


class TestExpectedMove:
    def test_straddle_over_spot(self, chain):
        # ATM call mid + put mid = 4.0 on spot 100 -> 4%
        assert features.expected_move(chain, "2026-08-01") == pytest.approx(0.04)


class TestSnapshotFeatures:
    def test_one_row_summary(self, chain):
        summary = features.snapshot_features(chain)
        assert summary["atm_iv_30d"] == pytest.approx(0.20)
        assert summary["term_slope"] == pytest.approx(0.05)
        assert summary["skew_30d"] == pytest.approx(0.04)
        assert summary["expected_move_30d"] == pytest.approx(0.04)


class TestIVRank:
    def test_extremes_and_middle(self):
        history = [0.10, 0.20, 0.30]
        assert features.iv_rank(0.30, history) == 1.0
        assert features.iv_rank(0.10, history) == 0.0
        assert features.iv_rank(0.20, history) == pytest.approx(0.5)

    def test_needs_history(self):
        assert np.isnan(features.iv_rank(0.2, [0.2]))

    def test_constant_history_is_middling(self):
        assert features.iv_rank(0.2, [0.2, 0.2, 0.2]) == 0.5
