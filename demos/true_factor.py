"""The other half of the test: a real edge must still get through.

A gate that rejects everything is not conservative, it is useless — and it is the
easiest thing in the world to ship by accident if you only ever measure false
positives. This demo plants a true RankIC of 0.05 on a 500-day panel and checks
that it survives the family correction.

    python demos/true_factor.py
"""

from __future__ import annotations

import numpy as np
from _common import banner, panel, scratch_ledger


def main() -> None:
    from alphaledger.evaluate import run_evaluation
    from alphaledger.stats.maxstat import estimate_bar

    banner("one planted factor (true RankIC = 0.05) inside a family of 190 noise factors")
    ledger = scratch_ledger("true_factor")
    rng = np.random.default_rng(11)

    # The return panel carries the planted signal.
    true_factor, forward = panel(T=500, N=300, seed=42, signal_ic=0.05)
    for i in range(190):
        noise = rng.standard_normal(true_factor.shape)
        run_evaluation(noise, forward, ledger=ledger, horizon=5, label=f"noise_{i:03d}", with_gate=False)

    result = run_evaluation(true_factor, forward, ledger=ledger, horizon=5, label="planted_0.05", with_gate=False)

    row = ledger.conn.execute("SELECT * FROM trial WHERE fp = ?", (result.fp,)).fetchone()
    _ids, family = ledger.family_ic_series(row["panel_id"], row["horizon"])
    est = estimate_bar(family, alpha=0.05)

    print()
    print(f"  planted IC      {result.stats['ic_mean']:+.4f}  (target 0.05)")
    print(f"  t (iid / NW)    {result.stats['t_iid']:.2f} / {result.stats['t_nw']:.2f}")
    print(f"  family          {est['n_trials']} trials")
    print(f"  bar_q95         {est['bar_q95']:.2f}")
    print(f"  p_family        {est['p_family']:.4f}")
    print(f"  verdict         {'PASS' if est['p_family'] <= 0.05 else 'REJECT'}")
    print()
    print("  A gate that fails this is not strict, it is broken.")
    ledger.close()


if __name__ == "__main__":
    main()
