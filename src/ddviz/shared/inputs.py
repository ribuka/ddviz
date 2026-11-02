"""The Parquet files of an input: one file, the files in a folder, or several files.

The files of an input are read one after another as one table, so their
order decides the row numbers (hover, selection, table). The order is the
natural order of the paths relative to the folder (for several files, their
common folder): numbers compare by value (``data_2`` before ``data_10``) and
letters without case.
"""

from __future__ import annotations

import os
from pathlib import Path

from ddviz.shared.natural import natural_key

SUFFIX = ".parquet"
# Names other tools write next to the data and readers skip: Spark's
# ``_SUCCESS``, Arrow's ``_metadata``, and hidden files.
_HIDDEN = ("_", ".")


def path_key(relative: str) -> tuple:
    """Return the sort key of a relative path in natural order.

    Parameters
    ----------
    relative : str
        Path relative to the folder, with ``/`` between its parts.

    Returns
    -------
    tuple
        Per part, its natural key (`ddviz.shared.natural.natural_key`); the
        path itself last, so that the order is total.
    """
    return (tuple(natural_key(part) for part in relative.split("/")), relative)


def unique(paths: list[Path]) -> list[Path]:
    """Return the paths without repeats, keeping the first of each.

    Parameters
    ----------
    paths : list of pathlib.Path
        Absolute paths, such as those the OS dialog returns.

    Returns
    -------
    list of pathlib.Path
        The paths; two that differ only in case count as one on Windows.
    """
    seen: dict[str, Path] = {}
    for path in paths:
        seen.setdefault(os.path.normcase(str(path)), path)
    return list(seen.values())


def input_base(paths: list[Path]) -> Path | None:
    """Return the folder that the files of an input are named relative to.

    Parameters
    ----------
    paths : list of pathlib.Path
        The input (`unique`): one file or folder, or several files.

    Returns
    -------
    pathlib.Path or None
        A folder itself; a file's folder; for several files, the folder
        holding them all. None when they have none, on different drives.
    """
    if len(paths) == 1:
        return paths[0] if paths[0].is_dir() else paths[0].parent
    try:
        return Path(os.path.commonpath([p.parent for p in paths]))
    except ValueError:
        return None


def relative_name(file: Path, base: Path | None) -> str:
    """Return a file's name in its input: its path relative to `base`.

    Parameters
    ----------
    file : pathlib.Path
        A file of the input.
    base : pathlib.Path or None
        The input's folder (`input_base`); None names the file by its
        whole path.

    Returns
    -------
    str
        The path, with ``/`` between its parts.
    """
    return file.as_posix() if base is None else file.relative_to(base).as_posix()


def parquet_files(paths: list[Path], recursive: bool = False) -> list[Path]:
    """Return the Parquet files of an input in reading order.

    Parameters
    ----------
    paths : list of pathlib.Path
        The input (`unique`): a Parquet file, a folder of them, or several
        Parquet files.
    recursive : bool
        For a folder, also read the files in its subfolders.

    Returns
    -------
    list of pathlib.Path
        A file itself, whatever its name; for a folder, its files ending in
        ``.parquet`` (any case) in natural order, without those whose name
        or folder starts with ``_`` or ``.``; several files in natural
        order of their paths relative to their common folder.

    Raises
    ------
    ValueError
        When several paths include a folder.
    """
    if len(paths) > 1:
        folders = [p for p in paths if p.is_dir()]
        if folders:
            raise ValueError(
                f"複数を選ぶときはファイルだけにしてください：{folders[0]}"
            )
        base = input_base(paths)
        return sorted(paths, key=lambda f: path_key(relative_name(f, base)))
    path = paths[0]
    if not path.is_dir():
        return [path]
    found = []
    for folder, dirs, names in os.walk(path):
        dirs[:] = [d for d in dirs if recursive and not d.startswith(_HIDDEN)]
        found += [
            Path(folder) / name
            for name in names
            if name.lower().endswith(SUFFIX) and not name.startswith(_HIDDEN)
        ]
    return sorted(found, key=lambda f: path_key(relative_name(f, path)))


def input_name(paths: list[Path]) -> tuple[str, int]:
    """Return what names an input to the user: its first name and how many more.

    Parameters
    ----------
    paths : list of pathlib.Path
        The input (`unique`).

    Returns
    -------
    tuple of str and int
        The name of the file or folder, and 0; for several files, the name
        of the first in reading order and the number of the others.
    """
    if len(paths) == 1:
        return paths[0].name, 0
    base = input_base(paths)
    first = min(paths, key=lambda f: path_key(relative_name(f, base)))
    return first.name, len(paths) - 1


def input_label(paths: list[str]) -> str:
    """Return the input's name in the window's title.

    Parameters
    ----------
    paths : list of str
        The input: a Parquet file or folder, or several Parquet files.

    Returns
    -------
    str
        The name of the file or folder; for several files, the first in
        reading order and how many more, as ``data_1.parquet and 2 more``.
    """
    first, more = input_name(unique([Path(p) for p in paths]))
    return f"{first} and {more} more" if more else first
