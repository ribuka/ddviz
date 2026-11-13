"""Columns added to an input of several Parquet files: each row's source file.

When an input reads two files or more one after another
(`ddviz.shared.inputs.parquet_files`), each row gets the absolute path of
its file (``source``) and the file's name without its extension
(``filename``), after the columns of the files. A name the files already
use is kept for their column; the added one takes the first free name of
``_2``, ``_3``, ... (case-sensitive, like the schema).
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

# The kinds of added column, in the order they follow the files' columns.
KINDS = ("source", "filename")
# Their type, as the schema writes it.
DTYPE = "String"


def generated_names(present: Iterable[str], files: int) -> dict[str, str]:
    """Return the names of the added columns, with their kinds.

    Parameters
    ----------
    present : iterable of str
        The columns of all the files.
    files : int
        The files the input reads, rows or not.

    Returns
    -------
    dict of str to str
        Per added column, in order, its kind (`KINDS`); empty for one file.
    """
    if files < 2:
        return {}
    taken = set(present)
    names = {}
    for kind in KINDS:
        name, n = kind, 1
        while name in taken:
            n += 1
            name = f"{kind}_{n}"
        taken.add(name)
        names[name] = kind
    return names


def generated_value(kind: str, path: str) -> str:
    r"""Return the value of an added column in the rows of a file.

    Parameters
    ----------
    kind : str
        ``"source"`` or ``"filename"``.
    path : str
        The file.

    Returns
    -------
    str
        For ``"source"``, the absolute path; for ``"filename"``, the name
        without its last extension (``C:\data\run.01.parquet`` gives
        ``run.01``).
    """
    file = Path(path).absolute()
    if kind == "source":
        return str(file)
    if kind == "filename":
        return file.stem
    raise ValueError(f"unknown added column: {kind}")


def part_key(dtype: str, kind: str | None) -> str:
    """Return what names a column's parts in the column cache, besides its name.

    An added column's parts are told apart from those of a file's column of
    the same name and type: replacing a file can give a name to the other.

    Parameters
    ----------
    dtype : str
        The input's type of the column.
    kind : str or None
        The kind of an added column; None for a column of the files.

    Returns
    -------
    str
        The key (`ddviz.shared.cache.ColumnCache.parts`).
    """
    return dtype if kind is None else f"{dtype}\0added:{kind}"
