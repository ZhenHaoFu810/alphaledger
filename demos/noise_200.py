"""200 pure-noise factors. The best one looks significant. It is not.

This is the demo the product exists for: read the last four lines. The winner's
single-test p-value is small enough to publish; the family-adjusted one says it is
indistinguishable from luck.

    python demos/noise_200.py
"""

from __future__ import annotations

import numpy as np
from _common import banner, scratch_ledger

T, N, K = 250, 300, 200


def gate_for(ledger, fp: str) -> dict:
    from alphaledger.stats.maxstat import estimate_bar

    row = ledger.conn.execute("SELECT * FROM trial WHERE fp = ?", (fp,)).fetchone()
    _ids, family = ledger.family_ic_series(row["panel_id"], row["horizon"])
    # Seeded: the README quotes these numbers, so they must not drift.
    return estimate_bar(family, alpha=0.05, rng=np.random.default_rng(20261020))


def main() -> None:
    from alphaledger.evaluate import run_evaluation

    banner(f"{K} pure-noise factors · {N} names x {T} dates")
    rng = np.random.default_rng(20261020)
    forward = rng.standard_normal((T, N))
    ledger = scratch_ledger("noise200")

    results = []
    for i in range(K):
        factor = rng.standard_normal((T, N))
        # with_gate=False: paying for 200 bootstraps would turn a 5 s demo into a minute
        results.append(
            run_evaluation(
                factor, forward, ledger=ledger, horizon=5, label=f"noise_{i:03d}", with_gate=False
            )
        )
        if (i + 1) % 50 == 0:
            print(f"  evaluated {i + 1}/{K}")

    best = max(results, key=lambda r: abs(r.stats["t_iid"]))
    est = gate_for(ledger, best.fp)

    print()
    print(f"  best factor     fp={best.fp[:12]}…")
    print(f"  RankIC          {best.stats['ic_mean']:+.4f}")
    print(f"  t (iid / NW)    {best.stats['t_iid']:.2f} / {best.stats['t_nw']:.2f}")
    print(f"  p_single        {best.stats['p_single']:.5f}   <- looks publishable")
    print(f"  family          {len(results)} trials")
    print(f"  bar_q95         {est['bar_q95']:.2f}   <- what a real factor needed")
    print(f"  p_family        {est['p_family']:.3f}   <- it is luck")
    print(f"  verdict         {'REJECT' if est['p_family'] > 0.05 else 'PASS'}")
    print()
    verdict = "REJECT" if est["p_family"] > 0.05 else "PASS"
    print(
        f'  "Trial #{len(results)} of {est["n_trials"]} — {verdict}. '
        f'IC={best.stats["ic_mean"]:+.4f}, t={best.stats["t_iid"]:.2f}, '
        f'p_single={best.stats["p_single"]:.4f}, p_family={est["p_family"]:.3f}."'
    )
    ledger.close()


if __name__ == "__main__":
    main()
