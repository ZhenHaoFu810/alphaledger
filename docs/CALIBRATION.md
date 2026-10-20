# Calibration

Produced by `tests/calibration/run_calibration.py` on 2026-10-20, Windows, Python
3.13.14, numpy 2.5.4. Raw output in `calibration.json` next to the script.

## Why both directions are measured

A significance gate can be wrong in two ways and only one of them is visible:

- **Too loose.** Noise passes. Every individual output looks like a result.
- **Too strict.** Nothing passes. Invisible too — and it *looks* rigorous. A tool that
  always rejects has a perfect false-positive rate and no value.

So the suite measures power alongside FPR. A change that improves one by sacrificing
the other fails CI (`tests/test_gate.py::test_false_positive_rate_is_controlled`,
`::test_power_on_a_planted_factor`).

## Results

```
null (FPR)        12 studies × 100 noise factors, T=250, N=200, B=400
                  pass rate 8.3% (1/12), bar_q95 median 3.49 (range 3.40–3.60)
                  bar_sigma median 2.69, 37 s total

power @ IC=0.03    4 studies × 100 factors, T=500, N=250, B=400
                  pass rate 100% (4/4), bar_q95 median 3.49

power @ IC=0.05    4 studies × 100 factors, T=500, N=250, B=400
                  pass rate 100% (4/4), bar_q95 median 3.50
```

Reading the null result honestly: 1 false positive in 12 studies is 8.3%, on a nominal
5% gate. With 12 studies the 95% interval around that estimate runs from roughly 0% to
35%, so this is consistent with 5% and does not prove it. The CI version uses fewer
studies for speed; the number to trust is the one above, and the honest statement is
"nominal 5%, measured 1 in 12, interval is wide".

The threshold itself is the more informative number: `bar_q95 ≈ 3.49` for 100 trials,
against 3.28 for 100 *independent* normal draws. The gap is the cross-trial
correlation induced by sharing one return panel — exactly what a Bonferroni correction
would miss and what the bootstrap picks up.

## Reproducing

```bash
python tests/calibration/run_calibration.py --studies 12 --factors 100 --boot 400
```

Rough cost: 18 ms per factor-evaluation at T=250/N=200, 73 ms at T=500/N=250. A full
200-factor study takes about 4 s of IC computation; the bootstrap itself is ~40 ms.

## Known limits of this measurement

- Synthetic Gaussian panels with a Gaussian copula. Real A-share returns are fatter
  tailed and have cross-sectional dependence through sector and size; the bootstrap is
  designed to absorb that without modelling it, but this calibration does not test it.
- `min_stocks = 30` throughout. A study on a 200-name universe where half the names are
  suspended will skip more dates than these panels do, which shrinks `T` and widens the
  threshold — conservative in the right direction.
- Single machine, single BLAS. The numbers should not be read as precise to the second.
