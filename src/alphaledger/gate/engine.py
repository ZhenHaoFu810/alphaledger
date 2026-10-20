"""The verdict.

Three states, and the order in which they are checked is the whole design:

1. ``INSUFFICIENT_DATA`` — fewer than 60 usable dates. We refuse to answer rather
   than answer loosely; a threshold fitted on 40 observations is theatre.
2. ``LABEL_CONTAMINATION`` — the factor is (or nearly is) the forward return. This
   outranks significance on purpose: a leaked factor can be arbitrarily
   significant, and reporting "PASS" there would be the single worst failure mode
   the tool has.
3. ``PASS`` / ``REJECT`` — ``p_family <= alpha``.

Family-wise error control, not FDR. The decision unit is one factor: there is no
set of discoveries to take a false-discovery proportion of, and an append-only
ledger never has a closed rejection set, which is what Benjamini-Hochberg needs.
The BH q value is still computed and reported, because it is informative — it just
is not what gates the verdict.
"""

from __future__ import annotations

import math

__all__ = ["decide", "benjamini_hochberg", "cross_family_alpha", "required_ic_mean"]

PASS = "PASS"
REJECT = "REJECT"
INSUFFICIENT = "INSUFFICIENT_DATA"
LEAK = "LABEL_CONTAMINATION"
DEGENERATE = "DEGENERATE"

_MIN_DATES = 60


def required_ic_mean(bar_q95: float, ic_std: float, n_dates: int) -> float:
    """The IC a factor would need for its t-statistic to reach the threshold.

    Answers the question every researcher actually asks after a REJECT: "how far
    off was it?" — and, less comfortably, "how big would a real edge have to be
    for this study to find it at all?"
    """
    if not math.isfinite(bar_q95) or not math.isfinite(ic_std) or n_dates <= 0:
        return float("nan")
    return bar_q95 * ic_std / math.sqrt(n_dates)


def cross_family_alpha(alpha: float, n_families: int) -> float:
    """Effective error rate across several independent studies.

    Ten families tested at 5% each is a 40% chance of at least one false positive
    somewhere. Printing the gate's alpha without this number lets a user believe
    they are operating at 5% when they are not.
    """
    return 1.0 - (1.0 - alpha) ** max(n_families, 1)


def benjamini_hochberg(p_values: list[float], alpha: float = 0.05) -> list[float]:
    """BH-adjusted q values, same order as the input. NaNs sort last and keep NaN."""
    n = len(p_values)
    indexed = [(p, i) for i, p in enumerate(p_values) if p is not None and math.isfinite(p)]
    q = [float("nan")] * n
    if not indexed:
        return q
    indexed.sort()
    m = len(indexed)
    running = 1.0
    for rank in range(m, 0, -1):
        p, i = indexed[rank - 1]
        running = min(running, p * m / rank)
        q[i] = min(1.0, running)
    return q


def decide(
    *,
    n_dates: int,
    t_obs: float,
    p_family: float,
    bar_q95: float,
    alpha: float = 0.05,
    leak_flag: str | None = None,
    orientation: int = 1,
    expected_direction: int | None = None,
    ic_std: float = float("nan"),
    confidence: str = "high",
) -> dict:
    """Map the numbers to a verdict and a machine-readable reason."""
    if leak_flag:
        return {
            "verdict": LEAK,
            "reason_code": "label_contamination",
            "detail": leak_flag,
        }
    if n_dates < _MIN_DATES:
        return {
            "verdict": INSUFFICIENT,
            "reason_code": "too_few_dates",
            "detail": f"{n_dates} usable dates < {_MIN_DATES}",
        }
    if not math.isfinite(p_family):
        return {
            "verdict": INSUFFICIENT,
            "reason_code": "no_null_distribution",
            "detail": "could not build a selection threshold",
        }
    if expected_direction is not None and orientation != expected_direction:
        return {
            "verdict": REJECT,
            "reason_code": "direction_mismatch",
            "detail": f"factor orients {orientation:+d}, expected {expected_direction:+d}",
        }

    if p_family <= alpha:
        return {
            "verdict": PASS,
            "reason_code": "family_significant",
            "detail": f"p_family={p_family:.4g} <= {alpha}",
        }

    return {
        "verdict": REJECT,
        "reason_code": "family_not_significant",
        "detail": (
            f"p_family={p_family:.4g} > {alpha}; "
            f"needed |t|>{bar_q95:.2f}, got {t_obs:.2f}"
        ),
        "required_ic_mean": required_ic_mean(bar_q95, ic_std, n_dates),
        "confidence": confidence,
    }
