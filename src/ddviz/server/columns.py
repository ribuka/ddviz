"""Search of the column list by name, for a data set of up to 100,000 columns."""

from __future__ import annotations

KINDS = ("numeric", "categorical")
ORDERS = ("file", "nonnull")


def search_columns(
    columns: list[dict],
    query: str,
    kind: str | None,
    limit: int,
    shares: list[float | None] | None = None,
    min_share: float | None = None,
    order: str = "file",
) -> dict:
    """Return the columns whose names hold every word of a query.

    Words are separated by white space and matched case-insensitively, in any
    order. The page shows only the first `limit` matches, with their count.
    A column whose share of non-null values is unknown passes `min_share`
    and comes last in the order of shares.

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
    shares : list of float or None, optional
        Share of non-null values per column (`ddviz.compute.nonnull`), None for
        unknown; without it, every share is unknown.
    min_share : float, optional
        Keep only the columns with at least this share; 0 is taken as more
        than 0, so that it drops the columns of nulls only.
    order : str
        ``"file"`` for file order, ``"nonnull"`` for the highest share first.

    Returns
    -------
    dict
        ``{"total", "matched", "columns"}``: the number of columns, the
        number of matches and the first `limit` matches, each with its
        ``"nonnull"`` share.

    Raises
    ------
    ValueError
        For an unknown kind or order.
    """
    if kind is not None and kind not in KINDS:
        raise ValueError(f"unknown kind: {kind}")
    if order not in ORDERS:
        raise ValueError(f"unknown order: {order}")
    words = query.casefold().split()
    if shares is None:
        shares = [None] * len(columns)
    found = []
    for i, column in enumerate(columns):
        if kind is not None and column["numeric"] != (kind == "numeric"):
            continue
        name = column["name"].casefold()
        if not all(w in name for w in words):
            continue
        share = shares[i]
        if (
            min_share is not None
            and share is not None
            and (share < min_share or share == 0)
        ):
            continue
        found.append(i)
    if order == "nonnull":
        found.sort(key=lambda i: (shares[i] is None, -(shares[i] or 0.0)))
    return {
        "total": len(columns),
        "matched": len(found),
        "columns": [{**columns[i], "nonnull": shares[i]} for i in found[:limit]],
    }
