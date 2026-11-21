"""The columns a join adds to the input, and what names their parts.

An input can take the columns of another table (the joined table) side by
side, by keys or by the order of the rows (`ddviz.server.source.Source.join`).
After the columns of the input come, in order: ``_joined`` (by keys only:
``both`` or ``left_only`` per row), the columns of the joined table but its
keys, and its added columns (``source_joined``, ``filename_joined``, for a
joined table of several files). A name already taken (case-sensitive, like
the schema) moves to the first free one of a series (a column left out takes
no name):

- ``_joined``: ``_joined_2``, ``_joined_3``, ...
- a column ``n``: ``n_joined``, ``n_joined_2``, ...
- an added column of kind ``k``: always ``k_joined``, then ``k_joined_2``, ...
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable

INDICATOR = "_joined"
SUFFIX = "_joined"
KINDS = ("key", "rows")
# What a join adding all the columns of the joined table does with one named
# like a column of the input: add it renamed, or leave it out.
SAME_NAMES = ("rename", "skip")
# The values of the indicator, as `polars_helpers.merge` writes them.
BOTH = "both"
LEFT_ONLY = "left_only"
# Types that cannot be keys, as their text starts: nested values.
NESTED = ("List", "Array", "Struct")
# The column of a part of the map (`ddviz.compute.join`): per row of the
# input, the row of the joined table, or null.
MAP_COLUMN = "row"


def _free(base: str, first: str, taken: set[str]) -> str:
    """Return `base` when free, else the first free name of `first`, `first_2`, ..."""
    if base not in taken:
        return base
    name, n = first, 1
    while name in taken:
        n += 1
        name = f"{first}_{n}"
    return name


def joined_names(
    taken: Iterable[str],
    columns: list[str],
    generated: dict[str, str],
    indicator: bool,
) -> dict[str, str | None]:
    """Return the names of the columns a join adds, in order, with the column of the joined table each holds.

    Parameters
    ----------
    taken : iterable of str
        The columns of the input, its added columns included.
    columns : list of str
        The columns of the joined table to add, in its order: its keys and
        its added columns are left out.
    generated : dict of str to str
        The added columns of the joined table to add, with their kinds
        (`ddviz.shared.generated`).
    indicator : bool
        Whether ``_joined`` comes first (a join by keys).

    Returns
    -------
    dict of str to str or None
        Per added column, in order, the column of the joined table; None for
        ``_joined``.
    """
    used = set(taken)
    names: dict[str, str | None] = {}

    def add(name: str, source: str | None) -> None:
        used.add(name)
        names[name] = source

    if indicator:
        add(_free(INDICATOR, INDICATOR, used), None)
    for column in columns:
        add(_free(column, column + SUFFIX, used), column)
    for column, kind in generated.items():
        first = kind + SUFFIX
        add(_free(first, first, used), column)
    return names


def join_id(
    kind: str,
    input_key: str,
    files: dict,
    keys: list[dict[str, str]],
    rows: list[int],
    paths: list[str],
) -> str:
    """Return what tells a join apart from another: it names the parts the join writes.

    Parameters
    ----------
    kind : str
        ``"key"`` or ``"rows"``.
    input_key : str
        What names the joined table's input in the column cache
        (`ddviz.shared.cache.ColumnCache.key`).
    files : dict
        The size and modification time of each file of the joined table
        (``files`` of its ``source.json``): a changed file makes another join.
    keys : list of dict of str to str
        Per pair of keys, ``{"left", "right", "left_dtype", "right_dtype"}``:
        the two types decide the type they are compared in.
    rows : list of int
        The rows of each file of the input, for a join by rows: a part of a
        file holds the joined table's rows from those of the files before.
        Empty for a join by keys, whose parts depend on the file alone.
    paths : list of str
        The paths of the input and of the joined table as given, absolute
        (`ddviz.shared.generated.part_key`): the cache knows an input by its
        resolved paths, while the values of their added columns
        (``source``), and so a key on them and the rows it matches, hold
        the paths as given.

    Returns
    -------
    str
        32 hexadecimal digits.
    """
    text = json.dumps(
        {
            "kind": kind,
            "input": input_key,
            "files": files,
            "keys": keys,
            "rows": rows,
            "paths": paths,
        },
        sort_keys=True,
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def joined_part_key(dtype: str, join: str, column: str | None) -> str:
    """Return what names the parts of a column a join adds, besides its name (`ddviz.shared.cache.ColumnCache.parts`).

    Parameters
    ----------
    dtype : str
        The type of the column.
    join : str
        The join (`join_id`).
    column : str or None
        The column of the joined table it holds; None for ``_joined``.

    Returns
    -------
    str
        The key.
    """
    held = "\0indicator" if column is None else f"\0column:{column}"
    return f"{dtype}\0joined:{join}{held}"


def map_part_key(join: str) -> str:
    """Return what names the parts of a join's map (`MAP_COLUMN`), besides `MAP_COLUMN`."""
    return f"map\0joined:{join}"
