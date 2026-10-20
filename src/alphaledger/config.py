"""Where the ledger lives.

One place decides, everything else asks. The ordering matters and is worth
spelling out, because "which database did it write to" is the kind of question
that costs an hour at the wrong moment:

1. ``ALPHALEDGER_DB`` — explicit file path, wins outright.
2. ``ALPHALEDGER_HOME`` — directory, ledger at ``<home>/ledger.db``.
3. Nearest ``.alphaledger/`` walking up from the working directory.
4. Nearest ``.git`` walking up, creating ``.alphaledger/`` there.
5. ``~/.alphaledger/``.

Project-local by default. Trial counts are per research project: merging two
unrelated studies into one ledger would over-penalise both.

Note the environment variable names deliberately avoid ``KEY``, ``TOKEN``,
``SECRET`` and ``PASSWORD``: the dsh MCP bridge scrubs any parent variable
matching ``/KEY|PASSWORD|SECRET|TOKEN/i`` before spawning a server, so a variable
named ``ALPHALEDGER_KEY`` would silently vanish.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["workdir", "ledger_path", "ensure_ledger_dir", "SCRUBBED_NAME_HINT"]

SCRUBBED_NAME_HINT = "avoid KEY/TOKEN/SECRET/PASSWORD in env var names (dsh scrubs them)"


def workdir() -> Path:
    """Base directory for resolving relative panel paths."""
    env = os.environ.get("ALPHALEDGER_CWD")
    return Path(env).expanduser().resolve() if env else Path.cwd().resolve()


def _walk_up(start: Path, marker: str) -> Path | None:
    for parent in (start, *start.parents):
        candidate = parent / marker
        if candidate.exists():
            return candidate
    return None


def ledger_path(create_dir: bool = True) -> Path:
    """Resolve the ledger file, honouring the five-step order above."""
    explicit = os.environ.get("ALPHALEDGER_DB")
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_absolute():
            path = workdir() / path
        if create_dir:
            path.parent.mkdir(parents=True, exist_ok=True)
        return path.resolve()

    home_env = os.environ.get("ALPHALEDGER_HOME")
    if home_env:
        base = Path(home_env).expanduser()
        if not base.is_absolute():
            base = workdir() / base
        if create_dir:
            base.mkdir(parents=True, exist_ok=True)
        return (base / "ledger.db").resolve()

    cwd = workdir()
    found = _walk_up(cwd, ".alphaledger")
    if found is not None:
        if create_dir:
            found.mkdir(parents=True, exist_ok=True)
        return (found / "ledger.db").resolve()

    git_root = _walk_up(cwd, ".git")
    if git_root is not None and (git_root / ".git").exists():
        base = git_root / ".alphaledger"
        if create_dir:
            base.mkdir(parents=True, exist_ok=True)
        return (base / "ledger.db").resolve()

    base = Path.home() / ".alphaledger"
    if create_dir:
        base.mkdir(parents=True, exist_ok=True)
    return (base / "ledger.db").resolve()


def ensure_ledger_dir() -> Path:
    """Create the ledger's parent directory and return the path."""
    path = ledger_path(create_dir=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
