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


def main() -> int:
    r"""Build ``dist\ddviz``.

    Returns
    -------
    int
        Exit code.
    """
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
