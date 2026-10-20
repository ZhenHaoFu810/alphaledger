"""Newey-West t-statistics and exact two-sided p-values, with no scipy.

The IC series is not i.i.d.: with a 5-day forward horizon, consecutive daily ICs
share four fifths of their return window, so the naive ``mean/std * sqrt(T)``
overstates significance, sometimes by a factor of two. We report both numbers and
let the gap speak.

The p-values use the Student-t distribution with ``T - 1`` degrees of freedom,
computed from the regularized incomplete beta function (Lentz continued fraction,
the standard Numerical Recipes formulation). For T = 250 the difference from the
normal approximation is small but free to get right, and this keeps the package at
"numpy and the standard library" — which is what makes ``uvx`` cold start fast
enough to sit inside an agent's tool timeout.
"""

from __future__ import annotations

import math

import numpy as np

__all__ = [
    "newey_west_lag",
    "hac_variance",
    "newey_west_t",
    "iid_t",
    "student_t_two_sided_p",
    "normal_two_sided_p",
    "skew_kurt",
]


def newey_west_lag(n_obs: int, horizon: int = 1) -> int:
    """Bandwidth rule: ``max(ceil(4 * (T/100)^(2/9)), horizon)``.

    The first term is Newey-West's rule of thumb for a decaying autocovariance.
    The second is a floor: with an h-day forward return, the IC series is
    mechanically MA(h-1), so a bandwidth below ``h`` would cut off correlation
    that is known to exist by construction.
    """
    rule = math.ceil(4.0 * (max(n_obs, 1) / 100.0) ** (2.0 / 9.0))
    return int(max(rule, horizon, 0))


def hac_variance(x: np.ndarray, lag: int) -> float:
    """Newey-West long-run variance of the mean's numerator (Bartlett kernel)."""
    arr = np.asarray(x, dtype=np.float64)
    n = arr.size
    if n < 2:
        return float("nan")
    e = arr - arr.mean()
    gamma0 = float(e @ e) / n
    total = gamma0
    for k in range(1, min(lag, n - 1) + 1):
        gamma_k = float(e[k:] @ e[:-k]) / n
        total += 2.0 * (1.0 - k / (lag + 1.0)) * gamma_k
    return max(total, 0.0)


def newey_west_t(x: np.ndarray, lag: int | None = None, horizon: int = 1) -> tuple[float, int]:
    """Newey-West t-statistic for H0: mean(x) = 0. Returns ``(t, lag_used)``."""
    arr = np.asarray(x, dtype=np.float64)
    arr = arr[np.isfinite(arr)]
    n = arr.size
    if n < 3:
        return float("nan"), 0
    lag_used = newey_west_lag(n, horizon) if lag is None else int(lag)
    s2 = hac_variance(arr, lag_used)
    if not np.isfinite(s2) or s2 <= 0:
        return float("nan"), lag_used
    return float(arr.mean() / math.sqrt(s2 / n)), lag_used


def iid_t(x: np.ndarray) -> float:
    """Plain t-statistic, ignoring autocorrelation. Reported for contrast only."""
    arr = np.asarray(x, dtype=np.float64)
    arr = arr[np.isfinite(arr)]
    n = arr.size
    if n < 3:
        return float("nan")
    sd = arr.std(ddof=1)
    if not np.isfinite(sd) or sd <= 0:
        return float("nan")
    return float(arr.mean() / (sd / math.sqrt(n)))


def skew_kurt(x: np.ndarray) -> tuple[float, float]:
    """Sample skewness and *non-excess* kurtosis (normal = 3.0).

    The deflated-Sharpe correction is written with kurtosis, not excess kurtosis,
    and mixing the two conventions quietly shifts the threshold by a quarter.
    """
    arr = np.asarray(x, dtype=np.float64)
    arr = arr[np.isfinite(arr)]
    n = arr.size
    if n < 4:
        return float("nan"), float("nan")
    e = arr - arr.mean()
    m2 = float(e @ e) / n
    if m2 <= 0:
        return float("nan"), float("nan")
    m3 = float((e**3).sum()) / n
    m4 = float((e**4).sum()) / n
    return m3 / m2**1.5, m4 / m2**2


def _betacf(a: float, b: float, x: float, max_iter: int = 300, eps: float = 3e-14) -> float:
    """Continued fraction for the incomplete beta function (Lentz's method)."""
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    d = tiny if abs(d) < tiny else d
    d = 1.0 / d
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = tiny if abs(d) < tiny else d
        c = 1.0 + aa / c
        c = tiny if abs(c) < tiny else c
        d = 1.0 / d
        h *= d * c

        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = tiny if abs(d) < tiny else d
        c = 1.0 + aa / c
        c = tiny if abs(c) < tiny else c
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def _betai(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta function I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    log_bt = (
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
        + a * math.log(x) + b * math.log1p(-x)
    )
    bt = math.exp(log_bt)
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def student_t_two_sided_p(t: float, df: int) -> float:
    """P(|T| >= |t|) for T ~ Student-t(df). Two-sided, always."""
    if not np.isfinite(t):
        return float("nan")
    if df <= 0:
        return float("nan")
    x = df / (df + t * t)
    return float(_betai(df / 2.0, 0.5, x))


def normal_two_sided_p(z: float) -> float:
    """P(|Z| >= |z|) for a standard normal. Kept for cross-checks."""
    if not np.isfinite(z):
        return float("nan")
    return float(math.erfc(abs(z) / math.sqrt(2.0)))
