"""Command line entry.

``ddviz [parquet]`` opens the app window; ``ddviz <parquet> --port N`` only
serves the UI on that port, for a browser in development; ``--worker`` runs a
worker.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # a worker does not import fastapi
    from fastapi import FastAPI


def make_app(path: str) -> FastAPI:
    """Build the UI server for a Parquet file.

    Parameters
    ----------
    path : str
        Absolute path of the Parquet file.

    Returns
    -------
    fastapi.FastAPI
        The application.
    """
    from ddviz.server.app import create_app
    from ddviz.server.settings import load_settings
    from ddviz.shared.cache import default_cache_root

    root = Path(tempfile.mkdtemp(prefix="ddviz-"))
    return create_app(path, root, default_cache_root(), load_settings())


def main() -> int:
    """Parse the command line and run the app, the server or a worker.

    Returns
    -------
    int
        Exit code.
    """
    if "--worker" in sys.argv[1:]:
        from ddviz.workers.worker import main as worker_main

        return worker_main()

    parser = argparse.ArgumentParser(prog="ddviz")
    parser.add_argument("path", nargs="?", help="Parquet file to plot")
    parser.add_argument(
        "--port", type=int, help="serve on this port for a browser, without a window"
    )
    args = parser.parse_args()

    if args.port is None:
        from ddviz.desktop.window import run_window

        return run_window(args.path, make_app)

    if args.path is None:
        parser.error("--port needs a Parquet file")
    import uvicorn

    print(f"ddviz: http://127.0.0.1:{args.port}/", flush=True)
    uvicorn.run(
        make_app(str(Path(args.path).resolve())), host="127.0.0.1", port=args.port
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
