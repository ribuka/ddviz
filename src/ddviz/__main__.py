"""Command line entry.

``ddviz [path ...]`` opens the app window for a Parquet file, a folder of
them (``--recursive`` also reads its subfolders) or several Parquet files
read one after another as one table; ``ddviz <path ...> --port N`` only
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


def make_app(paths: list[str], recursive: bool, token: str) -> FastAPI:
    """Build the UI server for a Parquet file, a folder of them or several files.

    Parameters
    ----------
    paths : list of str
        Absolute paths of the input: one Parquet file or folder, or several
        Parquet files.
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
    from ddviz.server.history import default_history_root
    from ddviz.server.settings import load_settings
    from ddviz.shared.cache import default_cache_root

    root = Path(tempfile.mkdtemp(prefix="ddviz-"))
    return create_app(
        paths,
        recursive,
        root,
        default_cache_root(),
        default_history_root(),
        load_settings(),
        token,
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
        "paths",
        nargs="*",
        metavar="path",
        help="Parquet file, folder of Parquet files, or several Parquet files, to plot",
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
    # Several paths with a folder among them fail at Load, on the page: the
    # exe has no console to print an error to.
    paths = [str(Path(p).resolve()) for p in args.paths]

    if args.port is None:
        from ddviz.desktop.window import run_window
        from ddviz.shared.inputs import input_label

        return run_window(paths or None, args.recursive, make_app, input_label)

    if not paths:
        parser.error("--port needs a Parquet file or folder")
    import uvicorn

    token = secrets.token_urlsafe(32)
    # Opening this URL once moves the token into a cookie of the browser.
    print(f"ddviz: http://127.0.0.1:{args.port}/?token={token}", flush=True)
    uvicorn.run(
        make_app(paths, args.recursive, token),
        host="127.0.0.1",
        port=args.port,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
