"""Command line entry.

``ddviz [path]`` opens the app window for a Parquet file or a folder of them
(``--recursive`` also reads its subfolders); ``ddviz <path> --port N`` only
serves the UI on that port, for a browser in development, and prints the URL
with the token to open; ``--worker`` runs a worker.
"""

from __future__ import annotations

import argparse
import secrets
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # a worker does not import fastapi
    from fastapi import FastAPI


def make_app(path: str, recursive: bool, token: str) -> FastAPI:
    """Build the UI server for a Parquet file or a folder of them.

    Parameters
    ----------
    path : str
        Absolute path of the Parquet file or folder.
    recursive : bool
        For a folder, also read the files in its subfolders.
    token : str
        Secret of this run; requests without it are refused.

    Returns
    -------
    fastapi.FastAPI
        The application.
    """
    from ddviz.server.app import create_app
    from ddviz.server.settings import load_settings
    from ddviz.shared.cache import default_cache_root

    root = Path(tempfile.mkdtemp(prefix="ddviz-"))
    return create_app(
        path, recursive, root, default_cache_root(), load_settings(), token
    )


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
    parser.add_argument(
        "path", nargs="?", help="Parquet file, or folder of Parquet files, to plot"
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="for a folder, also read the files in its subfolders",
    )
    parser.add_argument(
        "--port", type=int, help="serve on this port for a browser, without a window"
    )
    args = parser.parse_args()

    if args.port is None:
        from ddviz.desktop.window import run_window

        return run_window(args.path, args.recursive, make_app)

    if args.path is None:
        parser.error("--port needs a Parquet file or folder")
    import uvicorn

    token = secrets.token_urlsafe(32)
    # Opening this URL once moves the token into a cookie of the browser.
    print(f"ddviz: http://127.0.0.1:{args.port}/?token={token}", flush=True)
    uvicorn.run(
        make_app(str(Path(args.path).resolve()), args.recursive, token),
        host="127.0.0.1",
        port=args.port,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
