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

import random
import shutil
import sqlite3
import time
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


_TRANSIENT = ("database is locked", "database table is locked", "readonly database", "unable to open")


def _is_transient(exc: sqlite3.OperationalError) -> bool:
    return any(tag in str(exc).lower() for tag in _TRANSIENT)


def connect(path: str | Path, attempts: int = 8) -> sqlite3.Connection:
    """Open (and migrate) a ledger. Safe to call concurrently.

    The whole open sequence is retried, not just the writes. On Windows a file that
    has just been created can be briefly unavailable (indexer, antivirus, another
    process checkpointing), and the failure surfaces as ``SQLITE_READONLY`` during
    ``PRAGMA`` rather than as a lock error. An agent will not retry for us, so the
    library has to.
    """
    last: sqlite3.OperationalError | None = None
    for attempt in range(attempts):
        try:
            return _connect_once(Path(path))
        except sqlite3.OperationalError as exc:
            if not _is_transient(exc) or attempt == attempts - 1:
                raise
            last = exc
            time.sleep(0.02 * (2**attempt) + random.random() * 0.02)
    raise last if last else RuntimeError("unreachable")


def _connect_once(db_path: Path) -> sqlite3.Connection:
    """One attempt at opening and migrating."""
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

    try:
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if version > SCHEMA_VERSION:
            raise RuntimeError(
                f"ledger schema v{version} is newer than this build (v{SCHEMA_VERSION}); "
                "upgrade alphaledger"
            )
        if version < SCHEMA_VERSION:
            if version > 0 and db_path.exists():
                backup = db_path.with_suffix(db_path.suffix + f".v{version}.bak")
                shutil.copy2(db_path, backup)
            with conn:
                conn.executescript(_schema_sql())
                conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    except Exception:
        # Do not leak a half-open handle into the retry loop above.
        conn.close()
        raise

    return conn
