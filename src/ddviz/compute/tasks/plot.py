"""Tasks that aggregate a plot: its result with hover files, or the layer of a selection."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl

from ddviz.compute.aggregate import COUNT, INDEX, KEY, aggregate
from ddviz.compute.hoverfit import NPY_HEADER, fit_hover
from ddviz.compute.progress import Emit
from ddviz.compute.raster import occupancy
from ddviz.compute.tasks.images import write_gradient, write_images
from ddviz.compute.tasks.piles import selected_pixels, write_piles
from ddviz.shared.manifest import HoverColumn, PlotManifest, SelectionManifest
from ddviz.shared.missing import MISSING, MISSING_COLOR
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
    """Return the color of each series: that of its color level (`ScatterSpec.overlay`).

    The missing color level (`ddviz.shared.missing.MISSING`) is gray; the
    other levels keep the colors of their places.
    """
    shapes = max(_shapes(spec, levels), 1)
    color = levels["color"]
    return [
        MISSING_COLOR
        if color[s // shapes] == MISSING
        else series_color(spec.colors, s // shapes)
        for s in range(n_series)
    ]


def _solid(spec: ScatterSpec, colors: list[str], levels: dict[str, list]) -> dict:
    """Return the series of a gradient's missing level, drawn in one color (`write_gradient`)."""
    shapes = max(_shapes(spec, levels), 1)
    return {
        s: c for s, c in enumerate(colors) if levels["color"][s // shapes] == MISSING
    }


def run_plot(spec: ScatterSpec, out: Path, emit: Emit) -> None:
    """Aggregate a scatter plot and write its series images and hover files.

    The hover files keep within ``spec.hover_bytes`` (`ddviz.compute.hoverfit`):
    columns off the axes are left out, or all the files when even the axis
    columns do not fit. The files of the piles (`ddviz.compute.tasks.piles`)
    come first: the plot cannot be drawn without them, so the task fails
    when they alone pass the limit.

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
    n_piles, pile_columns, pile_files = write_piles(out, agg, spec.gradient)
    pile_bytes = sum(f.stat().st_size for f in pile_files)
    if spec.hover_bytes is not None and pile_bytes > spec.hover_bytes:
        for f in pile_files:
            f.unlink()
        raise ValueError(
            f"重なる点の集まりのファイル（{pile_bytes / 2**20:,.1f}MB）が、一時ファイルの"
            f"残り（{spec.hover_bytes / 2**20:,.1f}MB。[hover] max_temp_gb）を超えるため"
            "描けない。フィルタで行を絞るか、設定の上限を上げる"
        )
    emit({"type": "progress", "stage": "raster"})
    bitmask = occupancy(keys, agg.grid)
    colors = _colors(spec, agg.grid.n_series, agg.levels)
    shapes = spec.marker_shapes(agg.levels["overlay"])
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
            _solid(spec, colors, agg.levels),
        )
    else:
        images = write_images(
            out, keys, agg.grid, agg.layout.ncol, colors, shapes, sizes
        )

    emit({"type": "progress", "stage": "write"})
    hover = list(dict.fromkeys(spec.hover))
    sizes = {name: _column_bytes(bins[name].dtype) for name in hover}
    pile_bins = agg.pile_bins
    # The rows of the piles in their bins, for the plot's data (`ddviz.server.plotdata`).
    fixed = bitmask.nbytes + len(pile_bins) * (8 + 4) + 2 * NPY_HEADER
    limit = None if spec.hover_bytes is None else spec.hover_bytes - pile_bytes
    kept = fit_hover(sizes, [*spec.x, *spec.y], len(bins), fixed, limit)
    columns = []
    files = []
    if kept is not None:
        arrays = {
            "keys.npy": keys,
            "count.npy": bins[COUNT].cast(pl.UInt32).to_numpy(),
            "index.npy": bins[INDEX].cast(pl.Int64).to_numpy(),
            "occupancy.npy": bitmask,
            "pile_keys.npy": pile_bins[KEY].to_numpy(),
            "pile_count.npy": pile_bins[COUNT].cast(pl.UInt32).to_numpy(),
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
        rows=int(bins[COUNT].sum()) + int(pile_bins[COUNT].sum()),
        hover_files=kept is not None,
        hover_dropped=[c for c in hover if kept is None or c not in kept],
        hover_bytes=sum(f.stat().st_size for f in files) + pile_bytes,
        axis_levels=agg.axis_levels,
        piles=n_piles,
        pile_columns=pile_columns,
        pile_bytes=pile_bytes,
        boxes=agg.boxes,
        smooths=agg.smooths,
        nonpositive=[list(p) for p in agg.nonpositive],
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
    shapes = spec.marker_shapes(agg.levels["overlay"])
    sizes = spec.marker_sizes(agg.levels["overlay"])
    colors = _colors(spec, agg.grid.n_series, agg.levels)
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
            _solid(spec, colors, agg.levels),
        )
    else:
        images = write_images(
            out, keys, agg.grid, agg.layout.ncol, colors, shapes, sizes
        )
    SelectionManifest(
        selection=spec.selection,
        grid=agg.grid,
        images=images,
        rows=agg.selected_rows,
        piles=selected_pixels(agg.selected_piles, KEY, agg.grid),
    ).write(out)
