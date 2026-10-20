"""The ledger's one load-bearing behaviour: re-running is not re-trying.

If ``n_trials`` ever counts evaluations instead of hypotheses, every p-value in the
product becomes anti-conservative and nothing in the output looks broken. Most of
this file exists to make that failure loud.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from alphaledger.config import ledger_path, workdir
from alphaledger.store import Ledger

PANEL = "panel000000000001"


@pytest.fixture()
def ledger(tmp_path):
    db = tmp_path / "ledger.db"
    lg = Ledger(db)
    yield lg
    lg.close()


def _trial(lg: Ledger, fp="v1:abc", horizon=5, expr="rank(close)") -> tuple[int, int, bool]:
    panel_id = lg.upsert_panel(PANEL, n_dates=250, n_symbols=300)
    return lg.upsert_trial(fp, panel_id, horizon, 1, expr_text=expr)


def test_rerunning_a_factor_does_not_add_a_trial(ledger):
    trial_id, n_evals, created = _trial(ledger)
    assert created is True and n_evals == 1

    again_id, again_evals, again_created = _trial(ledger)
    assert again_id == trial_id
    assert again_evals == 2
    assert again_created is False
    assert ledger.trial_count(_trial(ledger)[0] * 0 + 1, 5) == 1


def test_a_new_horizon_is_a_new_hypothesis(ledger):
    _trial(ledger, fp="v1:abc", horizon=5)
    _trial(ledger, fp="v1:abc", horizon=20)
    assert ledger.trial_count(1, 5) == 1
    assert ledger.trial_count(1, 20) == 1


def test_a_new_panel_is_a_new_hypothesis(ledger):
    """Same factor on a different universe is a different test, not a repeat."""
    p1 = ledger.upsert_panel("panelA")
    p2 = ledger.upsert_panel("panelB")
    ledger.upsert_trial("v1:abc", p1, 5, 1)
    ledger.upsert_trial("v1:abc", p2, 5, 1)
    assert ledger.trial_count(p1, 5) == 1
    assert ledger.trial_count(p2, 5) == 1


def test_eval_and_ic_series_round_trip(ledger):
    trial_id, _, _ = _trial(ledger)
    ic = np.array([0.1, np.nan, -0.05, 0.02], dtype=np.float64)
    eval_id = ledger.append_eval(trial_id, ic=ic, ic_mean=0.02, n_dates=4, t_nw=1.5)
    back = ledger.ic_series(eval_id)
    assert back is not None
    assert np.allclose(back[:2], [0.1, np.nan], equal_nan=True)
    assert ledger.latest_eval(trial_id)["t_nw"] == pytest.approx(1.5)


def test_family_matrix_aligns_to_the_shortest_series(ledger):
    panel_id = ledger.upsert_panel(PANEL)
    for i, ic in enumerate([[0.1] * 10, [0.2] * 8, [0.3] * 10]):
        tid, _, _ = ledger.upsert_trial(f"v1:f{i}", panel_id, 5, 1)
        ledger.append_eval(tid, ic=np.array(ic))
    ids, matrix = ledger.family_ic_series(panel_id, 5)
    assert len(ids) == 3
    assert matrix is not None and matrix.shape == (8, 3)


def test_events_are_append_only(ledger):
    ledger.log_event("sign_flip", trial_id=None, detail={"from": "+1", "to": "-1"})
    ledger.log_event("reeval", detail={"n": 2})
    kinds = [row["kind"] for row in ledger.events()]
    assert kinds == ["reeval", "sign_flip"]


def test_migration_is_idempotent(tmp_path):
    db = tmp_path / "m.db"
    first = Ledger(db)
    first.close()
    second = Ledger(db)
    try:
        assert second.conn.execute("PRAGMA user_version").fetchone()[0] == 1
    finally:
        second.close()


def test_eight_processes_writing_the_same_trial(tmp_path):
    """Eight real processes, not threads: this is the lock path that differs on Windows.

    Expected outcome: one row, ``n_evals == 8``, and nobody raises 'database is locked'.
    """
    db = tmp_path / "race.db"
    setup = Ledger(db)
    panel_id = setup.upsert_panel(PANEL)
    setup.close()

    script = """
import sys
sys.path.insert(0, sys.argv[1])
from alphaledger.store import Ledger
lg = Ledger(sys.argv[2])
for _ in range(10):
    lg.upsert_trial("v1:race", int(sys.argv[3]), 5, 1)
lg.close()
"""
    src = str(Path(__file__).resolve().parents[1] / "src")
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", script, src, str(db), str(panel_id)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for _ in range(8)
    ]
    for proc in procs:
        out, err = proc.communicate(timeout=90)
        assert proc.returncode == 0, err.decode(errors="replace")

    lg = Ledger(db)
    try:
        row = lg.get_trial("v1:race", panel_id, 5)
        assert row is not None
        assert row["n_evals"] == 80
        assert lg.trial_count(panel_id, 5) == 1
    finally:
        lg.close()


def test_env_override_picks_the_explicit_file(tmp_path, monkeypatch):
    target = tmp_path / "explicit.db"
    monkeypatch.setenv("ALPHALEDGER_DB", str(target))
    assert ledger_path() == target.resolve()
    lg = Ledger()
    lg.close()
    assert target.exists()


def test_home_override_picks_the_directory(tmp_path, monkeypatch):
    monkeypatch.delenv("ALPHALEDGER_DB", raising=False)
    monkeypatch.setenv("ALPHALEDGER_HOME", str(tmp_path / "home"))
    assert ledger_path() == (tmp_path / "home" / "ledger.db").resolve()


def test_workdir_honours_the_env(monkeypatch, tmp_path):
    monkeypatch.setenv("ALPHALEDGER_CWD", str(tmp_path))
    assert workdir() == tmp_path.resolve()
