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
    bins : polars.DataFrame
        One row per non-empty bin, sorted by `KEY`: the key, the number of
        rows in the bin (`COUNT`), the representative row's index (`INDEX`,
        the largest row index in the bin) and its hover columns.
    """

    grid: BinGrid
    layout: GridLayout
    axes: AxisGrid
    x_ranges: list[tuple[float, float]]
    y_ranges: list[tuple[float, float]]
    levels: dict[str, list]
    bins: pl.DataFrame


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
    spec: ScatterSpec, progress: Callable[[str], None] = lambda _: None
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

    Parameters
    ----------
    spec : ScatterSpec
        What to aggregate.
    progress : callable
        Called with the name of each stage as it starts.

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

    def pair(xi: int, yj: int) -> pl.LazyFrame:
        """Return the keys and row indices of the panels of one pair of axis columns."""
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
            _scan(spec, [x_col, y_col, *used], INDEX)
            .filter(
                x.is_finite(),
                y.is_finite(),
                x.is_between(*x_ranges[xi]),
                y.is_between(*y_ranges[yj]),
                *[pl.col(c).is_not_null() for c in used],
            )
            .select(key.alias(KEY), pl.col(INDEX))
            .group_by(KEY)
            .agg(pl.len().alias(COUNT), pl.col(INDEX).max())
        )

    progress("bins")
    # One query per pair, one after another: the pairs' panels differ, so
    # their keys do too. One query over all pairs was about 10% faster but
    # its peak grew with the pairs (9 pairs of 100M rows: 9.0GB against 4.0GB).
    bins = pl.concat(
        [
            pair(xi, yj).collect(engine="streaming")
            for yj in range(axes.ny)
            for xi in range(axes.nx)
        ]
    ).sort(KEY)

    progress("rows")
    hover = list(dict.fromkeys(spec.hover))
    rows = (
        _scan(spec, hover, INDEX)
        .join(bins.lazy().select(INDEX), on=INDEX, how="semi")
        .select(INDEX, *hover)
        .collect(engine="streaming")
    )
    bins = bins.join(rows, on=INDEX, how="left", maintain_order="left")
    return Aggregation(
        grid=grid,
        layout=layout,
        axes=axes,
        x_ranges=x_ranges,
        y_ranges=y_ranges,
        levels=levels,
        bins=bins,
    )
