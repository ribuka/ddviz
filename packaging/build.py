r"""Build the ddviz folder for distribution: ``dist\ddviz``.

Run from the repository root with ``uv run --group build packaging/build.py``.
It builds the exe with PyInstaller (onedir) and copies ``config`` and the
notices of the WebView2 SDK next to the exe. The WebView2 Runtime is not
bundled: the exe uses the one installed on the PC, or a fixed-version runtime
that an administrator places in ``webview2`` next to the exe.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / "packaging"
DIST = ROOT / "dist" / "ddviz"

# The notices shipped next to the exe, copied byte for byte (CRLF, for Notepad
# on Server 2016).
NOTICES = ("LICENSE-WebView2-SDK.txt", "NOTICE.txt")


def busy_files(folder: Path) -> list[Path]:
    """List the files in ``folder`` that cannot be opened for writing.

    A running ``ddviz.exe`` keeps its exe and DLLs open, and PyInstaller's
    ``--clean`` fails to delete them only after the whole build. Renaming the
    folder is no test: Windows allows it while the exe runs.

    Parameters
    ----------
    folder : Path
        The folder to check. A missing folder has no busy files.

    Returns
    -------
    list[Path]
        The busy files.
    """
    busy = []
    for path in sorted(folder.rglob("*")):
        if not path.is_file():
            continue
        try:
            with path.open("r+b"):
                pass
        except PermissionError:
            busy.append(path)
    return busy


def main() -> int:
    r"""Build ``dist\ddviz``.

    Returns
    -------
    int
        Exit code.
    """
    busy = busy_files(DIST)
    if busy:
        print(
            f"error: {DIST} is in use; close ddviz.exe and build again. "
            f"In use: {busy[0]}",
            file=sys.stderr,
            flush=True,
        )
        return 1
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            str(ROOT / "dist"),
            "--workpath",
            str(ROOT / "build"),
            str(PACKAGING / "ddviz.spec"),
        ],
        check=True,
    )
    shutil.copytree(ROOT / "config", DIST / "config")
    for name in NOTICES:
        shutil.copy2(PACKAGING / name, DIST / name)
    print(f"built {DIST}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
