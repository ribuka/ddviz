"""Command line entry.

``ddviz [path ...]`` opens the app window for a Parquet file, a folder of
them (``--recursive`` also reads its subfolders) or several Parquet files
read one after another as one table; ``ddviz <path ...> --port N`` only
serves the UI on that port, for a browser in development, and prints the URL
with the token to open; ``--worker`` runs a worker. ``--check-desktop-runtime``
(not in ``--help``) checks, in the exe, that the DLLs of the window load:
packaging/smoke.py runs it.
"""

from __future__ import annotations

import argparse
import secrets
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # a worker does not import fastapi
    from fastapi import FastAPI

    from ddviz.server.api_saves import SaveActions


def make_app(
    paths: list[str],
    recursive: bool,
    token: str,
    frontend_pids: Callable[[], list[int] | None] | None = None,
    desktop: bool = False,
    saves: SaveActions | None = None,
) -> FastAPI:
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
    frontend_pids : callable or None
        Returns the ids of the window's WebView2 processes, for the memory in
        the footer; None in a browser.
    desktop : bool
        Serving the desktop window, whose page draws its title bar.
    saves : SaveActions or None
        The window's saves of the plot's data (`ddviz.server.api_saves`);
        None in a browser.

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
        frontend_pids,
        desktop,
        saves,
    )


def main() -> int:
    """Parse the command line and run the app, the server or a worker.

    Returns
    -------
    int
        Exit code.
    """
    # With the check, ``--worker`` is left to argparse, which refuses it.
    if "--worker" in sys.argv[1:] and "--check-desktop-runtime" not in sys.argv[1:]:
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
    parser.add_argument(
        "--check-desktop-runtime", action="store_true", help=argparse.SUPPRESS
    )
    args = parser.parse_args()
    if args.check_desktop_runtime:
        if args.paths or args.recursive or args.port is not None:
            parser.error("--check-desktop-runtime takes no other arguments")
        from ddviz.desktop.runtime_check import check_desktop_runtime

        return check_desktop_runtime()
    # Several paths with a folder among them fail at Load, on the page: the
    # exe has no console to print an error to.
    paths = [str(Path(p).resolve()) for p in args.paths]

    if args.port is None:
        from ddviz.desktop.dll_access import unblock_or_warn
        from ddviz.desktop.messages import show_warning

        # Before the window module: pywebview loads pythonnet's DLLs.
        if not unblock_or_warn(show_warning):
            return 1
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
