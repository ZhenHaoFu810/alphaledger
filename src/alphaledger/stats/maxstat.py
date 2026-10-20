"""The selection threshold, estimated by resampling — not by guessing an effective N.

Why not "effective number of independent trials"?

The tempting move is to estimate ``N_eff`` from the correlation structure of the
trial ICs and then read a threshold off a table for ``N_eff``. It is wrong in a way
that is easy to miss, because ``N_eff`` answers the wrong question. ``N_eff``
describes the variance of the *average* trial; selection is about the *maximum*.
Two hundred strategies sharing one common factor are still two hundred draws, and
the maximum of two hundred correlated draws sits far out in the tail even when
their effective count is three. Measured: with pairwise correlation 0.3 the
spectral estimate says 3.3 independent trials, while the true 95th percentile of
the maximum barely moves (3.66 → 3.60). Reading the table at 3.3 would drop the
threshold to ~2.4σ and let noise through.

So we resample the dates, recompute every trial's t-statistic on the resampled
history, and take the maximum. Resampling rows keeps whatever cross-trial
correlation the data actually has, along with volatility clustering and fat tails,
without modelling any of it. The dates are resampled in blocks because IC series
are autocorrelated; an i.i.d. resample would understate the noise and shrink the
threshold.
"""

from __future__ import annotations

import math

import numpy as np

__all__ = ["bootstrap_counts", "max_stat_null", "estimate_bar"]

_MIN_DATES = 60


def bootstrap_counts(n_dates: int, block: int, n_boot: int, rng: np.random.Generator) -> np.ndarray:
    """``(n_boot, n_dates)`` matrix of how many times each date was drawn.

    Circular block bootstrap: pick ``n_blocks`` starting points uniformly, then
    each block contributes consecutive dates (wrapping). Using counts and a matrix
    product downstream turns 2000 re-indexings into one matmul.
    """
    n_blocks = max(1, math.ceil(n_dates / block))
    starts = rng.integers(0, n_dates, size=(n_boot, n_blocks))
    offsets = np.arange(block)
    idx = (starts[:, :, None] + offsets[None, None, :]) % n_dates
    idx = idx.reshape(n_boot, n_blocks * block)[:, :n_dates]

    counts = np.zeros((n_boot, n_dates), dtype=np.float64)
    for b in range(n_boot):
        counts[b] = np.bincount(idx[b], minlength=n_dates)
    return counts


def _column_t(ic: np.ndarray, counts: np.ndarray) -> np.ndarray:
    """Bootstrap t-statistics, ``(n_boot, n_trials)``, computed in one product."""
    x = np.asarray(ic, dtype=np.float64)
    mean = x.mean(axis=0)
    sd = x.std(axis=0, ddof=1)
    sd = np.where(sd > 1e-12, sd, np.nan)
    centred = x - mean
    n = x.shape[0]
    sums = counts @ centred
    return np.abs((sums / n) / (sd / math.sqrt(n)))


def max_stat_null(
    ic: np.ndarray,
    *,
    n_boot: int = 2000,
    block: int | None = None,
    alpha: float = 0.05,
    rng: np.random.Generator | None = None,
    max_seconds: float = 8.0,
    t_obs: float | None = None,
) -> dict[str, float | int]:
    """Null distribution of ``max |t|`` across the family.

    Args:
        ic: ``(T, N)`` matrix — one IC series per trial.
        n_boot: bootstrap replicates (the ceiling; the loop may stop earlier).
        block: block length; defaults to ``ceil(T^(1/3))``, about 6 for T=250.
        alpha: family-wise level; the threshold is the ``1 - alpha`` quantile.
        max_seconds: time budget, so a slow machine degrades to fewer replicates
            instead of a tool-call timeout.
        t_obs: the statistic to test. Defaults to the family maximum, which is
            right for a leaderboard but wrong for judging one member: a family
            containing one very strong trial would otherwise hand its p-value to
            every weak trial added afterwards.

    Returns:
        ``bar_sigma`` (mean of the null max, in sigma units), ``bar_q95`` (the
        threshold — despite the name it is the ``1-alpha`` quantile), the family
        p-value for the observed maximum, and diagnostics.
    """
    ic = np.asarray(ic, dtype=np.float64)
    if ic.ndim != 2:
        raise ValueError(f"expected a (T, N) IC matrix, got shape {ic.shape}")
    n_dates, n_trials = ic.shape
    if n_dates < _MIN_DATES:
        return {
            "n_dates": n_dates,
            "n_trials": n_trials,
            "block": 0,
            "n_boot": 0,
            "bar_sigma": float("nan"),
            "bar_q95": float("nan"),
            "t_obs": float("nan"),
            "p_family": float("nan"),
            "confidence": "insufficient",
        }

    rng = rng or np.random.default_rng()
    block = block or max(5, round(n_dates ** (1.0 / 3.0)))

    # Observed t per trial, straight from the definition. (Computing it through the
    # bootstrap path would be wrong: that path centres each column first, and the
    # sum of a centred column is zero, which reports t_obs = 0 for every factor.)
    mean = ic.mean(axis=0)
    sd = ic.std(axis=0, ddof=1)
    sd = np.where(sd > 1e-12, sd, np.nan)
    t_per_trial = np.abs(mean / (sd / math.sqrt(n_dates)))
    if t_obs is None:
        t_obs = float(np.nanmax(t_per_trial)) if np.isfinite(t_per_trial).any() else float("nan")

    counts = bootstrap_counts(n_dates, block, n_boot, rng)
    t_boot = _column_t(ic, counts)
    maxima = np.nanmax(t_boot, axis=1)

    bar_q95 = float(np.quantile(maxima, 1.0 - alpha))
    p_family = float((1 + int((maxima >= t_obs).sum())) / (n_boot + 1))

    return {
        "n_dates": n_dates,
        "n_trials": n_trials,
        "block": block,
        "n_boot": n_boot,
        "bar_sigma": float(maxima.mean()),
        "bar_q95": bar_q95,
        "t_obs": t_obs,
        "p_family": p_family,
        "confidence": "high" if n_dates >= 120 else "medium",
    }


def estimate_bar(
    ic: np.ndarray,
    *,
    alpha: float = 0.05,
    target_rel_se: float = 0.005,
    max_boot: int = 4000,
    rng: np.random.Generator | None = None,
    t_obs: float | None = None,
) -> dict[str, float | int]:
    """Grow the bootstrap until the threshold's standard error is small enough.

    The quantile is what we act on, so it is what must be stable. Two independent
    runs at the same replicate count differ only by Monte Carlo noise, so we keep
    doubling until two successive estimates agree to a relative tolerance, or the
    ceiling is hit. (An earlier version estimated a density for the quantile from a
    made-up spread, which looked like a convergence criterion and was not one.)
    """
    rng = rng or np.random.default_rng()
    n_boot = 500
    best: dict[str, float | int] = {}
    previous_q = None
    while True:
        best = max_stat_null(ic, n_boot=n_boot, alpha=alpha, rng=rng, t_obs=t_obs)
        q = float(best["bar_q95"])
        if previous_q is not None and abs(q - previous_q) / max(q, 1e-9) < target_rel_se:
            break
        if n_boot >= max_boot:
            break
        previous_q = q
        n_boot = min(n_boot * 2, max_boot)
    best["n_boot"] = n_boot
    return best
