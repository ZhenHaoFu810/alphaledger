"""The value fingerprint: a factor's identity is what it ranks, not how it was written.

RankIC depends on the factor only through the cross-sectional ranks of each date.
So if two factors produce the same ranks every day, they produce the same IC, the
same t, the same p — to the last bit. Counting them as two trials would invent
selection pressure that never existed, and would punish a user for writing
``rank(x)`` instead of ``x``.

Hence: hash the ranks, not the source.

Three properties this buys, each with a test:

* **Monotone invariance.** ``x``, ``rank(x)``, ``log(x)`` for positive x, ``2x+3``
  and ``winsorize(x)`` at the ranks they don't touch all collide.
* **Sign invariance.** ``-x`` is the same hypothesis viewed from the other side, so
  the fingerprint is the min of the forward and reversed hashes and the direction
  is recorded separately. Flipping the sign and re-testing is the most common form
  of p-hacking there is; it must not buy a fresh trial.
* **No float comparison anywhere.** Ranks are integers (``2 * rank``), packed as
  int32, hashed as bytes. Two machines either agree byte for byte or they don't —
  there is no tolerance to tune.

What it does *not* do: near-duplicates are reported, never merged. ``x`` and
``x + 0.01 * noise`` may correlate at 0.97; merging them would let "just change a
parameter" escape the count.
"""

from __future__ import annotations

import hashlib
import struct

import numpy as np

from alphaledger.stats.rank import average_rank_int

__all__ = ["FINGERPRINT_VERSION", "BLOB_MAGIC", "rank_pattern", "value_fingerprint"]

FINGERPRINT_VERSION = "v1"
BLOB_MAGIC = b"ALFP1"
_MIN_STOCKS = 3


def rank_pattern(
    factor: np.ndarray, min_stocks: int = _MIN_STOCKS
) -> list[tuple[int, np.ndarray]]:
    """Per-date integer ranks, dropping dates that would not enter the IC anyway.

    Returns ``[(n_valid, doubled_ranks_int32), ...]`` in date order. A date with
    fewer than ``min_stocks`` finite values is dropped entirely, matching
    :func:`alphaledger.stats.ic.cross_sectional_rank_ic`, which skips those dates.
    Keeping them would make the fingerprint sensitive to data the statistics
    never saw.
    """
    arr = np.asarray(factor, dtype=np.float64)
    if arr.ndim != 2:
        raise ValueError(f"expected a (T, N) panel, got shape {arr.shape}")

    pattern: list[tuple[int, np.ndarray]] = []
    for t in range(arr.shape[0]):
        row = arr[t]
        valid = np.isfinite(row)
        n_valid = int(valid.sum())
        if n_valid < max(min_stocks, _MIN_STOCKS):
            continue
        pattern.append((n_valid, average_rank_int(row[valid])))
    return pattern


def _encode(pattern: list[tuple[int, np.ndarray]], panel_fp: str, n_dates: int) -> bytes:
    parts = [BLOB_MAGIC, panel_fp.encode("utf-8"), struct.pack("<I", n_dates)]
    for n_valid, ranks in pattern:
        parts.append(struct.pack("<I", n_valid))
        parts.append(np.ascontiguousarray(ranks, dtype=np.int32).tobytes())
    return b"".join(parts)


def _reverse(ranks: np.ndarray, n_valid: int) -> np.ndarray:
    """Doubled rank of the reversed ordering: ``2*(n+1) - r``."""
    return np.int32(2 * n_valid + 2) - ranks


def value_fingerprint(
    factor: np.ndarray,
    panel_fp: str,
    *,
    min_stocks: int = _MIN_STOCKS,
) -> tuple[str, int, bytes]:
    """Fingerprint a factor's rank pattern.

    Args:
        factor: ``(T, N)`` panel, NaN for names outside the universe.
        panel_fp: identity of the panel (universe + dates + symbols). Fingerprints
            are only comparable within one panel, so this is part of the hash.
        min_stocks: dates thinner than this are dropped, mirroring the IC.

    Returns:
        ``(fp, orientation, blob)`` where ``fp`` is ``"v1:<32 hex>"``,
        ``orientation`` is ``+1`` or ``-1`` (which of the two sign conventions the
        caller's data represents), and ``blob`` is the forward-rank encoding that
        was hashed — handy for debugging two fingerprints that "should" match.
    """
    pattern = rank_pattern(factor, min_stocks=min_stocks)
    n_dates = len(pattern)

    forward = _encode(pattern, panel_fp, n_dates)
    reversed_pattern = [(n_valid, _reverse(ranks, n_valid)) for n_valid, ranks in pattern]
    backward = _encode(reversed_pattern, panel_fp, n_dates)

    h_forward = hashlib.sha256(forward).hexdigest()
    h_backward = hashlib.sha256(backward).hexdigest()

    if h_forward <= h_backward:
        return f"{FINGERPRINT_VERSION}:{h_forward[:32]}", 1, forward
    return f"{FINGERPRINT_VERSION}:{h_backward[:32]}", -1, backward
