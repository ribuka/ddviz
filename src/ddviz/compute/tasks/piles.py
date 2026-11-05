"""The files of the piles a plot draws (`ddviz.compute.stacks`): where each lies, its rows, and its rows by series.

The page draws each pile as one marker with its number of rows, and the
hover shows a pile's values and rows by series from these files
(`ddviz.server.hover.HoverIndex`); the UI server reads them without polars.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl

from ddviz.compute.aggregate import Aggregation
from ddviz.compute.stacked import COLOR_MAX, COLOR_MIN, ROWS, VALUES
from ddviz.compute.stacks import KEYS, PANEL, SERIES, N
from ddviz.shared.keys import BinGrid
from ddviz.shared.manifest import HoverColumn

_PIXEL = "__pixel"


def pile_pixel(panel: pl.Expr, by: pl.Expr, bx: pl.Expr, grid: BinGrid) -> pl.Expr:
    """Return the pixel of piles in the panels: ``(panel * height + by) * width + bx``.

    Parameters
    ----------
    panel, by, bx : polars.Expr
        The panel and the bins along y and x.
    grid : BinGrid
        Key space of the bins.

    Returns
    -------
    polars.Expr
        The pixels as Int64.
    """
    return ((panel * grid.height + by) * grid.width + bx).cast(pl.Int64)


def selected_pixels(selected: pl.DataFrame, key: str, grid: BinGrid) -> list[int]:
    """Return the pixels of the bins of the selected rows of the piles, sorted.

    Parameters
    ----------
    selected : polars.DataFrame
        Bins of the selected rows of the piles
        (`ddviz.compute.aggregate.Aggregation.selected_piles`).
    key : str
        Their key column.
    grid : BinGrid
        Key space of the bins.

    Returns
    -------
    list of int
        The pixels (`pile_pixel`) with selected rows of a pile.
    """
    panel, _, by, bx = grid.unpack(selected[key].to_numpy())
    pixels = (panel * grid.height + by) * grid.width + bx
    return [int(p) for p in np.unique(pixels)]


def _array(values: pl.Series) -> tuple[np.ndarray, list | None]:
    """Return the values of an axis column at the piles: integers exact, other numbers as floats, text as codes."""
    if values.dtype.is_integer():
        # A pile of another pair's panel has none; its value is never read.
        return values.fill_null(0).cast(pl.Int64).to_numpy(), None
    if values.dtype.is_numeric():
        return values.cast(pl.Float64).fill_null(np.nan).to_numpy(), None
    text = values.cast(pl.String)
    labels = text.drop_nulls().unique().sort()
    codes = text.replace_strict(
        labels, list(range(len(labels))), default=-1, return_dtype=pl.Int32
    )
    return codes.to_numpy(), labels.to_list()


def _value(i: int) -> str:
    """Return the internal column of the `i`-th axis column's values at the piles."""
    return f"__value{i}"


def write_piles(
    out: Path, agg: Aggregation, gradient: bool
) -> tuple[int, list[HoverColumn], list[Path]]:
    """Write the files of the drawn piles of an aggregation.

    Parameters
    ----------
    out : pathlib.Path
        Directory of the task.
    agg : Aggregation
        The aggregation, with its piles.
    gradient : bool
        Whether the color is a gradient: the piles then have the least and
        largest color of their rows.

    Returns
    -------
    tuple
        The number of piles, the axis columns' values at the piles, and the
        files written (none without piles). The files are those
        `ddviz.shared.manifest.PlotManifest.piles` lists, in the order of
        the pixels.
    """
    grid = agg.grid
    levels, by_series, named = [], [], {}
    for found in agg.piles:
        if found.series is None or found.piles.height == 0:
            continue
        pixels = found.piles.select(
            *KEYS,
            N,
            pile_pixel(pl.col(PANEL), pl.col("by"), pl.col("bx"), grid).alias(_PIXEL),
        )
        joined = found.series.join(pixels, on=KEYS)
        named.update(dict.fromkeys([found.x, found.y]))
        order = list(named)
        extremes = (
            [pl.col(COLOR_MIN).min(), pl.col(COLOR_MAX).max()] if gradient else []
        )
        levels.append(
            joined.group_by(_PIXEL).agg(
                pl.col(N).first(),
                *extremes,
                *(
                    pl.col(VALUES).struct.field(c).first().alias(_value(order.index(c)))
                    for c in dict.fromkeys([found.x, found.y])
                ),
            )
        )
        by_series.append(joined.select(_PIXEL, SERIES, ROWS))
    if not levels:
        return 0, [], []
    piles = pl.concat(levels, how="diagonal_relaxed").sort(_PIXEL)
    series = pl.concat(by_series).sort(_PIXEL, SERIES)
    starts = np.searchsorted(series[_PIXEL].to_numpy(), piles[_PIXEL].to_numpy())
    arrays = {
        "pile_pixel.npy": piles[_PIXEL].to_numpy(),
        "pile_n.npy": piles[N].cast(pl.Int64).to_numpy(),
        "pile_start.npy": np.append(starts, series.height).astype(np.int64),
        "pile_series.npy": series[SERIES].cast(pl.Int32).to_numpy(),
        "pile_series_n.npy": series[ROWS].cast(pl.Int64).to_numpy(),
    }
    if gradient:
        arrays["pile_min.npy"] = piles[COLOR_MIN].cast(pl.Float64).to_numpy()
        arrays["pile_max.npy"] = piles[COLOR_MAX].cast(pl.Float64).to_numpy()
    columns = []
    # The axis columns by their names, whatever they are (even "min", "max" or
    # an internal name such as "__color_min").
    for i, name in enumerate(named):
        arrays[f"pile_col{i}.npy"], labels = _array(piles[_value(i)])
        columns.append(HoverColumn(name, f"pile_col{i}.npy", labels))
    files = []
    for file, array in arrays.items():
        np.save(out / file, array)
        files.append(out / file)
    return piles.height, columns, files
