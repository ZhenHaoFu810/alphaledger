"""Structurally validate the dsh bundle against the host's documented schema.

dsh is not installed here, so this checks the parts that can be checked offline:
the manifest declares a patch, the patch inserts the official MCP client with a
stdio transport, and every file the manifest promises exists. It cannot prove the
host accepts it — only `dsh plugin add` can do that — so this is a guard against
typos, not a substitute for running it.

    python tests/test_dsh_bundle.py     # or via pytest
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

BUNDLE = Path(__file__).resolve().parents[1] / "dsh" / "alphaledger"
REQUIRED_CONFIG = {"serverName", "transport"}
ALLOWED_KEYS = {
    "serverName",
    "transport",
    "command",
    "args",
    "env",
    "cwd",
    "url",
    "headers",
    "toolCallTimeoutMs",
    "maxInstructionBytes",
    "failOnStartupError",
    "reconnect",
}


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads((BUNDLE / "package.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def patch() -> list:
    return yaml.safe_load((BUNDLE / "cordis.patch.yml").read_text(encoding="utf-8"))


def test_manifest_declares_a_patch(manifest):
    assert manifest["dsh"]["bundle"]["patch"] == "./cordis.patch.yml"
    assert (BUNDLE / manifest["dsh"]["bundle"]["patch"]).is_file()


def test_every_promised_file_exists(manifest):
    for pattern in manifest["files"]:
        assert list(BUNDLE.glob(pattern)), f"files entry {pattern!r} matches nothing"


def test_exports_resolve(manifest):
    """The host reads the icon and locale strings through package exports.

    Subpath *patterns* (``./locale/*.json``) are legal in exports, so this resolves
    globs as well as literal paths.
    """
    for subpath, target in manifest["exports"].items():
        if "*" in target:
            assert list(BUNDLE.glob(target)), f"{subpath} -> {target} matches nothing"
        else:
            assert (BUNDLE / target).is_file(), f"{subpath} -> {target} missing"


def test_patch_inserts_the_official_client(patch):
    assert isinstance(patch, list) and len(patch) == 1
    insert = patch[0]["insert"]
    assert len(insert) == 1
    row = insert[0]
    assert row["name"] == "@deepseek-ai/dsh-mcp-client", "must not reinvent the transport"
    assert row["id"] == "alphaledger"


def test_transport_is_stdio_and_launchable(patch):
    config = patch[0]["insert"][0]["config"]
    assert set(config) >= REQUIRED_CONFIG
    assert config["transport"] == "stdio"
    assert config["serverName"] == "alphaledger"
    assert config["command"] == "uvx", "dsh does not install Python; uvx has to do it"
    assert "alphaledger-mcp" in config["args"]


def test_unknown_config_keys_would_be_rejected(patch):
    """The client schema is strict about key names; a typo silently does nothing."""
    config = patch[0]["insert"][0]["config"]
    assert set(config) <= ALLOWED_KEYS, f"unknown keys: {set(config) - ALLOWED_KEYS}"


def test_startup_errors_are_loud(patch):
    """With failOnStartupError=false the tools vanish and the user sees nothing."""
    assert patch[0]["insert"][0]["config"]["failOnStartupError"] is True


def test_locale_files_are_valid_json():
    for name in ("en", "zh"):
        data = json.loads((BUNDLE / "locale" / f"{name}.json").read_text(encoding="utf-8"))
        assert data["meta"]["title"] == "alphaledger"
        assert len(data["meta"]["description"]) > 20
