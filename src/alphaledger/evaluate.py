"""One evaluation, end to end: measure, identify, record, judge.

This is the function the MCP tool wraps. Keeping it a plain function — no server,
no JSON, no globals — is what makes the whole product testable in-process, which in
turn is what makes the calibration suite (false-positive rate, power) cheap enough
to run on every commit.

The order of operations is deliberate: identify *after* measuring, because the
value fingerprint needs the realised ranks, and record *before* judging, because a
rejected factor is still a draw that must count against the next one.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from alphaledger.identity.value_fp import value_fingerprint
from alphaledger.panel.ref import PanelError, describe_panel, panel_fingerprint
from alphaledger.stats.ic import cross_sectional_rank_ic, ic_summary
from alphaledger.stats.maxstat import estimate_bar
from alphaledger.stats.nw import iid_t, newey_west_t, skew_kurt, student_t_two_sided_p

__all__ = ["ENGINE_VERSION", "EvaluationResult", "run_evaluation"]

ENGINE_VERSION = "0.1.0"


@dataclass
class EvaluationResult:
    fp: str
    orientation: int
    trial_id: int
    trial_index: int
    n_family: int
    n_evals: int
    created: bool
    ic: np.ndarray
    stats: dict
    gate: dict
    panel: dict
    summary: str

    def to_dict(self) -> dict:
        return {
            "fp": self.fp,
            "orientation": self.orientation,
            "trial_id": self.trial_id,
            "trial_index": self.trial_index,
            "n_family": self.n_family,
            "n_evals": self.n_evals,
            "created": self.created,
            "stats": self.stats,
            "gate": self.gate,
            "panel": self.panel,
            "summary": self.summary,
        }


def _leak_check(ic: np.ndarray) -> str | None:
    """Cheap label-contamination detector.

    A factor that ranks identically to the forward return gives RankIC of exactly
    1 on every usable date. That is not a strong factor; it is the answer key. The
    full perturbation protocol (rewrite the future with noise and watch the past
    change) is v0.2 — this catches the accidental version, which is the common one.
    """
    finite = ic[np.isfinite(ic)]
    if finite.size and np.allclose(finite, 1.0, atol=1e-9):
        return "factor ranks identically to the forward return on every date"
    return None


def _fmt(x: float, digits: int = 4) -> str:
    return "nan" if not math.isfinite(x) else f"{x:.{digits}f}"


def run_evaluation(
    factor: np.ndarray,
    forward: np.ndarray,
    *,
    ledger,
    horizon: int = 5,
    expr: str | None = None,
    fp_expr: str | None = None,
    label: str | None = None,
    alpha: float = 0.05,
    min_stocks: int = 30,
    expected_direction: int | None = None,
    session_id: str | None = None,
    with_gate: bool = True,
    n_boot: int = 1000,
    rng: np.random.Generator | None = None,
) -> EvaluationResult:
    """Measure one factor, record it, and judge it against its family."""
    f = np.asarray(factor, dtype=np.float64)
    r = np.asarray(forward, dtype=np.float64)
    if f.shape != r.shape:
        raise PanelError(
            "PANEL_SHAPE_MISMATCH",
            f"factor {f.shape} and forward {r.shape} must match",
            "both panels are (dates × names), aligned on the same dates and names",
        )

    ic = cross_sectional_rank_ic(f, r, min_stocks=min_stocks)
    summary_ic = ic_summary(ic)
    n_dates = int(summary_ic["n"])

    fp, orientation, _blob = value_fingerprint(f, panel_fingerprint(r), min_stocks=min_stocks)
    panel_id = ledger.upsert_panel(
        panel_fingerprint(r),
        n_dates=int(r.shape[0]),
        n_symbols=int(r.shape[1]),
    )
    trial_id, n_evals, created = ledger.upsert_trial(
        fp,
        panel_id,
        horizon,
        orientation,
        fp_expr=fp_expr,
        label=label,
        expr_text=expr,
    )
    ordinal = ledger.trial_ordinal(trial_id, panel_id, horizon)
    n_family = ledger.trial_count(panel_id, horizon)

    leak = _leak_check(ic) if n_dates else None
    degenerate = n_dates == 0

    if degenerate:
        stats = {
            "n_dates": 0,
            "ic_mean": float("nan"),
            "ic_std": float("nan"),
            "ic_ir": float("nan"),
            "t_iid": float("nan"),
            "t_nw": float("nan"),
            "nw_lag": 0,
            "p_single": float("nan"),
            "skew": float("nan"),
            "kurt": float("nan"),
        }
    else:
        t_nw, lag = newey_west_t(ic, horizon=horizon)
        t_plain = iid_t(ic)
        p_single = student_t_two_sided_p(t_plain, max(n_dates - 1, 1))
        sk, ku = skew_kurt(ic)
        stats = {
            "n_dates": n_dates,
            "ic_mean": float(summary_ic["mean"]),
            "ic_std": float(summary_ic["std"]),
            "ic_ir": float(summary_ic["ir"]),
            "t_iid": float(t_plain),
            "t_nw": float(t_nw),
            "nw_lag": int(lag),
            "p_single": float(p_single),
            "skew": float(sk),
            "kurt": float(ku),
        }

    ledger.append_eval(
        trial_id,
        ic=ic,
        session_id=session_id,
        data_fp=panel_fingerprint(r),
        n_dates=n_dates,
        n_stocks_med=int(np.median(np.isfinite(f).sum(axis=1))) if f.size else 0,
        insufficient=degenerate or n_dates < 60,
        leak_flag=leak,
        engine_version=ENGINE_VERSION,
        ic_mean=stats["ic_mean"],
        ic_std=stats["ic_std"],
        ic_ir=stats["ic_ir"],
        t_iid=stats["t_iid"],
        t_nw=stats["t_nw"],
        nw_lag=stats["nw_lag"],
        p_single=stats["p_single"],
        skew=stats["skew"],
        kurt=stats["kurt"],
    )

    gate: dict[str, Any] = {"verdict": "DEGENERATE" if degenerate else "INSUFFICIENT_DATA"}
    if leak:
        # Short-circuit: a contaminated factor is rejected on identity, and building a
        # null distribution for it would be both pointless and numerically degenerate
        # (RankIC is constant 1.0, so its standard deviation is zero).
        from alphaledger.gate.engine import decide  # local import keeps gate optional

        gate = decide(n_dates=n_dates, t_obs=float("nan"), p_family=float("nan"),
                      bar_q95=float("nan"), alpha=alpha, leak_flag=leak, direction=1)
        gate.update({"n_family": n_family, "alpha": alpha, "p_family": float("nan"),
                     "bar_q95": float("nan"), "bar_sigma": float("nan"),
                     "method": "identity_check"})
    elif not degenerate:
        if with_gate:
            _, family = ledger.family_ic_series(panel_id, horizon)
            if family is not None and family.size:
                # Judge *this* trial against the family's null distribution of the
                # maximum. Passing the family maximum here would let one strong
                # factor carry every later weak one through the gate.
                est: dict[str, Any] = estimate_bar(
                    family,
                    alpha=alpha,
                    rng=rng,
                    max_boot=max(1000, n_boot),
                    t_obs=abs(float(stats["t_iid"])),
                )
            else:
                est = {"bar_q95": float("nan"), "bar_sigma": float("nan"),
                       "p_family": float("nan"), "t_obs": abs(float(stats["t_iid"])),
                       "n_boot": 0, "block": 0, "n_trials": n_family,
                       "n_dates": n_dates, "confidence": "low"}
            from alphaledger.gate.engine import decide  # local import keeps gate optional

            gate = decide(
                n_dates=n_dates,
                t_obs=float(est.get("t_obs", stats["t_iid"])),
                p_family=float(est.get("p_family", float("nan"))),
                bar_q95=float(est.get("bar_q95", float("nan"))),
                alpha=alpha,
                leak_flag=leak,
                direction=1 if stats["ic_mean"] >= 0 else -1,
                expected_direction=expected_direction,
                ic_std=stats["ic_std"],
                confidence=str(est.get("confidence", "high")),
            )
            gate.update(
                {
                    "bar_sigma": est.get("bar_sigma"),
                    "bar_q95": est.get("bar_q95"),
                    "p_family": est.get("p_family"),
                    "n_family": n_family,
                    "alpha": alpha,
                    "method": "block_bootstrap_max_t",
                }
            )
            ledger.record_gate(
                trial_id=trial_id,
                panel_id=panel_id,
                horizon=horizon,
                method="block_bootstrap_max_t",
                n_family=n_family,
                alpha=alpha,
                bar_sigma=gate.get("bar_sigma"),
                bar_q95=gate.get("bar_q95"),
                p_family=gate.get("p_family"),
                verdict=gate.get("verdict"),
                reason_code=gate.get("reason_code"),
                params={"n_boot": est.get("n_boot"), "block": est.get("block")},
                result=gate,
                engine_version=ENGINE_VERSION,
            )
        else:
            gate = {
                "verdict": "NOT_GATED",
                "reason_code": "gate_skipped",
                "p_family": float("nan"),
                "n_family": n_family,
                "alpha": alpha,
            }

    summary = _summary_line(ordinal, n_family, gate, stats)
    return EvaluationResult(
        fp=fp,
        orientation=orientation,
        trial_id=trial_id,
        trial_index=ordinal,
        n_family=n_family,
        n_evals=n_evals,
        created=created,
        ic=ic,
        stats=stats,
        gate=gate,
        panel=describe_panel(f),
        summary=summary,
    )


def _summary_line(ordinal: int, n_family: int, gate: dict, stats: dict) -> str:
    """One line that a human can read out loud.

    Deliberately contains no duplication: the p_family number appears once, inside
    the reason text, so quoting the line twice in an interview does not produce two
    different-looking numbers.
    """
    verdict = gate.get("verdict", "?")
    parts = [f"Trial #{ordinal} of {n_family} — {verdict}."]
    if math.isfinite(stats.get("ic_mean", float("nan"))):
        parts.append(
            f"IC={stats['ic_mean']:+.4f}, t={_fmt(stats['t_iid'], 2)}, "
            f"p_single={_fmt(stats['p_single'])}."
        )
    detail = gate.get("detail")
    if detail:
        parts.append(str(detail).rstrip(".") + ".")
    return " ".join(parts)
