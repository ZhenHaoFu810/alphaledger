"""Demos share this: a synthetic panel with a known answer, and a scratch ledger.

Everything here is deterministic. If a demo prints a different number on your
machine than in the README, that is a bug, not noise.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from alphaledger.store.ledger import Ledger  # noqa: E402


def panel(
    T: int = 250,
    N: int = 300,
    seed: int = 20261020,
    signal_ic: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Gaussian-copula panel: Spearman IC of ``signal_ic`` by construction."""
    rng = np.random.default_rng(seed)
    factor = rng.standard_normal((T, N))
    rho = 2.0 * np.sin(np.pi * signal_ic / 6.0) if signal_ic else 0.0
    forward = np.sqrt(max(1.0 - rho**2, 0.0)) * rng.standard_normal((T, N)) + rho * factor
    return factor, forward


def scratch_ledger(name: str) -> Ledger:
    path = Path(tempfile.mkdtemp(prefix=f"alphaledger-{name}-")) / "ledger.db"
    return Ledger(path)


def banner(title: str) -> None:
    print()
    print(title)
    print("-" * len(title))
