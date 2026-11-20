"""Read rows of columns a join added to the input, not converted yet, through the map of the join.

The selection table and the plot's data read the columns not in the column
cache from the source files (`ddviz.shared.tasks.SourceFiles`); a column a
join added is read the same way, without converting it: the rows of the
joined table of the rows asked for are looked up first (the map of a join by
keys; for a join by rows, the same rows), then the joined table's values of
those rows are read, from its column cache or its files, as the caller reads
them. The values are those its parts would hold (`ddviz.compute.join`).
"""

from __future__ import annotations

from collections.abc import Callable

import polars as pl

from ddviz.compute.aggregate import INDEX
from ddviz.compute.scan import scan_columns
from ddviz.shared.joined import BOTH, LEFT_ONLY, MAP_COLUMN
from ddviz.shared.tasks import JoinedFiles

# Reads the joined table's rows of a sorted index: the columns given, with
# the row index (`INDEX`) first.
ReadRight = Callable[[list[str], pl.Series], pl.DataFrame]
# Returns the bytes of the values of a column besides those every value
# takes, or None for a type of fixed size (`ddviz.compute.tasks.plotdata`).
Measure = Callable[[pl.Expr, pl.DataType], pl.Expr | None]
# The rows of the input and of the joined table while they are joined.
_LEFT = "__ddviz_left"
_MAP = "__ddviz_map"


def _value(i: int) -> str:
    """Return the name of the `i`-th column of the joined table while it is joined to the rows."""
    return f"__ddviz_value_{i}"


def right_rows(
    joined: JoinedFiles, index: pl.Series, spans: list[tuple[int, int]]
) -> pl.DataFrame:
    """Return the row of the joined table of each row of `index`, null for none.

    Parameters
    ----------
    joined : JoinedFiles
        The join.
    index : polars.Series
        Rows of the input, sorted.
    spans : list of tuple of int
        Slices (start, length) of the input covering `index`, read one
        after another.

    Returns
    -------
    polars.DataFrame
        `INDEX` and `MAP_COLUMN` (UInt64), in the order of `index`.
    """
    rows = index.cast(pl.UInt64)
    if not joined.maps:
        return pl.DataFrame({INDEX: index, MAP_COLUMN: rows})
    frame = scan_columns({MAP_COLUMN: joined.maps}, INDEX, numbers=False)
    found = [frame.slice(start, length).collect() for start, length in spans]
    if not found:
        return pl.DataFrame(
            {INDEX: index, MAP_COLUMN: pl.Series([], dtype=pl.UInt64)}
        )
    return (
        pl.concat(found)
        .filter(pl.col(INDEX).is_in(index.implode()))
        .with_columns(pl.col(MAP_COLUMN).cast(pl.UInt64))
    )


def joined_rows(
    joined: JoinedFiles,
    columns: list[str],
    index: pl.Series,
    spans: list[tuple[int, int]],
    read_right: ReadRight,
    measure: Measure | None = None,
) -> pl.DataFrame:
    """Return the rows `index` of columns a join added, with the row index.

    Parameters
    ----------
    joined : JoinedFiles
        The join and where its columns are.
    columns : list of str
        Columns among ``joined.columns``.
    index : polars.Series
        Rows of the input, sorted.
    spans : list of tuple of int
        Slices of the input covering `index` (`right_rows`).
    read_right : callable
        Reads rows of the joined table (`ReadRight`).
    measure : callable, optional
        With it, the bytes of the values of variable size instead of the
        values, one column for each such column (`Measure`): `read_right`
        then reads them too.

    Returns
    -------
    polars.DataFrame
        `INDEX` and the columns, in the order of `index`.
    """
    # Named apart from the joined table's columns.
    found = right_rows(joined, index, spans).rename({INDEX: _LEFT, MAP_COLUMN: _MAP})
    held = list(dict.fromkeys(s for c in columns if (s := joined.columns[c]) is not None))
    if held:
        wanted = found[_MAP].drop_nulls().unique().sort()
        values = read_right(held, wanted.cast(index.dtype))
        # Under names of their own: a column of the joined table may have
        # the name of one of the row indices.
        found = found.join(
            values.select(
                pl.col(INDEX).cast(pl.UInt64).alias(_MAP),
                *(pl.col(c).alias(_value(i)) for i, c in enumerate(held) if c in values.columns),
            ),
            on=_MAP,
            how="left",
            maintain_order="left",
        )
    present = set(found.columns)
    named = {c: _value(i) for i, c in enumerate(held)}
    out = [pl.col(_LEFT).alias(INDEX)]
    for column in columns:
        source = joined.columns[column]
        if source is None:
            value = (
                pl.when(pl.col(_MAP).is_not_null())
                .then(pl.lit(BOTH))
                .otherwise(pl.lit(LEFT_ONLY))
            )
            if measure is not None:
                value = measure(value, pl.String)
            out.append(value.alias(column))
        elif named[source] in present:
            out.append(pl.col(named[source]).alias(column))
    return found.select(out)
