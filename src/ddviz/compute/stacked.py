"""The bins of a pair of axis columns with a categorical axis, its points placed by their stacks (`ddviz.compute.stacks`).

The rows of a pair whose panels draw points are read once to estimate their
distinct coordinates, once per part to count the stacks
(`ddviz.compute.stacks.stack_groups`), then once per group of parts (one
group unless the stacks are many): to describe the stacks, to bin the rows
at their centers (the rows alone, and the rows of the piles, into bins of
their own), and to rank and bin the rows of the stacks that fit. The piles
drawn (one per pixel, `ddviz.compute.stacks.tops`) take one more pass for
their rows by series.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import polars as pl

from ddviz.compute.bands import level_index
from ddviz.compute.scan import scan_columns
from ddviz.compute.stacks import (
    DX,
    DY,
    FIT,
    KC,
    KEYS,
    KV,
    PANEL,
    PX,
    PY,
    SERIES,
    WX,
    WY,
    Axis,
    Coordinates,
    bins_of,
    key_value,
    ranked,
    stack_groups,
    tops,
)
from ddviz.compute.temporal import temporal_kind, with_numbers
from ddviz.shared.keys import BinGrid
from ddviz.shared.shapes import marker

# Whether a row is among those the bins count (a selection's): the stacks
# are placed over every drawn row all the same.
SELECTED = "__selected"
# Columns of the bins of a pair (`StackedBins`).
KEY = "__key"
ROWS = "__rows"
TOP = "__top"
_PILE = "__pile"
# The coordinates of x and y as compared, before they are packed into `KEYS`.
_KX = "__kx"
_KY = "__ky"


@dataclass(frozen=True)
class StackedBins:
    """The bins of a pair (`stacked_bins`).

    Parameters
    ----------
    bins : polars.DataFrame
        The bins of the points: `KEY`, its rows (`ROWS`) and the largest
        row index (`TOP`), of the selected rows.
    pile_bins : polars.DataFrame
        The bins of the rows of the piles, at their centers: `KEY` and
        `ROWS`, of the selected rows.
    piles : polars.DataFrame or None
        The pile drawn at each pixel (`ddviz.compute.stacks.tops`); None
        when not asked for.
    pile_series : polars.DataFrame or None
        The rows of each drawn pile by series: its `KEYS`, `SERIES` and
        `ROWS`, with the least and largest color value (``"min"``,
        ``"max"``) for a gradient, and the values of the `values` columns.
    """

    bins: pl.DataFrame
    pile_bins: pl.DataFrame
    piles: pl.DataFrame | None = None
    pile_series: pl.DataFrame | None = None


def marker_boxes(
    shapes: list[str | None], sizes: list[int]
) -> tuple[list[int], list[int]]:
    """Return the width and height of the bounding box of each overlay level's marker.

    Parameters
    ----------
    shapes : list of str or None
        Shape of each overlay level
        (`ddviz.shared.scatter.ScatterSpec.marker_shapes`).
    sizes : list of int
        Size of each (`ddviz.shared.scatter.ScatterSpec.marker_sizes`).

    Returns
    -------
    tuple of list of int
        The widths and the heights in pixels, of the pixels the markers
        cover (`ddviz.shared.shapes.marker`), centered on their point.
    """
    widths, heights = [], []
    n = max(len(shapes), len(sizes))
    for i in range(n):
        rows, cols = np.nonzero(marker(shapes[i % len(shapes)], sizes[i % len(sizes)]))
        widths.append(int(cols.max() - cols.min() + 1))
        heights.append(int(rows.max() - rows.min() + 1))
    return widths, heights


def _key(column: str, levels: list[str] | None, dtype: pl.DataType) -> pl.Expr:
    """Return the coordinate of a column as stacks compare it, from its values as read."""
    if levels is not None:
        return level_index(column, levels, strict=False)
    if temporal_kind(dtype) is not None:
        # The temporal value itself, not its number of milliseconds as a float.
        return pl.col(column).to_physical()
    return key_value(pl.col(column), dtype)


def _center(column: str, levels: list[str] | None) -> pl.Expr:
    """Return the position of a row's center along an axis: its level's index or its number."""
    if levels is not None:
        return level_index(column, levels, strict=False).cast(pl.Float64)
    return pl.col(column).cast(pl.Float64)


def stack_frame(
    files: dict[str, list[str]],
    index: str,
    x_col: str,
    y_col: str,
    x: Axis,
    y: Axis,
    axis_levels: dict[str, list[str]],
    conditions: list[pl.Expr],
    cell: pl.Expr,
    panels: list[int],
    series: pl.Expr,
    overlay: pl.Expr,
    boxes: tuple[list[int], list[int]],
    selected: list[pl.Expr],
) -> tuple[pl.LazyFrame, Coordinates]:
    """Return the drawn rows of a pair with what their stacks need, and how their keys hold their coordinates.

    Parameters
    ----------
    files : dict of str to list of str
        Files of the columns to read (`ddviz.compute.scan.scan_columns`):
        the pair's, and those `conditions`, `cell`, `series`, `overlay` and
        `selected` read.
    index : str
        Name of the row index column.
    x_col, y_col : str
        The pair's columns.
    x, y : Axis
        The pair's axes.
    axis_levels : dict
        Levels of each categorical axis column.
    conditions : list of polars.Expr
        Conditions of the drawn rows, besides their centers in the panel.
    cell : polars.Expr
        Each row's facet cell.
    panels : list of int
        The panel of each facet cell.
    series, overlay : polars.Expr
        Each row's series and overlay level.
    boxes : tuple of list of int
        Width and height of the marker of each overlay level (`marker_boxes`).
    selected : list of polars.Expr
        Conditions of the rows the bins count; the stacks hold every drawn row.

    Returns
    -------
    tuple
        The rows, with `index`, the columns of `files`, `KEYS`, `PX`, `PY`,
        `PANEL`, `SERIES`, `WX`, `WY` and `SELECTED`; and the
        `ddviz.compute.stacks.Coordinates` of their keys.
    """
    raw = scan_columns(files, index, numbers=False)
    schema = raw.collect_schema()
    levels_of = {c: axis_levels.get(c) for c in (x_col, y_col)}
    # The coordinates of a temporal column are its values, not their numbers.
    frame = with_numbers(
        raw.with_columns(
            _key(x_col, levels_of[x_col], schema.get(x_col, pl.String)).alias(_KX),
            _key(y_col, levels_of[y_col], schema.get(y_col, pl.String)).alias(_KY),
        )
    )
    cx, cy = _center(x_col, levels_of[x_col]), _center(y_col, levels_of[y_col])
    widths, heights = boxes
    packed = cell.cast(pl.Int64)
    value, dtype = pl.lit(0, pl.Int64), None
    for column, key, levels in (
        (x_col, _KX, levels_of[x_col]),
        (y_col, _KY, levels_of[y_col]),
    ):
        if levels is None:
            value, dtype = pl.col(key), schema[column]
        else:
            packed = packed * len(levels) + pl.col(key)
    coordinates = Coordinates(
        x_levels=None if levels_of[x_col] is None else len(levels_of[x_col]),
        y_levels=None if levels_of[y_col] is None else len(levels_of[y_col]),
        value=dtype,
        panels=panels,
        widths=widths,
        heights=heights,
    )
    frame = (
        frame.filter(
            cx.is_finite(),
            cy.is_finite(),
            cx.is_between(x.lo, x.hi),
            cy.is_between(y.lo, y.hi),
            *conditions,
        )
        .with_columns(packed.alias(KC), value.alias(KV))
        .drop(_KX, _KY)
        .with_columns(
            x.pixel(cx).alias(PX),
            y.pixel(cy).alias(PY),
            pl.lit(pl.Series(panels, dtype=pl.Int64)).gather(cell).alias(PANEL),
            series.cast(pl.Int64).alias(SERIES),
            pl.lit(pl.Series(widths, dtype=pl.Int64)).gather(overlay).alias(WX),
            pl.lit(pl.Series(heights, dtype=pl.Int64)).gather(overlay).alias(WY),
            pl.all_horizontal(pl.lit(True), *selected).alias(SELECTED),
        )
    )
    return frame, coordinates


def _bin_rows(
    frame: pl.LazyFrame | pl.DataFrame,
    grid: BinGrid,
    x: Axis,
    y: Axis,
    index: str,
    dx: pl.Expr,
    dy: pl.Expr,
    by: list[str],
) -> pl.LazyFrame | pl.DataFrame:
    """Return the bins of the selected rows of a frame placed at their centers plus offsets."""
    bx, b_y = bins_of(x, y, dx, dy)
    key = grid.pack(pl.col(PANEL), pl.col(SERIES), b_y, bx)
    return (
        frame.filter(pl.col(SELECTED))
        .with_columns(key.alias(KEY))
        .group_by([KEY, *by])
        .agg(pl.len().cast(pl.Int64).alias(ROWS), pl.col(index).max().alias(TOP))
    )


def _merge(frames: list[pl.DataFrame]) -> pl.DataFrame:
    """Return bins of several parts as one, summed where parts share a bin, by key."""
    if not frames:
        return pl.DataFrame(schema={KEY: pl.Int64, ROWS: pl.Int64, TOP: pl.Int64})
    return (
        pl.concat(frames)
        .group_by(KEY)
        .agg(pl.col(ROWS).sum(), pl.col(TOP).max())
        .sort(KEY)
    )


def stacked_bins(
    frame: pl.LazyFrame,
    x: Axis,
    y: Axis,
    grid: BinGrid,
    index: str,
    coordinates: Coordinates,
    color: str | None = None,
    piles: bool = True,
    values: tuple[str, ...] = (),
) -> StackedBins:
    """Return the bins of a pair's rows placed by their stacks.

    Parameters
    ----------
    frame : polars.LazyFrame
        The pair's drawn rows (`stack_frame`).
    x, y : Axis
        The pair's axes.
    grid : BinGrid
        Key space of the bins.
    index : str
        Column of the row index.
    coordinates : Coordinates
        How the rows' keys hold their coordinates (`stack_frame`).

    color : str or None
        A gradient's color column, whose least and largest value each drawn
        pile has by series.
    piles : bool
        Whether to find the drawn piles and their rows by series.
    values : tuple of str
        Columns whose value (the same in every row of a pile: its axis
        columns) the drawn piles have by series.

    Returns
    -------
    StackedBins
        The bins.
    """
    points, pile_bins, drawn = [], [], []
    for rows, stacks, part in stack_groups(frame, x, y, coordinates):
        # The rows alone and the rows of the piles stay at their centers.
        if stacks.height:
            kinds = stacks.select(*KEYS, FIT).lazy()
            centered = rows.join(kinds, on=KEYS, how="left").filter(
                pl.col(FIT).fill_null(False).not_()
            )
        else:
            centered = rows.with_columns(pl.lit(None, pl.Boolean).alias(FIT))
        found = _bin_rows(
            centered.with_columns(pl.col(FIT).is_not_null().alias(_PILE)),
            grid,
            x,
            y,
            index,
            pl.lit(0.0),
            pl.lit(0.0),
            [_PILE],
        ).collect(engine="streaming")
        points.append(found.filter(~pl.col(_PILE)).drop(_PILE))
        pile_bins.append(found.filter(pl.col(_PILE)).drop(_PILE))
        for placed in ranked(rows, stacks, part, index, x, y, [SERIES, SELECTED]):
            points.append(
                _bin_rows(placed, grid, x, y, index, pl.col(DX), pl.col(DY), [])
            )
        if piles:
            drawn.append(tops(stacks.filter(~pl.col(FIT)), x, y))
    bins = _merge(points)
    pile_bins = _merge(pile_bins).drop(TOP)
    if not piles:
        return StackedBins(bins, pile_bins)
    shown = tops(pl.concat(drawn), x, y)
    if shown.height == 0:
        return StackedBins(bins, pile_bins, shown, None)
    extremes = (
        []
        if color is None
        else [pl.col(color).min().alias("min"), pl.col(color).max().alias("max")]
    )
    by_series = (
        frame.join(shown.select(KEYS).lazy(), on=KEYS, how="semi")
        .group_by([*KEYS, SERIES])
        .agg(
            pl.len().cast(pl.Int64).alias(ROWS),
            *extremes,
            *(pl.col(c).first() for c in values),
        )
        .collect(engine="streaming")
        .sort([*KEYS, SERIES])
    )
    return StackedBins(bins, pile_bins, shown, by_series)
