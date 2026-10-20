"""Near-duplicate detection. Reports; never merges.

Two factors can be algebraically different and statistically almost the same:
``momentum_20`` and ``momentum_20 + 0.01 * noise`` correlate at 0.97 but are not
the same hypothesis by the rank test. The honest treatment is to surface the
similarity and let the human decide, because the alternative — auto-merging — is
exactly the loophole that lets "I only tweaked a parameter" escape the trial count.
"""

from __future__ import annotations

import numpy as np

__all__ = ["max_abs_corr", "NEAR_DUPLICATE_THRESHOLD"]

NEAR_DUPLICATE_THRESHOLD = 0.95


def max_abs_corr(a: np.ndarray, b: np.ndarray, min_overlap: int = 60) -> float | None:
    """Largest ``|corr|`` between two IC series on their overlapping dates.

    Returns ``None`` when there are fewer than ``min_overlap`` shared dates or when
    either series is constant on the overlap — in both cases the number would be
    noise dressed as evidence.
    """
    x = np.asarray(a, dtype=np.float64)
    y = np.asarray(b, dtype=np.float64)
    n = min(x.size, y.size)
    if n == 0:
        return None
    x, y = x[:n], y[:n]
    mask = np.isfinite(x) & np.isfinite(y)
    if int(mask.sum()) < min_overlap:
        return None
    x, y = x[mask], y[mask]
    dx, dy = x - x.mean(), y - y.mean()
    denom = float(np.sqrt((dx @ dx) * (dy @ dy)))
    if denom <= 0:
        return None
    return abs(float(dx @ dy) / denom)
