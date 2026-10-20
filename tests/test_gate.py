"""The two numbers that decide whether this product is honest.

A significance gate can fail in two directions and only one of them is loud:

* **Too loose** — it lets noise through. Invisible: every individual output looks
  like a result.
* **Too strict** — it rejects everything. Also invisible, and worse, it *looks*
  rigorous. A tool that always says REJECT has a perfect false-positive rate.

So the calibration test runs both, and a change that breaks either one fails CI.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from alphaledger.gate.engine import (
    benjamini_hochberg,
    cross_family_alpha,
    decide,
    required_ic_mean,
)
from alphaledger.stats.ic import cross_sectional_rank_ic
from alphaledger.stats.maxstat import max_stat_null


def _family_ics(n_factors: int, *, T: int, N: int, seed: int, signal_ic: float = 0.0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    factor = rng.standard_normal((T, N))
    rho = 2.0 * np.sin(np.pi * signal_ic / 6.0) if signal_ic else 0.0
    forward = np.sqrt(max(1 - rho**2, 0.0)) * rng.standard_normal((T, N)) + rho * factor

    ics = [cross_sectional_rank_ic(factor, forward)]
    for _ in range(n_factors - 1):
        ics.append(cross_sectional_rank_ic(rng.standard_normal((T, N)), forward))
    return np.column_stack(ics)


def test_false_positive_rate_is_controlled():
    """Eight independent studies of 100 noise factors. A 5% gate may not fire often."""
    passes = 0
    studies = 8
    for seed in range(studies):
        ics = _family_ics(100, T=250, N=200, seed=1000 + seed)
        est = max_stat_null(ics, n_boot=400, alpha=0.05, rng=np.random.default_rng(seed))
        if est["p_family"] <= 0.05:
            passes += 1
    rate = passes / studies
    assert rate <= 0.15, f"false-positive rate {rate:.0%} over {studies} studies is too high"


def test_power_on_a_planted_factor():
    """A real edge must survive the correction, or the gate is just a very confident NO."""
    passes = 0
    studies = 4
    for seed in range(studies):
        ics = _family_ics(80, T=500, N=250, seed=2000 + seed, signal_ic=0.03)
        est = max_stat_null(ics, n_boot=400, alpha=0.05, rng=np.random.default_rng(seed))
        if est["p_family"] <= 0.05:
            passes += 1
    assert passes / studies >= 0.75, f"power {passes}/{studies} is too low — the gate rejects real edges"


def test_threshold_matches_the_theory_of_extremes():
    """For independent trials E[max|Z|] ~ 2.97 at N=200, 95th percentile ~ 3.66."""
    ics = _family_ics(200, T=250, N=200, seed=99)
    est = max_stat_null(ics, n_boot=1500, alpha=0.05, rng=np.random.default_rng(3))
    assert 2.6 <= est["bar_sigma"] <= 3.3
    assert 3.3 <= est["bar_q95"] <= 4.0


def test_insufficient_dates_refuses_to_answer():
    ics = np.random.default_rng(0).standard_normal((40, 20))
    est = max_stat_null(ics, n_boot=100)
    assert est["confidence"] == "insufficient"
    assert np.isnan(est["p_family"])


def test_leak_outranks_significance():
    verdict = decide(
        n_dates=250, t_obs=99.0, p_family=0.0, bar_q95=3.6, leak_flag="ranks == returns"
    )
    assert verdict["verdict"] == "LABEL_CONTAMINATION"


def test_direction_mismatch_rejects_even_when_significant():
    verdict = decide(
        n_dates=250, t_obs=9.0, p_family=0.0001, bar_q95=3.6, direction=-1, expected_direction=1
    )
    assert verdict["verdict"] == "REJECT"
    assert verdict["reason_code"] == "direction_mismatch"


def test_pass_and_reject_on_the_boundary():
    assert decide(n_dates=250, t_obs=4.0, p_family=0.05, bar_q95=3.6)["verdict"] == "PASS"
    assert decide(n_dates=250, t_obs=2.0, p_family=0.06, bar_q95=3.6)["verdict"] == "REJECT"


def test_required_ic_is_consistent_with_the_threshold():
    """If a factor hit exactly the required IC, its t would equal the threshold."""
    ic_std, n_dates, bar = 0.05, 250, 3.6
    needed = required_ic_mean(bar, ic_std, n_dates)
    t_implied = needed / (ic_std / np.sqrt(n_dates))
    assert t_implied == pytest.approx(bar, rel=1e-9)


def test_cross_family_alpha_compounds():
    assert cross_family_alpha(0.05, 1) == pytest.approx(0.05)
    assert cross_family_alpha(0.05, 10) == pytest.approx(1 - 0.95**10)
    assert cross_family_alpha(0.05, 10) > 0.39


def test_benjamini_hochberg_is_monotone_and_bounded():
    q = benjamini_hochberg([0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205])
    assert all(q[i] <= q[i + 1] + 1e-12 for i in range(len(q) - 1))
    assert max(q) <= 1.0
    assert q[0] == pytest.approx(0.008)


def test_p_family_belongs_to_the_trial_not_to_the_family_maximum():
    """A weak trial in a family containing a strong one must not inherit its p-value.

    This was a real bug: `evaluate` used to pass the family maximum as the observed
    statistic, so one genuine discovery made every later noise factor "significant".
    """
    ics = _family_ics(50, T=250, N=200, seed=321, signal_ic=0.10)

    weak_t = 0.4
    est = max_stat_null(ics, n_boot=400, alpha=0.05, rng=np.random.default_rng(1), t_obs=weak_t)
    assert est["t_obs"] == pytest.approx(weak_t)
    assert est["p_family"] > 0.5, "a t of 0.4 must never look family-significant"

    best = max_stat_null(ics, n_boot=400, alpha=0.05, rng=np.random.default_rng(1))
    assert best["t_obs"] > weak_t, "the default remains the family maximum, for leaderboards"


def test_a_strong_member_does_not_lift_a_weak_one_through_the_gate():
    """End to end through run_evaluation: the bug users would actually hit."""
    import tempfile

    from alphaledger.evaluate import run_evaluation
    from alphaledger.store import Ledger

    ledger = Ledger(Path(tempfile.mkdtemp()) / "l.db")
    rng = np.random.default_rng(3)
    T, N = 250, 200

    rho = 2 * np.sin(np.pi * 0.15 / 6)
    strong = rng.standard_normal((T, N))
    forward = np.sqrt(1 - rho**2) * rng.standard_normal((T, N)) + rho * strong
    first = run_evaluation(strong, forward, ledger=ledger, horizon=5, with_gate=True)
    assert first.gate["verdict"] == "PASS"

    noise = rng.standard_normal((T, N))
    second = run_evaluation(noise, forward, ledger=ledger, horizon=5, with_gate=True)
    assert second.stats["t_iid"] < 2.0
    assert second.gate["verdict"] == "REJECT", (
        "a noise factor must be judged on its own t, not on the family's best"
    )
    ledger.close()


def test_expected_direction_follows_the_ic_sign_not_the_fingerprint_bit():
    base = dict(n_dates=250, t_obs=9.0, p_family=0.0001, bar_q95=3.6)
    assert decide(**base, direction=-1, expected_direction=1)["verdict"] == "REJECT"
    assert decide(**base, direction=1, expected_direction=1)["verdict"] == "PASS"
