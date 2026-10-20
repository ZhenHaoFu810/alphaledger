"""Ranks and cross-sectional RankIC.

The reference implementations here are deliberately naive (explicit loops,
``np.corrcoef``) so that a bug in the fast path cannot hide behind the same bug in
a fast reference.
"""

from __future__ import annotations

import numpy as np
import pytest
from conftest import make_panel

from alphaledger.stats.ic import cross_sectional_rank_ic, ic_summary
from alphaledger.stats.rank import average_rank_int


def test_rank_matches_hand_computation():
    values = np.array([10.0, 30.0, 20.0, 50.0, 40.0])
    # sorted: 10,20,30,40,50 -> ranks 1,2,3,4,5 -> doubled 2,4,6,8,10
    assert average_rank_int(values).tolist() == [2, 6, 4, 10, 8]


def test_ties_share_the_average_of_the_positions_they_span():
    values = np.array([5.0, 5.0, 5.0, 9.0])
    # three ties occupy positions 1..3 -> average 2 -> doubled 4; then 4 -> 8
    assert average_rank_int(values).tolist() == [4, 4, 4, 8]


def test_rank_rejects_nan_and_wrong_ndim():
    with pytest.raises(ValueError, match="NaN"):
        average_rank_int(np.array([1.0, np.nan, 3.0]))
    with pytest.raises(ValueError, match="1-D"):
        average_rank_int(np.zeros((3, 2)))


def test_rank_is_scale_invariant_because_it_is_monotone_only():
    x = np.array([1.0, -2.0, 3.0, 0.5])
    assert average_rank_int(x).tolist() == average_rank_int(x * 1000.0).tolist()


def test_ic_is_plus_one_for_a_perfectly_ordered_factor():
    rng = np.random.default_rng(1)
    factor = rng.standard_normal((40, 60))
    ic = cross_sectional_rank_ic(factor, factor.copy(), min_stocks=30)
    assert np.allclose(ic, 1.0, atol=1e-12)


def test_ic_is_minus_one_when_the_factor_is_reversed():
    rng = np.random.default_rng(2)
    factor = rng.standard_normal((40, 60))
    ic = cross_sectional_rank_ic(factor, -factor, min_stocks=30)
    assert np.allclose(ic, -1.0, atol=1e-12)


def test_ic_matches_a_naive_spearman_on_ranks():
    factor, forward = make_panel(T=30, N=80, seed=3, signal_ic=0.0, nan_frac=0.05)
    fast = cross_sectional_rank_ic(factor, forward, min_stocks=30)

    for t in range(factor.shape[0]):
        mask = np.isfinite(factor[t]) & np.isfinite(forward[t])
        if mask.sum() < 30:
            assert np.isnan(fast[t])
            continue
        rf = average_rank_int(factor[t][mask]).astype(float)
        rr = average_rank_int(forward[t][mask]).astype(float)
        expected = np.corrcoef(rf, rr)[0, 1]
        assert fast[t] == pytest.approx(expected, abs=1e-12)


def test_thin_dates_are_nan_not_zero():
    """A date with too few names must be skipped. Returning 0 would drag the mean
    toward zero and, worse, shrink the standard deviation that the t-statistic divides by."""
    factor = np.random.default_rng(4).standard_normal((10, 40))
    factor[:, :35] = np.nan  # only 5 names per date
    ic = cross_sectional_rank_ic(factor, np.isfinite(factor).astype(float), min_stocks=30)
    assert np.all(np.isnan(ic))


def test_constant_factor_yields_nan_rather_than_zero():
    factor = np.ones((20, 50))
    forward = np.random.default_rng(5).standard_normal((20, 50))
    ic = cross_sectional_rank_ic(factor, forward, min_stocks=30)
    assert np.all(np.isnan(ic)), "a constant factor has no rank information; it is undefined, not zero"


def test_planted_ic_is_recovered():
    """The Gaussian-copula construction in conftest must actually plant the IC we ask for."""
    factor, forward = make_panel(T=250, N=300, seed=11, signal_ic=0.05)
    summary = ic_summary(cross_sectional_rank_ic(factor, forward, min_stocks=30))
    assert summary["n"] == 250
    assert summary["mean"] == pytest.approx(0.05, abs=0.012)


def test_shape_mismatch_is_rejected():
    with pytest.raises(ValueError, match="same shape"):
        cross_sectional_rank_ic(np.zeros((5, 4)), np.zeros((5, 5)))
