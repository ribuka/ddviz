"""Search of the column list by name, for a data set of up to 100,000 columns."""

from __future__ import annotations

from ddviz.shared.keywords import keywords, matches
from ddviz.shared.natural import natural_key

KINDS = ("numeric", "categorical")
ORDERS = ("file", "name", "count")

# The schema last ranked by name and its ranks: the natural keys of 100,000
# names take about 0.7 s, and every search of the same input reuses them.
_name_ranks: tuple[list[dict], list[int]] | None = None


def _ranks_by_name(columns: list[dict]) -> list[int]:
    """Return the place of each column in the natural order of the names.

    The ranks of the last schema are kept: a source returns the same list
    for every search (`ddviz.server.source.Source.schema`).

    Parameters
    ----------
    columns : list of dict
        The schema, ``{"name", ...}`` per column.

    Returns
    -------
    list of int
        The rank of each column, in the order of `columns`.
    """
    global _name_ranks
    if _name_ranks is None or _name_ranks[0] is not columns:
        order = sorted(
            range(len(columns)), key=lambda i: natural_key(columns[i]["name"])
        )
        ranks = [0] * len(columns)
        for rank, i in enumerate(order):
            ranks[i] = rank
        _name_ranks = (columns, ranks)
    return _name_ranks[1]


def search_columns(
    columns: list[dict],
    query: str,
    kind: str | None,
    limit: int,
    nonnull: dict | None = None,
    min_share: float | None = None,
    order: str = "file",
) -> dict:
    """Return the columns whose names hold every word of a query.

    Words are separated by white space and matched case-insensitively, in any
    order (`ddviz.shared.keywords`). The page shows only the first `limit` matches, with their count.
    Filters and order use the share of non-null values: every column shares
    the rows of the whole input, so it ranks and bounds the columns as their
    counts do. A column whose count is unknown passes `min_share` and comes
    last in the order of counts.

    Parameters
    ----------
    columns : list of dict
        The schema: ``{"name", "dtype", "numeric"}`` per column, in file order.
    query : str
        Words to look for; an empty query matches every column.
    kind : str or None
        ``"numeric"`` or ``"categorical"`` to keep only that kind, or None.
    limit : int
        Largest number of columns to return.
    nonnull : dict, optional
        ``{"counts", "rows"}`` (`ddviz.compute.nonnull`): the non-null values
        per column, None for unknown, and the rows of the input; without it,
        every count is unknown.
    min_share : float, optional
        Keep only the columns with at least this share; 0 is taken as more
        than 0, so that it drops the columns of nulls only.
    order : str
        ``"file"`` for file order, ``"name"`` for the natural order of the
        names (`ddviz.shared.natural`, as the levels of a categorical
        column), ``"count"`` for the most non-null values first.

    Returns
    -------
    dict
        ``{"total", "matched", "rows", "columns"}``: the number of columns,
        the number of matches, the rows of the input (None without
        `nonnull`) and the first `limit` matches, each with its ``"nonnull"``
        count and ``"share"``.

    Raises
    ------
    ValueError
        For an unknown kind or order.
    """
    if kind is not None and kind not in KINDS:
        raise ValueError(f"unknown kind: {kind}")
    if order not in ORDERS:
        raise ValueError(f"unknown order: {order}")
    words = keywords(query)
    if nonnull is None:
        counts = [None] * len(columns)
    else:
        counts = nonnull["counts"]
    # A known count implies rows: `nonnull_counts` gives none without rows.
    shares = [None if c is None else c / nonnull["rows"] for c in counts]
    found = []
    for i, column in enumerate(columns):
        if kind is not None and column["numeric"] != (kind == "numeric"):
            continue
        if not matches(column["name"], words):
            continue
        share = shares[i]
        if (
            min_share is not None
            and share is not None
            and (share < min_share or share == 0)
        ):
            continue
        found.append(i)
    if order == "name":
        ranks = _ranks_by_name(columns)
        found.sort(key=ranks.__getitem__)
    elif order == "count":
        found.sort(key=lambda i: (shares[i] is None, -(shares[i] or 0.0)))
    return {
        "total": len(columns),
        "matched": len(found),
        "rows": None if nonnull is None else nonnull["rows"],
        "columns": [
            {**columns[i], "nonnull": counts[i], "share": shares[i]}
            for i in found[:limit]
        ],
    }
