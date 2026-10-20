"""SQLite plumbing: connection, pragmas, migration.

Two decisions worth the ink:

* **WAL with a busy timeout**, because an agent may run several tool calls at once
  and the alternative is ``database is locked`` at the worst possible moment.
* **A fallback to the rollback journal on synced folders** (OneDrive, Dropbox,
  iCloud). WAL relies on shared memory and file locking that these services break
  in creative ways; the failure looks like corruption, not like an error.

Schema versions are tracked in ``PRAGMA user_version``. Migration is
forward-only, and it copies the file aside before touching an older database.
"""

from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

__all__ = ["SCHEMA_VERSION", "connect", "now", "is_synced_path"]

SCHEMA_VERSION = 1
_SYNCED_MARKERS = ("onedrive", "dropbox", "icloud", "google drive", "googledrive")


def now() -> str:
    """UTC timestamp, second resolution, sortable as text."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_synced_path(path: Path) -> bool:
    lowered = str(path).lower()
    return any(marker in lowered for marker in _SYNCED_MARKERS)


def _schema_sql() -> str:
    return (Path(__file__).with_name("schema.sql")).read_text(encoding="utf-8")


def connect(path: str | Path) -> sqlite3.Connection:
    """Open (and migrate) a ledger. Safe to call concurrently."""
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path), timeout=5.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")

    # Only switch the journal mode when it differs. On Windows, `PRAGMA
    # journal_mode=WAL` needs a brief exclusive lock, so eight processes racing to
    # "set" an already-WAL database can surface as SQLITE_READONLY rather than as a
    # lock error. Reading first makes the call a no-op in the common case.
    desired = "DELETE" if is_synced_path(db_path) else "WAL"
    current = str(conn.execute("PRAGMA journal_mode").fetchone()[0]).upper()
    if current != desired:
        conn.execute(f"PRAGMA journal_mode={desired}")

    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if version > SCHEMA_VERSION:
        raise RuntimeError(
            f"ledger schema v{version} is newer than this build (v{SCHEMA_VERSION}); upgrade alphaledger"
        )
    if version < SCHEMA_VERSION:
        if version > 0 and db_path.exists():
            backup = db_path.with_suffix(db_path.suffix + f".v{version}.bak")
            shutil.copy2(db_path, backup)
        with conn:
            conn.executescript(_schema_sql())
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    return conn
