"""Synthetic panels with a known answer.

Every test in this project is built on data where the truth is known by
construction. That is the only way to distinguish "the code runs" from "the code
is right", and it is the thing none of the existing dsh quant plugins do.

The key identity: for a Gaussian copula, a target Spearman correlation ``rho_s``
corresponds to a Pearson correlation ``rho_p = 2 * sin(pi * rho_s / 6)``. So we can
plant an exact rank IC and assert the estimator recovers it.
"""

from __future__ import annotations

import numpy as np
import pytest


def make_panel(
    T: int = 250,
    N: int = 300,
    seed: int = 0,
    signal_ic: float = 0.0,
    nan_frac: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(factor, forward)`` panels of shape ``(T, N)``.

    ``rank_ic(factor[:, t], forward[:, t])`` has expectation ``signal_ic`` on every
    date: the factor is a standard normal, and the forward return mixes it with
    independent noise in the proportion implied by the Gaussian copula.

    Args:
        T: number of dates.
        N: number of names.
        seed: everything is seeded; these panels are reproducible to the bit.
        signal_ic: target cross-sectional Spearman IC.
        nan_frac: fraction of cells (in both panels) blanked to NaN, to exercise
            universe gaps the way suspensions and late listings do.
    """
    rng = np.random.default_rng(seed)

    factor = rng.standard_normal((T, N))

    rho_p = 2.0 * np.sin(np.pi * signal_ic / 6.0) if signal_ic else 0.0
    rho_p = float(np.clip(rho_p, -0.999, 0.999))
    noise = rng.standard_normal((T, N))
    forward = np.sqrt(max(1.0 - rho_p**2, 0.0)) * noise + rho_p * factor

    if nan_frac > 0:
        mask = rng.random((T, N)) < nan_frac
        factor = np.where(mask, np.nan, factor)
        forward = np.where(mask, np.nan, forward)

    return factor, forward


def make_noise_family(n_factors: int = 200, T: int = 250, N: int = 300, seed: int = 0):
    """``n_factors`` mutually independent pure-noise factors against one return panel."""
    rng = np.random.default_rng(seed)
    factors = rng.standard_normal((n_factors, T, N))
    forward = rng.standard_normal((T, N))
    return factors, forward


@pytest.fixture
def noise_panel():
    """A single pure-noise panel pair: truth is IC = 0."""
    return make_panel(T=250, N=300, seed=7, signal_ic=0.0)
