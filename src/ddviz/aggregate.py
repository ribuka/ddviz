"""Pixel-bin aggregation of a scatter plot with one representative row per bin."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import polars as pl

from ddviz.keys import BinGrid
from ddviz.layout import GridLayout, grid_layout
from ddviz.scan import scan_columns
from ddviz.scatter import ScatterSpec

KEY = "__key"
COUNT = "__n"
INDEX = "__idx"

# Margin added on each side of the data range, as a fraction of the range.
RANGE_PADDING = 0.02


@dataclass(frozen=True)
class Aggregation:
    """Result of `aggregate`.

    Parameters
    ----------
    grid : BinGrid
        Key space of the bins.
    layout : GridLayout
        Panels in the figure; one bin is one pixel of a panel.
    x_range, y_range : tuple of float
        Data ranges the bins cover; bin ``i`` along x spans
        ``x_range[0] + i * (x_range[1] - x_range[0]) / grid.width`` onward.
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
    x_range: tuple[float, float]
    y_range: tuple[float, float]
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


def _overview(
    spec: ScatterSpec, roles: dict[str, str | None], used: list[str]
) -> tuple[tuple[float, float], tuple[float, float], dict[str, list]]:
    """Return the padded data ranges and the levels of each role, in one pass."""
    x = pl.col(spec.x).cast(pl.Float64)
    y = pl.col(spec.y).cast(pl.Float64)
    # Levels and ranges come from the unfiltered scan: a row filter on the
    # same pass made the streaming engine peak at about 6.5GB on 100M rows,
    # against about 1.1GB without it.
    found = pl.collect_all(
        [
            _scan(spec, [spec.x, spec.y]).select(
                x.filter(x.is_finite()).min().alias("x_min"),
                x.filter(x.is_finite()).max().alias("x_max"),
                y.filter(y.is_finite()).min().alias("y_min"),
                y.filter(y.is_finite()).max().alias("y_max"),
            ),
            *[_scan(spec, [c]).group_by(pl.col(c).cast(pl.String)).len() for c in used],
        ],
        engine="streaming",
    )
    row = found[0].row(0, named=True)
    x_range = _padded(row["x_min"], row["x_max"])
    y_range = _padded(row["y_min"], row["y_max"])
    column_levels = {
        c: sorted(f[c].drop_nulls().to_list())
        for c, f in zip(used, found[1:], strict=True)
    }
    levels = {
        role: (column_levels[c] if c is not None else [None])
        for role, c in roles.items()
    }
    return x_range, y_range, levels


def aggregate(
    spec: ScatterSpec, progress: Callable[[str], None] = lambda _: None
) -> Aggregation:
    """Aggregate a scatter plot into pixel bins and pick their representative rows.

    Rows with a null or non-finite x or y, or a null color, row or col, are
    left out, and for a view, rows outside its ranges. The overview finds the
    levels and the data ranges first; a view takes them from the spec.

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
    """
    roles = {"color": spec.color, "row": spec.row, "col": spec.col}
    used = list(dict.fromkeys(c for c in roles.values() if c is not None))
    x = pl.col(spec.x).cast(pl.Float64)
    y = pl.col(spec.y).cast(pl.Float64)

    if spec.view is not None:
        x_range = (spec.view.x_range[0], spec.view.x_range[1])
        y_range = (spec.view.y_range[0], spec.view.y_range[1])
        levels = spec.view.levels
    else:
        progress("levels")
        x_range, y_range, levels = _overview(spec, roles, used)

    layout = grid_layout(
        spec.width, spec.height, len(levels["row"]), len(levels["col"])
    )
    grid = BinGrid(
        n_panels=layout.nrow * layout.ncol,
        n_series=len(levels["color"]),
        width=layout.panel_width,
        height=layout.panel_height,
    )
    panel = _index_expr(spec.row, levels["row"]) * len(levels["col"]) + _index_expr(
        spec.col, levels["col"]
    )
    key = grid.pack(
        panel,
        _index_expr(spec.color, levels["color"]),
        _bin_expr(spec.y, y_range, grid.height),
        _bin_expr(spec.x, x_range, grid.width),
    )

    progress("bins")
    bins = (
        _scan(spec, [spec.x, spec.y, *used], INDEX)
        .filter(
            x.is_finite(),
            y.is_finite(),
            x.is_between(*x_range),
            y.is_between(*y_range),
            *[pl.col(c).is_not_null() for c in used],
        )
        .select(key.alias(KEY), pl.col(INDEX))
        .group_by(KEY)
        .agg(pl.len().alias(COUNT), pl.col(INDEX).max())
        .sort(KEY)
        .collect(engine="streaming")
    )

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
        x_range=x_range,
        y_range=y_range,
        levels=levels,
        bins=bins,
    )
