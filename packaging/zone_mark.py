"""Give files the Mark of the Web and read it back, for packaging/smoke.py.

The mark is the ``Zone.Identifier`` alternate data stream that Windows
writes on files from the internet (on NTFS; off Windows it is a file of
that name, which the tests use). The DLLs are found here on their own, not
with the code that the smoke test checks (`ddviz.desktop.dll_access`).
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

#: The mark of a file from the internet (zone 3).
MARK = b"[ZoneTransfer]\r\nZoneId=3\r\n"


def stream(path: Path) -> str:
    """Return the path of a file's mark.

    Parameters
    ----------
    path : pathlib.Path
        The file.

    Returns
    -------
    str
        ``<path>:Zone.Identifier``.
    """
    return f"{path}:Zone.Identifier"


def dlls(root: Path) -> list[Path]:
    """Return the DLLs in a folder and its subfolders, without following links.

    Parameters
    ----------
    root : pathlib.Path
        The folder.

    Returns
    -------
    list of pathlib.Path
        The regular files whose extension is ``.dll`` in any case, sorted.
    """
    found = []
    for folder, _, names in os.walk(root, followlinks=False):
        for name in names:
            path = Path(folder) / name
            if name.lower().endswith(".dll") and path.is_file() and not path.is_symlink():
                found.append(path)
    return sorted(found)


def mark(path: Path) -> None:
    """Give a file the mark, and fail unless it reads back.

    Parameters
    ----------
    path : pathlib.Path
        The file.

    Raises
    ------
    RuntimeError
        When the mark cannot be written or does not read back.
    """
    try:
        with open(stream(path), "wb") as f:
            f.write(MARK)
        with open(stream(path), "rb") as f:
            written = f.read()
    except OSError as error:
        raise RuntimeError(f"cannot mark {path}: {error}") from error
    if written != MARK:
        raise RuntimeError(f"the mark of {path} reads back as {written!r}")


def is_marked(path: Path) -> bool:
    """Tell whether a file has the mark.

    Parameters
    ----------
    path : pathlib.Path
        The file.

    Returns
    -------
    bool
        True when its ``Zone.Identifier`` stream exists.
    """
    return os.path.exists(stream(path))


def sha256(path: Path) -> str:
    """Return the SHA-256 of a file's content (its main stream).

    Parameters
    ----------
    path : pathlib.Path
        The file.

    Returns
    -------
    str
        The hex digest.
    """
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()
