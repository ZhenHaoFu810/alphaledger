"""Integer average ranks.

Ranks are the atomic unit of this whole project: the value fingerprint hashes
ranks, and RankIC is a correlation between ranks. Both need the same definition,
so it lives here and nowhere else.

Two decisions that look pedantic and are not:

* Ranks are returned as ``2 * rank`` so that tied groups (whose average rank is
  a half-integer) stay exactly representable as int32. No floats anywhere in the
  identity path, so there is no rounding to disagree about between platforms.
* Ties share the mean of the positions they span (the "average" convention, same
  as scipy's default). Any other convention changes the fingerprint of every
  factor with ties, which on A-share data is most of them.
"""

from __future__ import annotations

import numpy as np


def average_rank_int(values: np.ndarray) -> np.ndarray:
    """1-based average ranks as ``2 * rank``.

    Args:
        values: 1-D array, no NaN (callers filter first). Any numeric dtype.

    Returns:
        int32 array, same order as ``values``. A unique minimum gets 2, the next
        4, and so on; a tie spanning positions 3 and 4 gets 7 both (= 2 * 3.5).

    Raises:
        ValueError: if the input is not 1-D or contains NaN.
    """
    arr = np.asarray(values)
    if arr.ndim != 1:
        raise ValueError(f"average_rank_int expects 1-D input, got shape {arr.shape}")
    n = arr.size
    if n == 0:
        return np.empty(0, dtype=np.int32)
    if np.isnan(arr).any():
        raise ValueError("average_rank_int received NaN; filter with isfinite first")

    # Stable sort so that equal values keep input order and the grouping below is
    # deterministic across numpy versions.
    order = np.argsort(arr, kind="stable")
    sorted_vals = arr[order]

    group_start = np.empty(n, dtype=bool)
    group_start[0] = True
    np.not_equal(sorted_vals[1:], sorted_vals[:-1], out=group_start[1:])
    group_id = np.cumsum(group_start) - 1

    counts = np.bincount(group_id, minlength=group_id[-1] + 1)
    ends = np.cumsum(counts)              # 1-based position of the last member
    starts = ends - counts + 1            # 1-based position of the first member
    doubled = (starts + ends)[group_id]   # (start + end) == 2 * average rank

    out = np.empty(n, dtype=np.int32)
    out[order] = doubled
    return out


def ranks_to_float(doubled: np.ndarray) -> np.ndarray:
    """Convert ``2 * rank`` back to float ranks, for correlation math only."""
    return np.asarray(doubled, dtype=np.float64) * 0.5
