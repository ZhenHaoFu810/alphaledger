"""Five ways to write one factor. The ledger must count one trial, not five.

    x, rank(x), 2x+3, log(exp(x)), and x with the sign flipped

All five rank identically (the last one backwards), so they are the same hypothesis
viewed five times. Counting them separately would invent four trials of selection
pressure out of thin air — and, worse, would let a user manufacture a family large
enough to justify anything.

    python demos/equivalents.py
"""

from __future__ import annotations

import numpy as np
from _common import banner, panel, scratch_ledger


def main() -> None:
    from alphaledger.evaluate import run_evaluation

    banner("one factor, five spellings")
    ledger = scratch_ledger("equivalents")
    factor, forward = panel(T=250, N=300, seed=13, signal_ic=0.02)

    variants = {
        "x": factor,
        "rank(x)": np.apply_along_axis(lambda r: np.argsort(np.argsort(r)), 1, factor).astype(float),
        "2x+3": 2.0 * factor + 3.0,
        "log(exp(x))": np.log(np.exp(factor)),
        "-x": -factor,
    }

    seen = {}
    for name, values in variants.items():
        result = run_evaluation(values, forward, ledger=ledger, horizon=5, label=name, with_gate=False)
        seen[name] = result
        print(f"  {name:<12} fp={result.fp[:12]}…  trial#{result.trial_index}  n_evals={result.n_evals}  orient={result.orientation:+d}")

    n_trials = len({r.fp for r in seen.values()})
    total_evals = max(r.n_evals for r in seen.values())
    print()
    print(f"  distinct fingerprints: {n_trials}")
    print(f"  evaluations recorded:  {total_evals}")
    print("  verdict: five spellings, one trial — the count is the whole point")
    ledger.close()


if __name__ == "__main__":
    main()
