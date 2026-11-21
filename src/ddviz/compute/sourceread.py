"""Expressions that read the values of columns not in the column cache from one source file, in the input's types.

Used by what reads rows without converting them: the selection table
(`ddviz.compute.tasks.table`) and the saved plot data
(`ddviz.compute.tasks.plotdata`).
"""

from __future__ import annotations

import polars as pl

from ddviz.compute.convert import column_expr
from ddviz.shared.generated import generated_value
from ddviz.shared.tasks import SourceFiles


def file_values(
    source: SourceFiles,
    path: str,
    columns: list[str],
    present: pl.Schema,
    target: dict[str, pl.DataType],
) -> dict[str, pl.Expr]:
    """Return the values of columns in a source file, in the input's types.

    Parameters
    ----------
    source : SourceFiles
        The source files of the input.
    path : str
        The source file, one of `source.paths`.
    columns : list of str
        The columns, each in `source.generated` or `source.dtypes`.
    present : polars.Schema
        The columns of the file.
    target : dict of str to polars.DataType
        The input's types; read only for a column the file lacks or holds
        in another type.

    Returns
    -------
    dict of str to polars.Expr
        The expression of each column in the order of `columns`, named by
        it: an added column (`ddviz.shared.generated`) gives the file's
        value as text, a column the file lacks gives nulls, and one of
        another type is cast (`ddviz.compute.convert.column_expr`).
    """
    values = {}
    for c in columns:
        if c in source.generated:
            value = generated_value(source.generated[c], path)
            expr = pl.lit(value, dtype=pl.String)
        elif c not in present:
            expr = pl.lit(None, dtype=target[c])
        else:
            expr = column_expr(c, source.dtypes[c], present, target)
        values[c] = expr.alias(c)
    return values
