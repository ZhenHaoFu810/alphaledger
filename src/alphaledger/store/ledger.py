"""The ledger: the only thing in this project with memory.

The whole product rests on one behaviour here — the idempotent upsert. Evaluating
the same factor twice must leave ``n_trials = 1`` and ``n_evals = 2``. If that
counter ever increments the wrong thing, every p-value downstream is quietly
anti-conservative, and nothing in the output will look wrong.
"""

from __future__ import annotations

import json
import random
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

import numpy as np

from alphaledger.config import ledger_path
from alphaledger.store.db import connect, now

__all__ = ["Ledger"]

T = TypeVar("T")
_TRANSIENT = ("database is locked", "database table is locked", "readonly database")


def _with_retry(fn: Callable[[], T], attempts: int = 12) -> T:
    """Retry transient lock failures that concurrent agents actually produce.

    ``busy_timeout`` covers ordinary contention inside SQLite, but a writer that
    arrives while another process is checkpointing or switching journal modes can
    get ``SQLITE_READONLY`` on Windows, which ``busy_timeout`` does not cover.
    Backing off and retrying is the correct response; surfacing it to the model,
    which cannot do anything about it, is not.
    """
    for attempt in range(attempts):
        try:
            return fn()
        except sqlite3.OperationalError as exc:
            message = str(exc).lower()
            if attempt == attempts - 1 or not any(tag in message for tag in _TRANSIENT):
                raise
            time.sleep(0.02 * (2 ** attempt) + random.random() * 0.02)
    raise RuntimeError("unreachable")


class Ledger:
    """Thin, explicit wrapper. No ORM, no magic: the SQL is the specification."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else ledger_path()
        self.conn = connect(self.path)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> Ledger:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ panels

    def upsert_panel(
        self,
        panel_fp: str,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        n_dates: int | None = None,
        n_symbols: int | None = None,
    ) -> int:
        with self.conn:
            self.conn.execute(
                """INSERT INTO panel (panel_fp, start_date, end_date, n_dates, n_symbols, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(panel_fp) DO UPDATE SET
                     start_date = COALESCE(panel.start_date, excluded.start_date),
                     end_date   = COALESCE(panel.end_date,   excluded.end_date),
                     n_dates    = COALESCE(panel.n_dates,    excluded.n_dates),
                     n_symbols  = COALESCE(panel.n_symbols,  excluded.n_symbols)""",
                (panel_fp, start_date, end_date, n_dates, n_symbols, now()),
            )
            row = self.conn.execute("SELECT id FROM panel WHERE panel_fp = ?", (panel_fp,)).fetchone()
        return int(row["id"])

    # ------------------------------------------------------------------ trials

    def upsert_trial(
        self,
        fp: str,
        panel_id: int,
        horizon: int,
        orientation: int,
        *,
        fp_expr: str | None = None,
        label: str | None = None,
        expr_text: str | None = None,
        family_tag: str | None = None,
    ) -> tuple[int, int, bool]:
        return _with_retry(
            lambda: self._upsert_trial_once(
                fp,
                panel_id,
                horizon,
                orientation,
                fp_expr=fp_expr,
                label=label,
                expr_text=expr_text,
                family_tag=family_tag,
            )
        )

    def _upsert_trial_once(
        self,
        fp: str,
        panel_id: int,
        horizon: int,
        orientation: int,
        *,
        fp_expr: str | None = None,
        label: str | None = None,
        expr_text: str | None = None,
        family_tag: str | None = None,
    ) -> tuple[int, int, bool]:
        """Record a draw. Returns ``(trial_id, n_evals, created)``.

        ``created`` is True only for a genuinely new hypothesis; a re-evaluation
        bumps ``n_evals`` and leaves the trial count alone.
        """
        ts = now()
        with self.conn:
            cur = self.conn.execute(
                """INSERT INTO trial
                     (fp, fp_expr, panel_id, horizon, orientation, label, expr_text,
                      family_tag, first_seen, last_seen, n_evals)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                   ON CONFLICT(fp, panel_id, horizon) DO UPDATE SET
                     last_seen = excluded.last_seen,
                     n_evals   = trial.n_evals + 1,
                     label      = COALESCE(trial.label, excluded.label),
                     expr_text  = COALESCE(trial.expr_text, excluded.expr_text),
                     fp_expr    = COALESCE(trial.fp_expr, excluded.fp_expr)
                   RETURNING id, n_evals, first_seen""",
                (fp, fp_expr, panel_id, horizon, orientation, label, expr_text, family_tag, ts, ts),
            )
            row = cur.fetchone()
        created = bool(row["n_evals"] == 1 and row["first_seen"] == ts)
        return int(row["id"]), int(row["n_evals"]), created

    def get_trial(self, fp: str, panel_id: int, horizon: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM trial WHERE fp = ? AND panel_id = ? AND horizon = ?",
            (fp, panel_id, horizon),
        ).fetchone()

    def trial_count(self, panel_id: int, horizon: int) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS c FROM trial WHERE panel_id = ? AND horizon = ?",
            (panel_id, horizon),
        ).fetchone()
        return int(row["c"] or 0)

    def trial_ordinal(self, trial_id: int, panel_id: int, horizon: int) -> int:
        """1-based position of this trial within its family, by insertion order.

        This is the "Trial #137 of 200" number. It is not a hash prefix and not a
        timestamp: it has to be stable and it has to be the order in which the
        hypotheses were tried.
        """
        row = self.conn.execute(
            "SELECT COUNT(*) AS c FROM trial WHERE panel_id = ? AND horizon = ? AND id <= ?",
            (panel_id, horizon, trial_id),
        ).fetchone()
        return int(row["c"] or 0)

    # --------------------------------------------------------------- evals

    def append_eval(self, trial_id: int, *, ic: np.ndarray | None = None, **fields: Any) -> int:
        payload = {
            "ts": now(),
            "trial_id": trial_id,
            "session_id": fields.get("session_id"),
            "data_fp": fields.get("data_fp"),
            "n_dates": fields.get("n_dates"),
            "n_stocks_med": fields.get("n_stocks_med"),
            "ic_mean": fields.get("ic_mean"),
            "ic_std": fields.get("ic_std"),
            "ic_ir": fields.get("ic_ir"),
            "t_iid": fields.get("t_iid"),
            "t_nw": fields.get("t_nw"),
            "nw_lag": fields.get("nw_lag"),
            "p_single": fields.get("p_single"),
            "skew": fields.get("skew"),
            "kurt": fields.get("kurt"),
            "leak_flag": fields.get("leak_flag"),
            "insufficient": int(bool(fields.get("insufficient", False))),
            "engine_version": fields.get("engine_version"),
        }
        cols = ", ".join(payload)
        marks = ", ".join("?" for _ in payload)
        with self.conn:
            cur = self.conn.execute(
                f"INSERT INTO trial_eval ({cols}) VALUES ({marks})", tuple(payload.values())
            )
            eval_id = int(cur.lastrowid or 0)
            if ic is not None:
                arr = np.asarray(ic, dtype=np.float32)
                self.conn.execute(
                    "INSERT INTO ic_series (eval_id, n, values_blob) VALUES (?, ?, ?)",
                    (eval_id, arr.size, arr.tobytes()),
                )
        return eval_id

    def latest_eval(self, trial_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM trial_eval WHERE trial_id = ? ORDER BY id DESC LIMIT 1", (trial_id,)
        ).fetchone()

    def ic_series(self, eval_id: int) -> np.ndarray | None:
        row = self.conn.execute(
            "SELECT n, values_blob FROM ic_series WHERE eval_id = ?", (eval_id,)
        ).fetchone()
        if row is None:
            return None
        return np.frombuffer(row["values_blob"], dtype=np.float32).astype(np.float64)[: row["n"]]

    def family_ic_series(self, panel_id: int, horizon: int) -> tuple[list[int], np.ndarray | None]:
        """IC series of every trial in the family, as a ``(T, N)`` matrix.

        This is the input to the bootstrap: the cross-trial correlation structure is
        what makes 200 momentum variants fewer than 200 independent draws — and,
        crucially, what the bootstrap handles without us pretending to know the
        effective count.
        """
        rows = self.conn.execute(
            "SELECT id FROM trial WHERE panel_id = ? AND horizon = ? ORDER BY id",
            (panel_id, horizon),
        ).fetchall()
        trial_ids = [int(r["id"]) for r in rows]
        series = []
        for tid in trial_ids:
            ev = self.latest_eval(tid)
            arr = self.ic_series(ev["id"]) if ev is not None else None
            if arr is not None and arr.size:
                series.append(arr)
        if not series:
            return trial_ids, None

        length = min(s.size for s in series)
        return trial_ids, np.column_stack([s[:length] for s in series])

    # --------------------------------------------------------------- events

    def log_event(self, kind: str, trial_id: int | None = None, detail: dict | None = None) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO event (ts, kind, trial_id, detail) VALUES (?, ?, ?, ?)",
                (now(), kind, trial_id, json.dumps(detail or {}, ensure_ascii=False)),
            )

    def events(self, limit: int = 100) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                "SELECT * FROM event ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        )

    def record_gate(self, **fields: Any) -> int:
        payload = {
            "ts": now(),
            "trial_id": fields.get("trial_id"),
            "panel_id": fields.get("panel_id"),
            "horizon": fields.get("horizon"),
            "method": fields.get("method"),
            "n_family": fields.get("n_family"),
            "alpha": fields.get("alpha"),
            "bar_sigma": fields.get("bar_sigma"),
            "bar_q95": fields.get("bar_q95"),
            "p_family": fields.get("p_family"),
            "verdict": fields.get("verdict"),
            "reason_code": fields.get("reason_code"),
            "scope_narrowed": int(bool(fields.get("scope_narrowed", False))),
            "params_json": json.dumps(fields.get("params") or {}, ensure_ascii=False),
            "result_json": json.dumps(fields.get("result") or {}, ensure_ascii=False),
            "engine_version": fields.get("engine_version"),
        }
        cols = ", ".join(payload)
        marks = ", ".join("?" for _ in payload)
        with self.conn:
            cur = self.conn.execute(
                f"INSERT INTO gate_run ({cols}) VALUES ({marks})", tuple(payload.values())
            )
        return int(cur.lastrowid or 0)
