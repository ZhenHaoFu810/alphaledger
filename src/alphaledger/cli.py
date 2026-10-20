"""Command line entry points.

`alphaledger-mcp` is what dsh launches (via ``uvx alphaledger-mcp``); `alphaledger`
is for humans. Keeping both in one module means one place to change when the
launch story changes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from alphaledger import __version__
from alphaledger.config import ledger_path, workdir
from alphaledger.evaluate import ENGINE_VERSION
from alphaledger.store.ledger import Ledger

__all__ = ["main", "serve"]


def serve(argv: list[str] | None = None) -> int:
    """stdio MCP server — the entry point dsh / Claude Code / Codex call."""
    parser = argparse.ArgumentParser(prog="alphaledger-mcp", add_help=True)
    parser.add_argument("--db", default=None, help="ledger path (default: project-local .alphaledger/)")
    parser.add_argument("--version", action="version", version=f"alphaledger {__version__}")
    args, _unknown = parser.parse_known_args(argv)

    from alphaledger.server import serve as _serve

    return _serve(args.db)


def _cmd_doctor() -> int:
    try:
        import numpy

        np_version = numpy.__version__
    except ImportError:  # pragma: no cover
        np_version = "MISSING"

    path = ledger_path()
    info = {
        "alphaledger": __version__,
        "engine_version": ENGINE_VERSION,
        "python": sys.version.split()[0],
        "numpy": np_version,
        "cwd": str(workdir()),
        "ledger": str(path),
        "ledger_exists": path.exists(),
    }
    try:
        with Ledger(path) as ledger:
            row = ledger.conn.execute("PRAGMA user_version").fetchone()
            info["schema_version"] = int(row[0])
            info["trials"] = int(ledger.conn.execute("SELECT COUNT(*) FROM trial").fetchone()[0])
    except Exception as exc:  # noqa: BLE001 - doctor reports, never crashes
        info["ledger_error"] = f"{type(exc).__name__}: {exc}"
    print(json.dumps(info, indent=2))
    return 0 if np_version != "MISSING" else 1


def _cmd_init(path: str | None) -> int:
    target = Path(path).resolve() if path else (workdir() / ".alphaledger")
    target.mkdir(parents=True, exist_ok=True)
    with Ledger(target / "ledger.db") as ledger:
        ledger.conn.execute("SELECT 1")
    print(f"ledger ready at {target / 'ledger.db'}")
    return 0


def _cmd_stats() -> int:
    with Ledger() as ledger:
        rows = ledger.conn.execute(
            "SELECT panel_id, horizon, COUNT(*) n, SUM(n_evals) e FROM trial GROUP BY 1,2 ORDER BY n DESC"
        ).fetchall()
        total = ledger.conn.execute("SELECT COUNT(*) FROM trial").fetchone()[0]
    print(f"ledger: {ledger.path}")
    print(f"trials: {total}")
    for row in rows:
        print(
            f"  panel {row['panel_id']} horizon {row['horizon']}: "
            f"{row['n']} trials, {row['e']} evaluations"
        )
    return 0


def _cmd_demo(name: str) -> int:
    demos_dir = Path(__file__).resolve().parents[2] / "demos"
    script = demos_dir / f"{name}.py"
    if not script.exists():
        available = sorted(p.stem for p in demos_dir.glob("*.py")) if demos_dir.exists() else []
        print(
            f"demo {name!r} is not available here.\n"
            f"  looked in: {demos_dir}\n"
            "  demos ship with the source checkout, not with the installed wheel;"
            " run `python demos/<name>.py` from a clone.",
            file=sys.stderr,
        )
        if available:
            print(f"  available: {', '.join(available)}", file=sys.stderr)
        return 2
    import runpy

    runpy.run_path(str(script), run_name="__main__")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="alphaledger", description="A trial ledger for factor research.")
    parser.add_argument("--version", action="version", version=f"alphaledger {__version__}")
    sub = parser.add_subparsers(dest="command")

    init_p = sub.add_parser("init", help="create a ledger in the current project")
    init_p.add_argument("--path", default=None)

    sub.add_parser("doctor", help="print versions, paths and ledger state")
    sub.add_parser("stats", help="summarize the ledger")

    demo_p = sub.add_parser("demo", help="run a bundled demo")
    demo_p.add_argument("name", choices=["noise_200", "true_factor", "leaky_momentum", "equivalents"])

    args = parser.parse_args(argv)
    if args.command == "init":
        return _cmd_init(args.path)
    if args.command == "doctor":
        return _cmd_doctor()
    if args.command == "stats":
        return _cmd_stats()
    if args.command == "demo":
        return _cmd_demo(args.name)
    parser.print_help()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
