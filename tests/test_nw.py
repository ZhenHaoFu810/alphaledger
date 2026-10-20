"""Newey-West t and the exact two-sided p-values.

Two things are being tested here that are easy to get silently wrong:

1. The autocorrelation correction must actually widen the interval for a series
   that is positively autocorrelated (otherwise overlapping horizons look free).
2. The Student-t tail must be the real thing, not a normal approximation wearing
   a t-distribution's name. The known values below are exact to the digit.
"""

from __future__ import annotations

import numpy as np
import pytest

from alphaledger.stats.nw import (
    hac_variance,
    iid_t,
    newey_west_lag,
    newey_west_t,
    normal_two_sided_p,
    skew_kurt,
    student_t_two_sided_p,
)


def test_lag_rule_matches_the_documented_formula():
    # 4 * (250/100)^(2/9) = 4 * 1.2296... = 4.918... -> ceil 5, floored by horizon 1
    assert newey_west_lag(250, horizon=1) == 5
    # an overlapping 5-day horizon raises the floor to 5 (already satisfied above)
    assert newey_west_lag(250, horizon=5) == 5
    # a 20-day horizon must dominate the rule of thumb
    assert newey_west_lag(250, horizon=20) == 20


def test_hac_with_zero_lag_is_just_the_sample_variance():
    x = np.random.default_rng(0).standard_normal(200)
    assert hac_variance(x, lag=0) == pytest.approx(float(x.var(ddof=0)), rel=1e-12)


def test_autocorrelation_shrinks_the_t_statistic():
    """AR(1) with rho=0.5: the naive t is inflated, the HAC t must be visibly smaller."""
    rng = np.random.default_rng(42)
    n = 400
    rho = 0.5
    eps = rng.standard_normal(n)
    x = np.empty(n)
    x[0] = eps[0]
    for i in range(1, n):
        x[i] = rho * x[i - 1] + eps[i]
    x = x + 0.15  # give it a mean so the t is finite and positive

    t_hac, lag = newey_west_t(x)
    t_naive = iid_t(x)
    assert lag > 0
    assert t_hac < t_naive, "HAC must not be more confident than the i.i.d. t under positive autocorrelation"


def test_newey_west_on_white_noise_is_close_to_the_naive_t():
    x = np.random.default_rng(7).standard_normal(1000)
    t_hac, _ = newey_west_t(x)
    assert t_hac == pytest.approx(iid_t(x), abs=0.6)


@pytest.mark.parametrize(
    ("t", "df", "expected"),
    [
        (12.7062047, 1, 0.05),
        (2.2281389, 10, 0.05),
        (1.959963985, 1_000_000, 0.05),
        (0.0, 250, 1.0),
    ],
)
def test_student_t_two_sided_matches_exact_values(t, df, expected):
    assert student_t_two_sided_p(t, df) == pytest.approx(expected, abs=1e-6)


def test_student_t_tail_is_fatter_than_normal():
    t = 3.0
    assert student_t_two_sided_p(t, df=20) > normal_two_sided_p(t)


def test_normal_two_sided_p_is_the_textbook_value():
    assert normal_two_sided_p(1.959963985) == pytest.approx(0.05, abs=1e-8)


def test_skew_and_kurtosis_use_the_non_excess_convention():
    x = np.random.default_rng(3).standard_normal(20_000)
    skew, kurt = skew_kurt(x)
    assert skew == pytest.approx(0.0, abs=0.06)
    assert kurt == pytest.approx(3.0, abs=0.15), "kurtosis, not excess kurtosis"


def test_degenerate_inputs_do_not_raise():
    assert np.isnan(newey_west_t(np.array([1.0, 2.0]))[0])
    assert np.isnan(iid_t(np.array([1.0, 1.0, 1.0, 1.0])))
    assert np.isnan(student_t_two_sided_p(float("nan"), 10))
