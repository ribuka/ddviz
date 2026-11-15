"""Unblock the DLLs bundled in the exe that Windows marked as from the internet.

A zip downloaded from the internet carries the Mark of the Web (the
``Zone.Identifier`` alternate data stream), and Explorer may pass it on to
the files it extracts. .NET Framework then refuses to load those DLLs, and
pythonnet fails before the window opens (Issue #207). The exe removes the
mark from the DLLs of its own bundle (``sys._MEIPASS``) before pywebview
loads pythonnet; it does nothing in development.

Only the DLLs inside the bundle are touched, without following reparse
points (junctions, symbolic links); the DLL itself is not written to. A DLL
without the mark is left alone, so a read-only bundle without marks works.
"""

from __future__ import annotations

import os
import stat
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

#: The alternate data stream that holds the Mark of the Web.
ZONE_STREAM = "Zone.Identifier"


class UnblockError(Exception):
    """A bundled DLL could not be unblocked: its folder listed, or its mark read or removed.

    Parameters
    ----------
    path : pathlib.Path
        The folder or the DLL.
    action : str
        What failed: ``"list"``, ``"read"`` or ``"remove"``.
    error : OSError
        The OS's error.
    """

    def __init__(self, path: Path, action: str, error: OSError) -> None:
        super().__init__(f"cannot {action} {path}: {error}")
        self.path = path
        self.action = action
        self.error = error


def bundle_dir() -> Path | None:
    """Return the folder of the exe's bundled files, whose DLLs are unblocked.

    Returns
    -------
    pathlib.Path or None
        ``sys._MEIPASS`` (``_internal`` next to the onedir exe) in the
        PyInstaller exe on Windows; None in development and off Windows.
    """
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return None
    return Path(sys._MEIPASS)


def _scan(folder: Path) -> list[os.DirEntry]:
    """Return the entries of a folder (`os.scandir`; tests replace it)."""
    with os.scandir(folder) as entries:
        return list(entries)


def _is_reparse_point(entry: os.DirEntry) -> bool:
    """Tell whether an entry is a junction, a symbolic link or another reparse point."""
    if entry.is_symlink() or entry.is_junction():
        return True
    attributes = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
    return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def bundled_dlls(root: Path) -> Iterator[Path]:
    """Yield the DLLs in a folder and its subfolders, without following reparse points.

    Parameters
    ----------
    root : pathlib.Path
        The bundle's folder.

    Yields
    ------
    pathlib.Path
        Each regular file whose extension is ``.dll`` in any case.

    Raises
    ------
    UnblockError
        When a folder cannot be listed (``action="list"``).
    """
    folders = [root]
    while folders:
        folder = folders.pop()
        try:
            entries = _scan(folder)
            for entry in entries:
                if _is_reparse_point(entry):
                    continue
                if entry.is_dir(follow_symlinks=False):
                    folders.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False) and entry.name.lower().endswith(
                    ".dll"
                ):
                    yield Path(entry.path)
        except OSError as error:
            raise UnblockError(folder, "list", error) from error


def _zone_stream(dll: Path) -> str:
    """Return the path of the mark's stream of a file."""
    return f"{dll}:{ZONE_STREAM}"


def _has_stream(stream: str) -> bool:
    """Tell whether a stream exists; a missing one is no mark, other errors raise."""
    try:
        os.stat(stream)
    except FileNotFoundError:
        return False
    return True


def _remove_stream(stream: str) -> None:
    """Remove a stream (`os.remove`; tests replace it)."""
    os.remove(stream)


def unblock_dll(dll: Path) -> bool:
    """Remove the Mark of the Web of one DLL, if it has one.

    Parameters
    ----------
    dll : pathlib.Path
        The DLL.

    Returns
    -------
    bool
        True when a mark was removed, False when there was none (nothing is
        written then).

    Raises
    ------
    UnblockError
        When the mark cannot be read (``"read"``) or removed (``"remove"``),
        e.g. without write access: that is not taken as no mark.
    """
    stream = _zone_stream(dll)
    try:
        if not _has_stream(stream):
            return False
    except OSError as error:
        raise UnblockError(dll, "read", error) from error
    try:
        _remove_stream(stream)
    except OSError as error:
        raise UnblockError(dll, "remove", error) from error
    return True


def unblock_bundle(root: Path) -> int:
    """Remove the Mark of the Web of every DLL in the bundle; stop at the first failure.

    Parameters
    ----------
    root : pathlib.Path
        The bundle's folder (`bundle_dir`).

    Returns
    -------
    int
        How many marks were removed.

    Raises
    ------
    UnblockError
        At the first folder that cannot be listed or mark that cannot be
        read or removed; the marks already removed stay removed.
    """
    return sum(unblock_dll(dll) for dll in bundled_dlls(root))


def powershell_literal(text: str) -> str:
    """Quote a text as a PowerShell single-quoted string.

    Parameters
    ----------
    text : str
        The text, e.g. a path.

    Returns
    -------
    str
        ``'...'`` with each ``'`` inside doubled.
    """
    return "'" + text.replace("'", "''") + "'"


def failure_message(root: Path, error: UnblockError) -> str:
    """Return the message box's text for a bundle that cannot be unblocked.

    Parameters
    ----------
    root : pathlib.Path
        The bundle's folder, for the administrator's command.
    error : UnblockError
        What failed.

    Returns
    -------
    str
        The cause, the path and the OS's error, and the two ways to fix it.
    """
    command = (
        f"Get-ChildItem -LiteralPath {powershell_literal(str(root))} "
        "-Recurse -File -Filter '*.dll' | Unblock-File"
    )
    return (
        "インターネットから取得した DLL のブロックを解除できませんでした。\n"
        f"対象：{error.path}\n"
        f"エラー：{error.error}\n\n"
        "次のどちらかで解除してから、もう一度起動してください。\n"
        "1. 元の ZIP のプロパティで「許可する」にチェックを入れて適用し、"
        "書き込みのできる別のフォルダへ展開し直す。\n"
        "2. 共有フォルダに置いたときは、管理者が PowerShell で次を実行する。\n"
        f"{command}"
    )


def unblock_or_warn(warn: Callable[[str], None]) -> bool:
    """Unblock the exe's bundled DLLs before pythonnet loads them; tell the user when that fails.

    Parameters
    ----------
    warn : callable
        Shows the failure's message once (`ddviz.desktop.messages.show_warning`).

    Returns
    -------
    bool
        True when the run may go on (also in development), False when a
        DLL could not be unblocked and the user has been told.
    """
    root = bundle_dir()
    if root is None:
        return True
    try:
        unblock_bundle(root)
    except UnblockError as error:
        warn(failure_message(root, error))
        return False
    return True
