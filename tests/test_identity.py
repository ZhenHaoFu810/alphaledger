"""Factor identity.

The load-bearing assertion in this file is the first one: five different ways of
writing the same factor produce one fingerprint. If that ever fails, the ledger is
counting phantom trials and every number downstream is wrong.
"""

from __future__ import annotations

import numpy as np
import pytest
from conftest import make_panel

from alphaledger.identity import (
    CanonicalizeError,
    canonical_expr,
    expr_fingerprint,
    max_abs_corr,
    value_fingerprint,
)

PANEL = "testpanel0000000"


def test_strict_monotone_rewrites_are_one_factor():
    """rank(x), log(exp(x)) and 2x+3 are strictly monotone: same ranks, same trial."""
    rng = np.random.default_rng(0)
    x = rng.standard_normal((60, 80))

    base, _, _ = value_fingerprint(x, PANEL)
    variants = {
        "rank": np.apply_along_axis(lambda r: np.argsort(np.argsort(r)), 1, x).astype(float),
        "log_exp": np.log(np.exp(x)),
        "affine": 2.0 * x + 3.0,
    }
    for name, variant in variants.items():
        fp, _, _ = value_fingerprint(variant, PANEL)
        assert fp == base, f"{name} should be the same trial as the original"


def test_winsorising_creates_ties_and_is_therefore_a_different_trial():
    """This is the case that forces value-based identity instead of algebraic identity.

    Clipping the tails is only *weakly* monotone: the clipped values all become one
    tie group, so average ranks change and the IC changes with them. Two factors
    that correlate at 0.99 are still two draws, and the ledger must say so.
    """
    rng = np.random.default_rng(0)
    x = rng.standard_normal((60, 80))
    lo, hi = np.quantile(x, 0.01), np.quantile(x, 0.99)
    clipped = np.clip(x, lo, hi)

    fp_x, _, _ = value_fingerprint(x, PANEL)
    fp_c, _, _ = value_fingerprint(clipped, PANEL)
    assert fp_x != fp_c


def test_sign_flip_is_the_same_trial_with_opposite_orientation():
    rng = np.random.default_rng(1)
    x = rng.standard_normal((40, 60))
    fp_pos, orient_pos, _ = value_fingerprint(x, PANEL)
    fp_neg, orient_neg, _ = value_fingerprint(-x, PANEL)
    assert fp_pos == fp_neg
    assert orient_pos == -orient_neg


def test_squaring_is_a_different_factor():
    """x^2 is monotone only on x>0, so for mixed-sign data the ranks genuinely change."""
    rng = np.random.default_rng(2)
    x = rng.standard_normal((40, 60))
    fp_x, _, _ = value_fingerprint(x, PANEL)
    fp_x2, _, _ = value_fingerprint(x**2, PANEL)
    assert fp_x != fp_x2


def test_float32_and_float64_agree():
    rng = np.random.default_rng(3)
    x = rng.standard_normal((30, 50))
    assert value_fingerprint(x, PANEL)[0] == value_fingerprint(x.astype(np.float32).astype(np.float64), PANEL)[0]


def test_swapping_two_ranks_changes_the_fingerprint():
    rng = np.random.default_rng(4)
    x = rng.standard_normal((20, 40))
    fp_a, _, _ = value_fingerprint(x, PANEL)
    y = x.copy()
    y[3, [0, 1]] = y[3, [1, 0]]
    fp_b, _, _ = value_fingerprint(y, PANEL)
    assert fp_a != fp_b


def test_dates_the_ic_skips_do_not_affect_identity():
    """A date that neither the IC nor the fingerprint can use is not part of the factor.

    Both variants below leave date 0 with too few names, so date 0 is dropped in
    both cases and the remaining information is identical. Whether the row holds
    two names or none cannot change what was tested.
    """
    rng = np.random.default_rng(5)
    x = rng.standard_normal((20, 40))
    x[0, 2:] = np.nan          # 2 names on date 0 -> dropped
    y = x.copy()
    y[0, :2] = np.nan          # 0 names on date 0 -> also dropped
    assert value_fingerprint(x, PANEL)[0] == value_fingerprint(y, PANEL)[0]


def test_removing_a_usable_date_does_change_identity():
    """The mirror image: information that *would* have been counted cannot vanish silently."""
    rng = np.random.default_rng(6)
    x = rng.standard_normal((20, 40))
    y = x.copy()
    y[0, :] = np.nan
    assert value_fingerprint(x, PANEL)[0] != value_fingerprint(y, PANEL)[0]


def test_fingerprint_is_panel_scoped():
    rng = np.random.default_rng(6)
    x = rng.standard_normal((20, 40))
    assert value_fingerprint(x, "panelA")[0] != value_fingerprint(x, "panelB")[0]


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("close/delay(close,20)", "close / delay( close , 20 )"),
        ("RANK(x)", "cs_rank(x)"),
        ("shift(x,1)", "delay(x,1)"),
        ("x*1", "x"),
        ("x+0", "x"),
        ("2*x", "x*2"),
        ("a+b+c", "c+a+b"),
        ("x - y", "x + (-y)"),
        ("ln(x)", "log(x)"),
        ("x/1", "x"),
    ],
)
def test_semantically_identical_expressions_canonicalise_the_same(a, b):
    assert canonical_expr(a) == canonical_expr(b)


@pytest.mark.parametrize("a,b", [("x+y", "x*y"), ("x", "x+1"), ("rank(x)", "ts_rank(x)")])
def test_different_expressions_stay_different(a, b):
    assert canonical_expr(a) != canonical_expr(b)


def test_canonical_form_is_idempotent():
    src = "rank(close/delay(close, 20))"
    once = canonical_expr(src)
    assert canonical_expr(once) == once


def test_expr_fingerprint_is_stable_and_prefixed():
    fp1 = expr_fingerprint("rank(close/delay(close,20))")
    fp2 = expr_fingerprint("RANK(close / delay(close, 20))")
    assert fp1 == fp2
    assert fp1 is not None and fp1.startswith("e1:") and len(fp1) == 3 + 16


def test_unparseable_expression_returns_none_instead_of_raising():
    assert expr_fingerprint("close + ") is None
    assert expr_fingerprint("") is None
    with pytest.raises(CanonicalizeError):
        canonical_expr("close + ")


def test_near_duplicate_detection_reports_but_two_distinct_factors_are_not_equal():
    factor, forward = make_panel(T=120, N=200, seed=9, signal_ic=0.03)
    from alphaledger.stats.ic import cross_sectional_rank_ic

    ic1 = cross_sectional_rank_ic(factor, forward)
    noisy = factor + 0.05 * np.random.default_rng(10).standard_normal(factor.shape)
    ic2 = cross_sectional_rank_ic(noisy, forward)

    sim = max_abs_corr(ic1, ic2)
    assert sim is not None and sim > 0.8
    assert value_fingerprint(factor, PANEL)[0] != value_fingerprint(noisy, PANEL)[0], (
        "similarity must never be treated as identity"
    )


def test_max_abs_corr_returns_none_on_thin_overlap():
    a = np.array([1.0, 2.0, np.nan, np.nan])
    b = np.array([1.0, 2.0, np.nan, np.nan])
    assert max_abs_corr(a, b, min_overlap=10) is None
