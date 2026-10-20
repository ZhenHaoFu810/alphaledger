"""Cross-sectional RankIC, one number per date.

This is deliberately *not* a time-series correlation of a flattened panel. The
distinction matters and most tools get it wrong:

* Correct: on each date, correlate the cross-section of factor values against the
  cross-section of forward returns, then treat the resulting per-date ICs as a
  time series.
* Wrong: flatten (dates x stocks) into one long vector and correlate. That mixes
  cross-sectional and time-series variation, and on a panel where every stock
  drifts over time it will happily report a large "IC" for a constant factor.

RankIC uses ranks, not levels, so it is insensitive to outliers and monotone
transforms. That is also why the value fingerprint can hash ranks: if two factors
have the same ranks every day, they have the same RankIC to the last bit, so they
are the same trial, not two.
"""

from __future__ import annotations

import numpy as np

from alphaledger.stats.rank import average_rank_int

__all__ = ["cross_sectional_rank_ic", "ic_summary"]


def cross_sectional_rank_ic(
    factor: np.ndarray,
    forward: np.ndarray,
    min_stocks: int = 30,
) -> np.ndarray:
    """Per-date RankIC.

    Args:
        factor: ``(T, N)`` factor values. NaN means "not in the universe".
        forward: ``(T, N)`` forward returns, aligned so ``forward[t]`` is the
            return earned *after* deciding on ``factor[t]``. The caller owns the
            shift; this function never shifts anything. (An off-by-one shift here
            is the single most common source of look-ahead in factor research.)
        min_stocks: skip a date with fewer than this many names on both sides.
            Below roughly 30 names a rank correlation is mostly noise, and
            including those dates silently inflates the IC's t-statistic.

    Returns:
        float64 array of length ``T``; NaN where the date was skipped.

    Raises:
        ValueError: if the two panels differ in shape.
    """
    f = np.asarray(factor, dtype=np.float64)
    r = np.asarray(forward, dtype=np.float64)
    if f.shape != r.shape:
        raise ValueError(f"factor {f.shape} and forward {r.shape} must have the same shape")
    if f.ndim != 2:
        raise ValueError(f"expected a (T, N) panel, got shape {f.shape}")

    n_dates = f.shape[0]
    out = np.full(n_dates, np.nan, dtype=np.float64)

    for t in range(n_dates):
        ft, rt = f[t], r[t]
        valid = np.isfinite(ft) & np.isfinite(rt)
        if int(valid.sum()) < min_stocks:
            continue
        rf = average_rank_int(ft[valid]).astype(np.float64)
        rr = average_rank_int(rt[valid]).astype(np.float64)

        rf -= rf.mean()
        rr -= rr.mean()
        denom = np.sqrt(float(rf @ rf) * float(rr @ rr))
        if denom <= 0.0:
            # Constant factor or constant returns on this date: no rank variation,
            # so the correlation is undefined rather than zero.
            continue
        out[t] = float(rf @ rr) / denom

    return out


def ic_summary(ic: np.ndarray) -> dict[str, float | int]:
    """Summarize an IC series.

    ``ic_ir`` is the information ratio of the IC series, not annualized: the
    annualized version depends on the rebalance frequency, and multiplying by
    sqrt(252) on a 5-day-horizon factor is a well-known way to look impressive
    and mean nothing.
    """
    arr = np.asarray(ic, dtype=np.float64)
    valid = arr[np.isfinite(arr)]
    n = int(valid.size)
    if n == 0:
        return {"n": 0, "mean": float("nan"), "std": float("nan"), "ir": float("nan")}

    mean = float(valid.mean())
    std = float(valid.std(ddof=1)) if n > 1 else float("nan")
    ir = mean / std if std and np.isfinite(std) and std > 0 else float("nan")
    return {"n": n, "mean": mean, "std": std, "ir": ir}
