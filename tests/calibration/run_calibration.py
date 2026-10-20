"""Measure the operating characteristics and write them down.

Not part of the test suite (it takes minutes, and CI runs a smaller version). The
point is to have a number, produced by this code, on this machine, that a reader
can compare against their own run.

    python tests/calibration/run_calibration.py --studies 20 --factors 100
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from alphaledger.stats.ic import cross_sectional_rank_ic  # noqa: E402
from alphaledger.stats.maxstat import max_stat_null  # noqa: E402


def family(n_factors: int, T: int, N: int, seed: int, signal_ic: float) -> np.ndarray:
    rng = np.random.default_rng(seed)
    factor = rng.standard_normal((T, N))
    rho = 2.0 * np.sin(np.pi * signal_ic / 6.0) if signal_ic else 0.0
    forward = np.sqrt(max(1 - rho**2, 0.0)) * rng.standard_normal((T, N)) + rho * factor
    ics = [cross_sectional_rank_ic(factor, forward)]
    for _ in range(n_factors - 1):
        ics.append(cross_sectional_rank_ic(rng.standard_normal((T, N)), forward))
    return np.column_stack(ics)


def run(studies: int, n_factors: int, T: int, N: int, signal_ic: float, n_boot: int, label: str) -> dict:
    passes, q95s, sigmas = 0, [], []
    t0 = time.perf_counter()
    for s in range(studies):
        est = max_stat_null(
            family(n_factors, T, N, seed=10_000 + s + int(signal_ic * 1000), signal_ic=signal_ic),
            n_boot=n_boot,
            alpha=0.05,
            rng=np.random.default_rng(s),
        )
        passes += int(est["p_family"] <= 0.05)
        q95s.append(est["bar_q95"])
        sigmas.append(est["bar_sigma"])
    elapsed = time.perf_counter() - t0
    result = {
        "label": label,
        "studies": studies,
        "factors_per_study": n_factors,
        "dates": T,
        "names": N,
        "signal_ic": signal_ic,
        "n_boot": n_boot,
        "pass_rate": round(passes / studies, 3),
        "bar_q95_median": round(float(np.median(q95s)), 3),
        "bar_q95_range": [round(float(np.min(q95s)), 3), round(float(np.max(q95s)), 3)],
        "bar_sigma_median": round(float(np.median(sigmas)), 3),
        "seconds": round(elapsed, 1),
    }
    print(json.dumps(result, ensure_ascii=False))
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--studies", type=int, default=20)
    ap.add_argument("--factors", type=int, default=100)
    ap.add_argument("--boot", type=int, default=500)
    args = ap.parse_args()

    results = [
        run(args.studies, args.factors, 250, 200, 0.0, args.boot, "null (FPR)"),
        run(max(4, args.studies // 4), args.factors, 500, 250, 0.03, args.boot, "power @ IC=0.03"),
        run(max(4, args.studies // 4), args.factors, 500, 250, 0.05, args.boot, "power @ IC=0.05"),
    ]
    out = Path(__file__).with_name("calibration.json")
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nwritten to {out}")


if __name__ == "__main__":
    main()
