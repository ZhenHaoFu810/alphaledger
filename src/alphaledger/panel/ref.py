"""Loading panels, and the one place that resolves paths.

The MCP tools receive their arguments from a language model, and a model cannot
type a 300 × 250 array. So the primary input is a *path*, with inline values
allowed only for toy panels. Every path-shaped error must echo the resolved
absolute path and the working directory, otherwise the agent has no way to correct
itself and will simply retry the same wrong thing.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from alphaledger.config import workdir

__all__ = ["PanelError", "ResolvedPanel", "load_panel", "panel_fingerprint", "MAX_INLINE_VALUES"]

MAX_INLINE_VALUES = 200 * 200


class PanelError(ValueError):
    """Structured failure; ``code`` is what the agent branches on."""

    def __init__(self, code: str, message: str, hint: str = "", **extra: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.extra = extra


@dataclass
class ResolvedPanel:
    values: np.ndarray
    resolved_path: str | None
    fmt: str | None
    source: str          # "file" | "inline"
    key: str | None = None


def _as_array(raw: Any, where: str) -> np.ndarray:
    arr = np.asarray(raw, dtype=np.float64)
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)
    if arr.ndim != 2:
        raise PanelError(
            "PANEL_SHAPE_MISMATCH",
            f"{where} must be 2-D (dates × names), got shape {arr.shape}",
            "pass a (T, N) panel; a single date is fine but must still be 2-D",
        )
    return arr


def load_panel(ref: Any, *, where: str = "panel") -> ResolvedPanel:
    """Accept either ``{"path": ...}`` or ``{"values": [[...]]}``."""
    if isinstance(ref, np.ndarray):
        return ResolvedPanel(_as_array(ref, where), None, None, "inline")
    if isinstance(ref, list):
        arr = np.asarray(ref, dtype=np.float64)
        if arr.size > MAX_INLINE_VALUES:
            raise PanelError(
                "TOO_MANY_INLINE_VALUES",
                f"{where}: {arr.size} inline values exceeds the {MAX_INLINE_VALUES} limit",
                "write the panel to a .npz/.npy file and pass its path instead",
            )
        return ResolvedPanel(_as_array(ref, where), None, None, "inline")
    if not isinstance(ref, dict):
        raise PanelError("BAD_PANEL_REF", f"{where}: expected an object, got {type(ref).__name__}")

    if "values" in ref:
        arr = np.asarray(ref["values"], dtype=np.float64)
        if arr.size > MAX_INLINE_VALUES:
            raise PanelError(
                "TOO_MANY_INLINE_VALUES",
                f"{where}: {arr.size} inline values exceeds the {MAX_INLINE_VALUES} limit",
                "write the panel to a .npz/.npy file and pass its path instead",
            )
        return ResolvedPanel(_as_array(ref["values"], where), None, None, "inline")

    path_raw = ref.get("path")
    if not path_raw:
        raise PanelError("BAD_PANEL_REF", f"{where}: needs either 'path' or 'values'")

    base = workdir()
    path = Path(path_raw).expanduser()
    if not path.is_absolute():
        path = base / path
    path = path.resolve()
    if not path.exists():
        raise PanelError(
            "PATH_NOT_FOUND",
            f"{where}: no such file: {path}",
            "paths are resolved relative to ALPHALEDGER_CWD; pass an absolute path if unsure",
            resolved_path=str(path),
            cwd=str(base),
        )

    fmt = (ref.get("format") or path.suffix.lstrip(".")).lower()
    key = ref.get("key")

    if fmt in ("npz",):
        with np.load(path, allow_pickle=False) as data:
            keys = list(data.keys())
            use = key or ("factor" if "factor" in keys else (keys[0] if keys else None))
            if use is None or use not in keys:
                raise PanelError(
                    "BAD_PANEL_REF",
                    f"{where}: {path.name} has no array {use!r}; available: {keys}",
                    "pass 'key' explicitly",
                    resolved_path=str(path),
                )
            arr = data[use]
    elif fmt in ("npy",):
        arr = np.load(path, allow_pickle=False)
    elif fmt in ("csv", "tsv"):
        delim = "," if fmt == "csv" else "\t"
        arr = np.genfromtxt(path, delimiter=delim, dtype=np.float64)
    elif fmt in ("parquet", "pq"):
        try:
            import pandas as pd  # noqa: PLC0415 - optional dependency
        except ImportError as exc:
            raise PanelError(
                "MISSING_EXTRA",
                "parquet support needs pandas + pyarrow",
                "pip install 'alphaledger-mcp[frames]'",
            ) from exc
        arr = pd.read_parquet(path, columns=key).to_numpy() if key else pd.read_parquet(path).to_numpy()
    else:
        raise PanelError(
            "BAD_PANEL_REF",
            f"{where}: unsupported format {fmt!r}",
            "supported: npz, npy, csv, tsv, parquet",
            resolved_path=str(path),
        )

    return ResolvedPanel(_as_array(arr, where), str(path), fmt, "file", key)


def panel_fingerprint(*arrays: np.ndarray) -> str:
    """Identity of the *data* a factor was tested on.

    Happens to be the hash of the panel bytes, which is crude but exactly right for
    the question being asked: "were these two numbers computed on the same data?"
    A regenerated dataset with different noise is a different panel, and it should
    be — otherwise a re-draw of the data would silently share a trial count.
    """
    h = hashlib.sha256()
    for arr in arrays:
        a = np.ascontiguousarray(np.asarray(arr, dtype=np.float64))
        h.update(str(a.shape).encode("ascii"))
        h.update(a.tobytes())
    return "p" + h.hexdigest()[:16]


def describe_panel(arr: np.ndarray) -> dict[str, Any]:
    finite_per_date = np.isfinite(arr).sum(axis=1)
    return {
        "n_dates": int(arr.shape[0]),
        "n_symbols": int(arr.shape[1]),
        "n_stocks_median": int(np.median(finite_per_date)) if arr.size else 0,
        "nan_fraction": round(float(1.0 - np.isfinite(arr).mean()), 4),
    }


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, allow_nan=False, default=str)
