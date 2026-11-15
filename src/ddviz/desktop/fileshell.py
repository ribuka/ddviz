"""Opens a saved file with its app, or shows it selected in its folder, in the Windows shell (Issue #194)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def open_file(path: Path) -> None:
    """Open `path` with the app Windows associates with it.

    Without an associated app, Windows asks which app to open it with; that
    is not a failure.

    Raises
    ------
    OSError
        Windows cannot open it.
    """
    os.startfile(path)


def show_in_folder(path: Path) -> None:
    """Open `path`'s folder in Explorer with `path` selected; does not wait for Explorer.

    Raises
    ------
    OSError
        Explorer cannot be started.
    """
    # Passed as is: a list would quote "/select,<path>" as one argument,
    # which Explorer does not read. A Windows path holds no quote.
    subprocess.Popen(f'explorer.exe /select,"{path}"')
