"""The Parquet files of an input: one file, or the files in a folder.

The files of a folder are read one after another as one table, so their
order decides the row numbers (hover, selection, table). The order is the
natural order of the paths relative to the folder: numbers compare by value
(``data_2`` before ``data_10``) and letters without case.
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


def parquet_files(path: Path, recursive: bool = False) -> list[Path]:
    """Return the Parquet files of an input in reading order.

    Parameters
    ----------
    path : pathlib.Path
        A Parquet file, or a folder of them.
    recursive : bool
        For a folder, also read the files in its subfolders.

    Returns
    -------
    list of pathlib.Path
        The file itself; for a folder, its files ending in ``.parquet`` (any
        case) in natural order, without those whose name or folder starts
        with ``_`` or ``.``.
    """
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
    return sorted(found, key=lambda f: path_key(f.relative_to(path).as_posix()))
