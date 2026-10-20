"""MCP server over stdio — hand-rolled, zero dependencies.

The official SDK is a fine thing, but it is a dependency the user pays for on every
cold start, and the transport is simple enough to own: newline-delimited JSON-RPC
2.0, one message per line, responses on stdout, logs on stderr. A tool that takes
25 seconds to appear is a tool an agent will time out on.

Protocol surface implemented: ``initialize``, ``notifications/initialized``,
``ping``, ``tools/list``, ``tools/call``. That is what a client needs to use the
tools; resources, prompts and sampling are out of scope (this server has none).
"""

from __future__ import annotations

import contextlib
import json
import math
import sys
import traceback
from collections.abc import Callable
from typing import Any

import numpy as np

from alphaledger import __version__
from alphaledger.evaluate import ENGINE_VERSION, run_evaluation
from alphaledger.identity.normalize import expr_fingerprint
from alphaledger.identity.value_fp import value_fingerprint
from alphaledger.panel.ref import PanelError, load_panel, panel_fingerprint
from alphaledger.store.ledger import Ledger

__all__ = ["handle", "serve", "TOOLS", "INSTRUCTIONS", "SERVER_NAME"]

SERVER_NAME = "alphaledger"
SUPPORTED_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")

INSTRUCTIONS = """\
alphaledger is a trial ledger for factor research. Every factor you evaluate is a \
draw from a lottery, and the ledger remembers how many draws have been taken.

1. Never compute IC yourself and present it as evidence — call `evaluate`.
2. `fingerprint` does not consume a trial; use it before writing new factor code.
   It takes the same `forward` panel as `evaluate`, because identity is scoped to a
   panel: the same factor on a different universe is a different trial.
3. Re-running `evaluate` on the same factor does NOT add a trial. It increments
   `n_evals` and shows up in `ledger_stats`. Re-evaluation is not confirmation.
4. A PASS requires p_family <= alpha. p_single is reported but is never evidence.
5. `forward` must already be shifted: forward[t] is the return earned after acting
   on factor[t]. This server never shifts anything for you.
"""

_PANEL_SCHEMA = {
    "type": "object",
    "description": (
        "A (dates x names) panel. Prefer {'path': 'f.npz', 'key': 'factor'}; "
        "inline {'values': [[...]]} is allowed only up to 200x200."
    ),
    "properties": {
        "path": {
            "type": "string",
            "description": "File path; relative paths resolve against ALPHALEDGER_CWD.",
        },
        "key": {"type": "string", "description": "Array name inside .npz / column name in .parquet."},
        "format": {"type": "string", "enum": ["npz", "npy", "csv", "tsv", "parquet"]},
        "values": {"type": "array", "items": {"type": "array", "items": {"type": ["number", "null"]}}},
    },
}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "fingerprint",
        "description": (
            "Identify a factor WITHOUT consuming a trial. Returns the value fingerprint, "
            "whether the ledger has seen it, and its position if so. Call this before "
            "writing new factor code to avoid re-testing something already counted."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "factor": _PANEL_SCHEMA,
                "forward": {
                    **_PANEL_SCHEMA,
                    "description": (
                        "The return panel this factor would be tested on. Required because "
                        "identity is scoped to a panel: the same factor tested on a different "
                        "universe is a different trial, not a repeat."
                    ),
                },
                "horizon": {"type": "integer", "minimum": 1, "default": 5},
                "expr": {
                    "type": "string",
                    "description": "Optional factor expression, for diagnostics only.",
                },
            },
            "required": ["factor", "forward"],
        },
    },
    {
        "name": "evaluate",
        "description": (
            "Measure one factor and record it as a trial. Returns cross-sectional RankIC, "
            "Newey-West t, single-test p, the trial's index within its family, and the "
            "family-adjusted verdict. This is the only supported way to produce evidence."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "factor": _PANEL_SCHEMA,
                "forward": {
                    **_PANEL_SCHEMA,
                    "description": "Forward returns, already shifted: forward[t] follows factor[t].",
                },
                "horizon": {"type": "integer", "minimum": 1, "default": 5},
                "expr": {"type": "string"},
                "label": {"type": "string"},
                "alpha": {"type": "number", "minimum": 0.001, "maximum": 0.5, "default": 0.05},
                "with_gate": {"type": "boolean", "default": True},
            },
            "required": ["factor", "forward"],
        },
    },
    {
        "name": "gate",
        "description": (
            "Re-judge an already-recorded trial against its family, optionally at a different "
            "alpha. Use after importing more trials or to ask 'how much better would this need "
            "to be'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "fp": {"type": "string", "description": "Value fingerprint returned by evaluate."},
                "alpha": {"type": "number", "minimum": 0.001, "maximum": 0.5, "default": 0.05},
            },
            "required": ["fp"],
        },
    },
    {
        "name": "ledger_stats",
        "description": (
            "How much has been tried, and where the session is going in circles: repeated "
            "evaluations, sign flips, near-duplicate clusters, and the cross-family error rate."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _jsonable(value: Any) -> Any:
    """Make a payload strictly JSON-compliant.

    ``NaN`` and ``Infinity`` are not valid JSON, and a strict client (most of them)
    rejects the whole message rather than the one field. So non-finite numbers
    become ``null`` — which is also the honest representation: "undefined", not
    "zero". numpy scalars are converted because ``json`` refuses them.
    """
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (np.floating, float)):
        f = float(value)
        return f if math.isfinite(f) else None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, np.ndarray):
        return _jsonable(value.tolist())
    return value


def _text(payload: Any, is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                # ensure_ascii=True: the wire format must not depend on the host's
                # console code page. On Windows a non-UTF-8 stdout encodes an em dash
                # as 0x97, and every conforming client then fails to decode the frame.
                "text": json.dumps(_jsonable(payload), ensure_ascii=True, allow_nan=False),
            }
        ],
        "isError": is_error,
    }


def _err(code: str, message: str, hint: str = "", **extra: Any) -> dict[str, Any]:
    return _text({"error": {"code": code, "message": message, "hint": hint, **extra}}, is_error=True)


# --------------------------------------------------------------------- tools


def _tool_fingerprint(args: dict[str, Any], ledger: Ledger) -> dict[str, Any]:
    """Identity has to be computed against the same panel `evaluate` would use.

    Hashing the factor itself as if it were the panel was the first version of this
    function, and it made `fingerprint` and `evaluate` disagree on every input — the
    tool would answer "never seen" for a factor evaluated one call earlier. The
    panel is part of the key, so the panel must be supplied.
    """
    panel = load_panel(args.get("factor"), where="factor")
    forward = load_panel(args.get("forward"), where="forward")
    if panel.values.shape != forward.values.shape:
        return _err(
            "PANEL_SHAPE_MISMATCH",
            f"factor {panel.values.shape} vs forward {forward.values.shape}",
            "identity is scoped to a panel; both must be (dates x names) and aligned",
            resolved_factor=panel.resolved_path,
            resolved_forward=forward.resolved_path,
        )

    horizon = int(args.get("horizon", 5))
    panel_fp = panel_fingerprint(forward.values)
    fp, orientation, _ = value_fingerprint(panel.values, panel_fp, min_stocks=30)
    panel_id = ledger.upsert_panel(panel_fp)

    row = ledger.conn.execute(
        "SELECT id, panel_id, horizon, n_evals FROM trial "
        "WHERE fp = ? AND panel_id = ? AND horizon = ? ORDER BY id LIMIT 1",
        (fp, panel_id, horizon),
    ).fetchone()

    return _text(
        {
            "fp": fp,
            "orientation": orientation,
            "seen_before": row is not None,
            "trial_index": ledger.trial_ordinal(row["id"], row["panel_id"], horizon) if row else None,
            "n_evals": int(row["n_evals"]) if row else 0,
            "expr_fingerprint": expr_fingerprint(args["expr"]) if args.get("expr") else None,
            "note": "fingerprint does not consume a trial",
        }
    )


def _tool_evaluate(args: dict[str, Any], ledger: Ledger) -> dict[str, Any]:
    factor = load_panel(args.get("factor"), where="factor")
    forward = load_panel(args.get("forward"), where="forward")
    if factor.values.shape != forward.values.shape:
        return _err(
            "PANEL_SHAPE_MISMATCH",
            f"factor {factor.values.shape} vs forward {forward.values.shape}",
            "both panels must be (dates x names) with identical alignment",
            resolved_factor=factor.resolved_path,
            resolved_forward=forward.resolved_path,
        )

    result = run_evaluation(
        factor.values,
        forward.values,
        ledger=ledger,
        horizon=int(args.get("horizon", 5)),
        expr=args.get("expr"),
        fp_expr=expr_fingerprint(args["expr"]) if args.get("expr") else None,
        label=args.get("label"),
        alpha=float(args.get("alpha", 0.05)),
        with_gate=bool(args.get("with_gate", True)),
    )
    payload = result.to_dict()
    payload["panel"]["resolved_path"] = factor.resolved_path
    return _text(payload)


def _tool_gate(args: dict[str, Any], ledger: Ledger) -> dict[str, Any]:
    fp = args.get("fp")
    if not fp:
        return _err("BAD_ARGUMENT", "gate needs 'fp'", "call evaluate first and pass its fp")
    row = ledger.conn.execute("SELECT * FROM trial WHERE fp = ? ORDER BY id DESC LIMIT 1", (fp,)).fetchone()
    if row is None:
        return _err("UNKNOWN_FP", f"no trial with fp {fp}", "fingerprints are ledger-specific")

    alpha = float(args.get("alpha", 0.05))
    _, family = ledger.family_ic_series(row["panel_id"], row["horizon"])
    if family is None:
        return _err("NO_SERIES", "trial has no stored IC series", "re-run evaluate")

    from alphaledger.gate.engine import decide  # local import: keeps the module optional
    from alphaledger.stats.maxstat import estimate_bar

    ev = ledger.latest_eval(row["id"])
    t_this = abs(float(ev["t_iid"])) if ev and ev["t_iid"] is not None else None
    est = estimate_bar(family, alpha=alpha, t_obs=t_this)
    ev = ledger.latest_eval(row["id"])
    gate = decide(
        n_dates=int(est["n_dates"]),
        t_obs=float(est["t_obs"]),
        p_family=float(est["p_family"]),
        bar_q95=float(est["bar_q95"]),
        alpha=alpha,
        leak_flag=ev["leak_flag"] if ev else None,
        direction=1 if ev and (ev["ic_mean"] or 0) >= 0 else -1,
        ic_std=float(ev["ic_std"]) if ev and ev["ic_std"] is not None else float("nan"),
    )
    gate.update({"fp": fp, "n_family": int(est["n_trials"]), "alpha": alpha})
    return _text(gate)


def _tool_ledger_stats(args: dict[str, Any], ledger: Ledger) -> dict[str, Any]:
    totals = ledger.conn.execute(
        "SELECT (SELECT COUNT(*) FROM trial) AS trials, (SELECT COUNT(*) FROM trial_eval) AS evals"
    ).fetchone()
    families = ledger.conn.execute(
        """SELECT panel_id, horizon, COUNT(*) AS n_trials, SUM(n_evals) AS n_evals
           FROM trial GROUP BY panel_id, horizon ORDER BY n_trials DESC"""
    ).fetchall()
    repeated = ledger.conn.execute(
        "SELECT fp, n_evals FROM trial WHERE n_evals > 1 ORDER BY n_evals DESC LIMIT 5"
    ).fetchall()
    events = ledger.conn.execute(
        "SELECT kind, COUNT(*) AS c FROM event GROUP BY kind"
    ).fetchall()

    n_trials = int(totals["trials"])
    return _text(
        {
            "totals": {"trials": n_trials, "evaluations": int(totals["evals"])},
            "families": [dict(row) for row in families],
            "churn": {
                "top_reevaluated": [{"fp": r["fp"], "n_evals": int(r["n_evals"])} for r in repeated],
                "repeated_evaluations": int(sum(r["n_evals"] - 1 for r in repeated)),
                "events": {r["kind"]: int(r["c"]) for r in events},
            },
            "cross_family": {
                "n_families": len(families),
                "effective_alpha": 1.0 - (1.0 - 0.05) ** max(len(families), 1),
            },
            "engine_version": ENGINE_VERSION,
        }
    )


_DISPATCH: dict[str, Callable[[dict[str, Any], Ledger], dict[str, Any]]] = {
    "fingerprint": _tool_fingerprint,
    "evaluate": _tool_evaluate,
    "gate": _tool_gate,
    "ledger_stats": _tool_ledger_stats,
}


# ------------------------------------------------------------------ jsonrpc


def handle(request: dict[str, Any], ledger: Ledger) -> dict[str, Any] | None:
    """Pure request handler. Returns None for notifications."""
    method = request.get("method")
    req_id = request.get("id")

    if req_id is None and method is not None:
        return None  # notification: no reply, ever

    def ok(result: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    def fail(code: int, message: str, data: Any = None) -> dict[str, Any]:
        error: dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        return {"jsonrpc": "2.0", "id": req_id, "error": error}

    if method == "initialize":
        requested = (request.get("params") or {}).get("protocolVersion")
        version = requested if requested in SUPPORTED_PROTOCOLS else SUPPORTED_PROTOCOLS[0]
        return ok(
            {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": __version__},
                "instructions": INSTRUCTIONS,
            }
        )
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": TOOLS})
    if method == "tools/call":
        params = request.get("params") or {}
        name = str(params.get("name") or "")
        args = params.get("arguments") or {}
        fn = _DISPATCH.get(name)
        if fn is None:
            return fail(-32602, f"unknown tool {name!r}")
        try:
            return ok(fn(args, ledger))
        except PanelError as exc:
            return ok(_err(exc.code, exc.message, exc.hint, **exc.extra))
        except Exception as exc:  # noqa: BLE001 - the agent must see a structured error
            return ok(
                _err(
                    "INTERNAL_ERROR",
                    f"{type(exc).__name__}: {exc}",
                    "this is a bug; see stderr for the traceback",
                )
            )

    return fail(-32601, f"method not found: {method}")


def _force_utf8() -> None:
    """Pin the protocol streams to UTF-8 regardless of the platform default.

    Outbound frames are ASCII-escaped anyway; this is for the inbound direction —
    a tool argument containing Chinese would otherwise be decoded with cp1252 and
    arrive as mojibake — and so that stderr diagnostics stay readable.
    """
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError, OSError):
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]


def serve(ledger_path: str | None = None) -> int:
    """Read JSON-RPC lines from stdin, write replies to stdout. Logs to stderr."""
    _force_utf8()
    ledger = Ledger(ledger_path)
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError as exc:
                sys.stdout.write(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": None,
                            "error": {"code": -32700, "message": f"parse error: {exc}"},
                        }
                    )
                    + "\n"
                )
                sys.stdout.flush()
                continue

            try:
                response = handle(request, ledger)
            except Exception as exc:  # noqa: BLE001 - never die mid-session
                traceback.print_exc(file=sys.stderr)
                # Silence is worse than an error: a client waiting for a reply to
                # id=7 will block until its own timeout. Always answer.
                response = {
                    "jsonrpc": "2.0",
                    "id": request.get("id"),
                    "error": {"code": -32603, "message": f"internal error: {type(exc).__name__}: {exc}"},
                }
            if response is not None:
                sys.stdout.write(json.dumps(response, ensure_ascii=True) + "\n")
                sys.stdout.flush()
    finally:
        ledger.close()
    return 0
