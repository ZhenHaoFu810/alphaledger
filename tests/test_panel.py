"""Panels arrive as paths, because a model cannot type 75,000 numbers.

These tests pin the behaviours that make path errors self-correcting: the resolved
absolute path and the working directory come back in the error, and inline panels
are capped.
"""

from __future__ import annotations

import numpy as np
import pytest

from alphaledger.panel.ref import MAX_INLINE_VALUES, PanelError, load_panel, panel_fingerprint


def test_inline_values_are_accepted():
    panel = load_panel({"values": [[1, 2], [3, 4]]})
    assert panel.source == "inline"
    assert panel.values.shape == (2, 2)


def test_single_row_is_promoted_to_2d():
    assert load_panel([[1.0, 2.0, 3.0]]).values.shape == (1, 3)


def test_inline_limit_is_enforced():
    big = np.zeros((MAX_INLINE_VALUES // 10 + 1, 10))
    with pytest.raises(PanelError) as exc:
        load_panel({"values": big.tolist()})
    assert exc.value.code == "TOO_MANY_INLINE_VALUES"


def test_missing_file_reports_the_resolved_path_and_cwd(tmp_path, monkeypatch):
    monkeypatch.setenv("ALPHALEDGER_CWD", str(tmp_path))
    with pytest.raises(PanelError) as exc:
        load_panel({"path": "nope.npz"})
    assert exc.value.code == "PATH_NOT_FOUND"
    assert exc.value.extra["resolved_path"] == str((tmp_path / "nope.npz").resolve())
    assert exc.value.extra["cwd"] == str(tmp_path.resolve())


def test_npz_round_trip_uses_the_key(tmp_path):
    path = tmp_path / "p.npz"
    np.savez(path, factor=np.arange(6.0).reshape(2, 3), other=np.zeros((2, 3)))
    panel = load_panel({"path": str(path), "key": "factor"})
    assert panel.values.shape == (2, 3)
    assert panel.fmt == "npz"
    assert panel.resolved_path == str(path.resolve())


def test_npz_without_the_requested_key_lists_what_is_there(tmp_path):
    path = tmp_path / "p.npz"
    np.savez(path, alpha=np.zeros((2, 3)))
    with pytest.raises(PanelError) as exc:
        load_panel({"path": str(path), "key": "factor"})
    assert "alpha" in exc.value.message


def test_csv_and_npy(tmp_path):
    csv_path = tmp_path / "p.csv"
    csv_path.write_text("1,2\n3,4\n", encoding="utf-8")
    assert load_panel({"path": str(csv_path)}).values.shape == (2, 2)

    npy_path = tmp_path / "p.npy"
    np.save(npy_path, np.ones((4, 5)))
    assert load_panel({"path": str(npy_path)}).values.shape == (4, 5)


def test_unsupported_format_is_named():
    with pytest.raises(PanelError) as exc:
        load_panel({"path": "x.xlsx"})
    assert exc.value.code == "BAD_PANEL_REF" or exc.value.code == "PATH_NOT_FOUND"


def test_panel_fingerprint_is_content_addressed():
    a = np.arange(12.0).reshape(3, 4)
    b = a.copy()
    c = a.copy()
    c[0, 0] = 99.0
    assert panel_fingerprint(a) == panel_fingerprint(b)
    assert panel_fingerprint(a) != panel_fingerprint(c)


def test_nan_pattern_is_part_of_the_panel_identity():
    a = np.ones((3, 4))
    b = a.copy()
    b[1, 1] = np.nan
    assert panel_fingerprint(a) != panel_fingerprint(b)
