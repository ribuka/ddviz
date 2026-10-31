"""Levels of a numeric column cut into intervals, for the color, overlay, row and col roles.

A numeric column on Group X or Group Y, or on Color when it is not drawn as
a gradient, has too many values to be levels of their own. It is cut into
intervals (`ddviz.shared.scatter.Binning`), and each interval is a level.

The cuts of a column are ``{"breaks": [b0, ..., bk], "values": bool}``: ``k``
intervals, ``[b0, b1)``, ..., ``[b(k-1), bk]`` (the last one closed). With
``values``, the column has few values and each is a level of its own: the
breaks are the values and the last one again.
"""

from __future__ import annotations

import polars as pl

from ddviz.shared.scatter import Binning
from ddviz.shared.temporal import text


def _finite(column: str) -> pl.Expr:
    """Return the column as floats."""
    return pl.col(column).cast(pl.Float64)


def find_cuts(scan: pl.LazyFrame, column: str, binning: Binning) -> dict:
    """Return the cuts of a numeric column, over its finite values.

    Parameters
    ----------
    scan : polars.LazyFrame
        A scan holding the column; each query below uses it on its own.
    column : str
        The column.
    binning : Binning
        How to cut it.

    Returns
    -------
    dict
        The cuts; no breaks when the column has no finite value.
    """
    value = _finite(column)
    finite = value.filter(value.is_finite())
    if binning.values_up_to:
        # A cheap estimate first: listing the values of a column with about
        # one value per row would hold them all.
        estimate = scan.select(finite.approx_n_unique()).collect(engine="streaming")
        if estimate.item() <= 2 * binning.values_up_to:
            values = (scan.select(finite.unique().sort()).collect(engine="streaming"))[
                column
            ].to_list()
            if len(values) <= binning.values_up_to:
                breaks = [*values, values[-1]] if values else []
                return {"breaks": breaks, "values": True}
    if binning.by == "values":
        lo, hi = (
            scan.select(finite.min(), finite.max().alias("max"))
            .collect(engine="streaming")
            .row(0)
        )
        if lo is None:
            return {"breaks": [], "values": False}
        step = (hi - lo) / binning.n
        breaks = [lo + i * step for i in range(binning.n)] + [hi]
    else:
        n = scan.select(finite.len()).collect(engine="streaming").item()
        if n == 0:
            return {"breaks": [], "values": False}
        # One sort and the rows at the quantiles: on 100M rows 1.1s and
        # 2.5GB, against 1s per quantile with `quantile`.
        at = [round(i * (n - 1) / binning.n) for i in range(binning.n + 1)]
        breaks = (scan.select(finite.sort().gather(at)).collect(engine="streaming"))[
            column
        ].to_list()
    breaks = sorted(set(breaks))
    if len(breaks) == 1:
        breaks *= 2
    return {"breaks": breaks, "values": False}


def _text(value: float, digits: int) -> str:
    """Return a break as text: an integer without its decimal point, else to `digits` significant digits."""
    if float(value).is_integer() and abs(value) < 1e15:
        return str(int(value))
    return f"{value:.{digits}g}"


def _texts(breaks: list[float], kind: str | None = None) -> list[str]:
    """Return the breaks as text with the fewest significant digits (3 or more) that tell them apart.

    A break of a date-axis kind (`ddviz.shared.temporal.DATE_KINDS`) is its
    date or time (`ddviz.shared.temporal.text`) instead. Breaks of a date
    that fall within one day are told apart by their time, as a datetime's:
    the levels are found again by their names.
    """
    kinds = {"date": ["date", "datetime"]}.get(kind, [kind] if kind else [])
    for k in kinds:
        dates = [text(k, b) for b in breaks]
        if None not in dates and len(set(dates)) == len(set(breaks)):
            return dates
    for digits in range(3, 18):
        texts = [_text(b, digits) for b in breaks]
        if len(set(texts)) == len(set(breaks)):
            return texts
    return [repr(b) for b in breaks]


def cut_labels(cuts: dict, kind: str | None = None) -> list[str]:
    """Return the level of each interval as text.

    Parameters
    ----------
    cuts : dict
        The cuts (`find_cuts`).
    kind : str or None
        The kind of a temporal column (`ddviz.shared.temporal.KINDS`), whose
        breaks of a datetime, date or time are dates or times; None for
        another column.

    Returns
    -------
    list of str
        ``"[a, b)"`` for each interval, ``"[a, b]"`` for the last one, or
        the value itself with ``values``.
    """
    breaks = cuts["breaks"]
    texts = _texts(breaks, kind)
    if cuts["values"]:
        return texts[:-1]
    k = len(breaks) - 1
    return [
        f"[{texts[i]}, {texts[i + 1]}{']' if i == k - 1 else ')'}" for i in range(k)
    ]


def cut_index(column: str, cuts: dict, kept: list[int] | None = None) -> pl.Expr:
    """Return the level index of each row of a cut column.

    Parameters
    ----------
    column : str
        The column.
    cuts : dict
        Its cuts.
    kept : list of int, optional
        The levels drawn, in order; the index is the position among them.
        Rows of the other levels must be left out by the caller. All the
        levels when omitted.

    Returns
    -------
    polars.Expr
        The index, as Int64.
    """
    breaks = cuts["breaks"]
    if kept is None:
        kept = list(range(len(breaks) - 1))
    # A row in level j is at or above the lower breaks of levels 0..j, so
    # its position among the kept levels is the count of kept lower breaks
    # past the first that it reaches.
    value = _finite(column)
    index = pl.lit(0, pl.Int64)
    for j in kept[1:]:
        index = index + (value >= breaks[j]).cast(pl.Int64)
    return index


def in_level(column: str, cuts: dict, level: int) -> pl.Expr:
    """Return whether a row of a cut column is in one level.

    Parameters
    ----------
    column : str
        The column.
    cuts : dict
        Its cuts.
    level : int
        The level's index.

    Returns
    -------
    polars.Expr
        The condition.
    """
    breaks = cuts["breaks"]
    value = _finite(column)
    if cuts["values"]:
        return value == breaks[level]
    lo, hi = breaks[level], breaks[level + 1]
    last = level == len(breaks) - 2
    return (value >= lo) & ((value <= hi) if last else (value < hi))
