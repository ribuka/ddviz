"""Command line entry: ``ddviz <parquet>`` starts the UI server; ``--worker`` runs a worker."""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path


def main() -> int:
    """Parse the command line and run the server or a worker.

    Returns
    -------
    int
        Exit code.
    """
    if "--worker" in sys.argv[1:]:
        from ddviz.worker import main as worker_main

        return worker_main()

    parser = argparse.ArgumentParser(prog="ddviz")
    parser.add_argument("path", help="Parquet file to plot")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    import uvicorn

    from ddviz.server import create_app

    root = Path(tempfile.mkdtemp(prefix="ddviz-"))
    print(f"ddviz: http://127.0.0.1:{args.port}/", flush=True)
    uvicorn.run(
        create_app(str(Path(args.path).resolve()), root),
        host="127.0.0.1",
        port=args.port,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
