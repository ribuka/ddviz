"""Pixel-bin aggregation of a scatter plot with one representative row per bin."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import polars as pl

from ddviz.keys import BinGrid
from ddviz.layout import AxisGrid, GridLayout, grid_layout
from ddviz.scan import scan_columns
from ddviz.scatter import ScatterSpec

KEY = "__key"
COUNT = "__n"
INDEX = "__idx"

# Margin added on each side of the data range, as a fraction of the range.
RANGE_PADDING = 0.02
# Most levels a color, row or col column may have. A numeric column placed on
# these roles has about one level per row: its masks would not fit in memory.
MAX_LEVELS = 50


@dataclass(frozen=True)
class Aggregation:
    """Result of `aggregate`.

    Parameters
    ----------
    grid : BinGrid
        Key space of the bins.
    layout : GridLayout
        Panels in the figure; one bin is one pixel of a panel.
    axes : AxisGrid
        Facet cell and pair of axis columns of each panel.
    x_ranges, y_ranges : list of tuple of float
        Data range of each x and each y column that the bins cover; along x
        in a panel of the x column ``xi``, bin ``i`` spans
        ``lo + i * (hi - lo) / grid.width`` onward, where ``lo, hi`` is
        ``x_ranges[xi]``.
    levels : dict
        Levels of the ``"color"``, ``"row"`` and ``"col"`` roles as text, in
        index order; a role without a column has the single level None.
    bins : polars.DataFrame or None
        One row per non-empty bin, sorted by `KEY`: the key, the number of
        rows in the bin (`COUNT`), the representative row's index (`INDEX`,
        the largest row index in the bin) and its hover columns. None when
        only the selection was aggregated.
    selected : polars.DataFrame or None
        For a spec with a selection, the bins of the selected rows in every
        panel (`KEY` and `COUNT`), sorted by key.
    selected_rows : int or None
        For a spec with a selection, the number of selected rows; a row in
        several panels counts once.
    """

    grid: BinGrid
    layout: GridLayout
    axes: AxisGrid
    x_ranges: list[tuple[float, float]]
    y_ranges: list[tuple[float, float]]
    levels: dict[str, list]
    bins: pl.DataFrame | None
    selected: pl.DataFrame | None = None
    selected_rows: int | None = None


def selection_filter(spec: ScatterSpec) -> list[pl.Expr]:
    """Return the conditions that pick the selected rows of a spec with a selection.

    A row is selected when it is drawn in the panel the box was drawn on:
    its facet levels are the panel's, its x and y are in the box, and its
    color, row and col are not null.

    Parameters
    ----------
    spec : ScatterSpec
        A spec whose ``selection`` is set.

    Returns
    -------
    list of polars.Expr
        Conditions to filter on.
    """
    selection = spec.selection
    x = pl.col(selection.x).cast(pl.Float64)
    y = pl.col(selection.y).cast(pl.Float64)
    conditions = [
        x.is_finite(),
        y.is_finite(),
        x.is_between(*selection.x_range),
        y.is_between(*selection.y_range),
        *[pl.col(c).is_not_null() for c in (spec.color, spec.row, spec.col) if c],
    ]
    for column, level in ((spec.row, selection.row), (spec.col, selection.col)):
        if column is not None and level is not None:
            conditions.append(pl.col(column).cast(pl.String) == level)
    return conditions


def selection_columns(spec: ScatterSpec) -> list[str]:
    """Return the columns `selection_filter` reads.

    Parameters
    ----------
    spec : ScatterSpec
        A spec whose ``selection`` is set.

    Returns
    -------
    list of str
        The columns, once each.
    """
    columns = [spec.selection.x, spec.selection.y, spec.color, spec.row, spec.col]
    return list(dict.fromkeys(c for c in columns if c is not None))


def _padded(lo: float | None, hi: float | None) -> tuple[float, float]:
    """Return a data range with a margin, or a unit range around a constant."""
    if lo is None or hi is None:
        return (0.0, 1.0)
    if lo == hi:
        return (lo - 0.5, hi + 0.5)
    pad = (hi - lo) * RANGE_PADDING
    return (lo - pad, hi + pad)


def _bin_expr(column: str, bounds: tuple[float, float], n: int) -> pl.Expr:
    """Return the bin index of a numeric column over `bounds` split into `n` bins."""
    lo, hi = bounds
    scaled = (pl.col(column).cast(pl.Float64) - lo) * (n / (hi - lo))
    return scaled.floor().clip(0, n - 1).cast(pl.Int64)


def _index_expr(column: str | None, levels: list) -> pl.Expr:
    """Return the level index of a categorical column by its text, or 0 without a column."""
    if column is None:
        return pl.lit(0, pl.Int64)
    # An Enum cast streams; replace_strict on 100M rows took over 9GB.
    return (
        pl.col(column)
        .cast(pl.String)
        .cast(pl.Enum(levels))
        .to_physical()
        .cast(pl.Int64)
    )


def _scan(
    spec: ScatterSpec, columns: list[str], row_index: str | None = None
) -> pl.LazyFrame:
    """Return a scan of only `columns` of the plot.

    Each query gets its own scan: queries in one `collect_all` sharing a scan
    followed by a ``select`` made the streaming engine peak at about 6.7GB on
    100M rows, against about 1.2GB with separate scans.
    """
    return scan_columns({c: spec.files[c] for c in dict.fromkeys(columns)}, row_index)


def _range_query(spec: ScatterSpec, column: str) -> pl.LazyFrame:
    """Return the query of the finite minimum and maximum of a numeric column."""
    value = pl.col(column).cast(pl.Float64)
    finite = value.filter(value.is_finite())
    return _scan(spec, [column]).select(
        finite.min().alias("min"), finite.max().alias("max")
    )


def _overview(
    spec: ScatterSpec, roles: dict[str, str | None], used: list[str]
) -> tuple[list[tuple[float, float]], list[tuple[float, float]], dict[str, list]]:
    """Return the padded data range of each axis column and the levels of each role, in one pass."""
    numeric = list(dict.fromkeys([*spec.x, *spec.y]))
    # Levels and ranges come from the unfiltered scan: a row filter on the
    # same pass made the streaming engine peak at about 6.5GB on 100M rows,
    # against about 1.1GB without it. The range of an axis column covers all
    # its rows, so that all its panels share one axis.
    found = pl.collect_all(
        [
            *[_range_query(spec, c) for c in numeric],
            *[_scan(spec, [c]).group_by(pl.col(c).cast(pl.String)).len() for c in used],
        ],
        engine="streaming",
    )
    ranges = {c: _padded(*f.row(0)) for c, f in zip(numeric, found, strict=False)}
    x_ranges = [ranges[c] for c in spec.x]
    y_ranges = [ranges[c] for c in spec.y]
    column_levels = {
        c: sorted(f[c].drop_nulls().to_list())
        for c, f in zip(used, found[len(numeric) :], strict=True)
    }
    many = {c: len(v) for c, v in column_levels.items() if len(v) > MAX_LEVELS}
    if many:
        raise ValueError(
            f"too many levels (at most {MAX_LEVELS}): "
            + ", ".join(f"{c} has {n}" for c, n in many.items())
        )
    levels = {
        role: (column_levels[c] if c is not None else [None])
        for role, c in roles.items()
    }
    return x_ranges, y_ranges, levels


def aggregate(
    spec: ScatterSpec,
    progress: Callable[[str], None] = lambda _: None,
    selection_only: bool = False,
) -> Aggregation:
    """Aggregate a scatter plot into pixel bins and pick their representative rows.

    Each pair of an x and a y column is a panel of each facet cell
    (`ddviz.layout.AxisGrid`); a row is in the panels of the pairs whose x
    and y it has. The pairs are aggregated one after another in this
    process. A panel leaves out
    rows with a null or non-finite x or y, and for a view, rows outside the
    ranges of its columns; every panel leaves out rows with a null color,
    row or col. The overview finds the levels and the data ranges first; a
    view takes them from the spec.

    With a selection, the selected rows are also aggregated into bins of
    their own, in every panel (`selection_filter`).

    Parameters
    ----------
    spec : ScatterSpec
        What to aggregate.
    progress : callable
        Called with the name of each stage as it starts.
    selection_only : bool
        Aggregate only the selection, for the layer of a result already
        drawn; the spec must have a view (its levels and ranges) and a
        selection.

    Returns
    -------
    Aggregation
        The bins.

    Raises
    ------
    ValueError
        When the color, row or col column has more than `MAX_LEVELS` levels.
    """
    roles = {"color": spec.color, "row": spec.row, "col": spec.col}
    used = list(dict.fromkeys(c for c in roles.values() if c is not None))

    if spec.view is not None:
        x_ranges = [(lo, hi) for lo, hi in spec.view.x_ranges]
        y_ranges = [(lo, hi) for lo, hi in spec.view.y_ranges]
        levels = spec.view.levels
    else:
        progress("levels")
        x_ranges, y_ranges, levels = _overview(spec, roles, used)

    axes = AxisGrid(
        nrow=len(levels["row"]),
        ncol=len(levels["col"]),
        nx=len(spec.x),
        ny=len(spec.y),
    )
    layout = grid_layout(spec.width, spec.height, axes.rows, axes.cols, *axes.gaps)
    grid = BinGrid(
        n_panels=layout.nrow * layout.ncol,
        n_series=len(levels["color"]),
        width=layout.panel_width,
        height=layout.panel_height,
    )
    row = _index_expr(spec.row, levels["row"])
    col = _index_expr(spec.col, levels["col"])
    series = _index_expr(spec.color, levels["color"])

    def pair(
        xi: int, yj: int, extra: list[pl.Expr], extra_columns: list[str]
    ) -> pl.LazyFrame:
        """Return the bins of the panels of one pair of axis columns, of the rows `extra` keeps."""
        x_col, y_col = spec.x[xi], spec.y[yj]
        x = pl.col(x_col).cast(pl.Float64)
        y = pl.col(y_col).cast(pl.Float64)
        key = grid.pack(
            axes.panel(row, col, xi, yj),
            series,
            _bin_expr(y_col, y_ranges[yj], grid.height),
            _bin_expr(x_col, x_ranges[xi], grid.width),
        )
        return (
            _scan(spec, [x_col, y_col, *used, *extra_columns], INDEX)
            .filter(
                x.is_finite(),
                y.is_finite(),
                x.is_between(*x_ranges[xi]),
                y.is_between(*y_ranges[yj]),
                *[pl.col(c).is_not_null() for c in used],
                *extra,
            )
            .select(key.alias(KEY), pl.col(INDEX))
            .group_by(KEY)
            .agg(pl.len().alias(COUNT), pl.col(INDEX).max())
        )

    def all_pairs(extra: list[pl.Expr], extra_columns: list[str]) -> pl.DataFrame:
        # One query per pair, one after another: the pairs' panels differ, so
        # their keys do too. One query over all pairs was about 10% faster but
        # its peak grew with the pairs (9 pairs of 100M rows: 9.0GB against 4.0GB).
        return pl.concat(
            [
                pair(xi, yj, extra, extra_columns).collect(engine="streaming")
                for yj in range(axes.ny)
                for xi in range(axes.nx)
            ]
        ).sort(KEY)

    bins = None
    if not selection_only:
        progress("bins")
        bins = all_pairs([], [])
        progress("rows")
        hover = list(dict.fromkeys(spec.hover))
        rows = (
            _scan(spec, hover, INDEX)
            .join(bins.lazy().select(INDEX), on=INDEX, how="semi")
            .select(INDEX, *hover)
            .collect(engine="streaming")
        )
        bins = bins.join(rows, on=INDEX, how="left", maintain_order="left")
    selected = selected_rows = None
    if spec.selection is not None:
        progress("selection")
        conditions = selection_filter(spec)
        columns = selection_columns(spec)
        selected = all_pairs(conditions, columns).select(KEY, COUNT)
        selected_rows = (
            _scan(spec, columns)
            .filter(*conditions)
            .select(pl.len())
            .collect(engine="streaming")
            .item()
        )
    return Aggregation(
        grid=grid,
        layout=layout,
        axes=axes,
        x_ranges=x_ranges,
        y_ranges=y_ranges,
        levels=levels,
        bins=bins,
        selected=selected,
        selected_rows=selected_rows,
    )
