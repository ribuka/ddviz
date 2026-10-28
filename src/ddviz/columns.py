"""Search of the column list by name, for a data set of up to 100,000 columns."""

from __future__ import annotations

KINDS = ("numeric", "categorical")


def search_columns(
    columns: list[dict], query: str, kind: str | None, limit: int
) -> dict:
    """Return the columns whose names hold every word of a query.

    Words are separated by white space and matched case-insensitively, in any
    order. The page shows only the first `limit` matches, with their count.

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

    Returns
    -------
    dict
        ``{"total", "matched", "columns"}``: the number of columns, the
        number of matches and the first `limit` matches in file order.

    Raises
    ------
    ValueError
        For an unknown kind.
    """
    if kind is not None and kind not in KINDS:
        raise ValueError(f"unknown kind: {kind}")
    words = query.casefold().split()
    matched = 0
    found = []
    for column in columns:
        if kind is not None and column["numeric"] != (kind == "numeric"):
            continue
        name = column["name"].casefold()
        if not all(w in name for w in words):
            continue
        matched += 1
        if len(found) < limit:
            found.append(column)
    return {"total": len(columns), "matched": matched, "columns": found}
