"""A perfect factor with a t-statistic of infinity — which is the answer key, not an edge.

Passing the forward return in as the factor produces RankIC of exactly 1 on every
date. No amount of statistical significance makes that a discovery, so the gate has
to refuse it *before* it looks at p-values. This is the failure mode that would do
real damage if it slipped through: it is the one case where the tool's own numbers
look best.

    python demos/leaky_momentum.py
"""

from __future__ import annotations

from _common import banner, panel, scratch_ledger


def main() -> None:
    from alphaledger.evaluate import run_evaluation

    banner("a factor built from the future")
    ledger = scratch_ledger("leaky")
    _, forward = panel(T=250, N=300, seed=5, signal_ic=0.0)

    result = run_evaluation(forward.copy(), forward, ledger=ledger, horizon=5, label="label_leak", with_gate=True)

    print()
    print(f"  RankIC          {result.stats['ic_mean']:+.4f}")
    print(f"  t (iid)         {result.stats['t_iid']:.2f}")
    print(f"  p_single        {result.stats['p_single']:.3g}")
    print(f"  verdict         {result.gate['verdict']}")
    print(f"  reason          {result.gate.get('reason_code')}")
    print()
    print("  Significance is checked second. Contamination is checked first.")
    ledger.close()


if __name__ == "__main__":
    main()
