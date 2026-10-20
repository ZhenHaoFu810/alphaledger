"""The MCP surface, tested through a real subprocess over real stdio.

Testing ``handle()`` in-process would miss the things that actually break: framing,
flushing, the server dying on a bad line, and whether a tool result survives JSON
serialisation (numpy scalars and NaN both bite here).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = str(Path(__file__).resolve().parents[1] / "src")


class Client:
    def __init__(self, db: Path) -> None:
        self.proc = subprocess.Popen(
            [sys.executable, "-c", f"import sys; sys.path.insert(0, {SRC!r});"
             f"from alphaledger.server import serve; raise SystemExit(serve({str(db)!r}))"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        self._id = 0

    def send(self, method: str, params: dict | None = None, *, notify: bool = False):
        self._id += 1
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if not notify:
            msg["id"] = self._id
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        if notify:
            return None
        assert self.proc.stdout is not None
        line = self.proc.stdout.readline()
        return json.loads(line)

    def call(self, name: str, arguments: dict):
        response = self.send("tools/call", {"name": name, "arguments": arguments})
        assert "result" in response, response
        text = response["result"]["content"][0]["text"]
        return response["result"].get("isError", False), json.loads(text)

    def close(self) -> None:
        if self.proc.stdin:
            self.proc.stdin.close()
        self.proc.wait(timeout=20)


@pytest.fixture()
def client(tmp_path):
    c = Client(tmp_path / "ledger.db")
    yield c
    c.close()


def test_initialize_returns_capabilities_and_instructions(client):
    response = client.send("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}})
    result = response["result"]
    assert result["serverInfo"]["name"] == "alphaledger"
    assert "tools" in result["capabilities"]
    assert "p_trial" in result["instructions"] or "trial" in result["instructions"]


def test_notifications_get_no_reply(client):
    client.send("notifications/initialized", {}, notify=True)
    assert client.send("ping")["result"] == {}


def test_tools_list_has_the_four_tools(client):
    tools = client.send("tools/list")["result"]["tools"]
    assert {t["name"] for t in tools} == {"fingerprint", "evaluate", "gate", "ledger_stats"}
    for tool in tools:
        assert tool["description"] and tool["inputSchema"]["type"] == "object"


def test_ledger_stats_on_an_empty_ledger(client):
    _err, payload = client.call("ledger_stats", {})
    assert payload["totals"]["trials"] == 0
    assert payload["cross_family"]["n_families"] == 0


def test_fingerprint_does_not_consume_a_trial(client):
    payload = {
        "factor": {"values": [[1.0, 2.0, 3.0], [3.0, 1.0, 2.0]]},
        "horizon": 5,
    }
    is_err, first = client.call("fingerprint", payload)
    assert not is_err and first["seen_before"] is False
    _err, second = client.call("fingerprint", payload)
    assert second["fp"] == first["fp"]
    _err, stats = client.call("ledger_stats", {})
    assert stats["totals"]["trials"] == 0, "fingerprinting must not create a trial"


def _grid(rows: int, cols: int, seed: int) -> list[list[float]]:
    """A panel wide enough to clear min_stocks (30 names per date)."""
    rng = np.random.default_rng(seed)
    return rng.standard_normal((rows, cols)).round(6).tolist()


def test_evaluate_records_a_trial_and_returns_a_verdict(client):
    factor = _grid(70, 40, 1)
    forward = _grid(70, 40, 2)
    is_err, result = client.call("evaluate", {"factor": {"values": factor}, "forward": {"values": forward}})
    assert not is_err, result
    assert result["trial_index"] == 1
    assert result["n_family"] == 1
    assert result["gate"]["verdict"] in {"REJECT", "PASS", "INSUFFICIENT_DATA"}
    assert result["summary"].startswith("Trial #1 of 1")


def test_evaluate_twice_is_one_trial_two_evaluations(client):
    factor = _grid(65, 40, 3)
    forward = _grid(65, 40, 4)
    args = {"factor": {"values": factor}, "forward": {"values": forward}, "with_gate": False}
    _e1, first = client.call("evaluate", args)
    _e2, second = client.call("evaluate", args)
    assert first["trial_id"] == second["trial_id"]
    assert second["n_evals"] == 2
    _err, stats = client.call("ledger_stats", {})
    assert stats["totals"]["trials"] == 1
    assert stats["totals"]["evaluations"] == 2


def test_missing_panel_returns_a_structured_error_with_the_path(client):
    is_err, payload = client.call("evaluate", {"factor": {"path": "missing.npz"}, "forward": {"values": [[1.0]]}})
    assert is_err
    assert payload["error"]["code"] == "PATH_NOT_FOUND"
    assert payload["error"]["resolved_path"].endswith("missing.npz")


def test_unknown_tool_is_a_protocol_error(client):
    response = client.send("tools/call", {"name": "nope", "arguments": {}})
    assert response["error"]["code"] == -32602


def test_bad_json_does_not_kill_the_server(client):
    assert client.proc.stdin is not None
    client.proc.stdin.write("this is not json\n")
    client.proc.stdin.flush()
    assert client.proc.stdout is not None
    error = json.loads(client.proc.stdout.readline())
    assert error["error"]["code"] == -32700
    assert client.send("ping")["result"] == {}, "server must survive a parse error"
