r"""Build the ddviz folder for distribution: ``dist\ddviz``.

Run from the repository root with ``uv run --group build packaging/build.py``.
It builds the exe with PyInstaller (onedir) and copies ``config`` (without
the local settings, ``settings.local.toml``, which the Preferences of the
app write) and the notices of the WebView2 SDK next to the exe. The WebView2 Runtime is not
bundled: the exe uses the one installed on the PC, or a fixed-version runtime
that an administrator places in ``webview2`` next to the exe.
"""

from __future__ import annotations

import shutil
import struct
import subprocess
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / "packaging"
DIST = ROOT / "dist" / "ddviz"

# The notices shipped next to the exe, copied byte for byte (CRLF, for Notepad
# on Server 2016).
NOTICES = ("LICENSE-WebView2-SDK.txt", "NOTICE.txt")
# The local settings of this checkout, which the distribution leaves out:
# it ships the shared ``settings.toml`` alone.
LOCAL_SETTINGS = "settings.local.toml"
# The image of the splash screen, which ddviz.spec reads at this fixed path:
# written by each build, so the repository holds no binary. Outside
# build/ddviz, which PyInstaller's --clean removes.
SPLASH_PNG = ROOT / "build" / "splash.png"
# The image's size and colour: the colour of the window's title bar.
SPLASH_SIZE = (360, 100)
SPLASH_RGB = (0xF3, 0xF3, 0xF3)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _chunk(kind: bytes, data: bytes) -> bytes:
    """Return one PNG chunk: its length, type, data and CRC."""
    crc = zlib.crc32(kind + data)
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)


def write_splash_png(path: Path) -> None:
    """Write the splash screen's image: a plain #f3f3f3 rectangle, 360 x 100 px.

    Parameters
    ----------
    path : Path
        The PNG to write; its folder is made if missing.
    """
    width, height = SPLASH_SIZE
    # Each row: filter type 0 (none), then its RGB pixels.
    row = bytes(1) + bytes(SPLASH_RGB) * width
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        PNG_SIGNATURE
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(row * height, 9))
        + _chunk(b"IEND", b"")
    )


def copy_config(source: Path, target: Path) -> None:
    """Copy the ``config`` folder `source` to `target`, without the local settings.

    Parameters
    ----------
    source : Path
        The repository's ``config``; it is not changed.
    target : Path
        The distribution's ``config``, which must not exist.
    """
    shutil.copytree(source, target, ignore=shutil.ignore_patterns(LOCAL_SETTINGS))


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
    write_splash_png(SPLASH_PNG)
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
    copy_config(ROOT / "config", DIST / "config")
    for name in NOTICES:
        shutil.copy2(PACKAGING / name, DIST / name)
    print(f"built {DIST}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
