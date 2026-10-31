"""Tasks that aggregate a plot: its result with hover files, or the layer of a selection."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl

from ddviz.compute.aggregate import COUNT, INDEX, KEY, aggregate
from ddviz.compute.hoverfit import fit_hover
from ddviz.compute.progress import Emit
from ddviz.compute.raster import occupancy
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


def _column_bytes(dtype: pl.DataType) -> int:
    """Return the bytes per bin of a hover column as `_column_array` writes it."""
    return 8 if dtype.is_numeric() else 4


def _shapes(spec: ScatterSpec, levels: dict[str, list]) -> int:
    """Return the number of overlay levels, whose shapes the series take; 0 without an overlay."""
    return len(levels["overlay"]) if spec.overlay is not None else 0


def _colors(spec: ScatterSpec, n_series: int, levels: dict[str, list]) -> list[str]:
    """Return the color of each series: that of its color level (`ScatterSpec.overlay`)."""
    shapes = max(_shapes(spec, levels), 1)
    return [series_color(spec.colors, s // shapes) for s in range(n_series)]


def run_plot(spec: ScatterSpec, out: Path, emit: Emit) -> None:
    """Aggregate a scatter plot and write its series images and hover files.

    The hover files keep within ``spec.hover_bytes`` (`ddviz.compute.hoverfit`):
    columns off the axes are left out, or all the files when even the axis
    columns do not fit.

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
    bins = agg.bins
    keys = bins[KEY].to_numpy()
    emit({"type": "progress", "stage": "raster"})
    bitmask = occupancy(keys, agg.grid)
    colors = _colors(spec, agg.grid.n_series, agg.levels)
    shapes = _shapes(spec, agg.levels)
    sizes = spec.marker_sizes(agg.levels["overlay"])
    if spec.gradient:
        images = write_gradient(
            out,
            keys,
            bins[spec.color],
            bins[INDEX].to_numpy(),
            agg.grid,
            agg.layout.ncol,
            agg.color_range,
            shapes,
            sizes,
        )
    else:
        images = write_images(
            out, keys, agg.grid, agg.layout.ncol, colors, shapes, sizes
        )

    emit({"type": "progress", "stage": "write"})
    hover = list(dict.fromkeys(spec.hover))
    sizes = {name: _column_bytes(bins[name].dtype) for name in hover}
    kept = fit_hover(
        sizes, [*spec.x, *spec.y], len(bins), bitmask.nbytes, spec.hover_bytes
    )
    columns = []
    files = []
    if kept is not None:
        arrays = {
            "keys.npy": keys,
            "count.npy": bins[COUNT].cast(pl.UInt32).to_numpy(),
            "index.npy": bins[INDEX].cast(pl.Int64).to_numpy(),
            "occupancy.npy": bitmask,
        }
        for i, name in enumerate(kept):
            arrays[f"col{i}.npy"], labels = _column_array(bins[name])
            columns.append(HoverColumn(name, f"col{i}.npy", labels))
        for file, array in arrays.items():
            np.save(out / file, array)
            files.append(out / file)

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
        hover_files=kept is not None,
        hover_dropped=[c for c in hover if kept is None or c not in kept],
        hover_bytes=sum(f.stat().st_size for f in files),
        axis_levels=agg.axis_levels,
        spreads=agg.spreads,
        boxes=agg.boxes,
        smooths=agg.smooths,
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
    shapes = _shapes(spec, agg.levels)
    sizes = spec.marker_sizes(agg.levels["overlay"])
    if spec.gradient:
        images = write_gradient(
            out,
            keys,
            agg.selected[spec.color],
            agg.selected[INDEX].to_numpy(),
            agg.grid,
            agg.layout.ncol,
            agg.color_range,
            shapes,
            sizes,
        )
    else:
        colors = _colors(spec, agg.grid.n_series, agg.levels)
        images = write_images(
            out, keys, agg.grid, agg.layout.ncol, colors, shapes, sizes
        )
    SelectionManifest(
        selection=spec.selection,
        grid=agg.grid,
        images=images,
        rows=agg.selected_rows,
    ).write(out)
