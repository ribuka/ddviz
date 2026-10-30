"""Tasks that aggregate a plot: its result with hover files, or the layer of a selection."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl

from ddviz.compute.aggregate import COUNT, INDEX, KEY, aggregate
from ddviz.compute.progress import Emit
from ddviz.compute.raster import masks, occupancy
from ddviz.compute.tasks.images import write_gradient, write_images
from ddviz.shared.manifest import HoverColumn, PlotManifest, SelectionManifest
from ddviz.shared.palette import series_color
from ddviz.shared.scatter import ScatterSpec


def _column_array(series: pl.Series) -> tuple[np.ndarray, list | None]:
    """Return a hover column as a numpy array, with labels for codes of a non-numeric column."""
    if series.dtype.is_numeric():
        if series.dtype.is_integer() and series.null_count() == 0:
            return series.cast(pl.Int64).to_numpy(), None
        return series.cast(pl.Float64).fill_null(np.nan).to_numpy(), None
    text = series.cast(pl.String)
    labels = text.drop_nulls().unique().sort()
    codes = text.replace_strict(
        labels, list(range(len(labels))), default=-1, return_dtype=pl.Int32
    )
    return codes.to_numpy(), labels.to_list()


def run_plot(spec: ScatterSpec, out: Path, emit: Emit) -> None:
    """Aggregate a scatter plot and write its series images and hover files.

    Parameters
    ----------
    spec : ScatterSpec
        What to plot.
    out : pathlib.Path
        Directory to write the result into.
    emit : callable
        Receives progress messages.
    """
    agg = aggregate(spec, lambda stage: emit({"type": "progress", "stage": stage}))
    emit({"type": "progress", "stage": "write"})
    bins = agg.bins
    keys = bins[KEY].to_numpy()
    np.save(out / "keys.npy", keys)
    np.save(out / "count.npy", bins[COUNT].cast(pl.UInt32).to_numpy())
    np.save(out / "index.npy", bins[INDEX].cast(pl.Int64).to_numpy())
    columns = []
    for i, name in enumerate(dict.fromkeys(spec.hover)):
        array, labels = _column_array(bins[name])
        np.save(out / f"col{i}.npy", array)
        columns.append(HoverColumn(name, f"col{i}.npy", labels))

    emit({"type": "progress", "stage": "raster"})
    bin_masks = masks(keys, agg.grid)
    np.save(out / "occupancy.npy", occupancy(bin_masks))
    colors = [series_color(spec.colors, s) for s in range(agg.grid.n_series)]
    if spec.gradient:
        images = write_gradient(
            out, keys, bins[spec.color], agg.grid, agg.layout.ncol, agg.color_range
        )
    else:
        images = write_images(out, bin_masks, agg.layout.ncol, colors)

    PlotManifest(
        spec=spec,
        grid=agg.grid,
        layout=agg.layout,
        axes=agg.axes,
        x_ranges=[list(r) for r in agg.x_ranges],
        y_ranges=[list(r) for r in agg.y_ranges],
        levels=agg.levels,
        all_levels=agg.all_levels,
        cuts=agg.cuts,
        color_range=None if agg.color_range is None else list(agg.color_range),
        colors=colors,
        columns=columns,
        images=images,
        rows=int(bins[COUNT].sum()),
    ).write(out)


def run_selection(spec: ScatterSpec, out: Path, emit: Emit) -> None:
    """Aggregate the selected rows of a drawn result and write their images.

    Parameters
    ----------
    spec : ScatterSpec
        The drawn result's spec with its view (levels and ranges) and a
        selection.
    out : pathlib.Path
        Directory to write the result into.
    emit : callable
        Receives progress messages.
    """
    agg = aggregate(
        spec,
        lambda stage: emit({"type": "progress", "stage": stage}),
        selection_only=True,
    )
    emit({"type": "progress", "stage": "raster"})
    keys = agg.selected[KEY].to_numpy()
    if spec.gradient:
        images = write_gradient(
            out,
            keys,
            agg.selected[spec.color],
            agg.grid,
            agg.layout.ncol,
            agg.color_range,
        )
    else:
        colors = [series_color(spec.colors, s) for s in range(agg.grid.n_series)]
        images = write_images(out, masks(keys, agg.grid), agg.layout.ncol, colors)
    SelectionManifest(
        selection=spec.selection,
        grid=agg.grid,
        images=images,
        rows=agg.selected_rows,
    ).write(out)
